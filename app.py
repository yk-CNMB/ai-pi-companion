# =======================================================================
# Pico AI Server - app.py (最终完整版)
# 功能: 聊天室 | 记忆 | Piper(本地) | Edge-TTS(在线) | 强力模型扫描
# 兼容: Python 3.13 (原生线程模式)
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

# 移除不兼容的库，只用标准库和稳定库
import edge_tts
import soundfile as sf
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from google import genai

# --- 1. 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret_key_default'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB

# 使用 threading 模式，最稳定
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 2. 目录配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")

# 确保目录存在
for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# --- 3. API 配置 ---
CONFIG = {}
try:
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            CONFIG = json.load(f)
    print("✅ 配置加载成功")
except Exception as e:
    print(f"⚠️ 配置加载出错: {e}")

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if api_key and "在这里" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini API 就绪")
    except Exception as e:
        print(f"❌ API 初始化失败: {e}")
else:
    print("❌ 未找到有效 API KEY")

# --- 4. 核心数据 ---
def load_user_memories(u): return []

CURRENT_MODEL = {
    "id": "default", "name": "Default", "path": "", 
    "persona": "", "voice": "zh-CN-XiaoxiaoNeural", 
    "rate": "+0%", "pitch": "+0Hz", 
    "scale": 0.5, "x": 0.5, "y": 0.5
}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    data = {
        "persona": f"你是{mid}。",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%", "pitch": "+0Hz",
        "scale": 0.5, "x": 0.5, "y": 0.5
    }
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except: pass
    return data

def save_model_config(mid, data):
    p_dir = os.path.join(MODELS_DIR, mid)
    if not os.path.exists(p_dir): os.makedirs(p_dir)
    p = os.path.join(p_dir, "config.json")
    
    curr = get_model_config(mid)
    curr.update(data)
    
    with open(p, "w", encoding="utf-8") as f:
        json.dump(curr, f, indent=2, ensure_ascii=False)
    return curr

def scan_models():
    ms = []
    print(f"🔍 [Model] 开始扫描: {MODELS_DIR}")
    # 强力递归扫描所有 .model3.json
    # 无论藏多深都能找到
    for json_path in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        # 计算相对路径
        rel_path = os.path.relpath(json_path, MODELS_DIR)
        # ID 取第一层文件夹名 (防止重名冲突)
        mid = rel_path.split(os.sep)[0]
        
        # 如果 JSON 就在根目录，ID 就是文件名
        if os.path.dirname(rel_path) == "":
            mid = os.path.splitext(os.path.basename(json_path))[0]

        cfg = get_model_config(mid)
        
        # 构造 Web 路径 (必须是 /static/...)
        # path 必须指向 .model3.json 文件本身
        web_path = "/static/live2d/" + os.path.relpath(json_path, MODELS_DIR).replace("\\", "/")
        
        # 避免重复
        if not any(m['id'] == mid for m in ms):
            ms.append({
                "id": mid, 
                "name": mid.capitalize(), 
                "path": web_path, 
                **cfg
            })
            print(f"   ✅ 发现模型: {mid} -> {web_path}")
            
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = None
    # 优先找 Hiyori
    for m in ms:
        if "hiyori" in m['id'].lower():
            t = m
            break
    # 没找到就用第一个
    if t is None and len(ms) > 0:
        t = ms[0]
    
    if t:
        CURRENT_MODEL = t
        print(f"🤖 初始化模型: {t['name']}")

init_model()

# --- 5. TTS 引擎 (Piper + Edge) ---

def run_piper_tts(text, model_file, output_path):
    # 路径处理
    if not os.path.isabs(model_file):
        model_path = os.path.join(VOICES_DIR, model_file)
    else:
        model_path = model_file
        
    if not os.path.exists(PIPER_BIN):
        print(f"❌ Piper 引擎丢失: {PIPER_BIN}")
        return False
    if not os.path.exists(model_path):
        print(f"❌ 模型文件丢失: {model_path}")
        return False
        
    try:
        print(f"🎤 [Piper] 生成中: {text[:10]}...")
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", output_path]
        
        proc = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )
        out, err = proc.communicate(input=text.encode('utf-8'))
        
        if proc.returncode == 0:
            print("✅ [Piper] 生成成功")
            return True
        else:
            print(f"❌ [Piper] 引擎报错: {err.decode()}")
            return False
    except Exception as e:
        print(f"❌ [Piper] 执行异常: {e}")
        return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    
    fname = f"{uuid.uuid4()}"
    success = False
    url = ""
    
    # 1. Piper (本地)
    if voice and voice.endswith(".onnx"):
         out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
         if run_piper_tts(clean, voice, out_path):
             success = True
             url = f"/static/audio/{fname}.wav"

    # 2. Edge-TTS (在线兜底)
    if not success:
        out_path = os.path.join(AUDIO_DIR, f"{fname}.mp3")
        safe_voice = voice
        if not safe_voice or ".onnx" in safe_voice or "Neural" not in safe_voice:
            safe_voice = "zh-CN-XiaoxiaoNeural"
            
        try:
            print(f"☁️ [Edge] 正在生成: {safe_voice}")
            async def _run():
                cm = edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.close()
            success = True
            url = f"/static/audio/{fname}.mp3"
        except Exception as e:
            print(f"❌ TTS 失败: {e}")

    if success:
        payload = {'audio': url}
        if room: socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', payload, to=sid, namespace='/')

# --- 6. 路由 ---
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
            # 智能整理套娃
            for root, dirs, files in os.walk(p):
                if any(f.endswith('.model3.json') for f in files):
                    if root != p: 
                         for item in os.listdir(root): shutil.move(os.path.join(root, item), p)
                    break
            # 触发重扫
            on_get_data()
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
    voices = [{"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓 (默认)"},{"id":"en-US-AnaNeural","name":"☁️ Ana"}]
    # 扫描本地 Piper
    if os.path.exists(VOICES_DIR):
        for onnx in glob.glob(os.path.join(VOICES_DIR, "*.onnx")):
            mid = os.path.basename(onnx); name = mid.replace(".onnx", "")
            if os.path.exists(os.path.join(VOICES_DIR, f"{name}.txt")): 
                try: name = open(os.path.join(VOICES_DIR, f"{name}.txt")).read().strip()
                except: pass
            voices.append({"id": mid, "name": f"🏠 {name} (本地)"})
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
