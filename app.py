# =======================================================================
# Pico AI Server - app.py (语法修复完整版)
# =======================================================================

import os
import json
import uuid
import asyncio
import time
import glob
import shutil
import re

# 【关键】导入 eventlet 并打补丁
import eventlet
eventlet.monkey_patch()

import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

# --- 1. 初始化框架 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)

# 服务器版本号
SERVER_VERSION = str(int(time.time()))

# --- 2. 创建必要目录 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")

os.makedirs(MEMORIES_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

# --- 3. 加载配置与 API ---
CONFIG = {}
# 【修复】这里必须换行写
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
    print("✅ 已加载 config.json")
except FileNotFoundError:
    print("⚠️ 未找到 config.json")

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里粘贴" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini API 就绪")
    except Exception as e:
        print(f"❌ Gemini 初始化失败: {e}")
else:
    print("❌ 未找到有效的 GEMINI_API_KEY")

# =========================================
# 🧠 模型与人设管理器
# =========================================
CURRENT_MODEL = {"id": "default", "path": "", "persona": ""}

def get_default_persona(model_name):
    return f"你是一个名为'{model_name}'的AI虚拟主播。请用中文简短回复，活泼可爱。每句话开头加上情感标签如 [HAPPY], [ANGRY] 等。"

def scan_models():
    """扫描所有可用模型及其人设"""
    models = []
    for model_json in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        model_dir = os.path.dirname(model_json)
        model_id = os.path.basename(model_dir)
        persona_path = os.path.join(model_dir, "persona.txt")
        
        if not os.path.exists(persona_path):
            with open(persona_path, "w", encoding="utf-8") as f:
                f.write(get_default_persona(model_id.capitalize()))
        
        with open(persona_path, "r", encoding="utf-8") as f:
            persona = f.read()
        
        web_path = "/" + os.path.relpath(model_json, BASE_DIR).replace("\\", "/")
        models.append({"id": model_id, "name": model_id.capitalize(), "path": web_path, "persona": persona})
    
    return sorted(models, key=lambda x: x['name'])

def init_current_model():
    models = scan_models()
    global CURRENT_MODEL
    target = next((m for m in models if "hiyori" in m['id'].lower()), models[0] if models else None)
    if target:
        CURRENT_MODEL = target
    print(f"🤖 当前模型: {CURRENT_MODEL.get('id')}")

init_current_model()

# --- 4. 语音合成 (TTS) ---
TTS_VOICE = "zh-CN-XiaoxiaoNeural"

def background_generate_audio(text, room=None, sid=None):
    clean_text = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean_text:
        return

    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    
    try:
        async def _run_tts():
            communicate = edge_tts.Communicate(clean_text, TTS_VOICE)
            await communicate.save(filepath)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_tts())
        loop.close()
        
        url = f"/static/audio/{filename}"
        if room:
            socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid:
            socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
            
    except Exception as e:
        print(f"❌ TTS失败: {e}")

# --- 5. Web 路由 ---
@app.route('/')
def index_redirect():
    return redirect(url_for('pico_dynamic', version=SERVER_VERSION))

@app.route('/pico')
def pico_legacy():
    return redirect(url_for('pico_dynamic', version=SERVER_VERSION))

@app.route('/pico/<version>')
def pico_dynamic(version):
    if version != SERVER_VERSION:
        return redirect(url_for('pico_dynamic', version=SERVER_VERSION))
    response = make_response(render_template('chat.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# --- 6. Socket.IO 事件 ---
users = {}
chatroom_chat = None

@socketio.on('connect')
def handle_connect():
    emit('server_ready', {'status': 'ok'})

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in users:
        username = users.pop(request.sid)
        leave_room('lobby')
        emit('system_message', {'text': f"💨 {username} 离开了。"}, to='lobby')

@socketio.on('login')
def handle_login(data):
    username = data.get('username', 'Anonymous').strip() or "匿名"
    users[request.sid] = username
    join_room('lobby')
    
    emit('login_success', {'username': username, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 欢迎 {username} 加入！"}, to='lobby', include_self=False)

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    if sid not in users:
        return
    
    sender = users[sid]
    msg = data['text']
    
    # 广播用户消息
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    
    try:
        # 使用当前模型的人设创建会话
        chat = client.chats.create(
            model="gemini-2.5-flash",
            config={"system_instruction": CURRENT_MODEL['persona']}
        )
        response = chat.send_message(f"【{sender}说】: {msg}")
        
        # 解析情感
        emotion = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', response.text)
        display_text = response.text
        if match:
            emotion = match.group(1)
            display_text = response.text.replace(match.group(0), '').strip()
            
        # 广播回复
        emit('response', {'text': display_text, 'sender': 'Pico', 'emotion': emotion}, to='lobby')
        socketio.start_background_task(background_generate_audio, display_text, room='lobby')
        
    except Exception as e:
        print(f"API Error: {e}")
        emit('system_message', {'text': "⚠️ 大脑短路中..."}, to='lobby')

# --- 7. 工作室管理接口 ---
@socketio.on('get_studio_data')
def handle_get_studio_data():
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})

@socketio.on('switch_model')
def handle_switch_model(data):
    global CURRENT_MODEL
    target = next((m for m in scan_models() if m['id'] == data['id']), None)
    if target:
        CURRENT_MODEL = target
        emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_persona')
def handle_save_persona(data):
    model_id = data['id']
    new_text = data['text']
    model_path = os.path.join(MODELS_DIR, model_id)
    if os.path.exists(model_path):
        with open(os.path.join(model_path, "persona.txt"), "w", encoding="utf-8") as f:
            f.write(new_text)
        if CURRENT_MODEL['id'] == model_id:
            CURRENT_MODEL['persona'] = new_text
        emit('toast', {'text': '✅ 人设已保存', 'type': 'success'})

@socketio.on('delete_model')
def handle_delete_model(data):
    if data['id'] == CURRENT_MODEL['id']:
        emit('toast', {'text': '❌ 不能删除当前模型', 'type': 'error'})
        return
    try:
        shutil.rmtree(os.path.join(MODELS_DIR, data['id']))
        emit('toast', {'text': '🗑️ 模型已删除', 'type': 'success'})
        emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
    except Exception as e:
        emit('toast', {'text': f'删除失败: {e}', 'type': 'error'})

# 后台下载任务
def bg_download_task(url, name):
    try:
        target_dir = os.path.join(MODELS_DIR, name.lower())
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        # 创建父目录
        os.makedirs(target_dir, exist_ok=True)
        # 使用 svn export
        os.system(f"svn export --force -q {url} {target_dir}")
        print(f"✅ {name} 下载完成")
        socketio.emit('toast', {'text': f'🎉 {name} 下载完成！', 'type': 'success'}, namespace='/')
    except Exception as e:
        print(f"❌ 下载失败: {e}")

@socketio.on('download_model')
def handle_download_model(data):
    presets = {
        "Mao": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Mao",
        "Natori": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Natori",
        "Rice": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Rice",
        "Wanko": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Wanko"
    }
    url = presets.get(data['name'])
    if url:
        emit('toast', {'text': f'🚀 开始下载 {data["name"]}...', 'type': 'info'})
        socketio.start_background_task(bg_download_task, url, data['name'])
    else:
        emit('toast', {'text': '未知模型', 'type': 'error'})
