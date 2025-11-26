# =======================================================================
# Pico AI Server - app.py (智能上传修复版)
# 修复: 自动处理 Zip 套娃，精准提取 .model3.json
# =======================================================================
import os
import json
import uuid
import asyncio
import time
import glob
import shutil
import re
import zipfile
import subprocess
import threading
import edge_tts
import soundfile as sf
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024 # 提升限制到 200MB

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 目录 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")

for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# --- API ---
CONFIG = {}
try:
    if os.path.exists("config.json"):
        with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里" not in api_key:
    try: client = genai.Client(api_key=api_key)
    except Exception as e: print(f"API Error: {e}")

# --- 核心 ---
def load_user_memories(u): return []
CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    d = {"persona":f"你是{mid}。", "voice":"zh-CN-XiaoxiaoNeural", "rate":"+0%", "pitch":"+0Hz", "scale":0.5, "x":0.5, "y":0.5}
    if os.path.exists(p):
        try: d.update(json.load(open(p))) 
        except: pass
    return d
def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    curr = get_model_config(mid); curr.update(data)
    with open(p, "w", encoding="utf-8") as f: json.dump(curr, f, ensure_ascii=False, indent=2)
    return curr
def scan_models():
    ms = []
    # 深度扫描所有 .model3.json
    for j in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        # 计算相对路径
        rel_path = os.path.relpath(j, MODELS_DIR)
        # 这里的 ID 应该是文件夹的名字 (第一层)
        parts = rel_path.split(os.sep)
        mid = parts[0] 
        
        cfg = get_model_config(mid)
        # path 必须是相对于 static 的 web 路径
        web_path = "/static/live2d/" + rel_path.replace("\\", "/")
        
        # 避免重复添加 (如果有多个json在同一个文件夹)
        if not any(m['id'] == mid for m in ms):
            ms.append({"id": mid, "name": mid.capitalize(), "path": web_path, **cfg})
            
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
init_model()

# --- 【核心修复】智能上传 ---
@app.route('/upload_model', methods=['POST'])
def upload_model():
    if 'file' not in request.files: return jsonify({'success': False, 'msg': 'No file'})
    f = request.files['file']
    if not f.filename.endswith('.zip'): return jsonify({'success': False, 'msg': 'Need .zip'})
    
    try:
        # 1. 创建临时目录和最终目录
        safe_name = secure_filename(f.filename.rsplit('.', 1)[0]).lower()
        target_dir = os.path.join(MODELS_DIR, safe_name)
        temp_dir = os.path.join(MODELS_DIR, "temp_" + safe_name)
        
        # 清理旧的
        if os.path.exists(target_dir): shutil.rmtree(target_dir)
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        # 2. 解压到临时目录
        with zipfile.ZipFile(f, 'r') as z: z.extractall(temp_dir)
        
        # 3. 【智能寻找】查找 .model3.json 到底在哪里
        model_json_path = None
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.model3.json'):
                    model_json_path = os.path.join(root, file)
                    break
            if model_json_path: break
            
        if not model_json_path:
            shutil.rmtree(temp_dir)
            return jsonify({'success': False, 'msg': '压缩包里没找到 .model3.json 文件！'})
            
        # 4. 【搬家】把找到的那个文件夹的内容，搬到 target_dir
        source_dir = os.path.dirname(model_json_path)
        shutil.move(source_dir, target_dir)
        
        # 5. 清理临时目录
        shutil.rmtree(temp_dir)
        
        print(f"✅ 上传成功: {safe_name}")
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"❌ 上传失败: {e}")
        return jsonify({'success': False, 'msg': str(e)})

# --- TTS & SocketIO (保持不变) ---
def run_piper_tts(text, model_file, output_path):
    if not os.path.isabs(model_file): model_path = os.path.join(VOICES_DIR, model_file)
    else: model_path = model_file
    if not os.path.exists(PIPER_BIN) or not os.path.exists(model_path): return False
    try:
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", output_path]
        subprocess.run(cmd, input=text.encode('utf-8'), check=True, capture_output=True)
        return True
    except: return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}"
    success = False; url = ""
    if voice.endswith(".onnx"):
         if run_piper_tts(clean, voice, os.path.join(AUDIO_DIR, f"{fname}.wav")): success=True; url=f"/static/audio/{fname}.wav"
    if not success:
        safe_voice = voice if ("Neural" in voice) else "zh-CN-XiaoxiaoNeural"
        try:
            edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch).save_sync(os.path.join(AUDIO_DIR, f"{fname}.mp3"))
            success=True; url=f"/static/audio/{fname}.mp3"
        except: pass
    if success:
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')

@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

users = {}
chatroom_chat = None
def init_chatroom():
    global chatroom_chat
    if not client: return
    try: chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": CURRENT_MODEL['persona']})
    except: pass
@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})
@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    welcome = f"[HAPPY] Hi {u}!"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], sid=request.sid)
@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]['username']; msg = d['text']
    if "/管理员" in msg:
        if sender.lower() == "yk": users[sid]['is_admin']=True; emit('admin_unlocked'); return
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    try:
        if not chatroom_chat: init_chatroom()
        resp = chatroom_chat.send_message(f"【{sender}】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt=resp.text.replace(match.group(0),'').strip() if match else resp.text
        if match: emo=match.group(1)
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except: init_chatroom()

@socketio.on('get_studio_data')
def on_get_data():
    voices = [{"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓"},{"id":"en-US-AnaNeural","name":"☁️ Ana"}]
    if os.path.exists(VOICES_DIR):
        for onnx in glob.glob(os.path.join(VOICES_DIR, "*.onnx")):
            mid = os.path.basename(onnx); name = mid.replace(".onnx", "")
            if os.path.exists(os.path.join(VOICES_DIR, f"{name}.txt")): 
                try: name = open(os.path.join(VOICES_DIR, f"{name}.txt")).read().strip()
                except: pass
            voices.append({"id": mid, "name": f"🏠 {name}"})
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'voices': voices})
@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_settings')
def on_save_settings(d):
    global CURRENT_MODEL
    if not users.get(request.sid, {}).get('is_admin'): return
    try: d['scale']=float(d['scale']); d['x']=float(d['x']); d['y']=float(d['y'])
    except: pass
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL.update(updated); init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})
@socketio.on('delete_model')
def on_del(d):
    if not users.get(request.sid, {}).get('is_admin'): return
    if d['id']==CURRENT_MODEL['id']: return emit('toast',{'text':'❌ 占用中','type':'error'})
    try: shutil.rmtree(os.path.join(MODELS_DIR, d['id'])); emit('toast',{'text':'🗑️ 已删除'}); on_get_data()
    except: pass
@socketio.on('download_model')
def on_dl(d):
    if not users.get(request.sid, {}).get('is_admin'): return
    name=d.get('name'); emit('toast',{'text':f'🚀 下载 {name}...','type':'info'}); socketio.start_background_task(bg_dl_task, name)
def bg_dl_task(name):
    u={"Mao":".../Mao","Natori":".../Natori"}.get(name,"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/"+name)
    t=os.path.join(MODELS_DIR,name.lower()); shutil.rmtree(t, ignore_errors=True); os.makedirs(t,exist_ok=True)
    try: os.system(f"svn export --force -q {u} {t}"); socketio.emit('toast',{'text':f'✅ {name} 完成!'},namespace='/')
    except: pass

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
