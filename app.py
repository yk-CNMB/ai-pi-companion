# =======================================================================
# Pico AI Server - app.py (Sherpa + Piper 双引擎版)
# =======================================================================
import os
import json
import uuid
import asyncio
import time
import glob
import shutil
import re
import zipfile
import subprocess
import requests
import threading

# 尝试导入 sherpa (如果没装会报错，所以上面那步安装很重要)
try:
    import sherpa_onnx
    HAS_SHERPA = True
except ImportError:
    HAS_SHERPA = False
    print("⚠️ 未检测到 sherpa-onnx 库，GlaDOS 模型将无法使用")

import edge_tts
import soundfile as sf
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from google import genai

# --- 1. 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 2. 目录 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")

for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# --- 3. API 配置 ---
CONFIG = {}
try:
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            CONFIG = json.load(f)
    print("✅ 已加载 config.json")
except:
    pass

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if api_key and "在这里" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini API 就绪")
    except Exception as e:
        print(f"❌ API 初始化失败: {e}")
else:
    print("❌ 未找到有效 API KEY")

# --- 4. 核心函数 ---
def load_user_memories(u): return []

CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5}

def get_model_config(model_id):
    p = os.path.join(MODELS_DIR, model_id, "config.json")
    data = {"persona":f"你是{model_id}。","voice":"zh-CN-XiaoxiaoNeural","rate":"+0%","pitch":"+0Hz","scale":0.5,"x":0.5,"y":0.5}
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
        ms.append({"id": mid, "name": mid.capitalize(), "path": "/"+os.path.relpath(j, BASE_DIR).replace("\\","/"), **cfg})
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
init_model()

# --- 5. 语音合成引擎 (双模) ---

# 预加载 Sherpa (GlaDOS)
glados_engine = None
def load_glados():
    global glados_engine
    if not HAS_SHERPA: return
    
    # 你的文件结构是直接在 voices 下
    model_path = os.path.join(VOICES_DIR, "en_US-glados.onnx")
    tokens_path = os.path.join(VOICES_DIR, "tokens.txt")
    data_dir = os.path.join(VOICES_DIR, "espeak-ng-data")
    
    if os.path.exists(model_path) and os.path.exists(tokens_path):
        try:
            print("🔧 正在加载 GlaDOS 引擎...")
            cfg = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=model_path,
                        tokens=tokens_path,
                        data_dir=data_dir,
                    ),
                    provider="cpu",
                    num_threads=2
                )
            )
            glados_engine = sherpa_onnx.OfflineTts(cfg)
            print("✅ GlaDOS 引擎就绪！")
        except Exception as e:
            print(f"❌ GlaDOS 加载失败: {e}")

# 启动时加载
if HAS_SHERPA:
    threading.Thread(target=load_glados).start()

def run_sherpa_tts(text, output_path):
    if not glados_engine: return False
    try:
        # sid=0 是默认说话人
        audio = glados_engine.generate(text, sid=0, speed=1.0)
        sf.write(output_path, audio.samples, audio.sample_rate)
        return True
    except Exception as e:
        print(f"Sherpa Error: {e}")
        return False

def run_piper_tts(text, model_file, output_path):
    # ... (保留 Piper 逻辑，虽然 GlaDOS 不用它) ...
    model_path = os.path.join(VOICES_DIR, model_file)
    if not os.path.exists(PIPER_BIN): return False
    try:
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", output_path]
        subprocess.run(cmd, input=text.encode('utf-8'), check=True, capture_output=True)
        return True
    except: return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    
    fname = f"{uuid.uuid4()}"
    success = False
    url = ""
    
    # 1. 判断是不是 GlaDOS (通过文件名判断)
    if "glados" in voice.lower() and glados_engine:
        out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
        if run_sherpa_tts(clean, out_path):
            success = True
            url = f"/static/audio/{fname}.wav"
            print("🐟 GlaDOS 生成成功")
            
    # 2. Piper (普通 .onnx)
    if not success and voice.endswith(".onnx"):
         out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
         if run_piper_tts(clean, voice, out_path):
             success = True
             url = f"/static/audio/{fname}.wav"

    # 3. Edge-TTS (兜底)
    if not success:
        out_path = os.path.join(AUDIO_DIR, f"{fname}.mp3")
        safe_voice = "zh-CN-XiaoxiaoNeural"
        # 只有当 voice 是有效的 Edge 格式时才用，否则回退到晓晓
        if voice and "Neural" in voice:
            safe_voice = voice
            
        try:
            async def _run():
                cm = edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.close()
            success = True
            url = f"/static/audio/{fname}.mp3"
        except Exception as e:
            print(f"❌ TTS Error: {e}")

    if success:
        if room:
            socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid:
            socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')

# --- 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    if v != SERVER_VERSION: return redirect(url_for('pico_v', v=SERVER_VERSION))
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

@app.route('/upload_model', methods=['POST'])
def upload_model():
    # (保持不变)
    if 'file' not in request.files: return jsonify({'success': False})
    f = request.files['file']
    if f.filename == '': return jsonify({'success': False})
    if f and f.filename.endswith('.zip'):
        try:
            n = secure_filename(f.filename).rsplit('.', 1)[0].lower()
            p = os.path.join(MODELS_DIR, n)
            if os.path.exists(p): shutil.rmtree(p)
            with zipfile.ZipFile(f, 'r') as z: z.extractall(p)
            items = os.listdir(p)
            if len(items) == 1 and os.path.isdir(os.path.join(p, items[0])):
                sub = os.path.join(p, items[0])
                for i in os.listdir(sub): shutil.move(os.path.join(sub, i), p)
                os.rmdir(sub)
            return jsonify({'success': True})
        except Exception as e: return jsonify({'success': False})
    return jsonify({'success': False})

# --- SocketIO ---
users = {}
chatroom_chat = None

def init_chatroom():
    global chatroom_chat
    if not client: return
    try:
        chatroom_chat = client.chats.create(
            model="gemini-2.5-flash",
            config={"system_instruction": CURRENT_MODEL['persona']}
        )
    except: pass

@socketio.on('connect')
def on_connect():
    emit('server_ready', {'status': 'ok'})

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

    if "/管理员" in msg:
        if sender.lower() == "yk":
            users[sid]['is_admin'] = True
            emit('admin_unlocked')
            emit('system_message', {'text': f"👑 管理员上线"}, to=sid)
        else:
            emit('system_message', {'text': "🤨 拒绝"}, to=sid)
        return
    
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')

    try:
        if not chatroom_chat: init_chatroom()
        mem_ctx = f" (记忆: {', '.join(user_memories)})" if user_memories else ""
        resp = chatroom_chat.send_message(f"【{sender}说{mem_ctx}】: {msg}")
        
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text.replace(match.group(0), '').strip() if match else resp.text
        if match: emo = match.group(1)

        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")
        init_chatroom()

# --- 工作室 ---
def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    voices = [{"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓 (默认)"},{"id":"zh-CN-YunxiNeural","name":"☁️ 云希 (少年)"}]
    
    # 扫描本地
    # 1. 扫描通用 Piper (.onnx)
    for onnx in glob.glob(os.path.join(VOICES_DIR, "*.onnx")):
        mid = os.path.basename(onnx)
        name = mid.replace(".onnx", "")
        if os.path.exists(os.path.join(VOICES_DIR, f"{name}.txt")):
            try: name = open(os.path.join(VOICES_DIR, f"{name}.txt")).read().strip()
            except: pass
        voices.append({"id": mid, "name": f"🏠 {name}"})
    
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'voices': voices})

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t:
        CURRENT_MODEL = t
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_settings')
def on_save_settings(d):
    global CURRENT_MODEL
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 无权限', 'type': 'error'})
    try:
        d['scale'] = float(d['scale'])
        d['x'] = float(d['x'])
        d['y'] = float(d['y'])
    except: pass

    updated = save_model_config(d['id'], d)
    
    if CURRENT_MODEL['id'] == d['id']:
        CURRENT_MODEL.update(updated)
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})

@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return
    if d['id'] == CURRENT_MODEL['id']: return emit('toast', {'text': '❌ 占用中', 'type': 'error'})
    try:
        shutil.rmtree(os.path.join(MODELS_DIR, d['id']))
        emit('toast', {'text': '🗑️ 已删除', 'type': 'success'})
        on_get_data()
    except: pass

@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return
    name = d.get('name')
    if name:
        emit('toast', {'text': f'🚀 开始下载 {name}...', 'type': 'info'})
        socketio.start_background_task(bg_dl_task, name)

def bg_dl_task(name):
    u = {"Mao":".../Mao","Natori":".../Natori"}.get(name, "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/"+name)
    t = os.path.join(MODELS_DIR, name.lower())
    if os.path.exists(t): shutil.rmtree(t, ignore_errors=True)
    os.makedirs(t, exist_ok=True)
    try:
        os.system(f"svn export --force -q {u} {t}")
        socketio.emit('toast',{'text':f'✅ {name} 完成!'},namespace='/')
    except: pass

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)


