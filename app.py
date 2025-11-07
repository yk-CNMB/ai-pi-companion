# app.py (TTS 语音版)

import os
import json
import asyncio
import uuid
import edge_tts
from flask import Flask, render_template, request, url_for
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
socketio = SocketIO(app, cors_allowed_origins="*")

# 确保音频存放目录存在
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

# --- TTS 设置 ---
# 可选语音: zh-CN-XiaoxiaoNeural (可爱女声), zh-CN-YunxiNeural (活泼男声)
TTS_VOICE = "zh-CN-XiaoxiaoNeural"

async def generate_tts_async(text, output_path):
    """异步生成 TTS 音频文件"""
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(output_path)

def generate_audio(text):
    """TTS 的同步包装函数"""
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    try:
        # 在同步环境中运行异步 TTS
        asyncio.run(generate_tts_async(text, filepath))
        # 返回相对于 static 文件夹的 Web 路径
        return f"/static/audio/{filename}"
    except Exception as e:
        print(f"TTS 生成失败: {e}")
        return None

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
            # 开场白也加上语音
            welcome_text = "嗨！我是Pico，很高兴见到你！"
            audio_url = generate_audio(welcome_text)
            emit('response', {'text': welcome_text, 'sender': 'Pico', 'audio': audio_url})
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
        
        # 1. 生成语音
        print(f"正在为回复生成语音...")
        audio_url = generate_audio(ai_text)
        
        # 2. 同时发送文本和语音 URL 给前端
        emit('response', {'text': ai_text, 'sender': 'Pico', 'audio': audio_url})
        
    except Exception as e:
        print(f"API Error: {e}")
        emit('response', {'text': "❌ Pico：哎呀，大脑短路了。", 'sender': 'Pico'})
    finally:
        emit('typing_status', {'status': 'idle'})

if __name__ == '__main__':
    # 清理旧的音频文件 (可选)
    print("Starting server...")
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

