# =======================================================================
# Pico AI Server - app.py (Gunicorn/Eventlet 稳定版)
# 
# 启动命令 (在.venv环境下):
# gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================

import os
import json

# 关键: 导入 eventlet 并打上补丁
# 必须放在所有网络库 (如 flask) 之前！
# 这会强制 Python 的标准库使用 eventlet 的异步功能，
# 极大地提高了 Socket.IO 在高并发或长连接下的稳定性。
import eventlet
eventlet.monkey_patch()

# 导入 Flask 和 Socket.IO 相关的库
# make_response: 用于自定义 HTTP 响应 (比如添加防缓存头部)
# redirect, url_for: 用于 URL 跳转 (将 / 重定向到 /pico)
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit
from google import genai

# --- 1. Flask & SocketIO 初始化 ---

# Gunicorn 会自动寻找这个 'app' 对象
# __name__ 是 Python 的一个魔法变量，Flask 用它来定位模板和静态文件
# static_folder='static' 是默认设置，但明确写出来更清晰
app = Flask(__name__, static_folder='static')

# 设置一个密钥，用于保护 session (虽然我们没用 session，但 Socket.IO 需要它)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')

# 初始化 Socket.IO
# 我们不再需要指定 async_mode，因为 Gunicorn 的 --worker-class eventlet 会强制设置它
socketio = SocketIO(app, cors_allowed_origins="*")

# --- 2. 配置加载 (config.json) ---
CONFIG = {}
try:
    # 打开 config.json 文件并读取内容
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
        print("✅ 成功加载 config.json")
except FileNotFoundError:
    print("⚠️ 未找到 config.json，将尝试使用环境变量。")

# --- 3. 记忆系统 (memories/) ---

# 记忆文件存储的目录
MEMORIES_DIR = "memories"
# 确保这个目录一定存在
os.makedirs(MEMORIES_DIR, exist_ok=True)

# --- 4. Gemini AI 客户端初始化 ---
client = None
# 优先从 config.json 读取 API Key，如果不存在，再尝试从环境变量读取
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

# 检查 API Key 是否有效 (不是空，也不是占位符)
if api_key and "在这里粘贴" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini 客户端初始化成功")
    except Exception as e:
        print(f"❌ Gemini 初始化失败: {e}")
else:
     print("❌ 错误: 未找到有效的 GEMINI_API_KEY。请检查 config.json。")

# --- 5. 记忆管理功能函数 ---

def get_user_memory_file(username):
    """根据用户名生成一个安全的文件路径"""
    # 清理用户名，只保留字母、数字、下划线和连字符，并转为小写
    safe_username = "".join([c for c in username if c.isalnum() or c in ('-', '_')]).lower()
    if not safe_username: safe_username = "default_user"
    # 返回完整路径，例如: memories/yk.json
    return os.path.join(MEMORIES_DIR, f"{safe_username}.json")

def load_user_memories(username):
    """从 JSON 文件加载指定用户的记忆列表"""
    filepath = get_user_memory_file(username)
    try:
        # 使用 utf-8 编码读取，防止中文乱码
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # 如果文件不存在或文件是空的/损坏的，返回一个空列表
        return []

def save_user_memory(username, fact):
    """保存一条新记忆到指定用户的 JSON 文件"""
    memories = load_user_memories(username)
    if fact not in memories:
        memories.append(fact)
        filepath = get_user_memory_file(username)
        # 使用 utf-8 编码写入，ensure_ascii=False 确保中文按原样存为中文
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        return True
    return False

# --- 6. 全局会话存储 ---
# 这是一个字典，用于存储当前所有活跃的连接
# 键 (Key) 是用户的 SID (Socket ID)，值 (Value) 是一个包含聊天对象和用户名的字典
# 例如: {'asdf123': {'chat': <GeminiChat>, 'username': 'YK'}}
active_sessions = {}

# --- 7. Flask 路由 (网页 URL) ---

@app.route('/')
def index_redirect():
    """
    根路由 /
    将所有访问旧网址 (/) 的请求，重定向到新的 /pico 网址。
    这是为了强制浏览器丢弃旧的缓存。
    """
    # url_for('pico') 会自动寻找名为 'pico' 的函数 (见下方)
    return redirect(url_for('pico'))

@app.route('/pico')
def pico():
    """
    新的 /pico 路由
    这是我们的主应用界面。
    """
    # 渲染 templates/chat.html 文件
    response = make_response(render_template('chat.html'))
    
    # 关键的 "缓存终结者"！
    # 这三行命令告诉浏览器和 Cloudflare "永远不要缓存这个 HTML 页面"
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response

# --- 8. Socket.IO 事件处理 (实时通信) ---

@socketio.on('login')
def handle_login(data):
    """
    处理 'login' 事件
    当用户在前端点击 "连接并登录" 按钮时触发
    """
    sid = request.sid # 获取这个用户的唯一连接 ID
    username = data.get('username', 'Anonymous').strip()
    if not username: username = "匿名用户"
    
    print(f"🔑 [尝试登录] 用户: {username} (SID: {sid})")
    
    try:
        # 1. 加载此用户的专属记忆
        user_memories = load_user_memories(username)
        print(f"📖 已加载记忆: {len(user_memories)} 条")
        memory_str = "\n".join([f"- {m}" for m in user_memories]) if user_memories else "暂无"

        # 2. 为 Gemini 构建专属的系统指令 (包含记忆)
        system_instruction = (
            f"你是一个名为'Pico'的AI虚拟形象。你现在正在和用户【{username}】聊天。\n"
            f"【关于 {username} 的核心记忆】\n{memory_str}\n\n"
            "请在对话中自然地运用这些记忆。"
        )

        # 3. 检查 AI 客户端是否正常
        if not client:
             raise Exception("Gemini API 未初始化 (可能是 Key 错误)")
        
        # 4. 创建一个全新的 Gemini 聊天会话
        chat = client.chats.create(
            model="gemini-2.5-flash",
            config={"system_instruction": system_instruction}
        )
        
        # 5. 将会话存入全局字典
        active_sessions[sid] = {'chat': chat, 'username': username}
        print(f"✅ {username} 登录成功！")

        # 6. 向前端回传 'login_success' 信号
        emit('login_success', {'username': username})
        
        # 使用 socketio.sleep 在 eventlet 模式下更稳定
        socketio.sleep(0.5) 
        welcome = f"嗨，{username}！Pico 已激活！"
        if user_memories: welcome += " (记忆已载入 🧠)"
        emit('response', {'text': welcome, 'sender': 'Pico'})

    except Exception as e:
        # 如果登录过程中任何一步失败 (例如 API Key 错)
        error_msg = f"登录失败: {str(e)}"
        print(f"❌ {error_msg}")
        # 向前端回传 'login_failed' 信号
        emit('login_failed', {'error': error_msg})

@socketio.on('disconnect')
def handle_disconnect():
    """
    处理 'disconnect' 事件
    当用户关闭浏览器或网络断开时触发
    """
    sid = request.sid
    # 检查这个用户是否已登录 (在 active_sessions 中)
    if sid in active_sessions:
        print(f"👋 已登录用户断开: {active_sessions[sid]['username']}")
        # 从字典中移除，释放内存
        del active_sessions[sid]
    else:
        print(f"👋 未登录的客户端断开连接: {sid}")

@socketio.on('message')
def handle_message(data):
    """
    处理 'message' 事件
    当用户发送聊天消息时触发
    """
    sid = request.sid
    # 安全检查：如果这个 SID 没有登录，就忽略
    if sid not in active_sessions:
        emit('response', {'text': "⚠️ 请先刷新页面登录。", 'sender': 'Pico'})
        return

    # 提取会话信息
    session_data = active_sessions[sid]
    chat = session_data['chat']
    username = session_data['username']
    msg = data['text']

    # 特殊指令：/记 (用于添加记忆)
    if msg.startswith("/记 "):
        fact = msg[3:].strip()
        if fact:
            save_user_memory(username, fact)
            emit('response', {'text': f"🧠 好的，{username}，我记住了：{fact}", 'sender': 'Pico'})
            return # 处理完毕，不再调用 AI

    # 向所有客户端广播 "正在输入" 状态 (这里可以改为只发给 sid)
    emit('typing_status', {'status': 'typing'})
    
    try:
        # 将消息发送给 Gemini AI
        response = chat.send_message(msg)
        # 将 AI 的回复发送回客户端
        emit('response', {'text': response.text, 'sender': 'Pico'})
    except Exception as e:
        print(f"API Error: {e}")
        emit('response', {'text': "大脑短路中...", 'sender': 'Pico'})
    finally:
        # 停止 "正在输入" 状态
        emit('typing_status', {'status': 'idle'})

# --- 9. 启动入口 ---
# 
# 我们删除了 if __name__ == '__main__': ... 部分
# 因为 Gunicorn 会以模块方式导入 'app'，而不是直接运行这个 .py 文件
# Gunicorn 的启动命令是:
# gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
#
