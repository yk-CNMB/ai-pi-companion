# =======================================================================
# Pico AI Server - app.py (工作室版: 模型管理 + 独立人设)
# 启动: gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================
import os, json, uuid, asyncio, time, glob, shutil
import eventlet
eventlet.monkey_patch()
import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- 目录配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
os.makedirs(MEMORIES_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

# --- Gemini 初始化 ---
CONFIG = {}
try:
    with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
if CONFIG.get("GEMINI_API_KEY"):
    try: client = genai.Client(api_key=CONFIG.get("GEMINI_API_KEY"))
    except Exception as e: print(f"API Error: {e}")

# =========================================
# 🧠 模型与人设管理器 (核心升级)
# =========================================
CURRENT_MODEL = {"id": "default", "path": "", "persona": ""}

def get_default_persona(model_name):
    return f"你是一个名为'{model_name}'的AI虚拟主播。请用中文简短回复，活泼可爱。每句话开头加上情感标签如 [HAPPY], [ANGRY] 等。"

def scan_models():
    """扫描所有可用模型及其人设"""
    models = []
    # 查找所有 .model3.json 文件
    for model_json in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        model_dir = os.path.dirname(model_json)
        model_id = os.path.basename(model_dir)
        # 读取或创建专属人设文件
        persona_path = os.path.join(model_dir, "persona.txt")
        if not os.path.exists(persona_path):
            with open(persona_path, "w", encoding="utf-8") as f:
                f.write(get_default_persona(model_id.capitalize()))
        with open(persona_path, "r", encoding="utf-8") as f:
            persona = f.read()
        
        # 生成相对路径供前端使用
        web_path = "/" + os.path.relpath(model_json, BASE_DIR).replace("\\", "/")
        models.append({"id": model_id, "name": model_id.capitalize(), "path": web_path, "persona": persona})
    return sorted(models, key=lambda x: x['name'])

# 初始化默认模型
def init_current_model():
    models = scan_models()
    global CURRENT_MODEL
    # 优先找 Hiyori，否则用第一个
    target = next((m for m in models if "hiyori" in m['id'].lower()), models[0] if models else None)
    if target: CURRENT_MODEL = target
    print(f"🤖 当前模型: {CURRENT_MODEL['id']}")
init_current_model()

# --- 功能函数 ---
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
def bg_tts(text, room=None):
    import re
    clean_text = re.sub(r'\[(.*?)\]', '', text).strip() # 去掉情感标签再读
    if not clean_text: return
    fname = f"{uuid.uuid4()}.mp3"
    try:
        async def _run():
            cm = edge_tts.Communicate(clean_text, TTS_VOICE)
            await cm.save(os.path.join(AUDIO_DIR, fname))
        asyncio.run(_run())
        url = f"/static/audio/{fname}"
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
    except: pass

# --- 路由 ---
@app.route('/')
def idx(): return redirect('/pico/' + str(int(time.time())))
@app.route('/pico/<v>')
def pico(v):
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

# --- SocketIO 事件 ---
users = {}
chatroom_chat = None

@socketio.on('login')
def on_login(d):
    users[request.sid] = d.get('username','').strip() or "匿名"
    join_room('lobby')
    emit('login_success', {'username': users[request.sid], 'current_model': CURRENT_MODEL})
    emit('sys', {'text': f"🎉 {users[request.sid]} 加入了！"}, to='lobby', include_self=False)

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        emit('sys', {'text': f"💨 {users.pop(request.sid)} 离开了。"}, to='lobby')

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    msg = d['text']
    # 【修复】这里确保广播出去的 sender 是正确的用户名
    emit('chat', {'text': msg, 'sender': users[sid]}, to='lobby')
    
    global chatroom_chat
    try:
        # 每次对话都重新读取当前人设，确保实时生效
        current_persona = CURRENT_MODEL['persona']
        # 简单的上下文管理 (为了简化，这里每次都新建会话，生产环境可优化)
        chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": current_persona})
        
        resp = chat.send_message(f"【{users[sid]}说】: {msg}")
        
        # 解析情感标签 [HAPPY]
        import re
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        display_text = resp.text
        if match:
            emo = match.group(1)
            display_text = resp.text.replace(match.group(0), '').strip()

        emit('response', {'text': display_text, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, display_text, room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")

# ===========================
# 🛠️ 工作室管理接口
# ===========================
@socketio.on('get_studio_data')
def on_get_studio_data():
    """获取所有模型数据"""
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})

@socketio.on('switch_model')
def on_switch_model(data):
    """切换模型"""
    global CURRENT_MODEL
    models = scan_models()
    target = next((m for m in models if m['id'] == data['id']), None)
    if target:
        CURRENT_MODEL = target
        # 广播给所有人切换模型
        emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_persona')
def on_save_persona(data):
    """保存人设"""
    model_id = data['id']
    new_persona = data['text']
    model_path = os.path.join(MODELS_DIR, model_id)
    if os.path.exists(model_path):
        with open(os.path.join(model_path, "persona.txt"), "w", encoding="utf-8") as f:
            f.write(new_persona)
        # 如果是当前模型，立即更新内存
        if CURRENT_MODEL['id'] == model_id:
            CURRENT_MODEL['persona'] = new_persona
        emit('toast', {'text': '✅ 人设已保存！', 'type': 'success'})

@socketio.on('delete_model')
def on_delete_model(data):
    """删除模型"""
    model_id = data['id']
    # 禁止删除当前正在用的模型
    if model_id == CURRENT_MODEL['id']:
        emit('toast', {'text': '❌ 无法删除正在使用的模型！', 'type': 'error'})
        return
    
    model_path = os.path.join(MODELS_DIR, model_id)
    try:
        shutil.rmtree(model_path)
        emit('toast', {'text': '🗑️ 模型已删除', 'type': 'success'})
        emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']}) # 刷新列表
    except Exception as e:
        emit('toast', {'text': f'删除失败: {e}', 'type': 'error'})

# --- 简单的后台下载任务 ---
def bg_download_model(url, name):
    try:
        print(f"⬇️ 开始下载 {name}...")
        # 使用 svn export 下载 (需确保系统安装了 svn)
        target = os.path.join(MODELS_DIR, name.lower())
        if os.path.exists(target): shutil.rmtree(target)
        os.system(f"svn export --force -q {url} {target}")
        print(f"✅ {name} 下载完成")
        # 下载完成后广播通知刷新
        socketio.emit('toast', {'text': f'🎉 {name} 下载完成！', 'type': 'success'}, namespace='/')
    except Exception as e:
        print(f"❌ 下载失败: {e}")

@socketio.on('download_model')
def on_download_model(data):
    """触发后台下载"""
    # 这里预置几个官方模型链接
    presets = {
        "Mao": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Mao",
        "Natori": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Natori",
        "Rice": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Rice",
        "Wanko": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Wanko"
    }
    url = presets.get(data['name'])
    if url:
        emit('toast', {'text': f'🚀 开始下载 {data["name"]}，请稍候...', 'type': 'info'})
        socketio.start_background_task(bg_download_model, url, data['name'])
    else:
        emit('toast', {'text': '未知模型', 'type': 'error'})
