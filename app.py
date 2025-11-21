# =======================================================================
# Pico AI Server - app.py (支持 Sherpa-onnx VITS)
# =======================================================================
import os, json, uuid, asyncio, time, glob, shutil, re, subprocess
import eventlet
eventlet.monkey_patch()
import edge_tts
import sherpa_onnx # 新增库
import soundfile as sf # 用于保存音频
import numpy as np
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]: os.makedirs(d, exist_ok=True)

CONFIG = {}
try: with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
if CONFIG.get("GEMINI_API_KEY"):
    try: client = genai.Client(api_key=CONFIG.get("GEMINI_API_KEY"))
    except Exception as e: print(f"API Error: {e}")

# --- Sherpa 引擎初始化 ---
sherpa_tts = None
def init_sherpa():
    global sherpa_tts
    sherpa_path = os.path.join(VOICES_DIR, "sherpa")
    model_file = os.path.join(sherpa_path, "model.onnx")
    if os.path.exists(model_file):
        try:
            print("🔧 正在加载 Sherpa-onnx 引擎...")
            tts_config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=model_file,
                        lexicon=os.path.join(sherpa_path, "lexicon.txt"),
                        tokens=os.path.join(sherpa_path, "tokens.txt"),
                    ),
                    provider="cpu",
                    num_threads=2,
                    debug=False,
                )
            )
            sherpa_tts = sherpa_onnx.OfflineTts(tts_config)
            print("✅ Sherpa-onnx 加载成功！")
        except Exception as e:
            print(f"❌ Sherpa 加载失败: {e}")

# 启动时尝试加载
init_sherpa()

# --- 功能函数 ---
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

CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz"}
def scan_models():
    ms = []
    for j in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        mid = os.path.basename(os.path.dirname(j))
        pp = os.path.join(os.path.dirname(j), "persona.txt")
        if not os.path.exists(pp):
            with open(pp, "w", encoding="utf-8") as f: f.write(f"你是一个名为'{mid}'的AI。")
        with open(pp, "r", encoding="utf-8") as f: p = f.read()
        
        # 读取配置
        cfg = {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz"}
        cfg_path = os.path.join(os.path.dirname(j), "config.json")
        if os.path.exists(cfg_path):
            try: cfg.update(json.load(open(cfg_path)))
            except: pass
            
        ms.append({"id": mid, "name": mid.capitalize(), "path": "/"+os.path.relpath(j, BASE_DIR).replace("\\","/"), "persona": p, **cfg})
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
init_model()

# --- 核心 TTS ---
def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}.wav"
    out_path = os.path.join(AUDIO_DIR, fname)
    
    try:
        if voice == "sherpa-vits" and sherpa_tts:
            # 使用 Sherpa 生成
            # sid=0 是默认说话人，如果是多说话人模型可以改这个数字变声
            audio = sherpa_tts.generate(clean, sid=0, speed=1.0)
            sf.write(out_path, audio.samples, audio.sample_rate)
            
        else:
            # 默认 Edge-TTS (mp3)
            fname = f"{uuid.uuid4()}.mp3"
            out_path = os.path.join(AUDIO_DIR, fname)
            async def _run():
                cm = edge_tts.Communicate(clean, voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            asyncio.run(_run())
            
        url = f"/static/audio/{fname}"
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
    # (保持之前的上传代码不变)
    return jsonify({'success': False, 'msg': '暂略，请保留之前的上传代码'})

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
    if request.sid in users: emit('system_message', {'text': f"💨 {users.pop(request.sid)['username']} 离开了。"}, to='lobby')
@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 {u} 加入！"}, to='lobby', include_self=False)
    welcome = f"[HAPPY] 嗨 {u}！"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]['username']
    msg = d['text']
    user_memories = d.get('memories', [])

    if msg.strip()=="/管理员":
        if sender=="YK": users[sid]['is_admin']=True; emit('admin_unlocked'); emit('system_message',{'text':"👑 管理员上线"},to=sid)
        return
        
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    try:
        if not chatroom_chat: init_chatroom()
        mem_ctx = f" (记忆: {', '.join(user_memories)})" if user_memories else ""
        resp = chatroom_chat.send_message(f"【{sender}说{mem_ctx}】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt=resp.text.replace(match.group(0),'').strip() if match else resp.text
        if match: emo=match.group(1)
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except Exception as e: print(f"AI: {e}"); init_chatroom()

# --- 工作室 ---
def is_admin(sid): return users.get(sid, {}).get('is_admin', False)
@socketio.on('get_studio_data')
def on_get_data(): emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_settings')
def on_save_s(d):
    if not is_admin(request.sid): return
    # 保存到 config.json
    p = os.path.join(MODELS_DIR, d['id'], "config.json")
    with open(p, "w") as f: json.dump({"persona":d['persona'],"voice":d['voice'],"rate":d['rate'],"pitch":d['pitch']}, f)
    # 同时更新 persona.txt 兼容旧逻辑
    with open(os.path.join(MODELS_DIR, d['id'], "persona.txt"), "w") as f: f.write(d['persona'])
    
    if CURRENT_MODEL['id'] == d['id']:
        global CURRENT_MODEL
        CURRENT_MODEL.update(d)
        init_chatroom()
    emit('toast', {'text': '✅ 保存成功'})

# ... (保留 download_model, delete_model 逻辑) ...
```

---

### 🎨 步骤 4：前端 `chat.html` 增加 Sherpa 选项

你需要把 "Sherpa VITS" 加入到声音选择列表里。

修改 `templates/chat.html` 中的 `<select id="voice-select">`：

```html
<select id="voice-select" style="...">
    <option value="sherpa-vits">🔥 Sherpa VITS (本地高性能)</option> <!-- 新增这一行 -->
    <option value="zh-CN-XiaoxiaoNeural">晓晓</option>
    <!-- ... 其他选项 ... -->
</select>
