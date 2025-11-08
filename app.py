# =======================================================================
# Pico AI Server - app.py (多人聊天室版)
# 
# 启动命令:
# gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================

import os
import json
import uuid
import asyncio
import eventlet
eventlet.monkey_patch()
import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
# 新增导入 join_room, leave_room
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- 目录与配置 ---
MEMORIES_DIR = "memories"
os.makedirs(MEMORIES_DIR, exist_ok=True)
AUDIO_DIR = os.path.join("static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

CONFIG = {}
try:
    with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里粘贴" not in api_key:
    try: client = genai.Client(api_key=api_key)
    except: print("❌ Gemini 初始化失败")
else: print("❌ 未找到 API Key")

# --- 功能函数 ---
def load_user_memories(username):
    safe_name = "".join([c for c in username if c.isalnum() or c in ('-','_')]).lower() or "default"
    try:
        with open(os.path.join(MEMORIES_DIR, f"{safe_name}.json"), "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_user_memory(username, fact):
    safe_name = "".join([c for c in username if c.isalnum() or c in ('-','_')]).lower() or "default"
    memories = load_user_memories(username)
    if fact not in memories:
        memories.append(fact)
        with open(os.path.join(MEMORIES_DIR, f"{safe_name}.json"), "w", encoding="utf-8") as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        return True
    return False

TTS_VOICE = "zh-CN-XiaoxiaoNeural"
def background_generate_audio(text, room=None, sid=None):
    """后台生成语音，可发送给特定房间或特定用户"""
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    try:
        async def _run():
            cm = edge_tts.Communicate(text, TTS_VOICE)
            await cm.save(filepath)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
        loop.close()
        url = f"/static/audio/{filename}"
        
        # 如果指定了房间，就广播给房间；否则发给个人
        if room:
            socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid:
            socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
            
    except Exception as e: print(f"❌ TTS失败: {e}")

# --- 全局状态 ---
active_users = {} # 存储 {sid: username}
chatroom_chat = None # 全局聊天室会话

# --- 路由 ---
@app.route('/')
def index_redirect(): return redirect(url_for('pico'))

@app.route('/pico')
def pico():
    response = make_response(render_template('chat.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# --- Socket.IO 事件 ---

def init_chatroom():
    """初始化全局聊天室的 AI 会话"""
    global chatroom_chat
    if not client: return
    
    system_prompt = (
        "你是一个名为'Pico'的AI虚拟形象，正在一个多人聊天室中。\n"
        "你会收到格式为【用户A】: 消息内容 的输入。\n"
        "请用中文回复，保持活泼傲娇。回复时尽量提及你在和谁说话，例如：'小明你说得对！'。\n"
        "如果有多人同时说话，你可以一起回复。"
    )
    chatroom_chat = client.chats.create(model="gemini-1.5-flash", config={"system_instruction": system_prompt})
    print("🏠 全局聊天室已初始化")

@socketio.on('login')
def handle_login(data):
    sid = request.sid
    username = data.get('username', 'Anonymous').strip() or "匿名"
    print(f"🔑 用户登录: {username} (SID: {sid})")
    
    active_users[sid] = username
    
    # 1. 加入全局大厅 "lobby"
    join_room('lobby')
    
    # 2. 如果聊天室还没初始化，就初始化一个
    global chatroom_chat
    if not chatroom_chat:
        init_chatroom()
        
    emit('login_success', {'username': username})
    
    # 3. 广播给大厅里的其他人：有人进来了
    emit('system_message', {'text': f"🎉 欢迎 {username} 加入聊天室！"}, to='lobby', include_self=False)
    
    # 4. 给自己发个欢迎语
    emit('response', {'text': f"嗨，{username}！欢迎来到 Pico 的聊天室！", 'sender': 'Pico'})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in active_users:
        username = active_users[sid]
        del active_users[sid]
        # 广播离开消息
        emit('system_message', {'text': f"💨 {username} 离开了聊天室。"}, to='lobby')

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    if sid not in active_users: return
    
    sender_name = active_users[sid]
    msg = data['text']
    
    # 1. 将用户的消息广播给房间里的所有人 (包括自己，这样前端好处理)
    emit('chat_message', {'text': msg, 'sender': sender_name}, to='lobby')
    
    # 2. 构造带用户名的消息发给 AI
    ai_prompt = f"【{sender_name}说】: {msg}"
    
    # 3. 调用 AI 并广播回复
    try:
        if not chatroom_chat: init_chatroom()
        response = chatroom_chat.send_message(ai_prompt)
        
        # 广播文字回复
        emit('response', {'text': response.text, 'sender': 'Pico'}, to='lobby')
        # 广播语音回复
        socketio.start_background_task(background_generate_audio, response.text, room='lobby')
        
    except Exception as e:
        print(f"API Error: {e}")
        emit('system_message', {'text': "⚠️ Pico 大脑掉线了..."}, to='lobby')
