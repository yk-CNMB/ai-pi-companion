# =======================================================================
# Pico AI Server - app.py (分级权限版)
# =======================================================================
import os, json, uuid, asyncio, time, glob, shutil, re
import eventlet
eventlet.monkey_patch()
import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 目录 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR]: os.makedirs(d, exist_ok=True)

# --- API ---
CONFIG = {}
try:
    with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
if CONFIG.get("GEMINI_API_KEY"):
    try: client = genai.Client(api_key=CONFIG.get("GEMINI_API_KEY"))
    except Exception as e: print(f"API Error: {e}")

# --- 功能函数 (记忆, TTS, 模型扫描) ---
def load_user_memories(u):
    try:
        p = os.path.join(MEMORIES_DIR, f"{''.join([c for c in u if c.isalnum()]).lower() or 'default'}.json")
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    except: return []
def save_user_memory(u, f_text):
    p = os.path.join(MEMORIES_DIR, f"{''.join([c for c in u if c.isalnum()]).lower() or 'default'}.json")
    m = load_user_memories(u); m.append(f_text)
    with open(p, "w", encoding="utf-8") as f: json.dump(m[-50:], f, ensure_ascii=False)
    return True
def clear_user_memory(u):
    p = os.path.join(MEMORIES_DIR, f"{''.join([c for c in u if c.isalnum()]).lower() or 'default'}.json")
    if os.path.exists(p): os.remove(p); return True
    return False

CURRENT_MODEL = {"id": "default", "path": "", "persona": ""}
def scan_models():
    ms = []
    for j in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        mid = os.path.basename(os.path.dirname(j))
        pp = os.path.join(os.path.dirname(j), "persona.txt")
        if not os.path.exists(pp):
            with open(pp, "w", encoding="utf-8") as f: f.write(f"你是一个名为'{mid}'的AI。请用中文回复。")
        with open(pp, "r", encoding="utf-8") as f: p = f.read()
        ms.append({"id": mid, "name": mid.capitalize(), "path": "/"+os.path.relpath(j, BASE_DIR).replace("\\","/"), "persona": p})
    return sorted(ms, key=lambda x: x['name'])
def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
init_model()

def bg_tts(text, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}.mp3"
    try:
        async def _run():
            cm = edge_tts.Communicate(clean, "zh-CN-XiaoxiaoNeural")
            await cm.save(os.path.join(AUDIO_DIR, fname))
        asyncio.run(_run())
        url = f"/static/audio/{fname}"
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
    except: pass

# --- 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    if v!=SERVER_VERSION: return redirect(url_for('pico_v', v=SERVER_VERSION))
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

# --- SocketIO ---
users = {} # {sid: {'username': 'YK', 'is_admin': False}}
chatroom_chat = None

def init_chatroom():
    global chatroom_chat
    if not client: return
    chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": CURRENT_MODEL['persona']})
    print(f"🏠 聊天室已重置 (人设: {CURRENT_MODEL['name']})")

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})
@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        emit('system_message', {'text': f"💨 {users.pop(request.sid)['username']} 离开了。"}, to='lobby')

@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = {"username": u, "is_admin": False} # 默认非管理员
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 欢迎 {u} 加入！"}, to='lobby', include_self=False)
    
    welcome = f"[HAPPY] 嗨 {u}！我是{CURRENT_MODEL['name']}。\n发送 /清除记忆 可以让我忘掉你。\n点右上角【🛠️】可以换装哦！"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    
    sender_data = users[sid]
    sender_name = sender_data['username']
    msg = d['text']

    # --- 权限指令 ---
    if msg.strip() == "/管理员":
        if sender_name == "YK":
            users[sid]['is_admin'] = True
            emit('admin_unlocked') # 发送解锁信号
            emit('system_message', {'text': f"👑 管理员 {sender_name} 已上线！"}, to=sid)
        else:
            emit('system_message', {'text': "🤨 你不是 YK！"}, to=sid)
        return

    if msg.strip() == "/清除记忆":
        clear_user_memory(sender_name)
        emit('response', {'text': "[SHOCK] 咦？我好像忘了点什么...", 'sender': 'Pico', 'emotion': 'SHOCK'}, to=sid)
        return

    # 广播用户消息
    emit('chat_message', {'text': msg, 'sender': sender_name}, to='lobby')
    auto_save_memory(sender_name, msg)

    # AI 回复
    try:
        if not chatroom_chat: init_chatroom()
        mems = load_user_memories(sender_name)
        mem_ctx = f" ({sender_name}的记忆: {', '.join([m for m in mems[-3:]])})" if mems else "" # 修复了 .txt 的bug
        resp = chatroom_chat.send_message(f"【{sender_name}说{mem_ctx}】: {msg}")
        
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text.replace(match.group(0), '').strip() if match else resp.text
        if match: emo = match.group(1)

        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        init_chatroom()

# --- 🛠️ 工作室接口 (分级权限) ---

def is_admin(sid):
    return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    # 【公开】所有人都可以获取列表
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})

@socketio.on('switch_model')
def on_switch(d):
    # 【公开】所有人都可以切换模型
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t:
        CURRENT_MODEL = t
        init_chatroom() # 切换模型时重置聊天室人设
        emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_persona')
def on_save_p(d):
    # 【管理员】
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    p = os.path.join(MODELS_DIR, d['id'], "persona.txt")
    if os.path.exists(os.path.dirname(p)):
        with open(p, "w", encoding="utf-8") as f: f.write(d['text'])
        if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL['persona'] = d['text']; init_chatroom()
        emit('toast', {'text': '✅ 人设已保存'})

@socketio.on('delete_model')
def on_del(d):
    # 【管理员】
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    if d['id'] == CURRENT_MODEL['id']: return emit('toast', {'text': '❌ 不能删除当前模型', 'type': 'error'})
    try:
        shutil.rmtree(os.path.join(MODELS_DIR, d['id']))
        emit('toast', {'text': '🗑️ 已删除'})
        emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']}) # 刷新列表
    except:
        emit('toast', {'text': '删除失败', 'type': 'error'})

def bg_dl_task(name):
    urls = {
        "Mao": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Mao",
        "Natori": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Natori",
        "Rice": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Rice",
        "Wanko": "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Wanko"
    }
    url = urls.get(name)
    if not url: return
    t = os.path.join(MODELS_DIR, name.lower())
    if os.path.exists(t): shutil.rmtree(t)
    os.makedirs(t, exist_ok=True)
    try:
        os.system(f"svn export --force -q {url} {t}")
        socketio.emit('toast', {'text': f'✅ {name} 下载完成!'}, namespace='/')
    except:
        socketio.emit('toast', {'text': f'❌ {name} 下载失败', 'type': 'error'}, namespace='/')

@socketio.on('download_model')
def on_dl(d):
    # 【管理员】
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    name = d.get('name')
    if name in ["Mao", "Natori", "Rice", "Wanko"]:
        emit('toast', {'text': f'🚀 开始下载 {name}...', 'type': 'info'})
        socketio.start_background_task(bg_dl_task, name)
