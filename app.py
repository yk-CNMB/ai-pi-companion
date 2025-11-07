# app.py (使用 config.json 版)

import os
import json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from google import genai

# --- 配置加载 ---
# 尝试从 config.json 加载配置
CONFIG = {}
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
        print("✅ 成功加载 config.json")
except FileNotFoundError:
    print("⚠️ 未找到 config.json，尝试使用环境变量...")

# --- Flask 配置 ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Gemini 初始化 ---
client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not api_key or "在这里粘贴" in api_key:
     print("❌ 错误: 未找到有效的 GEMINI_API_KEY。请检查 config.json 文件。")
else:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini 客户端初始化成功")
    except Exception as e:
        print(f"❌ Gemini 初始化失败: {e}")

# AI 角色设定
SYSTEM_INSTRUCTION = (
    "你是一个名为'Pico'的AI虚拟形象，运行在树莓派上。你的性格是活泼、略带傲娇，并且对科技和游戏充满热情。 "
    "请用中文回复，并且保持简洁和拟人化的风格。你与用户通过手机进行文字聊天。不要提醒用户你是AI模型。"
    "在回复中可以加入一些表情符号，让回复更有生气。"
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
            emit('response', {'text': "🤖 Pico：嗨！我是Pico，很高兴在树莓派上和你聊天！", 'sender': 'Pico'})
        except Exception as e:
             print(f"创建聊天失败: {e}")
             emit('response', {'text': "⚠️ Pico：大脑连接失败，请检查服务器日志。", 'sender': 'Pico'})
    else:
        emit('response', {'text': "⚠️ Pico：我找不到我的 API 密钥 (config.json)，请帮我检查一下！", 'sender': 'Pico'})

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
        emit('response', {'text': response.text, 'sender': 'Pico'})
    except Exception as e:
        print(f"API Error: {e}")
        emit('response', {'text': "❌ Pico：哎呀，大脑短路了，稍后再试吧。", 'sender': 'Pico'})
    finally:
        emit('typing_status', {'status': 'idle'})

if __name__ == '__main__':
    print("Starting Flask-SocketIO server on http://0.0.0.0:5000...")
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

