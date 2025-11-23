# =======================================================================
# Pico AI Server - app.py (防崩溃兜底版)
# =======================================================================
import os, json, uuid, asyncio, time, glob, shutil, re, requests, subprocess
import eventlet
eventlet.monkey_patch()
import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 目录 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")
for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]: os.makedirs(d, exist_ok=True)

# --- API ---
CONFIG = {}
try:
    with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
if CONFIG.get("GEMINI_API_KEY"):
    try: client = genai.Client(api_key=CONFIG.get("GEMINI_API_KEY"))
    except Exception as e: print(f"API Error: {e}")

# --- 模型与配置 ---
CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz"}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    # 默认值：强制使用 Edge-TTS 晓晓，确保有声音
    d = {
        "persona": f"你是一个名为{mid}的AI。",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%", "pitch": "+0Hz",
        "scale": 0.5, "x": 0.0, "y": 0.0
    }
    if os.path.exists(p):
        try: d.update(json.load(open(p))) 
        except: pass
    return d

def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    c = get_model_config(mid); c.update(data)
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
    # 【关键修复】如果之前保存的模型找不到了，强制使用 Hiyori 或第一个可用模型
    candidate = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    
    if candidate:
        CURRENT_MODEL = candidate
        print(f"🤖 模型初始化为: {CURRENT_MODEL['name']} (Path: {CURRENT_MODEL['path']})")
    else:
        print("❌ 警告：未找到任何 Live2D 模型！请运行 factory_reset.sh")

init_model()

# --- TTS (强力兜底) ---
def bg_tts(text, voice, rate, pitch, api_url="", api_key="", model_id="", room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    
    fname = f"{uuid.uuid4()}.mp3"
    out_path = os.path.join(AUDIO_DIR, fname)
    success = False
    
    # 1. 尝试外部 API
    if api_url and api_key and model_id:
        # (此处省略 run_openai_tts 代码以防出错，既然你不用，我们专注于 Edge-TTS)
        pass 
    
    # 2. Edge-TTS (带强力回退)
    if not success:
        # 如果 voice 为空或配置错误，强制使用晓晓
        safe_voice = voice if voice and "Neural" in voice else "zh-CN-XiaoxiaoNeural"
        try:
            async def _run():
                cm = edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.close()
            success = True
        except Exception as e:
            print(f"Edge-TTS Error ({safe_voice}): {e}")
            # 二次尝试：不带参数，只用默认晓晓
            if safe_voice != "zh-CN-XiaoxiaoNeural":
                print("🔄 尝试降级到默认语音...")
                try:
                    async def _run_fallback():
                        cm = edge_tts.Communicate(clean, "zh-CN-XiaoxiaoNeural")
                        await cm.save(out_path)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(_run_fallback())
                    loop.close()
                    success = True
                except: pass

    if success:
        url = f"/static/audio/{fname}"
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')

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
    # ... (保持之前的上传逻辑) ...
    return jsonify({'success': False, 'msg': '上传暂时禁用，请用 reset 脚本'})

# --- SocketIO ---
users = {}
chatroom_chat = None
def init_chatroom():
    global chatroom_chat
    if not client: return
    try: chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": CURRENT_MODEL['persona']})
    except: pass

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})
@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users: emit('system_message', {'text': f"💨 {users.pop(request.sid)['username']} 离开了。"}, to='lobby')
@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    
    # 确保当前模型路径有效
    if not CURRENT_MODEL['path']: init_model()
    
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
    
    if "/管理员" in msg:
        if sender.lower() == "yk": users[sid]['is_admin']=True; emit('admin_unlocked'); emit('system_message', {'text': f"👑 管理员上线"}, to=sid)
        else: emit('system_message', {'text': "🤨 拒绝"}, to=sid)
        return
    
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    try:
        if not chatroom_chat: init_chatroom()
        resp = chatroom_chat.send_message(f"【{sender}说】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt=resp.text.replace(match.group(0),'').strip() if match else resp.text
        if match: emo=match.group(1)
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        # 传入参数
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], 
                                       CURRENT_MODEL.get('api_url'), CURRENT_MODEL.get('api_key'), CURRENT_MODEL.get('model_id'), room='lobby')
    except Exception as e: print(f"AI: {e}"); init_chatroom()

# --- 工作室接口 ---
def is_admin(sid): return users.get(sid, {}).get('is_admin', False)
@socketio.on('get_studio_data')
def on_get_data():
    voices = [{"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓"},{"id":"zh-CN-YunxiNeural","name":"☁️ 云希"}]
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'voices': voices})
@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_settings')
def on_save_settings(d):
    global CURRENT_MODEL
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 无权限', 'type': 'error'})
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL.update(updated); init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
