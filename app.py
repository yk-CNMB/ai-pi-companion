# =======================================================================
# Pico AI Server - app.py (情感引擎 + 口型同步支持版)
# 
# 启动命令:
# gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================

import os
import json
import uuid
import asyncio
import time
import re # 新增：用于解析情感标签

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

# --- 目录 ---
os.makedirs("memories", exist_ok=True)
AUDIO_DIR = os.path.join("static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# --- 配置 ---
CONFIG = {}
try:
    with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里粘贴" not in api_key:
    client = genai.Client(api_key=api_key)
else:
    client = None
    print("❌ 未找到有效 API KEY")

# --- 核心函数 ---
TTS_VOICE = "zh-CN-XiaoxiaoNeural"

def background_generate_audio(text, room=None, sid=None):
    """后台生成语音"""
    # 如果文本里还有残留的情感标签，清理掉再读，防止读出 "[HAPPY]"
    clean_text = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean_text: return # 如果没话可读就跳过

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
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
    except Exception as e: print(f"❌ TTS失败: {e}")

# --- 路由 ---
@app.route('/')
def index_redirect(): return redirect(url_for('pico_dynamic', version=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_dynamic', version=SERVER_VERSION))
@app.route('/pico/<version>')
def pico_dynamic(version):
    if version != SERVER_VERSION: return redirect(url_for('pico_dynamic', version=SERVER_VERSION))
    response = make_response(render_template('chat.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# --- Socket.IO ---
active_users = {}
chatroom_chat = None

def init_chatroom():
    global chatroom_chat
    if not client: return
    # 【关键修改】系统提示词增加了情感指令
    prompt = (
        "你是一个名为'Pico'的AI虚拟主播，正在直播间和大家聊天。\n"
        "请用中文回复，保持活泼、傲娇、表情丰富的性格。\n"
        "【重要】你必须在每句话的开头加上唯一的情感标签，格式为 [EMOTION]。\n"
        "可选标签: [HAPPY] (开心/大笑), [ANGRY] (生气/吐槽), [SAD] (悲伤/同情), [SHOCK] (惊讶/没想到), [NORMAL] (平静/普通)。\n"
        "例如: [HAPPY] 哈哈，你说得太对了！\n"
        "例如: [ANGRY] 哼，我才没有笨手笨脚呢！"
    )
    chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": prompt})
    print("🏠 情感引擎已加载 (v2.5)")

@socketio.on('login')
def handle_login(data):
    sid = request.sid
    username = data.get('username', 'Anonymous').strip() or "匿名"
    active_users[sid] = username
    join_room('lobby')
    
    global chatroom_chat
    if not chatroom_chat: init_chatroom()
        
    emit('login_success', {'username': username})
    emit('system_message', {'text': f"🎉 欢迎 {username} 进入直播间！"}, to='lobby', include_self=False)
    
    welcome = "嗨，欢迎来到 Pico 的直播间！"
    # 开场白默认开心
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'})
    socketio.start_background_task(background_generate_audio, welcome, sid=sid)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in active_users:
        username = active_users.pop(request.sid)
        leave_room('lobby')
        emit('system_message', {'text': f"💨 {username} 离开了。"}, to='lobby')

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    if sid not in active_users: return
    sender = active_users[sid]
    msg = data['text']
    
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    
    try:
        if not chatroom_chat: init_chatroom()
        response = chatroom_chat.send_message(f"【{sender}说】: {msg}")
        raw_text = response.text
        
        # 【核心逻辑】解析情感标签
        emotion = 'NORMAL' # 默认情感
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', raw_text)
        if match:
            emotion = match.group(1)
            # 把标签从显示的文字中去掉，不然看起来很怪
            display_text = raw_text.replace(match.group(0), '').strip()
        else:
            display_text = raw_text

        # 发送带有 emotion 字段的回复
        emit('response', {'text': display_text, 'sender': 'Pico', 'emotion': emotion}, to='lobby')
        # 语音读的是干净的文本
        socketio.start_background_task(background_generate_audio, display_text, room='lobby')
        
    except Exception as e:
        print(f"API Error: {e}")
        emit('system_message', {'text': "⚠️ Pico 大脑短路中..."}, to='lobby')

