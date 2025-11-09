# =======================================================================
# Pico AI Server - app.py (标准格式稳定版)
# =======================================================================
import os
import json
import uuid
import asyncio
import time
import glob
import shutil
import re

# --- 核心补丁 ---
import eventlet
eventlet.monkey_patch()

import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

# --- 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 目录 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR]:
    os.makedirs(d, exist_ok=True)

# --- 配置加载 (已修复缩进错误) ---
CONFIG = {}
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
    print("✅ 已加载 config.json")
except:
    print("⚠️ 未找到 config.json，使用默认环境")

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

# --- 核心功能 ---
def load_user_memories(username):
    safe_name = "".join([c for c in username if c.isalnum() or c in ('-','_')]).lower() or "default"
    path = os.path.join(MEMORIES_DIR, f"{safe_name}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_user_memory(username, fact):
    safe_name = "".join([c for c in username if c.isalnum() or c in ('-','_')]).lower() or "default"
    path = os.path.join(MEMORIES_DIR, f"{safe_name}.json")
    memories = load_user_memories(username)
    if fact not in memories:
        memories.append(fact)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        return True
    return False

CURRENT_MODEL = {"id": "default", "path": "", "persona": ""}

def scan_models():
    models = []
    for m_json in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        m_dir = os.path.dirname(m_json)
        m_id = os.path.basename(m_dir)
        p_path = os.path.join(m_dir, "persona.txt")
        # 确保人设文件存在
        if not os.path.exists(p_path):
            with open(p_path, "w", encoding="utf-8") as f:
                f.write(f"你是一个名为'{m_id.capitalize()}'的AI虚拟主播。请用中文简短回复，性格活泼。每句话开头加上情感标签如 [HAPPY], [ANGRY] 等。")
        
        with open(p_path, "r", encoding="utf-8") as f:
            persona = f.read()
            
        web_path = "/" + os.path.relpath(m_json, BASE_DIR).replace("\\", "/")
        models.append({"id": m_id, "name": m_id.capitalize(), "path": web_path, "persona": persona})
    return sorted(models, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    # 优先使用 Hiyori，如果没有就用列表第一个
    target = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if target:
        CURRENT_MODEL = target
    print(f"🤖 当前模型: {CURRENT_MODEL.get('id')}")

init_model()

# --- 语音合成 ---
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
def bg_tts(text, room=None, sid=None):
    clean_text = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean_text:
        return
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    try:
        async def _run():
            cm = edge_tts.Communicate(clean_text, TTS_VOICE)
            await cm.save(filepath)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
        loop.close()
        
        url = f"/static/audio/{filename}"
        if room:
            socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid:
            socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
    except Exception as e:
        print(f"TTS Error: {e}")

# --- 路由 ---
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
    return response

# --- Socket.IO 事件 ---
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
        print(f"🏠 聊天室已重置 (人设: {CURRENT_MODEL['name']})")
    except Exception as e:
        print(f"❌ 聊天室初始化失败: {e}")

@socketio.on('connect')
def on_connect():
    emit('server_ready', {'status': 'ok'})

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        username = users.pop(request.sid)
        emit('system_message', {'text': f"💨 {username} 离开了。"}, to='lobby')

@socketio.on('login')
def on_login(data):
    username = data.get('username', 'Anonymous').strip() or "匿名"
    users[request.sid] = username
    join_room('lobby')
    
    global chatroom_chat
    if not chatroom_chat:
        init_chatroom()
        
    emit('login_success', {'username': username, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 欢迎 {username} 加入！"}, to='lobby', include_self=False)
    
    welcome = f"[HAPPY] 嗨 {username}，欢迎！\n我是{CURRENT_MODEL['name']}，点右上角【🎯】可以让我归位，点【🛠️】可以换人哦！"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, sid=request.sid)

@socketio.on('message')
def on_message(data):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]
    msg = data['text']

    if msg.startswith("/记 "):
        fact = msg[3:].strip()
        if fact and save_user_memory(sender, fact):
             emit('response', {'text': f"🧠 好的 {sender}，记住了！", 'sender': 'Pico'}, to=sid)
        return

    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    
    try:
        global chatroom_chat
        if not chatroom_chat: init_chatroom()
        
        memories = load_user_memories(sender)
        mem_ctx = f" ({CURRENT_MODEL['name']}记得: {', '.join(memories[-2:])})" if memories else ""
        
        response = chatroom_chat.send_message(f"【{sender}说{mem_ctx}】: {msg}")
        
        emotion = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', response.text)
        display_text = response.text
        if match:
            emotion = match.group(1)
            display_text = response.text.replace(match.group(0), '').strip()

        emit('response', {'text': display_text, 'sender': 'Pico', 'emotion': emotion}, to='lobby')
        socketio.start_background_task(bg_tts, display_text, room='lobby')
        
    except Exception as e:
        print(f"AI Error: {e}")
        # 如果出错，可能是会话过期，尝试重置
        init_chatroom()

# --- 工作室接口 ---
@socketio.on('get_studio_data')
def on_get_studio_data():
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})

@socketio.on('switch_model')
def on_switch_model(data):
    global CURRENT_MODEL
    target = next((m for m in scan_models() if m['id'] == data['id']), None)
    if target:
        CURRENT_MODEL = target
        init_chatroom() # 切换模型要重置聊天室人设
        emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_persona')
def on_save_persona(data):
    model_id = data['id']
    new_text = data['text']
    path = os.path.join(MODELS_DIR, model_id, "persona.txt")
    if os.path.exists(os.path.dirname(path)):
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        if CURRENT_MODEL['id'] == model_id:
            CURRENT_MODEL['persona'] = new_text
            init_chatroom()
        emit('toast', {'text': '✅ 人设已保存'})

@socketio.on('delete_model')
def on_delete_model(data):
    if data['id'] == CURRENT_MODEL['id']:
        emit('toast', {'text': '❌ 不能删除当前模型', 'type': 'error'})
        return
    try:
        shutil.rmtree(os.path.join(MODELS_DIR, data['id']))
        emit('toast', {'text': '🗑️ 已删除'})
        emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
    except:
        emit('toast', {'text': '删除失败', 'type': 'error'})

# 后台下载任务
def bg_download_task(name):
    urls = {
        "Mao": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Mao",
        "Natori": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Natori",
        "Rice": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Rice",
        "Wanko": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Wanko"
    }
    url = urls.get(name)
    if not url: return

    target_dir = os.path.join(MODELS_DIR, name.lower())
    if os.path.exists(target_dir): shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    
    try:
        print(f"⬇️ 开始下载 {name}...")
        # 使用 SVN 下载，简单直接
        if os.system(f"svn export --force -q {url} {target_dir}") == 0:
            print(f"✅ {name} 下载成功")
            socketio.emit('toast', {'text': f'🎉 {name} 就位!'}, namespace='/')
        else:
            raise Exception("SVN 失败")
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        socketio.emit('toast', {'text': f'❌ {name} 下载失败', 'type': 'error'}, namespace='/')

@socketio.on('download_model')
def on_download_model(data):
    name = data.get('name')
    if name:
        emit('toast', {'text': f'🚀 开始下载 {name}...', 'type': 'info'})
        socketio.start_background_task(bg_download_task, name)
