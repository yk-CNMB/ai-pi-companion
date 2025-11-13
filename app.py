# =======================================================================
# Pico AI Server - app.py (无状态版)
# 后端不再存储任何个人记忆或聊天记录
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
# 【移除】不再需要 MEMORIES_DIR
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
for d in [AUDIO_DIR, MODELS_DIR]: os.makedirs(d, exist_ok=True)

CONFIG = {}
try:
    with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
if CONFIG.get("GEMINI_API_KEY"):
    try: client = genai.Client(api_key=CONFIG.get("GEMINI_API_KEY"))
    except Exception as e: print(f"API Error: {e}")

# --- 【移除】所有本地记忆函数 (load/save/clear) ---

# --- 模型管理 (保持不变) ---
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

# --- TTS ---
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
users = {}
chatroom_chat = None # 群聊会话依然在服务器，但*不*包含个人记忆

def init_chatroom():
    global chatroom_chat
    if not client: return
    chatroom_chat = client.chats.create(
        model="gemini-2.5-flash",
        config={"system_instruction": CURRENT_MODEL['persona']}
    )
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
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 欢迎 {u} 加入！"}, to='lobby', include_self=False)
    
    # 开场白更新
    welcome = f"[HAPPY] 嗨 {u}！我是{CURRENT_MODEL['name']}。\n你的聊天记录和个人记忆都会保存在你自己的浏览器上哦！\n发送 /清除记忆 就可以忘掉它们。"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender_name = users[sid]['username']
    msg = d['text']
    # 【核心】接收前端发来的本地记忆
    user_memories = d.get('memories', [])

    # --- 权限指令 ---
    if msg.strip() == "/管理员":
        if sender_name == "YK":
            users[sid]['is_admin'] = True
            emit('admin_unlocked')
            emit('system_message', {'text': f"👑 管理员 {sender_name} 已上线！"}, to=sid)
        else:
            emit('system_message', {'text': "🤨 你不是 YK！"}, to=sid)
        return
    # 【注意】/清除记忆 指令现在由前端处理，后端不再响应
    
    # 广播用户消息
    emit('chat_message', {'text': msg, 'sender': sender_name}, to='lobby')
    # 【移除】后端不再自动保存记忆

    # AI 回复
    try:
        if not chatroom_chat: init_chatroom()
        
        # 【核心】将本地记忆注入到 Prompt 中
        mem_ctx = ""
        if user_memories:
             mem_ctx = f" (这是我需要记住的关于{sender_name}的事: {', '.join(user_memories)})"
        
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
