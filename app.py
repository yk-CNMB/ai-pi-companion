# =======================================================================
# Pico AI Server - app.py (位置校准 + 宽松指令版)
# 启动: gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
# =======================================================================
import os, json, uuid, asyncio, time, glob, shutil, re, zipfile
import eventlet
eventlet.monkey_patch()
import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 目录配置 ---
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

# --- 模型配置管理 (新增位置参数) ---
CURRENT_MODEL = {
    "id": "default", "path": "", "persona": "", 
    "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz",
    "scale": 1.0, "x": 0, "y": 0 # 默认位置参数
}

def get_model_config(model_id):
    p = os.path.join(MODELS_DIR, model_id, "config.json")
    # 默认配置增加了 scale, x, y
    data = {
        "persona": f"你是一个名为{model_id}的AI。",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%", "pitch": "+0Hz",
        "scale": 0.5, "x": 0.5, "y": 0.5 # 使用比例坐标 (0.5 = 屏幕中心)
    }
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except: pass
    return data

def save_model_config(model_id, data):
    p = os.path.join(MODELS_DIR, model_id, "config.json")
    current = get_model_config(model_id)
    current.update(data)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return current

def scan_models():
    ms = []
    for j in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        mid = os.path.basename(os.path.dirname(j))
        cfg = get_model_config(mid)
        ms.append({
            "id": mid, "name": mid.capitalize(),
            "path": "/"+os.path.relpath(j, BASE_DIR).replace("\\","/"),
            "persona": cfg['persona'],
            "voice": cfg['voice'], "rate": cfg['rate'], "pitch": cfg['pitch'],
            "scale": cfg.get('scale', 0.5),
            "x": cfg.get('x', 0.5),
            "y": cfg.get('y', 0.5)
        })
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
init_model()

# --- TTS ---
def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}.mp3"
    try:
        async def _run():
            cm = edge_tts.Communicate(clean, voice, rate=rate, pitch=pitch)
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

@app.route('/upload_model', methods=['POST'])
def upload_model():
    if 'file' not in request.files: return jsonify({'success': False, 'msg': '无文件'})
    f = request.files['file']
    if f and f.filename.endswith('.zip'):
        try:
            n = secure_filename(f.filename).rsplit('.', 1)[0].lower()
            p = os.path.join(MODELS_DIR, n)
            if os.path.exists(p): shutil.rmtree(p)
            with zipfile.ZipFile(f, 'r') as z: z.extractall(p)
            items = os.listdir(p)
            if len(items)==1 and os.path.isdir(os.path.join(p, items[0])):
                sub = os.path.join(p, items[0]); 
                for i in os.listdir(sub): shutil.move(os.path.join(sub, i), p)
                os.rmdir(sub)
            return jsonify({'success': True})
        except Exception as e: return jsonify({'success': False, 'msg': str(e)})
    return jsonify({'success': False})

# --- SocketIO ---
users = {}
chatroom_chat = None
def init_chatroom():
    global chatroom_chat
    if not client: return
    chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": CURRENT_MODEL['persona']})

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})
@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        emit('system_message', {'text': f"💨 {users.pop(request.sid)['username']} 离开了。"}, to='lobby')

@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    # 登录时如果名字是 YK，先标记一下（虽然实际权限由指令激活）
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 欢迎 {u} 加入！"}, to='lobby', include_self=False)
    
    welcome = f"[HAPPY] 嗨 {u}！我是{CURRENT_MODEL['name']}。"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]['username']
    msg = d['text']

    # --- 宽松的管理员指令判定 ---
    if "/管理员" in msg: # 只要包含 /管理员 就算
        if sender.lower() == "yk":
            users[sid]['is_admin'] = True
            emit('admin_unlocked')
            emit('system_message', {'text': f"👑 管理员权限已解锁！"}, to=sid)
            # 阻断消息发给 AI
            return
        else:
            emit('system_message', {'text': "🤨 鉴权失败：名字不对"}, to=sid)
            return

    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')

    try:
        if not chatroom_chat: init_chatroom()
        user_memories = d.get('memories', [])
        mem_ctx = f" (记忆: {', '.join(user_memories)})" if user_memories else ""
        resp = chatroom_chat.send_message(f"【{sender}说{mem_ctx}】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt=resp.text.replace(match.group(0),'').strip() if match else resp.text
        if match: emo=match.group(1)
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        init_chatroom()

# --- 工作室接口 (更新了保存逻辑) ---
def is_admin(sid): return users.get(sid, {}).get('is_admin', False)
@socketio.on('get_studio_data')
def on_get_data(): emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_settings')
def on_save_settings(d):
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    
    # 保存所有参数 (包括位置)
    updated = save_model_config(d['id'], {
        "persona": d['persona'],
        "voice": d['voice'],
        "rate": d['rate'],
        "pitch": d['pitch'],
        "scale": float(d['scale']),
        "x": float(d['x']),
        "y": float(d['y'])
    })
    
    if CURRENT_MODEL['id'] == d['id']:
        global CURRENT_MODEL
        CURRENT_MODEL.update(updated)
        init_chatroom()
        # 广播新的模型参数给所有人，让他们也更新位置
        emit('model_switched', CURRENT_MODEL, to='lobby')
        
    emit('toast', {'text': '✅ 所有设置（含位置）已保存'})

# ... (删除和下载逻辑保持不变) ...
@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    if d['id']==CURRENT_MODEL['id']: return emit('toast',{'text':'❌ 占用中','type':'error'})
    try: shutil.rmtree(os.path.join(MODELS_DIR, d['id'])); emit('toast',{'text':'🗑️ 已删除'}); emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
    except: pass
@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    name=d.get('name')
    if name: emit('toast', {'text': f'🚀 开始下载 {name}...', 'type': 'info'}); socketio.start_background_task(bg_dl_task, name)
def bg_dl_task(name):
    urls = {"Mao":".../Mao","Natori":".../Natori","Rice":".../Rice","Wanko":".../Wanko"}
    url = urls.get(name, "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/"+name)
    t=os.path.join(MODELS_DIR,name.lower())
    if os.path.exists(t): shutil.rmtree(t)
    os.makedirs(t, exist_ok=True)
    try: os.system(f"svn export --force -q {url} {t}"); socketio.emit('toast', {'text': f'✅ {name} 完成!'}, namespace='/')
    except: pass
