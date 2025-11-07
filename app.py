# app.py (记忆核心版 - 无语音)

import os
import json
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
    pass

# --- 全局变量 ---
MEMORY_FILE = "memories.json"
memories = []

# --- 记忆功能函数 ---
def load_memories():
    """从 JSON 文件读取记忆"""
    global memories
    try:
        with open(MEMORY_FILE, "r") as f:
            memories = json.load(f)
        print(f"🧠 已加载 {len(memories)} 条记忆")
    except (FileNotFoundError, json.JSONDecodeError):
        memories = []
        print("🧠 记忆库为空，初始化完毕")

def save_memory(fact):
    """保存一条新记忆到 JSON 文件"""
    global memories
    if fact not in memories:
        memories.append(fact)
        with open(MEMORY_FILE, "w") as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        print(f"💾 已保存新记忆: {fact}")
        return True
    return False

# 初始化时加载一次记忆
load_memories()

# --- Flask & SocketIO ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'secret')
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Gemini 初始化 ---
client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里粘贴" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini 客户端初始化成功")
    except Exception as e:
        print(f"❌ Gemini 初始化失败: {e}")

# --- 核心：动态角色设定 ---
def get_system_instruction():
    """动态生成包含当前所有记忆的系统指令"""
    base_instruction = (
        "你是一个名为'Pico'的AI虚拟形象，运行在树莓派上。你的性格活泼、略带傲娇。与用户通过文字聊天。"
        "请用中文回复，保持简洁。不要主动提及你拥有记忆功能，表现得自然一点。"
    )
    # 如果有记忆，就把它们加到指令里
    if memories:
        memory_str = "\n".join([f"- {m}" for m in memories])
        return f"{base_instruction}\n\n【核心记忆列表】\n{memory_str}\n请在对话中自然地运用这些记忆。"
    else:
        return base_instruction

chat_sessions = {}

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    if client:
        sid = request.sid
        print(f"Client connected: {sid}")
        # 每次连接时，重新构建带记忆的指令
        current_instruction = get_system_instruction()
        chat_sessions[sid] = client.chats.create(
            model="gemini-2.5-flash",
            config={"system_instruction": current_instruction}
        )
        emit('response', {'text': "Pico 在线中！(记忆模块已激活 🧠)", 'sender': 'Pico'})

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in chat_sessions: del chat_sessions[request.sid]

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    msg = data['text']
    if sid not in chat_sessions: return

    # --- 简单的记忆触发指令 ---
    # 如果用户说 "/记 [内容]"，则手动添加记忆
    if msg.startswith("/记 "):
        fact = msg[3:].strip()
        if fact:
            save_memory(fact)
            emit('response', {'text': f"🧠 好的，我已经记住了：{fact}", 'sender': 'Pico'})
            # 重新加载当前会话的系统指令可能比较复杂，
            # 简单做法是告诉用户下次连接生效，或者尝试在当前会话中注入提示
            return

    emit('typing_status', {'status': 'typing'})
    try:
        response = chat_sessions[sid].send_message(msg)
        emit('response', {'text': response.text, 'sender': 'Pico'})
    except Exception as e:
        print(f"API Error: {e}")
        emit('response', {'text': "大脑短路了...", 'sender': 'Pico'})
    finally:
        emit('typing_status', {'status': 'idle'})

if __name__ == '__main__':
    print("Starting Memory-Core Server...")
    socketio.run(app, host='0.0.0.0', port=5000)
