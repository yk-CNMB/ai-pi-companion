# =======================================================================
# Pico AI Server - app.py (语法修正版)
# 启动: gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
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

import eventlet
eventlet.monkey_patch()

import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from google import genai

# --- 1. 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 2. 目录 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")

for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]:
    os.makedirs(d, exist_ok=True)

# --- 3. 配置 (修复了 try-except 格式) ---
CONFIG = {}
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
except:
    pass

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"API Error: {e}")

# --- 4. 核心函数 ---
def load_user_memories(u):
    # 记忆已移交前端，此函数仅作兼容
    return []

# 模型管理
CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.0, "y": 0.0}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    data = {
        "persona": f"你是一个名为{mid}的AI。",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%", "pitch": "+0Hz",
        "scale": 0.5, "x": 0.0, "y": 0.0
    }
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except:
            pass
    return data

def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    current = get_model_config(mid)
    current.update(data)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return current

def scan_models():
    ms = []
    for j in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        mid = os.path.basename(os.path.dirname(j))
        cfg = get_model_config(mid)
        ms.append({
            "id": mid, "name": mid.capitalize(),
            "path": "/"+os.path.relpath(j, BASE_DIR).replace("\\","/"),
            "persona": cfg['persona'],
            "voice": cfg['voice'],
            "rate": cfg.get('rate', '+0%'),
            "pitch": cfg.get('pitch', '+0Hz'),
            "scale": cfg.get('scale', 0.5),
            "x": cfg.get('x', 0.0),
            "y": cfg.get('y', 0.0)
        })
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t:
        CURRENT_MODEL = t
init_model()

# 语音合成
def run_piper_tts(text, model_file, output_path):
    model_path = os.path.join(VOICES_DIR, model_file)
    if not os.path.exists(PIPER_BIN): return False
    try:
        cmd = f'echo "{text}" | "{PIPER_BIN}" --model "{model_path}" --output_file "{output_path}"'
        subprocess.run(cmd, shell=True, check=True)
        return True
    except: return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}"
    try:
        if voice.endswith(".onnx"):
            out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
            if run_piper_tts(clean, voice, out_path):
                url = f"/static/audio/{fname}.wav"
            else: return
        else:
            out_path = os.path.join(AUDIO_DIR, f"{fname}.mp3")
            async def _run():
                cm = edge_tts.Communicate(clean, voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            asyncio.run(_run())
            url = f"/static/audio/{fname}.mp3"
        
        if room:
            socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid:
            socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
    except Exception as e:
        print(f"TTS Error: {e}")

# --- 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    if v!=SERVER_VERSION: return redirect(url_for('pico_v', v=SERVER_VERSION))
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

@app.route('/upload_model', methods=['POST'])
def upload_model():
    if 'file' not in request.files: return jsonify({'success': False, 'msg': '无文件'})
    f = request.files['file']
    if f.filename == '': return jsonify({'success': False, 'msg': '未选择'})
    if f and f.filename.endswith('.zip'):
        try:
            n = secure_filename(f.filename).rsplit('.', 1)[0].lower()
            p = os.path.join(MODELS_DIR, n)
            if os.path.exists(p): shutil.rmtree(p)
            with zipfile.ZipFile(f, 'r') as z: z.extractall(p)
            items = os.listdir(p)
            if len(items)==1 and os.path.isdir(os.path.join(p, items[0])):
                sub = os.path.join(p, items[0])
                for i in os.listdir(sub): shutil.move(os.path.join(sub, i), p)
                os.rmdir(sub)
            return jsonify({'success': True})
        except Exception as e: return jsonify({'success': False, 'msg': str(e)})
    return jsonify({'success': False, 'msg': '仅支持 .zip'})

# --- SocketIO ---
users = {}
chatroom_chat = None

def init_chatroom():
    global chatroom_chat
    if not client: return
    try:
        chatroom_chat = client.chats.create(
            model="gemini-2.5-flash",
            config={"system_instruction": CURRENT_MODEL['persona']}
        )
        print(f"🏠 聊天室重置")
    except: pass

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})
@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        emit('system_message', {'text': f"💨 {users.pop(request.sid)['username']} 离开了。"}, to='lobby')

@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 欢迎 {u} 加入！"}, to='lobby', include_self=False)
    
    welcome = f"[HAPPY] 嗨 {u}！我是{CURRENT_MODEL['name']}。"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]['username']
    msg = d['text']
    user_memories = d.get('memories', [])

    if "/管理员" in msg:
        if sender.lower() == "yk":
            users[sid]['is_admin'] = True
            emit('admin_unlocked')
            emit('system_message', {'text': f"👑 管理员 {sender} 已上线！"}, to=sid)
        else:
            emit('system_message', {'text': "🤨 你不是 YK！"}, to=sid)
        return
    
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')

    try:
        if not chatroom_chat: init_chatroom()
        mem_ctx = f" (记忆: {', '.join(user_memories)})" if user_memories else ""
        resp = chatroom_chat.send_message(f"【{sender}说{mem_ctx}】: {msg}")
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text.replace(match.group(0), '').strip() if match else resp.text
        if match: emo = match.group(1)
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        init_chatroom()

# --- 工作室接口 ---
def is_admin(sid): return users.get(sid, {}).get('is_admin', False)
@socketio.on('get_studio_data')
def on_get_data():
    # 所有人可看
    voices = [
        {"id": "zh-CN-XiaoxiaoNeural", "name": "☁️ 晓晓"},
        {"id": "zh-CN-XiaoyiNeural", "name": "☁️ 晓伊"},
        {"id": "zh-CN-YunxiNeural", "name": "☁️ 云希"},
        {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "☁️ 晓北"},
        {"id": "zh-TW-HsiaoChenNeural", "name": "☁️ 晓臻"}
    ]
    for onnx in glob.glob(os.path.join(VOICES_DIR, "*.onnx")):
        mid = os.path.basename(onnx)
        name = mid.replace(".onnx", "")
        if os.path.exists(os.path.join(VOICES_DIR, f"{name}.txt")):
            with open(os.path.join(VOICES_DIR, f"{name}.txt"),'r') as f: name=f.read().strip()
        voices.append({"id": mid, "name": f"🏠 {name}"})
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
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    
    updated = save_model_config(d['id'], {
        "persona": d['persona'],
        "voice": d['voice'],
        "rate": d['rate'],
        "pitch": d['pitch'],
        "scale": float(d['scale']),
        "x": float(d['x']),
        "y": float(d['y'])
    })
    
    if CURRENT_MODEL['id'] == d['id']:
        CURRENT_MODEL.update(updated)
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 设置已保存'})

@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    if d['id'] == CURRENT_MODEL['id']: return emit('toast', {'text': '❌ 不能删除当前模型', 'type': 'error'})
    try:
        shutil.rmtree(os.path.join(MODELS_DIR, d['id']))
        emit('toast', {'text': '🗑️ 已删除', 'type': 'success'})
        on_get_data()
    except:
        emit('toast', {'text': '删除失败', 'type': 'error'})

def bg_dl_task(name):
    urls = {"Mao":".../Mao","Natori":".../Natori","Rice":".../Rice","Wanko":".../Wanko"}
    url = urls.get(name, "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/"+name)
    t = os.path.join(MODELS_DIR, name.lower())
    if os.path.exists(t): shutil.rmtree(t)
    os.makedirs(t, exist_ok=True)
    try:
        os.system(f"svn export --force -q {url} {t}")
        socketio.emit('toast', {'text': f'✅ {name} 下载完成!'}, namespace='/')
    except: pass

@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    name = d.get('name')
    if name:
        emit('toast', {'text': f'🚀 开始下载 {name}...', 'type': 'info'})
        socketio.start_background_task(bg_dl_task, name)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
