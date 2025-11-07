# app.py (多用户独立记忆 + 增强型登录)

import os
import json
from flask import Flask, render_template, request, make_response
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

# --- Flask & SocketIO ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')
socketio = SocketIO(app, cors_allowed_origins="*")

# --- 记忆系统 ---
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
else:
     print("❌ 错误: 未找到有效的 GEMINI_API_KEY。")

# --- 多用户记忆管理函数 ---

def get_user_memory_file(username):
    """获取指定用户的记忆文件路径"""
    # 简单过滤，防止非法文件名
    safe_username = "".join([c for c in username if c.isalnum() or c in ('-', '_')]).lower()
    if not safe_username: safe_username = "default_user"
    return os.path.join(MEMORIES_DIR, f"{safe_username}.json")

def load_user_memories(username):
    """加载指定用户的记忆列表"""
    filepath = get_user_memory_file(username)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_user_memory(username, fact):
    """保存一条新记忆到指定用户的文件"""
    memories = load_user_memories(username)
    if fact not in memories:
        memories.append(fact)
        filepath = get_user_memory_file(username)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        return True
    return False

# 存储每个连接的 {sid: {'chat': chat_obj, 'username': 'yk'}}
active_sessions = {}

# --- Flask 路由 ---
@app.route('/')
def index():
    """渲染主页，并添加防缓存头部"""
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# --- SocketIO 事件处理 ---

@socketio.on('login')
def handle_login(data):
    """处理用户登录事件"""
    sid = request.sid
    username = data.get('username', 'Anonymous').strip()
    # 防止空名字
    if not username:
        username = "匿名用户"
        
    print(f"🔑 [尝试登录] 用户: {username} (SID: {sid})")

    try:
        # 1. 加载记忆
        user_memories = load_user_memories(username)
        print(f"📖 已加载记忆: {len(user_memories)} 条")
        memory_str = "\n".join([f"- {m}" for m in user_memories]) if user_memories else "暂无"

        # 2. 构建指令
        system_instruction = (
            f"你是一个名为'Pico'的AI虚拟形象。你现在正在和用户【{username}】聊天。\n"
            f"【关于 {username} 的核心记忆】\n{memory_str}\n\n"
            "请在对话中自然地运用这些记忆，保持活泼傲娇的性格。"
        )

        # 3. 创建 Gemini 会话 (最容易出错的步骤)
        if not client:
             raise Exception("Gemini API 未初始化 (可能是 Key 错误)")
             
        print("🤖 正在连接 Gemini 大脑...")
        chat = client.chats.create(
            model="gemini-1.5-flash",
            config={"system_instruction": system_instruction}
        )
        
        # 4. 成功！保存会话并通知前端
        active_sessions[sid] = {'chat': chat, 'username': username}
        print(f"✅ {username} 登录成功！")
        
        emit('login_success', {
            'username': username,
            'memory_count': len(user_memories)
        })
        
        # 延迟一点点发送欢迎语，让前端有时间切换界面
        socketio.sleep(0.5)
        welcome = f"嗨，{username}！Pico 准备好啦！"
        if user_memories: welcome += " (读取记忆完毕 🧠)"
        emit('response', {'text': welcome, 'sender': 'Pico'})

    except Exception as e:
        error_msg = f"登录失败: {str(e)}"
        print(f"❌ {error_msg}")
        # 关键：一定要告诉前端失败了！
        emit('login_failed', {'error': error_msg})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in active_sessions:
        print(f"👋 用户断开: {active_sessions[sid]['username']}")
        del active_sessions[sid]
    else:
        print(f"👋 未登录的客户端断开连接: {sid}")

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
