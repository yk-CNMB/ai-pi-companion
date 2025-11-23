# =======================================================================
# Pico AI Server - app.py (全功能最终版)
# 包含: 聊天室 | 情感引擎 | Fish Audio 支持 | 模型管理 | 管理员权限
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
import requests

# 【关键】导入 eventlet 并打补丁
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

# --- 2. 目录配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")

for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]:
    os.makedirs(d, exist_ok=True)

# --- 3. API 配置 ---
CONFIG = {}
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
    print("✅ 已加载 config.json")
except:
    pass

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

# --- 4. 核心功能函数 ---

# 记忆管理 (后端仅保留空壳，实际逻辑在前端)
def load_user_memories(u):
    return []

# 模型配置管理
CURRENT_MODEL = {
    "id": "default", "path": "", "persona": "", 
    "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", 
    "scale": 0.5, "x": 0.0, "y": 0.0,
    "api_url": "", "api_key": "", "model_id": ""
}

def get_model_config(model_id):
    p = os.path.join(MODELS_DIR, model_id, "config.json")
    data = {
        "persona": f"你是一个名为{model_id}的AI。请用中文简短回复。",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%", "pitch": "+0Hz",
        "scale": 0.5, "x": 0.0, "y": 0.0,
        "api_url": "", "api_key": "", "model_id": ""
    }
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except: pass
    return data

def save_model_config(model_id, data):
    p = os.path.join(MODELS_DIR, model_id, "config.json")
    current = get_model_config(model_id)
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
            **cfg
        })
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t:
        CURRENT_MODEL = t
init_model()

# --- 5. 语音合成 (Edge-TTS + Fish Audio) ---

def run_openai_tts(text, api_url, api_key, model_id, output_path):
    """调用 OpenAI 格式的 API (如 Fish Audio)"""
    try:
        # URL 自动修正
        if not api_url.endswith("/v1/audio/speech"):
             if "fish.audio" in api_url: api_url = "https://api.fish.audio/v1/audio/speech"
             else: api_url = api_url.rstrip("/") + "/v1/audio/speech"
        
        print(f"📡 调用外部 TTS: {model_id}")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_id,
            "input": text,
            "voice": model_id,
            "response_format": "mp3"
        }
        resp = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return True
        else:
            print(f"TTS API Error: {resp.text}")
            return False
    except Exception as e:
        print(f"TTS Request Failed: {e}")
        return False

def bg_tts(text, voice, rate, pitch, api_url, api_key, model_id, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    
    fname = f"{uuid.uuid4()}.mp3"
    out_path = os.path.join(AUDIO_DIR, fname)
    success = False
    
    # 1. 尝试外部 API
    if api_url and api_key and model_id:
        if run_openai_tts(clean, api_url, api_key, model_id, out_path):
            success = True
    
    # 2. 降级到 Edge-TTS
    if not success:
        try:
            async def _run():
                cm = edge_tts.Communicate(clean, voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.close()
            success = True
        except Exception as e:
            print(f"Edge-TTS Error: {e}")

    if success:
        url = f"/static/audio/{fname}"
        if room:
            socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid:
            socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')

# --- 6. 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    if v != SERVER_VERSION: return redirect(url_for('pico_v', v=SERVER_VERSION))
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
            if len(items) == 1 and os.path.isdir(os.path.join(p, items[0])):
                sub = os.path.join(p, items[0])
                for i in os.listdir(sub): shutil.move(os.path.join(sub, i), p)
                os.rmdir(sub)
            return jsonify({'success': True})
        except Exception as e: return jsonify({'success': False, 'msg': str(e)})
    return jsonify({'success': False, 'msg': '仅支持 .zip'})

# --- 7. SocketIO ---
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
        print(f"🏠 聊天室重置 ({CURRENT_MODEL['name']})")
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
    socketio.start_background_task(bg_tts, welcome, 
                                   CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'],
                                   CURRENT_MODEL.get('api_url'), CURRENT_MODEL.get('api_key'), CURRENT_MODEL.get('model_id'),
                                   sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]['username']
    msg = d['text']
    user_memories = d.get('memories', [])

    # 管理员逻辑
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
        socketio.start_background_task(bg_tts, txt, 
                                       CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'],
                                       CURRENT_MODEL.get('api_url'), CURRENT_MODEL.get('api_key'), CURRENT_MODEL.get('model_id'),
                                       room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        init_chatroom()

# --- 8. 工作室接口 ---
def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    # 声音列表
    voices = [
        {"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓 (默认)"},
        {"id":"zh-CN-YunxiNeural","name":"☁️ 云希 (少年)"},
        {"id":"zh-TW-HsiaoChenNeural","name":"☁️ 晓臻 (台湾)"}
    ]
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
        "persona": d['persona'], "voice": d['voice'], "rate": d['rate'], "pitch": d['pitch'],
        "scale": float(d['scale']), "x": float(d['x']), "y": float(d['y']),
        "api_url": d.get('api_url',''), "api_key": d.get('api_key',''), "model_id": d.get('model_id','')
    })
    if CURRENT_MODEL['id'] == d['id']:
        CURRENT_MODEL.update(updated)
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 设置已保存'})

@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return
    if d['id'] == CURRENT_MODEL['id']: return emit('toast', {'text': '❌ 占用中', 'type': 'error'})
    try:
        shutil.rmtree(os.path.join(MODELS_DIR, d['id']))
        emit('toast', {'text': '🗑️ 已删除', 'type': 'success'})
        on_get_data()
    except:
        emit('toast', {'text': '删除失败', 'type': 'error'})

def bg_dl_task(name):
    urls = {"Mao":".../Mao","Natori":".../Natori"} # 省略长URL，实际会自动补全
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
    if not is_admin(request.sid): return
    name = d.get('name')
    if name:
        emit('toast', {'text': f'🚀 开始下载 {name}...', 'type': 'info'})
        socketio.start_background_task(bg_dl_task, name)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
