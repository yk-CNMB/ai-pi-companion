# =======================================================================
# Pico AI Server - app.py (硬编码直连版)
# 放弃自动扫描，手动指定 GlaDOS 路径，确保 100% 可用
# =======================================================================
import os
import json
import uuid
import asyncio
import time
import subprocess
import threading
import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 1. 绝对路径配置 (根据你的环境写死) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 你的 GlaDOS 模型路径
GLADOS_MODEL = os.path.join(BASE_DIR, "static", "voices", "en_US-glados.onnx")
# 你的 Piper 引擎路径
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")
# 音频输出目录
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")

# 确保目录存在
os.makedirs(AUDIO_DIR, exist_ok=True)

# --- 2. API 配置 ---
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

# --- 3. 核心逻辑 ---
CURRENT_MODEL = {
    "id": "default", "name": "Default", "persona": "", 
    "voice": "zh-CN-XiaoxiaoNeural", # 默认值
    "rate": "+0%", "pitch": "+0Hz", 
    "scale": 0.5, "x": 0.5, "y": 0.5
}

def get_model_config(mid):
    p = os.path.join(BASE_DIR, "static", "live2d", mid, "config.json")
    d = {"persona":f"你是{mid}。", "voice":"zh-CN-XiaoxiaoNeural", "rate":"+0%", "pitch":"+0Hz", "scale":0.5, "x":0.5, "y":0.5}
    if os.path.exists(p):
        try: d.update(json.load(open(p))) 
        except: pass
    return d

def save_model_config(mid, data):
    p_dir = os.path.join(BASE_DIR, "static", "live2d", mid)
    os.makedirs(p_dir, exist_ok=True)
    p = os.path.join(p_dir, "config.json")
    curr = get_model_config(mid)
    curr.update(data)
    with open(p, "w", encoding="utf-8") as f: json.dump(curr, f, indent=2)
    return curr

def scan_models():
    ms = []
    models_dir = os.path.join(BASE_DIR, "static", "live2d")
    if os.path.exists(models_dir):
        for j in glob.glob(os.path.join(models_dir, "**", "*.model3.json"), recursive=True):
            mid = os.path.basename(os.path.dirname(j))
            cfg = get_model_config(mid)
            ms.append({
                "id": mid, "name": mid.capitalize(),
                "path": "/static/live2d/" + os.path.relpath(j, models_dir),
                **cfg
            })
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
init_model()

import glob

# --- 4. TTS 引擎 (硬编码 Piper 调用) ---
def run_piper_tts(text, output_path):
    # 检查文件
    if not os.path.exists(PIPER_BIN):
        print(f"❌ Piper 引擎没找到: {PIPER_BIN}")
        return False
    if not os.path.exists(GLADOS_MODEL):
        print(f"❌ GlaDOS 模型没找到: {GLADOS_MODEL}")
        # 尝试找一下 static/voices 下的任何 onnx
        onnx_list = glob.glob(os.path.join(BASE_DIR, "static", "voices", "*.onnx"))
        if onnx_list:
            print(f"⚠️ 尝试使用备用模型: {onnx_list[0]}")
            real_model = onnx_list[0]
        else:
            return False
    else:
        real_model = GLADOS_MODEL

    try:
        print(f"🎤 [Piper] 正在生成: {text[:10]}...")
        cmd = [PIPER_BIN, "--model", real_model, "--output_file", output_path]
        
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate(input=text.encode('utf-8'))
        
        if proc.returncode == 0:
            print("✅ [Piper] 生成成功")
            return True
        else:
            print(f"❌ [Piper] 报错: {err.decode()}")
            return False
    except Exception as e:
        print(f"❌ [Piper] 异常: {e}")
        return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}"
    success = False
    url = ""

    # 1. 判断：如果是 GlaDOS，直接走本地 Piper
    if voice == "glados_local":
        out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
        if run_piper_tts(clean, out_path):
            success = True
            url = f"/static/audio/{fname}.wav"
        else:
            print("⚠️ Piper 失败，转 Edge-TTS")

    # 2. 否则走 Edge-TTS
    if not success:
        out_path = os.path.join(AUDIO_DIR, f"{fname}.mp3")
        safe_voice = voice if "Neural" in voice else "zh-CN-XiaoxiaoNeural"
        try:
            async def _run():
                cm = edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); loop.run_until_complete(_run()); loop.close()
            success = True
            url = f"/static/audio/{fname}.mp3"
        except Exception as e: print(f"TTS Error: {e}")

    if success:
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')

# --- 5. 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    r = make_response(render_template('chat.html', ver=SERVER_VERSION))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

# --- SocketIO ---
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
    msg = d['text']
    if "/管理员" in msg:
        if users[sid]['username'].lower() == "yk": users[sid]['is_admin']=True; emit('admin_unlocked'); return
    emit('chat_message', {'text': msg, 'sender': users[sid]['username']}, to='lobby')
    try:
        if not chatroom_chat: init_chatroom()
        resp = chatroom_chat.send_message(f"【{users[sid]['username']}】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt=resp.text.replace(match.group(0),'').strip() if match else resp.text
        if match: emo=match.group(1)
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except Exception as e: print(f"AI: {e}"); init_chatroom()

def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    # 【关键】不再发送列表给前端，前端自己写死
    # 只发送模型数据
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_settings')
def on_save_settings(d):
    global CURRENT_MODEL
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 无权限', 'type': 'error'})
    try: d['scale']=float(d['scale']); d['x']=float(d['x']); d['y']=float(d['y'])
    except: pass
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL.update(updated); init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
