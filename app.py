# app.py (异步后台语音版)

import os
import json
import asyncio
import uuid
import threading
import edge_tts
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from google import genai

# --- 配置加载 ---
CONFIG = {}
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
        print("✅ 成功加载 config.json")
except FileNotFoundError:
    print("⚠️ 未找到 config.json，将尝试使用环境变量。")

# --- Flask 配置 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')
# ping_timeout 设置长一点，防止网络波动导致断连
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60)

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

# TTS 语音设置
TTS_VOICE = "zh-CN-XiaoxiaoNeural"

# --- 异步 TTS 生成函数 (将在后台线程运行) ---
def background_generate_audio(sid, text, app_context):
    """在后台生成音频，完成后主动推送给特定客户端"""
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    
    try:
        # 创建新的事件循环来运行异步的 edge-tts
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        print(f"🎵 [后台] 开始为 {sid[:4]}... 生成语音")
        communicate = edge_tts.Communicate(text, TTS_VOICE)
        loop.run_until_complete(communicate.save(filepath))
        loop.close()
        
        audio_url = f"/static/audio/{filename}"
        print(f"✅ [后台] 语音生成完毕，发送给 {sid[:4]}...")

        # 使用 socketio 发送给特定的客户端 (sid)
        socketio.emit('audio_response', {'audio': audio_url}, to=sid)

    except Exception as e:
        print(f"❌ [后台] TTS 生成失败: {e}")

# --- AI 角色设定 ---
SYSTEM_INSTRUCTION = (
    "你是一个名为'Pico'的AI虚拟形象，运行在树莓派上。你的性格是活泼、略带傲娇，并且对科技和游戏充满热情。"
    "请用中文回复，保持简洁口语化，不要长篇大论，因为你需要把回复读出来。"
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
            
            welcome_text = "嗨！我是Pico，很高兴见到你！"
            # 1. 先发送文字
            emit('response', {'text': welcome_text, 'sender': 'Pico'})
            # 2. 后台生成欢迎语音
            threading.Thread(target=background_generate_audio, args=(sid, welcome_text, app.app_context())).start()
            
        except Exception as e:
             print(f"创建聊天失败: {e}")
             emit('response', {'text': "⚠️ Pico：大脑连接失败。", 'sender': 'Pico'})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in chat_sessions:
        del chat_sessions[sid]
    print(f"Client disconnected: {sid}")

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    user_message = data['text']
    
    if sid not in chat_sessions:
        emit('response', {'text': "⚠️ 会话已过期，请刷新页面。", 'sender': 'Pico'})
        return

    emit('typing_status', {'status': 'typing'})

    try:
        chat = chat_sessions[sid]
        response = chat.send_message(user_message)
        ai_text = response.text
        
        # 1. 立刻发送文字回复，不等待语音
        emit('response', {'text': ai_text, 'sender': 'Pico'})
        
        # 2. 启动后台线程去生成语音，不阻塞主流程
        threading.Thread(target=background_generate_audio, args=(sid, ai_text, app.app_context())).start()
        
    except Exception as e:
        print(f"API Error: {e}")
        emit('response', {'text': "❌ Pico：哎呀，大脑短路了。", 'sender': 'Pico'})
    finally:
        emit('typing_status', {'status': 'idle'})

if __name__ == '__main__':
    print("Starting server (Async Audio Mode)...")
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
