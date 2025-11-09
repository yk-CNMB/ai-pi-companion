# =======================================================================
# Pico AI Server - app.py (连接修复版)
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
# 【关键】ping_timeout 设置长一点，防止网络波动导致断连
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60, ping_interval=25)

# --- 目录 & 配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
os.makedirs(MEMORIES_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

CONFIG = {}
try: with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
if CONFIG.get("GEMINI_API_KEY"):
    try: client = genai.Client(api_key=CONFIG.get("GEMINI_API_KEY"))
    except Exception as e: print(f"API Error: {e}")

# --- 模型管理 ---
CURRENT_MODEL = {"id": "default", "path": "", "persona": ""}
def scan_models():
    models = []
    for model_json in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        mid = os.path.basename(os.path.dirname(model_json))
        ppath = os.path.join(os.path.dirname(model_json), "persona.txt")
        if not os.path.exists(ppath):
            with open(ppath, "w", encoding="utf-8") as f: f.write(f"你是一个名为'{mid}'的AI。请用中文简短回复。")
        with open(ppath, "r", encoding="utf-8") as f: p = f.read()
        models.append({"id": mid, "name": mid.capitalize(), "path": "/"+os.path.relpath(model_json, BASE_DIR).replace("\\","/"), "persona": p})
    return sorted(models, key=lambda x: x['name'])
def init_model():
    ms = scan_models()
    global CURRENT_MODEL
    # 优先找 Hiyori
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
    print(f"🤖 当前模型: {CURRENT_MODEL.get('id')}")
init_model()

# --- TTS ---
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
def bg_tts(text, room=None):
    import re
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}.mp3"
    try:
        async def _run():
            cm = edge_tts.Communicate(clean, TTS_VOICE)
            await cm.save(os.path.join(AUDIO_DIR, fname))
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
        loop.close()
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

# 【关键修复】加回基础连接确认
@socketio.on('connect')
def handle_connect():
    print(f"🔌 新连接: {request.sid}")
    # 主动告诉客户端：服务器准备好了！
    emit('server_ready', {'status': 'ok', 'sid': request.sid})

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        emit('sys', {'text': f"💨 {users.pop(request.sid)} 离开了。"}, to='lobby')
    print(f"❌ 断开连接: {request.sid}")

@socketio.on('login')
def on_login(d):
    print(f"🔑 登录请求: {d.get('username')}")
    users[request.sid] = d.get('username','').strip() or "匿名"
    join_room('lobby')
    emit('login_success', {'username': users[request.sid], 'current_model': CURRENT_MODEL})
    emit('sys', {'text': f"🎉 {users[request.sid]} 加入了！"}, to='lobby', include_self=False)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    msg = d['text']
    emit('chat', {'text': msg, 'sender': users[sid]}, to='lobby')
    
    try:
        # 简单起见，每次都用最新人设创建新会话
        chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": CURRENT_MODEL['persona']})
        resp = chat.send_message(f"【{users[sid]}说】: {msg}")
        
        import re
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text.replace(match.group(0), '').strip() if match else resp.text
        if match: emo = match.group(1)

        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        emit('sys', {'text': "⚠️ 大脑短路中..."}, to='lobby')

# --- 工作室接口 ---
@socketio.on('get_studio_data')
def on_get_data(): emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t:
        CURRENT_MODEL = t
        emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_persona')
def on_save_p(d):
    p = os.path.join(MODELS_DIR, d['id'], "persona.txt")
    if os.path.exists(os.path.dirname(p)):
        with open(p, "w", encoding="utf-8") as f: f.write(d['text'])
        if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL['persona'] = d['text']
        emit('toast', {'text': '✅ 人设已保存'})
@socketio.on('delete_model')
def on_del(d):
    if d['id'] == CURRENT_MODEL['id']: return emit('toast', {'text': '❌ 不能删除当前模型', 'type': 'error'})
    try:
        shutil.rmtree(os.path.join(MODELS_DIR, d['id']))
        emit('toast', {'text': '🗑️ 已删除'})
        emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
    except: emit('toast', {'text': '删除失败', 'type': 'error'})
def bg_dl(url, name):
    try:
        t = os.path.join(MODELS_DIR, name.lower())
        if os.path.exists(t): shutil.rmtree(t)
        os.system(f"svn export --force -q {url} {t}")
        socketio.emit('toast', {'text': f'✅ {name} 下载完成!'}, namespace='/')
    except: pass
@socketio.on('download_model')
def on_dl(d):
    urls = {
        "Mao": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Mao",
        "Natori": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Natori",
        "Rice": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Rice",
        "Wanko": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Wanko"
    }
    if d['name'] in urls:
        emit('toast', {'text': f'🚀 开始下载 {d["name"]}...', 'type': 'info'})
        socketio.start_background_task(bg_dl, urls[d['name']], d['name'])
