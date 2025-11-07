# app.py

import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from google import genai
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量，包括 GEMINI_API_KEY
load_dotenv()

# --- 配置 ---
app = Flask(__name__)
# 生产环境中应使用一个更复杂的密钥
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret_key') 
socketio = SocketIO(app, cors_allowed_origins="*")

# 初始化 Gemini 客户端
try:
    # 尝试从环境变量中获取 API Key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment variables.")
    
    client = genai.Client(api_key=api_key)
except Exception as e:
    print(f"Error initializing Gemini client: {e}")
    client = None

# AI 角色设定 (System Instruction)
SYSTEM_INSTRUCTION = (
    "你是一个名为'Pico'的AI虚拟形象，运行在树莓派上。你的性格是活泼、略带傲娇，并且对科技和游戏充满热情。 "
    "请用中文回复，并且保持简洁和拟人化的风格。你与用户通过手机进行文字聊天。不要提醒用户你是AI模型。"
    "在回复中可以加入一些表情符号，让回复更有生气。"
)

# 存储每个连接的会话历史
# 注意: 在实际生产环境中，更复杂的应用会使用数据库存储
chat_sessions = {}

# --- Flask 路由 ---
@app.route('/')
def index():
    """渲染手机端的聊天界面"""
    return render_template('index.html')

# --- SocketIO 事件处理 ---
@socketio.on('connect')
def handle_connect():
    """处理新用户连接，创建新的 Gemini 聊天会话"""
    if client:
        # 使用 sid (session id) 作为会话 key
        sid = request.sid
        print(f"Client connected with SID: {sid}")
        
        # 使用 gemini-2.5-flash 模型，它是快速且高效的
        chat = client.chats.create(
            model="gemini-2.5-flash",
            system_instruction=SYSTEM_INSTRUCTION
        )
        chat_sessions[sid] = chat
        
        # 发送欢迎消息
        welcome_message = "🤖 Pico：嗨！我是Pico，很高兴在树莓派上和你聊天！有什么好玩的事情吗？"
        emit('response', {'text': welcome_message, 'sender': 'Pico'})
    else:
        # 如果 API 初始化失败，发送错误提示
        error_message = "⚠️ Pico：抱歉，Gemini API 初始化失败，请检查 GEMINI_API_KEY。"
        emit('response', {'text': error_message, 'sender': 'Pico'})
        
@socketio.on('disconnect')
def handle_disconnect():
    """处理用户断开连接，清除会话"""
    sid = request.sid
    if sid in chat_sessions:
        del chat_sessions[sid]
        print(f"Client disconnected and session cleared: {sid}")

@socketio.on('message')
def handle_message(data):
    """处理接收到的用户消息，并调用 Gemini API"""
    sid = request.sid
    user_message = data['text']
    print(f"User message received: {user_message}")

    if sid not in chat_sessions:
        emit('response', {'text': "⚠️ 会话已过期，请重新连接。", 'sender': 'Pico'})
        return

    # 1. 通知客户端 Pico 正在输入
    emit('typing_status', {'status': 'typing'})

    try:
        # 2. 调用 Gemini API
        chat = chat_sessions[sid]
        
        # send_message 会自动维护历史记录
        response = chat.send_message(user_message)
        ai_response = response.text
        
        # 3. 发送 AI 的回复给客户端
        emit('response', {'text': ai_response, 'sender': 'Pico'})
        
    except Exception as e:
        error_msg = f"与 Gemini API 通信发生错误：{e}"
        print(error_msg)
        emit('response', {'text': "❌ Pico：抱歉，我今天状态不好，无法连接到大脑。", 'sender': 'Pico'})
    finally:
        # 4. 通知客户端 Pico 停止输入
        emit('typing_status', {'status': 'idle'})

if __name__ == '__main__':
    # 在树莓派上，监听所有网络接口 (0.0.0.0)，以便手机可以访问
    print("Starting Flask-SocketIO server on http://0.0.0.0:5000...")
    # 注意: 生产环境中应使用 Gunicorn 或 Waitress 启动
    from flask_socketio import request 
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)