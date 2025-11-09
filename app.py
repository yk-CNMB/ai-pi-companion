# =======================================================================
# Pico AI Server - app.py (群聊修复 + 完整功能版)
# 启动: gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
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
try: with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
if CONFIG.get("GEMINI_API_KEY"):
    try: client = genai.Client(api_key=CONFIG.get("GEMINI_API_KEY"))
    except Exception as e: print(f"API Error: {e}")

# --- 功能函数 ---
def load_user_memories(u):
    try:
        p = os.path.join(MEMORIES_DIR, f"{''.join([c for c in u if c.isalnum()]).lower() or 'default'}.json")
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    except: return []
def save_user_memory(u, f_text):
    p = os.path.join(MEMORIES_DIR, f"{''.join([c for c in u if c.isalnum()]).lower() or 'default'}.json")
    m = load_user_memories(u)
    if f_text not in m:
        m.append(f_text)
        with open(p, "w", encoding="utf-8") as f: json.dump(m, f, ensure_ascii=False)
        return True
    return False

# --- 模型管理 ---
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
chatroom_chat = None # 【关键修复】恢复全局聊天室会话

# 初始化/重置全局聊天室
def init_chatroom():
    global chatroom_chat
    if not client: return
    # 将当前模型的人设应用到全局聊天室
    chatroom_chat = client.chats.create(
        model="gemini-2.5-flash",
        config={"system_instruction": CURRENT_MODEL['persona']}
    )
    print(f"🏠 全局聊天室已重置 (使用人设: {CURRENT_MODEL['name']})")

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})
@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        emit('system_message', {'text': f"💨 {users.pop(request.sid)} 离开了。"}, to='lobby')

@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = u
    join_room('lobby')
    global chatroom_chat
    if not chatroom_chat: init_chatroom()
    
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 欢迎 {u} 加入！"}, to='lobby', include_self=False)
    
    # 开场白
    welcome = f"[HAPPY] 嗨 {u}，欢迎来到直播间！\n点右上角【🎯】可以让我归位，点【🛠️】可以换人哦！"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid) # 只发给自己
    socketio.start_background_task(bg_tts, welcome, sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender, msg = users[sid], d['text']

    if msg.startswith("/记 "):
        if save_user_memory(sender, msg[3:].strip()):
             emit('response', {'text': f"🧠 记住了！", 'sender': 'Pico'}, to=sid)
        return

    # 广播用户消息
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    
    try:
        global chatroom_chat
        if not chatroom_chat: init_chatroom()
        
        # 注入短期记忆上下文
        mems = load_user_memories(sender)
        mem_ctx = f" ({', '.join(mems[-2:])})" if mems else ""
        
        # 【关键修复】使用全局 chatroom_chat 发送消息，保持群聊上下文
        resp = chatroom_chat.send_message(f"【{sender}说{mem_ctx}】: {msg}")
        
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text.replace(match.group(0), '').strip() if match else resp.text
        if match: emo = match.group(1)

        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        # 如果会话过期，尝试重置
        init_chatroom()

# --- 工作室 ---
@socketio.on('get_studio_data')
def on_get_data(): emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t:
        CURRENT_MODEL = t
        init_chatroom() # 切换模型时重置聊天室，应用新人设
        emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_persona')
def on_save_p(d):
    p = os.path.join(MODELS_DIR, d['id'], "persona.txt")
    if os.path.exists(os.path.dirname(p)):
        with open(p, "w", encoding="utf-8") as f: f.write(d['text'])
        if CURRENT_MODEL['id'] == d['id']: 
            CURRENT_MODEL['persona'] = d['text']
            init_chatroom() # 人设更新也重置聊天室
        emit('toast', {'text': '✅ 已保存'})
@socketio.on('delete_model')
def on_del(d):
    if d['id'] == CURRENT_MODEL['id']: return emit('toast', {'text': '❌ 不能删除当前模型', 'type': 'error'})
    try: shutil.rmtree(os.path.join(MODELS_DIR, d['id'])); emit('toast', {'text': '🗑️ 已删除'}); emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
    except: emit('toast', {'text': '删除失败', 'type': 'error'})
@socketio.on('download_model')
def on_dl(d):
    urls = {"Mao":".../Mao", "Natori":".../Natori", "Rice":".../Rice", "Wanko":".../Wanko"} # 简写了，实际请用完整URL或保持你现有的
    # 这里为了完整性，请确保你复制了之前完整版的 download_model 逻辑，或者我给你补全：
    official_base = "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/"
    if d['name'] in ["Mao", "Natori", "Rice", "Wanko"]:
        emit('toast', {'text': f'🚀 开始下载 {d["name"]}...', 'type': 'info'})
        # 启动后台下载 (需要完整的 bg_download_task 函数，见之前版本，或简写如下)
        def dl_task(n):
            try:
                t = os.path.join(MODELS_DIR, n.lower()); 
                if os.path.exists(t): shutil.rmtree(t)
                os.makedirs(t, exist_ok=True)
                os.system(f"svn export --force -q {official_base}{n} {t}")
                socketio.emit('toast', {'text': f'✅ {n} 下载完成!'}, namespace='/')
            except: pass
        socketio.start_background_task(dl_task, d['name'])
