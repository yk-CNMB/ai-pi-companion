# =======================================================================
# Pico AI Server - app.py (终极全功能版: 语音 + 记忆 + 多人聊天室)
# 
# 启动命令 (确保在 .venv 虚拟环境下):
# gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================

import os
import json
import uuid
import asyncio
import time

# 【关键】导入 eventlet 并打补丁，确保高并发下的稳定性
import eventlet
eventlet.monkey_patch()

import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

# --- 1. 初始化框架 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
# 强制使用 eventlet 作为异步模式
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 服务器版本号 (用于防缓存)
SERVER_VERSION = str(int(time.time()))

# --- 2. 创建必要目录 ---
MEMORIES_DIR = "memories"
os.makedirs(MEMORIES_DIR, exist_ok=True)

AUDIO_DIR = os.path.join("static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# --- 3. 加载配置与 API ---
CONFIG = {}
try:
    with open("config.json", "r") as f: CONFIG = json.load(f)
    print("✅ 已加载 config.json")
except: print("⚠️ 未找到 config.json")

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里粘贴" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini API 就绪")
    except Exception as e: print(f"❌ Gemini 初始化失败: {e}")
else:
    print("❌ 未找到有效的 GEMINI_API_KEY")

# --- 4. 核心功能函数 (记忆 & TTS) ---

def load_user_memories(username):
    """加载指定用户的记忆列表"""
    safe_name = "".join([c for c in username if c.isalnum() or c in ('-','_')]).lower()
    if not safe_name: safe_name = "default"
    path = os.path.join(MEMORIES_DIR, f"{safe_name}.json")
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_user_memory(username, fact):
    """保存一条新记忆"""
    safe_name = "".join([c for c in username if c.isalnum() or c in ('-','_')]).lower()
    if not safe_name: safe_name = "default"
    path = os.path.join(MEMORIES_DIR, f"{safe_name}.json")
    memories = load_user_memories(username)
    if fact not in memories:
        memories.append(fact)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        return True
    return False

TTS_VOICE = "zh-CN-XiaoxiaoNeural" # 可选语音

def background_generate_audio(text, room=None, sid=None):
    """【后台任务】生成语音并发送给指定房间(room)或个人(sid)"""
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    try:
        print(f"🎵 [TTS] 开始生成...")
        async def _run():
            cm = edge_tts.Communicate(text, TTS_VOICE)
            await cm.save(filepath)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
        loop.close()
        
        url = f"/static/audio/{filename}"
        # 根据参数决定发给谁
        if room:
            socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
            print(f"✅ [TTS] 广播给房间 {room}: {url}")
        elif sid:
            socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
            print(f"✅ [TTS] 发送给个人 {sid[:4]}: {url}")
            
    except Exception as e:
        print(f"❌ [TTS] 失败: {e}")

# --- 全局状态 ---
active_users = {}     # {sid: username} 存储所有在线用户
chatroom_chat = None  # 全局聊天室的 Gemini 会话

# --- 5. Web 路由 (防缓存) ---

@app.route('/')
def index_redirect():
    """强制将旧网址重定向到带版本号的新网址"""
    return redirect(url_for('pico_dynamic', version=SERVER_VERSION))

@app.route('/pico')
def pico_legacy():
    """旧的 /pico 也重定向"""
    return redirect(url_for('pico_dynamic', version=SERVER_VERSION))

@app.route('/pico/<version>')
def pico_dynamic(version):
    """主界面，URL 包含版本号，强制禁用缓存"""
    if version != SERVER_VERSION:
        return redirect(url_for('pico_dynamic', version=SERVER_VERSION))
        
    response = make_response(render_template('chat.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# --- 6. Socket.IO 事件 (聊天室核心逻辑) ---

def init_chatroom():
    """初始化全局聊天室"""
    global chatroom_chat
    if not client: return
    system_prompt = (
        "你是一个名为'Pico'的AI虚拟形象，正在一个多人聊天室中。\n"
        "你会收到格式为【用户A】: 消息内容 的输入。\n"
        "请用中文回复，保持活泼傲娇。回复时尽量提及你在和谁说话，例如：'小明你说得对！'。\n"
        "回复要简短口语化，方便语音合成。"
    )
    chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": system_prompt})
    print("🏠 全局聊天室已初始化")

@socketio.on('login')
def handle_login(data):
    sid = request.sid
    username = data.get('username', 'Anonymous').strip() or "匿名"
    print(f"🔑 用户登录: {username}")
    
    active_users[sid] = username
    join_room('lobby') # 加入全局大厅
    
    global chatroom_chat
    if not chatroom_chat: init_chatroom()
        
    # 1. 通知自己登录成功
    emit('login_success', {'username': username})
    
    # 2. 广播给大厅里的其他人
    emit('system_message', {'text': f"🎉 欢迎 {username} 加入聊天室！"}, to='lobby', include_self=False)
    
    # 3. 给自己发欢迎语 (带语音)
    welcome = f"嗨，{username}！欢迎来到 Pico 聊天室！"
    emit('response', {'text': welcome, 'sender': 'Pico'})
    socketio.start_background_task(background_generate_audio, welcome, sid=sid)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in active_users:
        username = active_users[sid]
        del active_users[sid]
        leave_room('lobby')
        # 广播离开消息
        emit('system_message', {'text': f"💨 {username} 离开了聊天室。"}, to='lobby')

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    if sid not in active_users: return
    sender = active_users[sid]
    msg = data['text']
    
    # --- 特殊指令：/记 (依然支持！) ---
    if msg.startswith("/记 "):
        fact = msg[3:].strip()
        if fact and save_user_memory(sender, fact):
             # 只发给自己，不广播
             emit('response', {'text': f"🧠 好的，{sender}，我私下记住了：{fact}", 'sender': 'Pico'})
        return

    # --- 普通聊天消息 ---
    
    # 1. 广播用户的原始消息给所有人 (前端自己判断是 self 还是 other)
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    
    # 2. 尝试读取发送者的记忆，增强 AI 回复
    user_memories = load_user_memories(sender)
    memory_context = ""
    if user_memories:
         memory_context = f"(Pico记得关于{sender}的事: {', '.join(user_memories[-3:])})"

    # 3. 构造带上下文的 Prompt 发给 AI
    ai_prompt = f"【{sender}说】: {msg} {memory_context}"
    
    try:
        if not chatroom_chat: init_chatroom()
        response = chatroom_chat.send_message(ai_prompt)
        
        # 广播 AI 的文字回复
        emit('response', {'text': response.text, 'sender': 'Pico'}, to='lobby')
        # 广播 AI 的语音回复
        socketio.start_background_task(background_generate_audio, response.text, room='lobby')
        
    except Exception as e:
        print(f"API Error: {e}")
        emit('system_message', {'text': "⚠️ Pico 大脑掉线了..."}, to='lobby')

