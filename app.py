# =======================================================================
# Pico AI Server - app.py (终极自动化版)
# 
# 启动命令:
# gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================

import os
import json
import uuid
import asyncio
import time # 新增：用于生成时间戳版本号

# 【关键】导入 eventlet 并打补丁
import eventlet
eventlet.monkey_patch()

import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit
from google import genai

# --- 1. 初始化与自动化版本号 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 【核心魔法】每次服务器重启，这个版本号都会变！
# 它是一个基于当前时间戳的字符串，例如 "1731081600"
SERVER_VERSION = str(int(time.time()))
print(f"🚀 服务器已启动！当前版本号: {SERVER_VERSION}")

# --- 2. 目录与配置 ---
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
    except Exception as e: print(f"❌ Gemini 初始化失败: {e}")
else: print("❌ 未找到 GEMINI_API_KEY")

# --- 3. 功能函数 (记忆 & TTS) ---
# (这部分代码与之前相同，为了节省篇幅，我简写了，请确保你用的是完整的)
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
def background_generate_audio(sid, text):
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
        socketio.emit('audio_response', {'audio': f"/static/audio/{filename}"}, to=sid, namespace='/')
    except Exception as e: print(f"❌ TTS失败: {e}")

active_sessions = {}

# --- 4. 智能路由 (核心改动) ---

@app.route('/')
def index_root():
    """根路由：永远自动跳转到最新的版本号 URL"""
    # 自动跳到 /pico/1731081600 这样的网址
    return redirect(url_for('pico_dynamic', version=SERVER_VERSION))

@app.route('/pico')
def pico_legacy():
    """旧路由：也自动跳转到最新版本号"""
    return redirect(url_for('pico_dynamic', version=SERVER_VERSION))

# 新的动态路由，URL 里包含版本号
@app.route('/pico/<version>')
def pico_dynamic(version):
    """
    真正的处理函数。
    虽然 URL 变了，但它们都加载同一个 templates/chat.html 文件。
    浏览器看到 URL 变了，就会乖乖地重新加载，不会用缓存。
    """
    # 如果用户访问了旧的版本号，自动把他踢到最新的
    if version != SERVER_VERSION:
        return redirect(url_for('pico_dynamic', version=SERVER_VERSION))

    response = make_response(render_template('chat.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# --- 5. Socket.IO 事件 (保持不变) ---
# (为了完整性，请确保你复制了完整的 handle_login, handle_disconnect, handle_message 函数)
# ... (此处省略了与之前完全相同的 Socket.IO 代码，实际使用时请保留) ...
@socketio.on('login')
def handle_login(data):
    sid = request.sid
    username = data.get('username', 'Anonymous').strip() or "匿名"
    print(f"🔑 用户登录: {username}")
    try:
        if not client: raise Exception("API 未连接")
        memories = load_user_memories(username)
        mem_str = "\n".join([f"- {m}" for m in memories]) if memories else "暂无"
        system_prompt = (
            f"你是一个名为'Pico'的AI虚拟形象。正在和【{username}】聊天。\n"
            f"【{username} 的记忆】\n{mem_str}\n\n"
            "请用中文回复，保持活泼傲娇。回复尽量简短口语化，因为你要把这些话读出来。"
        )
        chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": system_prompt})
        active_sessions[sid] = {'chat': chat, 'username': username}
        emit('login_success', {'username': username})
        socketio.sleep(0.5)
        welcome = f"嗨，{username}！Pico 准备好啦！(v{SERVER_VERSION})" # 欢迎语里也加上版本号，方便确认
        emit('response', {'text': welcome, 'sender': 'Pico'})
        socketio.start_background_task(background_generate_audio, sid, welcome)
    except Exception as e:
        print(f"❌ 登录错: {e}")
        emit('login_failed', {'error': str(e)})

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in active_sessions: del active_sessions[request.sid]

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    if sid not in active_sessions:
        emit('response', {'text': "⚠️ 请刷新重新登录", 'sender': 'Pico'})
        return
    user = active_sessions[sid]['username']
    msg = data['text']
    if msg.startswith("/记 "):
        fact = msg[3:].strip()
        if fact and save_user_memory(user, fact):
             emit('response', {'text': f"🧠 好的，记住了：{fact}", 'sender': 'Pico'})
        return
    emit('typing_status', {'status': 'typing'})
    try:
        resp = active_sessions[sid]['chat'].send_message(msg)
        emit('response', {'text': resp.text, 'sender': 'Pico'})
        socketio.start_background_task(background_generate_audio, sid, resp.text)
    except Exception as e:
        print(f"API Error: {e}")
        emit('response', {'text': "大脑短路中...", 'sender': 'Pico'})
    finally:
        emit('typing_status', {'status': 'idle'})

