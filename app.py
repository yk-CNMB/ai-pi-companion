# app.py (多用户独立记忆版)

import os
import json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from google import genai

# --- 配置与初始化 ---
CONFIG = {}
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
        print("✅ 成功加载 config.json")
except FileNotFoundError:
    pass

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'secret')
socketio = SocketIO(app, cors_allowed_origins="*")

# 创建记忆文件夹
MEMORIES_DIR = "memories"
os.makedirs(MEMORIES_DIR, exist_ok=True)

# Gemini 初始化
client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里粘贴" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini 客户端初始化成功")
    except Exception as e:
        print(f"❌ Gemini 初始化失败: {e}")

# --- 多用户记忆管理函数 ---
def get_user_memory_file(username):
    """获取指定用户的记忆文件路径"""
    # 简单处理：把用户名转成小写，作为文件名，避免字符问题
    safe_username = "".join([c for c in username if c.isalnum() or c in ('-', '_')]).lower()
    if not safe_username: safe_username = "default_user"
    return os.path.join(MEMORIES_DIR, f"{safe_username}.json")

def load_user_memories(username):
    """加载指定用户的记忆列表"""
    filepath = get_user_memory_file(username)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_user_memory(username, fact):
    """保存一条新记忆到指定用户的文件"""
    memories = load_user_memories(username)
    if fact not in memories:
        memories.append(fact)
        filepath = get_user_memory_file(username)
        with open(filepath, "w") as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        return True
    return False

# --- 会话管理 ---
# 存储每个连接的 {sid: {'chat': chat_obj, 'username': 'yk'}}
active_sessions = {}

@app.route('/')
def index():
    return render_template('index.html')

# --- SocketIO 事件 ---

# 1. 新的连接事件：用户必须在连接时"报上名来"
@socketio.on('login')
def handle_login(data):
    username = data.get('username', 'Anonymous').strip()
    sid = request.sid
    print(f"🔑 用户登录: {username} (SID: {sid})")

    # 加载该用户的专属记忆
    user_memories = load_user_memories(username)
    memory_str = "\n".join([f"- {m}" for m in user_memories]) if user_memories else "暂无"
    print(f"📖 加载 {username} 的记忆: {len(user_memories)} 条")

    # 为该用户构建专属的系统指令
    system_instruction = (
        f"你是一个名为'Pico'的AI虚拟形象。你现在正在和用户【{username}】聊天。\n"
        f"【关于 {username} 的核心记忆】\n{memory_str}\n\n"
        "请在对话中自然地运用这些记忆，保持活泼傲娇的性格。不要主动提及你在读取记忆。"
    )

    if client:
        try:
            chat = client.chats.create(
                model="gemini-2.5-flash",
                config={"system_instruction": system_instruction}
            )
            # 保存会话信息
            active_sessions[sid] = {'chat': chat, 'username': username}
            
            emit('login_success', {
                'username': username,
                'memory_count': len(user_memories)
            })
            
            # 发送个性化欢迎语
            welcome = f"嗨，{username}！Pico 准备好啦！"
            if user_memories:
                welcome += " (我好像记得你哦 😏)"
            emit('response', {'text': welcome, 'sender': 'Pico'})

        except Exception as e:
            print(f"创建聊天失败: {e}")
            emit('response', {'text': "大脑连接失败...", 'sender': 'Pico'})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in active_sessions:
        print(f"👋 用户断开: {active_sessions[sid]['username']}")
        del active_sessions[sid]

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    if sid not in active_sessions:
        emit('response', {'text': "⚠️ 请先刷新页面登录。", 'sender': 'Pico'})
        return

    session_data = active_sessions[sid]
    chat = session_data['chat']
    username = session_data['username']
    msg = data['text']

    # --- 记忆指令: /记 ---
    if msg.startswith("/记 "):
        fact = msg[3:].strip()
        if fact:
            save_user_memory(username, fact)
            emit('response', {'text': f"🧠 好，我把【{fact}】记在 {username} 的专属小本本上了！", 'sender': 'Pico'})
            return

    emit('typing_status', {'status': 'typing'})
    try:
        response = chat.send_message(msg)
        emit('response', {'text': response.text, 'sender': 'Pico'})
    except Exception as e:
        print(f"API Error: {e}")
        emit('response', {'text': "大脑短路中...", 'sender': 'Pico'})
    finally:
        emit('typing_status', {'status': 'idle'})

if __name__ == '__main__':
    print("Starting Multi-User Memory Server...")
    socketio.run(app, host='0.0.0.0', port=5000)
