# =======================================================================
# Pico AI Server - app.py (本地存储版)
# 后端不再存储任何公共聊天记录，只负责实时转发
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

# --- 目录 & 配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR]: os.makedirs(d, exist_ok=True)

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
    m = load_user_memories(u); m.append(f_text) # 修复: 之前版本保存的是对象，现在只存文本
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
chatroom_chat = None # 依然保留群聊上下文

# 【核心删除】
# chatroom_history = [] 
# add_to_history()
# 这两个函数已经不需要了

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
        data = {'text': f"💨 {users.pop(request.sid)['username']} 离开了。"}
        emit('system_message', data, to='lobby') # 依然广播，让前端存入历史

@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    
    # 【核心删除】不再发送 emit('chat_history', ...)
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    
    # 广播加入消息，让前端存入历史
    join_data = {'text': f"🎉 欢迎 {u} 加入！"}
    emit('system_message', join_data, to='lobby', include_self=False)
    
    # 个人欢迎语 (这个不存历史)
    welcome = f"[HAPPY] 嗨 {u}！我是{CURRENT_MODEL['name']}。\n聊天记录会保存在你的浏览器本地哦！"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender_name = users[sid]['username']
    msg = d['text']

    if msg.strip() == "/管理员": # ... (管理员逻辑保持不变)
        if sender_name == "YK":
            users[sid]['is_admin'] = True
            emit('admin_unlocked'); emit('system_message', {'text': f"👑 管理员 {sender_name} 已上线！"}, to=sid)
        else:
            emit('system_message', {'text': "🤨 你不是 YK！"}, to=sid)
        return
    if msg.strip() == "/清除记忆": # ... (个人记忆逻辑保持不变)
        clear_user_memory(sender_name)
        emit('response', {'text': "[SHOCK] 咦？我好像忘了点什么...", 'sender': 'Pico', 'emotion': 'SHOCK'}, to=sid)
        return

    # 1. 广播用户消息 (前端会收到并存入历史)
    chat_data = {'text': msg, 'sender': sender_name}
    emit('chat_message', chat_data, to='lobby')
    auto_save_memory(sender_name, msg)

    # 2. AI 回复 (前端会收到并存入历史)
    try:
        if not chatroom_chat: init_chatroom()
        mems = load_user_memories(sender_name)
        mem_ctx = f" (关于{sender_name}的记忆: {', '.join(mems[-3:])})" if mems else ""
        resp = chatroom_chat.send_message(f"【{sender_name}说{mem_ctx}】: {msg}")
        
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text.replace(match.group(0), '').strip() if match else resp.text
        if match: emo = match.group(1)

        response_data = {'text': txt, 'sender': 'Pico', 'emotion': emo}
        emit('response', response_data, to='lobby')
        socketio.start_background_task(bg_tts, txt, room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        init_chatroom()

# --- 工作室接口 (保持不变) ---
def is_admin(sid): return users.get(sid, {}).get('is_admin', False)
@socketio.on('get_studio_data')
def on_get_data(): emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_persona')
def on_save_p(d):
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    p = os.path.join(MODELS_DIR, d['id'], "persona.txt")
    if os.path.exists(os.path.dirname(p)):
        with open(p, "w", encoding="utf-8") as f: f.write(d['text'])
        if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL['persona'] = d['text']; init_chatroom()
        emit('toast', {'text': '✅ 人设已保存'})
@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    if d['id'] == CURRENT_MODEL['id']: return emit('toast', {'text': '❌ 不能删除当前模型', 'type': 'error'})
    try: shutil.rmtree(os.path.join(MODELS_DIR, d['id'])); emit('toast', {'text': '🗑️ 已删除'}); emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
    except: emit('toast', {'text': '删除失败', 'type': 'error'})
def bg_dl_task(name):
    urls = {"Mao":".../Mao", "Natori":".../Natori", "Rice":".../Rice", "Wanko":".../Wanko"}
    url = urls.get(name, "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/" + name)
    t = os.path.join(MODELS_DIR, name.lower())
    if os.path.exists(t): shutil.rmtree(t)
    os.makedirs(t, exist_ok=True)
    try:
        os.system(f"svn export --force -q {url} {t}")
        socketio.emit('toast', {'text': f'✅ {name} 下载完成!'}, namespace='/')
    except: pass
@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    name = d.get('name')
    if name:
        emit('toast', {'text': f'🚀 开始下载 {name}...', 'type': 'info'})
        socketio.start_background_task(bg_dl_task, name)
