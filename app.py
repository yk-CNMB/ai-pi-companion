# =======================================================================
# Pico AI Server - app.py (终极语音 + 多用户记忆版)
# 
# 启动命令 (确保在 .venv 虚拟环境下):
# gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================

import os
import json
import uuid
import asyncio

# 【关键】导入 eventlet 并打补丁，确保高并发下的稳定性
import eventlet
eventlet.monkey_patch()

import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit
from google import genai

# --- 1. 初始化框架 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
# 强制使用 eventlet 作为异步模式
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

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

# --- 4. 核心功能函数 ---

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

def background_generate_audio(sid, text):
    """【后台任务】生成语音并发送给指定客户端"""
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    try:
        print(f"🎵 [TTS] 开始生成: {text[:10]}...")
        async def _run():
            cm = edge_tts.Communicate(text, TTS_VOICE)
            await cm.save(filepath)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
        loop.close()
        
        url = f"/static/audio/{filename}"
        print(f"✅ [TTS] 完成，发送给 {sid[:4]}: {url}")
        # 指定 namespace='/' 很重要
        socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
    except Exception as e:
        print(f"❌ [TTS] 失败: {e}")

# 全局活跃会话存储
active_sessions = {}

# --- 5. Web 路由 ---

@app.route('/')
def index_redirect():
    """强制将旧网址重定向到新网址"""
    return redirect(url_for('pico'))

@app.route('/pico')
def pico():
    """主界面，强制禁用缓存"""
    response = make_response(render_template('chat.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# --- 6. Socket.IO 事件 ---

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
        
        chat = client.chats.create(model="gemini-1.5-flash", config={"system_instruction": system_prompt})
        active_sessions[sid] = {'chat': chat, 'username': username}
        
        emit('login_success', {'username': username})
        socketio.sleep(0.5)
        
        welcome = f"嗨，{username}！Pico 准备好啦！"
        emit('response', {'text': welcome, 'sender': 'Pico'})
        socketio.start_background_task(background_generate_audio, sid, welcome)
        
    except Exception as e:
        print(f"❌ 登录错: {e}")
        emit('login_failed', {'error': str(e)})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in active_sessions:
        del active_sessions[sid]

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
