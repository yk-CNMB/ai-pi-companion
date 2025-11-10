# =======================================================================
# Pico AI Server - app.py (自动记忆 + 记忆清除版)
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

# --- 核心：自动记忆管理 ---
MAX_MEMORIES = 100 # 每个用户最多保留最近 50 条记忆

def get_memory_path(username):
    safe_name = "".join([c for c in username if c.isalnum() or c in ('-','_')]).lower() or "default"
    return os.path.join(MEMORIES_DIR, f"{safe_name}.json")

def load_user_memories(username):
    try:
        with open(get_memory_path(username), "r", encoding="utf-8") as f:
            return json.load(f)
    except: return []

def auto_save_memory(username, text):
    """自动保存记忆，并执行滚动删除"""
    memories = load_user_memories(username)
    # 添加新记忆 (带时间戳，虽然目前没用到，但未来可能有用)
    memories.append({"ts": int(time.time()), "txt": text})
    # 滚动删除：只保留最后 MAX_MEMORIES 条
    if len(memories) > MAX_MEMORIES:
        memories = memories[-MAX_MEMORIES:]
    # 保存
    with open(get_memory_path(username), "w", encoding="utf-8") as f:
        json.dump(memories, f, ensure_ascii=False)

def clear_user_memory(username):
    """清除指定用户的记忆"""
    path = get_memory_path(username)
    if os.path.exists(path):
        os.remove(path)
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
chatroom_chat = None

def init_chatroom():
    global chatroom_chat
    if not client: return
    chatroom_chat = client.chats.create(
        model="gemini-2.5-flash",
        config={"system_instruction": CURRENT_MODEL['persona']}
    )
    print(f"🏠 聊天室重置 (人设: {CURRENT_MODEL['name']})")

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
    
    # 更新后的开场白
    welcome = f"[HAPPY] 嗨 {u}！我是{CURRENT_MODEL['name']}。\n我会自动记住我们说过的话哦！\n如果想让我忘掉一切，请发送【/清除记忆】。"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender, msg = users[sid], d['text']

    # 【新增】记忆清除指令
    if msg.strip() == "/清除记忆":
        if clear_user_memory(sender):
            emit('system_message', {'text': f"🧹 已清除 {sender} 的所有记忆！"}, to=sid)
            # 可选：让 Pico 也确认一下
            emit('response', {'text': "[SHOCK] 哎？刚才发生了什么？我怎么什么都不记得了...", 'sender': 'Pico', 'emotion': 'SHOCK'}, to=sid)
        return

    # 广播用户消息
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    
    # 【核心】自动保存这条消息到记忆
    auto_save_memory(sender, msg)

    try:
        global chatroom_chat
        if not chatroom_chat: init_chatroom()
        
        # 读取最近的 5 条记忆作为上下文，避免 Prompt 太长
        all_memories = load_user_memories(sender)
        recent_memories = [m['txt'] for m in all_memories[-5:]]
        mem_ctx = f" ({sender}的近期对话: {'; '.join(recent_memories)})" if recent_memories else ""
        
        resp = chatroom_chat.send_message(f"【{sender}说{mem_ctx}】: {msg}")
        
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text.replace(match.group(0), '').strip() if match else resp.text
        if match: emo = match.group(1)

        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        init_chatroom() # 尝试自愈

# --- 工作室接口 (保持不变) ---
@socketio.on('get_studio_data')
def on_get_data(): emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_persona')
def on_save_p(d):
    p = os.path.join(MODELS_DIR, d['id'], "persona.txt")
    if os.path.exists(os.path.dirname(p)):
        with open(p, "w", encoding="utf-8") as f: f.write(d['text'])
        if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL['persona'] = d['text']; init_chatroom()
        emit('toast', {'text': '✅ 人设已保存'})
@socketio.on('delete_model')
def on_del(d):
    if d['id'] == CURRENT_MODEL['id']: return emit('toast', {'text': '❌ 不能删除当前模型', 'type': 'error'})
    try: shutil.rmtree(os.path.join(MODELS_DIR, d['id'])); emit('toast', {'text': '🗑️ 已删除'}); emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
    except: emit('toast', {'text': '删除失败', 'type': 'error'})
@socketio.on('download_model')
def on_dl(d):
    urls = {"Mao":"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Mao", "Natori":"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Natori", "Rice":"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Rice", "Wanko":"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Wanko"}
    if d['name'] in urls:
        emit('toast', {'text': f'🚀 开始下载 {d["name"]}...', 'type': 'info'})
        def bg_dl_task(u, n):
            try:
                t = os.path.join(MODELS_DIR, n.lower())
                if os.path.exists(t): shutil.rmtree(t)
                os.makedirs(t, exist_ok=True)
                os.system(f"svn export --force -q {u} {t}")
                socketio.emit('toast', {'text': f'✅ {n} 下载完成!'}, namespace='/')
            except: socketio.emit('toast', {'text': f'❌ {n} 下载失败', 'type': 'error'}, namespace='/')
        socketio.start_background_task(bg_dl_task, urls[d['name']], d['name'])
