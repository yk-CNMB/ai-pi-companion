# =======================================================================
# Pico AI Server - app.py (终极版 + 模型管理)
# 
# 启动命令: gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================

import os
import json
import uuid
import asyncio
import time
import glob # 新增：用于文件扫描

import eventlet
eventlet.monkey_patch()
import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

# --- 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
SERVER_VERSION = str(int(time.time()))

# --- 目录 & 配置 ---
os.makedirs("memories", exist_ok=True)
os.makedirs("static/audio", exist_ok=True)
CONFIG = {}
try:
    with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里" not in api_key:
    try: client = genai.Client(api_key=api_key)
    except: print("❌ Gemini 初始化失败")
else: print("❌ 未找到 API KEY")

# --- 模型管理核心 ---
CURRENT_MODEL_PATH = "" # 当前选中的模型路径

def scan_models():
    """扫描 static/live2d 目录下所有的 .model3.json 文件"""
    models = []
    # 递归查找所有 .model3.json 文件
    for model_file in glob.glob("static/live2d/**/*.model3.json", recursive=True):
        # 转换为相对于 static 的 Web 路径
        web_path = "/" + model_file.replace("\\", "/")
        # 用文件夹名作为模型名称 (例如 static/live2d/Haru/Haru.model3.json -> Haru)
        model_name = os.path.basename(os.path.dirname(model_file))
        models.append({"name": model_name, "path": web_path})
    return sorted(models, key=lambda x: x['name'])

# 初始化默认模型 (优先找 Hiyori，找不到就用第一个)
available_models = scan_models()
if available_models:
    # 尝试找到 Hiyori
    hiyori = next((m for m in available_models if "hiyori" in m['name'].lower()), None)
    CURRENT_MODEL_PATH = hiyori['path'] if hiyori else available_models[0]['path']
    print(f"🤖 默认模型已设置为: {CURRENT_MODEL_PATH}")

# --- 功能函数 ---
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
def bg_tts(text, room=None, sid=None):
    fname = f"{uuid.uuid4()}.mp3"
    fpath = os.path.join("static/audio", fname)
    try:
        async def _run():
            cm = edge_tts.Communicate(text, TTS_VOICE)
            await cm.save(fpath)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
        loop.close()
        url = f"/static/audio/{fname}"
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
    except Exception as e: print(f"TTS Error: {e}")

# --- 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico')
def pico(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    if v!=SERVER_VERSION: return redirect(url_for('pico_v', v=SERVER_VERSION))
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

# --- SocketIO ---
users = {}
chat = None

@socketio.on('login')
def on_login(d):
    sid, name = request.sid, d.get('username','').strip() or "匿名"
    users[sid] = name
    join_room('lobby')
    emit('login_success', {'username': name, 'current_model': CURRENT_MODEL_PATH}) # 发送当前模型
    emit('sys', {'text': f"🎉 {name} 加入了！"}, to='lobby', include_self=False)

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        name = users.pop(request.sid)
        leave_room('lobby')
        emit('sys', {'text': f"💨 {name} 离开了。"}, to='lobby')

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    msg = d['text']
    emit('chat', {'text': msg, 'sender': users[sid]}, to='lobby')
    
    global chat
    try:
        if not chat and client:
            chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": "你是Pico，一个活泼可爱的虚拟主播。请用中文简短回复，每句话开头加上情感标签：[HAPPY],[ANGRY],[SAD],[SHOCK],[NORMAL]。"})
        
        if chat:
            resp = chat.send_message(f"【{users[sid]}说】: {msg}")
            # 解析情感
            import re
            emo = 'NORMAL'
            match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
            clean_text = resp.text
            if match:
                emo = match.group(1)
                clean_text = resp.text.replace(match.group(0), '').strip()
            
            emit('response', {'text': clean_text, 'sender': 'Pico', 'emotion': emo}, to='lobby')
            socketio.start_background_task(bg_tts, clean_text, room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        emit('sys', {'text': "⚠️ 大脑短路中..."}, to='lobby')

# --- 新增：模型管理事件 ---
@socketio.on('get_models')
def on_get_models():
    """前端请求可用模型列表"""
    # 重新扫描，以便发现新加的模型
    models = scan_models()
    emit('models_list', {'models': models, 'current': CURRENT_MODEL_PATH})

@socketio.on('change_model')
def on_change_model(data):
    """前端请求切换模型"""
    global CURRENT_MODEL_PATH
    new_path = data.get('path')
    if new_path:
        CURRENT_MODEL_PATH = new_path
        print(f"🔄 模型切换为: {new_path}")
        # 广播给所有人切换模型！
        emit('model_changed', {'path': CURRENT_MODEL_PATH}, to='lobby')
