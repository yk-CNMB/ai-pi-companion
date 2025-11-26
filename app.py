# =======================================================================
# Pico AI Server - app.py
# 功能: 聊天室 | 记忆 | Piper(本地) | Edge-TTS(在线) | 智能模型管理
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

import edge_tts
import soundfile as sf
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from google import genai

# --- 1. 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024 # 200MB 上传限制

# 【关键】使用 threading 模式，最稳定
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 2. 目录配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")
HISTORY_FILE = os.path.join(BASE_DIR, "chat_history.json") # 全局历史记录

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

# --- 4. 记忆系统 (全局) ---
GLOBAL_HISTORY = []

def load_history():
    global GLOBAL_HISTORY
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                GLOBAL_HISTORY = json.load(f)
            # 只保留最近 50 条
            if len(GLOBAL_HISTORY) > 50:
                GLOBAL_HISTORY = GLOBAL_HISTORY[-50:]
        except:
            GLOBAL_HISTORY = []
load_history()

def add_history(sender, text, role, emotion="NORMAL"):
    entry = {
        "timestamp": int(time.time()),
        "sender": sender,
        "text": text,
        "role": role,
        "emotion": emotion
    }
    GLOBAL_HISTORY.append(entry)
    if len(GLOBAL_HISTORY) > 50:
        GLOBAL_HISTORY.pop(0)
    # 异步保存 (在 threading 模式下简单处理)
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(GLOBAL_HISTORY, f, indent=2, ensure_ascii=False)
    except: pass
    return entry

def load_user_memories(u): return [] # 这里的私有记忆由前端传过来

# --- 5. 模型管理 ---
CURRENT_MODEL = {
    "id": "default", "path": "", "persona": "", 
    "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", 
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
    for j in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        mid = os.path.basename(os.path.dirname(j))
        cfg = get_model_config(mid)
        path = "/" + os.path.relpath(j, BASE_DIR).replace("\\", "/")
        ms.append({"id": mid, "name": mid.capitalize(), "path": path, **cfg})
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = None
    for m in ms:
        if "hiyori" in m['id'].lower(): t = m; break
    if t is None and len(ms) > 0: t = ms[0]
    if t: CURRENT_MODEL = t
init_model()

# --- 6. TTS 引擎 ---

def run_piper_tts(text, model_file, output_path):
    # 路径处理
    if not os.path.isabs(model_file):
        model_path = os.path.join(VOICES_DIR, model_file)
    else:
        model_path = model_file
        
    if not os.path.exists(PIPER_BIN): return False
    if not os.path.exists(model_path): return False
    
    try:
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", output_path]
        # 使用 communicate 传递 stdin (Python 3.13 兼容写法)
        proc = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )
        out, err = proc.communicate(input=text.encode('utf-8'))
        
        return proc.returncode == 0
    except: return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}"
    success = False
    url = ""
    
    # 1. Piper (本地优先)
    if voice.endswith(".onnx"):
         out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
         if run_piper_tts(clean, voice, out_path):
             success = True
             url = f"/static/audio/{fname}.wav"
             print(f"✅ [Piper] 生成成功: {fname}")

    # 2. Edge-TTS (在线兜底)
    if not success:
        out_path = os.path.join(AUDIO_DIR, f"{fname}.mp3")
        safe_voice = voice if ("Neural" in voice) else "zh-CN-XiaoxiaoNeural"
        try:
            async def _run():
                cm = edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.close()
            success = True
            url = f"/static/audio/{fname}.mp3"
            print(f"✅ [Edge] 生成成功: {safe_voice}")
        except Exception as e:
            print(f"❌ [TTS] 全部失败: {e}")

    if success:
        payload = {'audio': url}
        if room: socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', payload, to=sid, namespace='/')

# --- 7. 路由 ---
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
            return jsonify({'success': True})
        except: return jsonify({'success': False})
    return jsonify({'success': False})

# --- 8. SocketIO ---
users = {}
chatroom_chat = None

def init_chatroom():
    global chatroom_chat
    if not client: return
    try:
        # 注入历史上下文
        history_text = "\n".join([f"[{h['sender']}]: {h['text']}" for h in GLOBAL_HISTORY[-20:]])
        system_prompt = f"{CURRENT_MODEL['persona']}\n\n【历史聊天记录】:\n{history_text}"
        
        chatroom_chat = client.chats.create(
            model="gemini-2.5-flash",
            config={"system_instruction": system_prompt}
        )
        print(f"🏠 聊天室重置: {CURRENT_MODEL['name']}")
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
    # 【核心】下发历史记录
    emit('history_sync', GLOBAL_HISTORY)
    
    # 进场提示
    msg = f"🎉 欢迎 {u}！"
    add_history("System", msg, "system")
    emit('system_message', {'text': msg}, to='lobby')
    
    welcome = f"[HAPPY] 嗨 {u}！"
    # 不存入历史，仅发给个人
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]['username']
    msg = d['text']
    private_mem = d.get('memories', [])

    if "/管理员" in msg and sender.lower() == "yk": 
        users[sid]['is_admin'] = True
        emit('admin_unlocked')
        return
    
    # 记录并广播
    add_history(sender, msg, "user")
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')

    try:
        if not chatroom_chat: init_chatroom()
        
        # 注入私有记忆
        prompt = msg
        if private_mem:
            prompt = f"({sender}的备注: {', '.join(private_mem)}) {msg}"
            
        resp = chatroom_chat.send_message(f"【{sender}】: {prompt}")
        
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text.replace(match.group(0), '').strip() if match else resp.text
        if match: emo = match.group(1)

        add_history(CURRENT_MODEL['name'], txt, "pico", emo)
        socketio.emit('response', {'text': txt, 'sender': CURRENT_MODEL['name'], 'emotion': emo}, to='lobby')
        
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except: init_chatroom()

def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    # 硬编码 Edge 列表
    voices = [
        {"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓 (默认)"},
        {"id":"zh-CN-YunxiNeural","name":"☁️ 云希 (少年)"},
        {"id":"zh-CN-liaoning-XiaobeiNeural","name":"☁️ 晓北 (东北)"},
        {"id":"zh-TW-HsiaoChenNeural","name":"☁️ 晓臻 (台湾)"},
        {"id":"en-US-AnaNeural","name":"☁️ Ana (English)"}
    ]
    
    # 扫描本地 Piper
    if os.path.exists(VOICES_DIR):
        for onnx in glob.glob(os.path.join(VOICES_DIR, "*.onnx")):
            mid = os.path.basename(onnx)
            name = mid.replace(".onnx", "")
            if os.path.exists(os.path.join(VOICES_DIR, f"{name}.txt")):
                try: name = open(os.path.join(VOICES_DIR, f"{name}.txt")).read().strip()
                except: pass
            voices.append({"id": mid, "name": f"🏠 {name} (本地)"})
            
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'voices': voices})

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t:
        CURRENT_MODEL = t
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_settings')
def on_save_settings(d):
    global CURRENT_MODEL
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 无权限', 'type': 'error'})
    
    try:
        d['scale'] = float(d['scale'])
        d['x'] = float(d['x'])
        d['y'] = float(d['y'])
    except: pass

    updated = save_model_config(d['id'], d)
    
    if CURRENT_MODEL['id'] == d['id']:
        CURRENT_MODEL.update(updated)
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})

@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return
    if d['id'] == CURRENT_MODEL['id']: return
    try: shutil.rmtree(os.path.join(MODELS_DIR, d['id'])); emit('toast', {'text': '🗑️ 已删除'}); on_get_data()
    except: pass

@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return
    name = d.get('name')
    if name:
        emit('toast', {'text': f'🚀 下载中...'}); socketio.start_background_task(bg_dl_task, name)

def bg_dl_task(name):
    u = {"Mao":".../Mao","Natori":".../Natori"}.get(name, "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/"+name)
    t = os.path.join(MODELS_DIR, name.lower())
    if os.path.exists(t): shutil.rmtree(t, ignore_errors=True)
    os.makedirs(t, exist_ok=True)
    try: os.system(f"svn export --force -q {u} {t}"); socketio.emit('toast',{'text':'✅ 完成!'},namespace='/')
    except: pass

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
