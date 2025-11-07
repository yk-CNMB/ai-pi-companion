# app.py (SocketIO 后台任务版)

import os
import json
import asyncio
import uuid
# import threading # 不再需要标准线程库
import edge_tts
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

# 尝试导入 eventlet，如果没有就用默认的
try:
    import eventlet
    # eventlet.monkey_patch() # 如果安装了 eventlet 最好加上这一行
except ImportError:
    pass

from google import genai

# --- 配置加载 ---
CONFIG = {}
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
        print("✅ 成功加载 config.json")
except FileNotFoundError:
    print("⚠️ 未找到 config.json，使用环境变量。")

# --- Flask 配置 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')
# 增加 logger=True, engineio_logger=True 来在终端看到更多底层日志
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, async_mode='threading') 

AUDIO_DIR = os.path.join("static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# --- Gemini 初始化 ---
client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里粘贴" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini 客户端初始化成功")
    except Exception as e:
        print(f"❌ Gemini 初始化失败: {e}")
else:
     print("❌ 错误: 未找到有效的 GEMINI_API_KEY。")

TTS_VOICE = "zh-CN-XiaoxiaoNeural"

# --- 异步 TTS 生成函数 ---
def background_generate_audio(sid, text):
    """在后台生成音频，完成后主动推送给特定客户端"""
    # 注意：这里不需要 app_context，因为我们只用 socketio 发送
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    
    try:
        print(f"🎵 [后台] 开始生成语音...")
        # 创建新的事件循环来运行异步的 edge-tts
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        communicate = edge_tts.Communicate(text, TTS_VOICE)
        loop.run_until_complete(communicate.save(filepath))
        loop.close()
        
        audio_url = f"/static/audio/{filename}"
        print(f"✅ [后台] 语音完毕，正在发送给 {sid} URL: {audio_url}")

        # 关键修改：明确指定 namespace='/'
        socketio.emit('audio_response', {'audio': audio_url}, to=sid, namespace='/')

    except Exception as e:
        print(f"❌ [后台] TTS 生成失败: {e}")

# --- AI 角色设定 ---
SYSTEM_INSTRUCTION = (
    "你是一个名为'Pico'的AI虚拟形象，运行在树莓派上。你的性格是活泼、略带傲娇。请用中文回复，保持简洁口语化。"
)

chat_sessions = {}

# --- 路由 ---
@app.route('/')
def index():
    return render_template('index.html')

# --- SocketIO 事件 ---
@socketio.on('connect')
def handle_connect():
    if client:
        sid = request.sid
        print(f"Client connected: {sid}")
        try:
            chat = client.chats.create(
                model="gemini-2.5-flash",
                config={"system_instruction": SYSTEM_INSTRUCTION}
            )
            chat_sessions[sid] = chat
            welcome = "嗨！我是Pico！"
            emit('response', {'text': welcome, 'sender': 'Pico'})
            # 使用 socketio 的后台任务方法
            socketio.start_background_task(background_generate_audio, sid, welcome)
        except Exception as e:
             print(f"Connect Error: {e}")
             emit('response', {'text': "大脑连接失败", 'sender': 'Pico'})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in chat_sessions: del chat_sessions[sid]
    print(f"Client disconnected: {sid}")

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    user_message = data['text']
    if sid not in chat_sessions: return

    emit('typing_status', {'status': 'typing'})
    try:
        chat = chat_sessions[sid]
        response = chat.send_message(user_message)
        # 1. 发文字
        emit('response', {'text': response.text, 'sender': 'Pico'})
        # 2. 发后台语音任务
        socketio.start_background_task(background_generate_audio, sid, response.text)
    except Exception as e:
        print(f"API Error: {e}")
        emit('response', {'text': "大脑短路了", 'sender': 'Pico'})
    finally:
        emit('typing_status', {'status': 'idle'})

if __name__ == '__main__':
    print("Starting server (SocketIO Background Task Mode)...")
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

