# =======================================================================
# Pico AI Server - app.py (管理员记忆 + 语音热更新)
# =======================================================================
import os, json, uuid, asyncio, time, glob, shutil, re, zipfile, subprocess
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
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")
for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]: os.makedirs(d, exist_ok=True)

# --- API ---
CONFIG = {}
try: with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
if CONFIG.get("GEMINI_API_KEY"):
    try: client = genai.Client(api_key=CONFIG.get("GEMINI_API_KEY"))
    except Exception as e: print(f"API Error: {e}")

# --- 核心函数 ---
CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.0, "y": 0.0}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    # 默认值
    d = {"persona":f"你是一个名为{mid}的AI。","voice":"zh-CN-XiaoxiaoNeural","rate":"+0%","pitch":"+0Hz","scale":0.5,"x":0.0,"y":0.0}
    if os.path.exists(p):
        try: d.update(json.load(open(p))) 
        except: pass
    return d

def save_model_config(mid, d):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    c = get_model_config(mid); c.update(d)
    with open(p, "w", encoding="utf-8") as f: json.dump(c, f, ensure_ascii=False, indent=2)
    return c

def scan_models():
    ms = []
    for j in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        mid = os.path.basename(os.path.dirname(j))
        cfg = get_model_config(mid)
        ms.append({
            "id": mid, "name": mid.capitalize(),
            "path": "/"+os.path.relpath(j, BASE_DIR).replace("\\","/"),
            **cfg
        })
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
init_model()

def run_piper_tts(text, model_file, output_path):
    model_path = os.path.join(VOICES_DIR, model_file)
    if not os.path.exists(PIPER_BIN): return False
    try:
        cmd = f'echo "{text}" | "{PIPER_BIN}" --model "{model_path}" --output_file "{output_path}"'
        subprocess.run(cmd, shell=True, check=True)
        return True
    except: return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}"
    try:
        if voice.endswith(".onnx"):
            out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
            if run_piper_tts(clean, voice, out_path): url = f"/static/audio/{fname}.wav"
            else: return
        else:
            out_path = os.path.join(AUDIO_DIR, f"{fname}.mp3")
            async def _run():
                cm = edge_tts.Communicate(clean, voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            asyncio.run(_run())
            url = f"/static/audio/{fname}.mp3"
        
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
    except Exception as e: print(f"TTS Error: {e}")

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
    return jsonify({'success': False, 'msg': '仅支持 .zip'})

# --- SocketIO ---
users = {}
chatroom_chat = None
def init_chatroom():
    global chatroom_chat
    if not client: return
    # 【核心】这里使用了 CURRENT_MODEL 的最新 persona
    chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": CURRENT_MODEL['persona']})

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})
@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users: emit('system_message', {'text': f"💨 {users.pop(request.sid)['username']} 离开了。"}, to='lobby')

@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    token = d.get('token') # 【新增】接收前端的 token
    
    is_admin_user = False
    # 简单的 Token 验证 (只要前端说是 YK 且有标记，就认)
    # 生产环境需要更安全的 token，但这里够用了
    if u.lower() == "yk" and token == "pico_admin_secret":
        is_admin_user = True
        
    users[request.sid] = {"username": u, "is_admin": is_admin_user}
    join_room('lobby')
    
    if not chatroom_chat: init_chatroom()
    
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL, 'is_admin': is_admin_user})
    emit('system_message', {'text': f"🎉 欢迎 {u} 加入！"}, to='lobby', include_self=False)
    
    if is_admin_user:
         emit('system_message', {'text': f"👑 欢迎回来，管理员 {u}！"}, to=request.sid)

    welcome = f"[HAPPY] 嗨 {u}！我是{CURRENT_MODEL['name']}。"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    # 使用最新语音配置
    socketio.start_background_task(bg_tts, welcome, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]['username']
    msg = d['text']

    if "/管理员" in msg:
        if sender.lower() == "yk":
            users[sid]['is_admin'] = True
            emit('admin_unlocked') # 发送解锁信号给前端
            emit('system_message', {'text': f"👑 管理员 {sender} 权限激活！"}, to=sid)
        else: emit('system_message', {'text': "🤨 你不是 YK！"}, to=sid)
        return

    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    
    try:
        if not chatroom_chat: init_chatroom()
        # 使用最新人设
        chatroom_chat.history[-1].parts[0].text = CURRENT_MODEL['persona'] if chatroom_chat.history else ""
        
        resp = chatroom_chat.send_message(f"【{sender}说】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt=resp.text.replace(match.group(0),'').strip() if match else resp.text
        if match: emo=match.group(1)
        
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        # 【核心】确保使用当前内存中的最新配置
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except Exception as e: print(f"AI Error: {e}"); init_chatroom()

# --- 工作室 ---
def is_admin(sid): return users.get(sid, {}).get('is_admin', False)
@socketio.on('get_studio_data')
def on_get_data():
    # 获取可用语音列表
    voices = [
        {"id": "zh-CN-XiaoxiaoNeural", "name": "☁️ 晓晓 (默认)"},
        {"id": "zh-CN-YunxiNeural", "name": "☁️ 云希 (少年)"},
        {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "☁️ 晓北 (东北)"},
        {"id": "zh-TW-HsiaoChenNeural", "name": "☁️ 晓臻 (台湾)"}
    ]
    for onnx in glob.glob(os.path.join(VOICES_DIR, "*.onnx")):
        mid = os.path.basename(onnx)
        name = mid.replace(".onnx", "")
        if os.path.exists(os.path.join(VOICES_DIR, f"{name}.txt")):
            with open(os.path.join(VOICES_DIR, f"{name}.txt"),'r') as f: name=f.read().strip()
        voices.append({"id": mid, "name": f"🏠 {name} (本地)"})
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'voices': voices})

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_settings')
def on_save_s(d):
    global CURRENT_MODEL
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 权限不足', 'type': 'error'})
    
    # 保存到文件
    updated = save_model_config(d['id'], {
        "persona": d['persona'], 
        "voice": d['voice'], 
        "rate": d['rate'], 
        "pitch": d['pitch'],
        "scale": float(d['scale']),
        "x": float(d['x']),
        "y": float(d['y'])
    })
    
    # 【关键】如果保存的是当前正在用的模型，立刻更新内存！
    if CURRENT_MODEL['id'] == d['id']:
        CURRENT_MODEL.update(updated)
        init_chatroom() # 重置聊天室以应用新人设
        # 广播更新，让前端重绘模型位置
        emit('model_switched', CURRENT_MODEL, to='lobby')
        
    emit('toast', {'text': '✅ 配置已保存并生效！'})

# (删除和下载逻辑省略，保持不变)
