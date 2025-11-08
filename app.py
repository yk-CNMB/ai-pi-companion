# =======================================================================
# Pico AI Server - app.py (终极语音版)
# 
# 启动命令 (在.venv环境下):
# gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================

import os
import json
import uuid
import asyncio

# 关键: 导入 eventlet 并打上补丁，必须放在最前面
import eventlet
eventlet.monkey_patch()

# 导入 TTS 库
import edge_tts

from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit
from google import genai

# --- Flask & SocketIO 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')
# 强制使用 eventlet 模式，提高并发稳定性
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- 目录配置 ---
# 记忆文件目录
MEMORIES_DIR = "memories"
os.makedirs(MEMORIES_DIR, exist_ok=True)

# 音频文件存放目录
AUDIO_DIR = os.path.join("static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# --- Gemini 初始化 ---
CONFIG = {}
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
        print("✅ 成功加载 config.json")
except FileNotFoundError:
    print("⚠️ 未找到 config.json，将尝试使用环境变量")

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里粘贴" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini 客户端初始化成功")
    except Exception as e:
        print(f"❌ Gemini 初始化失败: {e}")
else:
     print("❌ 错误: 未找到有效的 GEMINI_API_KEY")

# --- 记忆管理函数 ---
def get_user_memory_file(username):
    """生成安全的用户记忆文件路径"""
    safe_username = "".join([c for c in username if c.isalnum() or c in ('-', '_')]).lower()
    if not safe_username: safe_username = "default_user"
    return os.path.join(MEMORIES_DIR, f"{safe_username}.json")

def load_user_memories(username):
    """加载指定用户的记忆"""
    try:
        with open(get_user_memory_file(username), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_user_memory(username, fact):
    """保存一条新记忆"""
    memories = load_user_memories(username)
    if fact not in memories:
        memories.append(fact)
        with open(get_user_memory_file(username), "w", encoding="utf-8") as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        return True
    return False

# --- 语音生成函数 (后台任务) ---
# 可选语音: zh-CN-XiaoxiaoNeural (可爱女声), zh-CN-YunxiNeural (活泼男声)
TTS_VOICE = "zh-CN-XiaoxiaoNeural"

def background_generate_audio(sid, text):
    """
    在后台生成音频，完成后发送给 *特定的* 客户端 (sid)。
    """
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    
    try:
        print(f"🎵 [后台] 开始为 {sid[:6]}... 生成语音")
        
        # 在 eventlet 线程中运行 asyncio 需要一点小技巧
        async def _run_tts():
            communicate = edge_tts.Communicate(text, TTS_VOICE)
            await communicate.save(filepath)

        # 创建一个新的事件循环来运行这个异步任务
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_tts())
        loop.close()
        
        audio_url = f"/static/audio/{filename}"
        print(f"✅ [后台] 语音完毕，发送给 {sid[:6]}... URL: {audio_url}")

        # 发送给特定的 sid，指定 namespace='/'
        socketio.emit('audio_response', {'audio': audio_url}, to=sid, namespace='/')

    except Exception as e:
        print(f"❌ [后台] TTS 生成失败: {e}")

# 全局会话存储
active_sessions = {}

# --- 路由 ---
@app.route('/')
def index_redirect():
    """将旧网址重定向到新网址，防止缓存问题"""
    return redirect(url_for('pico'))

@app.route('/pico')
def pico():
    """主界面路由，强制禁用缓存"""
    response = make_response(render_template('chat.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# --- SocketIO 事件 ---
@socketio.on('login')
def handle_login(data):
    sid = request.sid
    username = data.get('username', 'Anonymous').strip()
    if not username: username = "匿名用户"
    
    print(f"🔑 [尝试登录] 用户: {username} (SID: {sid})")
    try:
        # 1. 加载记忆
        user_memories = load_user_memories(username)
        memory_str = "\n".join([f"- {m}" for m in user_memories]) if user_memories else "暂无"
        
        # 2. 构建系统指令 (特别要求简短回复，适合语音)
        system_instruction = (
            f"你是一个名为'Pico'的AI虚拟形象。正在和【{username}】聊天。\n"
            f"【关于 {username} 的记忆】\n{memory_str}\n\n"
            "请用中文回复，保持活泼傲娇。回复尽量简短口语化，因为你要把这些话读出来。"
        )

        if not client: raise Exception("API Key Error (Gemini 未初始化)")
        
        # 3. 创建会话
        chat = client.chats.create(
            model="gemini-1.5-flash",
            config={"system_instruction": system_instruction}
        )
        active_sessions[sid] = {'chat': chat, 'username': username}
        print(f"✅ {username} 登录成功！")
        
        # 4. 通知前端
        emit('login_success', {'username': username})
        
        # 5. 发送欢迎语 (带语音)
        socketio.sleep(0.5) # 等待前端切换界面
        welcome = f"嗨，{username}！Pico 准备好啦！"
        emit('response', {'text': welcome, 'sender': 'Pico'})
        # 启动后台语音任务
        socketio.start_background_task(background_generate_audio, sid, welcome)

    except Exception as e:
        print(f"❌ 登录失败: {e}")
        emit('login_failed', {'error': str(e)})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in active_sessions:
        print(f"👋 用户断开: {active_sessions[sid]['username']}")
        del active_sessions[sid]

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    # 安全检查：未登录用户不能发送消息
    if sid not in active_sessions:
        emit('response', {'text': "⚠️ 会话已过期，请刷新页面重新登录。", 'sender': 'Pico'})
        return

    session_data = active_sessions[sid]
    chat = session_data['chat']
    username = session_data['username']
    msg = data['text']

    # 特殊指令：/记
    if msg.startswith("/记 "):
        fact = msg[3:].strip()
        if fact:
            save_user_memory(username, fact)
            emit('response', {'text': f"🧠 好的，我把【{fact}】记在 {username} 的专属小本本上了！", 'sender': 'Pico'})
            return

    emit('typing_status', {'status': 'typing'})
    try:
        # 调用 Gemini API
        response = chat.send_message(msg)
        ai_text = response.text
        
        # 1. 立刻发送文字回复
        emit('response', {'text': ai_text, 'sender': 'Pico'})
        
        # 2. 启动后台任务生成语音，不阻塞主线程
        socketio.start_background_task(background_generate_audio, sid, ai_text)
        
    except Exception as e:
        print(f"API Error: {e}")
        emit('response', {'text': "大脑短路中...稍后再试", 'sender': 'Pico'})
    finally:
        emit('typing_status', {'status': 'idle'})
