# =======================================================================
# Pico AI Server - app.py (全功能修复版)
# 修复: 模型扫描看不到 Miku, 语音列表缺失
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
import requests

import edge_tts
import soundfile as sf
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")

for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]:
    if not os.path.exists(d): os.makedirs(d)

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

def load_user_memories(u): return []
CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    d = {"persona":f"你是{mid}。", "voice":"zh-CN-XiaoxiaoNeural", "rate":"+0%", "pitch":"+0Hz", "scale":0.5, "x":0.5, "y":0.5}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f: d.update(json.load(f)) 
        except: pass
    return d
def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    curr = get_model_config(mid); curr.update(data)
    with open(p, "w", encoding="utf-8") as f: json.dump(curr, f, indent=2, ensure_ascii=False)
    return curr

# 【核心修复】强力模型扫描
def scan_models():
    ms = []
    # 遍历一级目录
    for item in os.listdir(MODELS_DIR):
        full_path = os.path.join(MODELS_DIR, item)
        if os.path.isdir(full_path):
            # 在该目录下寻找 model3.json
            json_files = glob.glob(os.path.join(full_path, "*.model3.json"))
            if json_files:
                # 找到了模型
                mid = item
                cfg = get_model_config(mid)
                # 构造 web 路径
                rel_path = os.path.relpath(json_files[0], BASE_DIR)
                web_path = "/" + rel_path.replace("\\", "/")
                
                ms.append({"id": mid, "name": mid.capitalize(), "path": web_path, **cfg})
    
    if not ms: print("⚠️ 未扫描到任何模型！")
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
init_model()

# TTS
def run_piper_tts(text, model_file, output_path):
    if not os.path.isabs(model_file): model_path = os.path.join(VOICES_DIR, model_file)
    else: model_path = model_file
    if not os.path.exists(PIPER_BIN): return False
    if not os.path.exists(model_path): return False
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
    
    # Piper
    if voice.endswith(".onnx"):
         out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
         if run_piper_tts(clean, voice, out_path): success=True; url=f"/static/audio/{fname}.wav"
    
    # Edge
    if not success:
        out_path = os.path.join(AUDIO_DIR, f"{fname}.mp3")
        safe_voice = voice if ("Neural" in voice) else "zh-CN-XiaoxiaoNeural"
        try:
            async def _run():
                cm = edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); loop.run_until_complete(_run()); loop.close()
            success=True; url=f"/static/audio/{fname}.mp3"
        except: pass

    if success:
        payload = {'audio': url}
        if room: socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', payload, to=sid, namespace='/')

@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r
@app.route('/upload_model', methods=['POST'])
def upload_model():
    if 'file' not in request.files: return jsonify({'success': False})
    f = request.files['file']
    if f.filename.endswith('.zip'):
        try:
            n = secure_filename(f.filename).rsplit('.', 1)[0].lower()
            p = os.path.join(MODELS_DIR, n); shutil.rmtree(p, ignore_errors=True)
            with zipfile.ZipFile(f, 'r') as z: z.extractall(p)
            # 简单化：不搞复杂移动，相信前端脚本的修复能力
            return jsonify({'success': True})
        except: return jsonify({'success': False})
    return jsonify({'success': False})

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
    socketio.start_background_task(bg_tts, f"Hi {u}", CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], sid=request.sid)
@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    msg = d['text']
    if "/管理员" in msg and users[sid]['username'].lower()=="yk": 
        users[sid]['is_admin']=True; emit('admin_unlocked'); return
    emit('chat_message', {'text': msg, 'sender': users[sid]['username']}, to='lobby')
    try:
        if not chatroom_chat: init_chatroom()
        resp = chatroom_chat.send_message(f"【{users[sid]['username']}】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt=resp.text.replace(match.group(0),'').strip() if match else resp.text
        if match: emo=match.group(1)
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except: init_chatroom()

def is_admin(sid): return users.get(sid, {}).get('is_admin', False)
@socketio.on('get_studio_data')
def on_get_data():
    # 【核心】强制发送完整列表
    voices = [
        {"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓 (默认)"},
        {"id":"zh-CN-YunxiNeural","name":"☁️ 云希 (少年)"},
        {"id":"zh-CN-liaoning-XiaobeiNeural","name":"☁️ 晓北 (东北)"},
        {"id":"zh-TW-HsiaoChenNeural","name":"☁️ 晓臻 (台湾)"},
        {"id":"en-US-AnaNeural","name":"☁️ Ana (English)"}
    ]
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
    if not is_admin(request.sid): return
    try: d['scale']=float(d['scale']); d['x']=float(d['x']); d['y']=float(d['y'])
    except: pass
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL.update(updated); init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})
@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return
    if d['id']==CURRENT_MODEL['id']: return
    try: shutil.rmtree(os.path.join(MODELS_DIR, d['id'])); emit('toast',{'text':'🗑️ 已删除'}); on_get_data()
    except: pass
@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return
    name=d.get('name'); emit('toast',{'text':f'🚀 下载 {name}...','type':'info'}); socketio.start_background_task(bg_dl_task, name)
def bg_dl_task(name):
    u={"Mao":".../Mao","Natori":".../Natori"}.get(name,"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/"+name)
    t=os.path.join(MODELS_DIR,name.lower()); shutil.rmtree(t, ignore_errors=True); os.makedirs(t,exist_ok=True)
    try: os.system(f"svn export --force -q {u} {t}"); socketio.emit('toast',{'text':f'✅ {name} 完成!'},namespace='/')
    except: pass

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
