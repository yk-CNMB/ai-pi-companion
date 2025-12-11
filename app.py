# =======================================================================
# Pico AI Server - 稳定回归版 (无额外依赖)
# =======================================================================
import os
import json
import uuid
import time
import glob
import shutil
import re
import zipfile
import threading
import requests
import urllib.parse
import base64
import asyncio

# 移除了 soundfile，只用 edge_tts
import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# 关键：设置 buffer size 防止发图断连
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60, max_http_buffer_size=10*1024*1024)
SERVER_VERSION = str(int(time.time()))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
BG_DIR = os.path.join(BASE_DIR, "static", "backgrounds")
STATE_FILE = os.path.join(BASE_DIR, "server_state.json")

for d in [AUDIO_DIR, MODELS_DIR, BG_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# --- 配置 ---
CONFIG = {
    "TTS_MODE": "edge", 
    "VITS_API_URL": "https://artrajz-vits-simple-api.hf.space/voice/vits?text={text}&id=165&format=wav&lang=zh"
}
try:
    if os.path.exists("config.json"):
        with open("config.json", "r") as f: 
            content = "\n".join([line for line in f.readlines() if not line.strip().startswith("//")])
            CONFIG.update(json.loads(content))
except: pass

client = None
api_key = CONFIG.get("GEMINI_API_KEY")
if api_key and "AIza" in api_key:
    try: client = genai.Client(api_key=api_key)
    except: pass

EMOTION_INSTRUCTION = """
【重要】请在回复开头用标签标记心情：
[HAPPY] - 开心
[ANGRY] - 生气
[SAD] - 悲伤
[SHOCK] - 惊讶
[NORMAL] - 平静
"""

GLOBAL_STATE = { "current_model_id": "default", "current_background": "", "chat_history": [] }

def load_state():
    global GLOBAL_STATE
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                GLOBAL_STATE.update(saved)
                GLOBAL_STATE["chat_history"] = GLOBAL_STATE["chat_history"][-50:]
        except: pass

def save_state():
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(GLOBAL_STATE, f, ensure_ascii=False, indent=2)
    except: pass

load_state()

CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "api_miku", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    default_persona = f"你是{mid}。{EMOTION_INSTRUCTION}"
    d = {"persona": default_persona, "voice":"api_miku", "rate":"+0%", "pitch":"+0Hz", "scale":0.5, "x":0.5, "y":0.5}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f: 
                loaded = json.load(f)
                if 'persona' in loaded and EMOTION_INSTRUCTION not in loaded['persona']:
                    loaded['persona'] += EMOTION_INSTRUCTION
                d.update(loaded)
        except: pass
    return d

def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    curr = get_model_config(mid)
    curr.update(data)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(curr, f, indent=2, ensure_ascii=False)
    except: pass
    return curr

def scan_models():
    ms = []
    for root, dirs, files in os.walk(MODELS_DIR):
        for file in files:
            if file.endswith(('.model3.json', '.model.json')):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, BASE_DIR).replace("\\", "/")
                if not rel_path.startswith("/"): rel_path = "/" + rel_path
                folder_name = os.path.basename(os.path.dirname(full_path))
                model_id = f"{folder_name}_{os.path.splitext(file)[0]}"
                if not any(m['id'] == folder_name for m in ms): model_id = folder_name
                cfg = get_model_config(model_id)
                ms.append({"id": model_id, "name": model_id.capitalize(), "path": rel_path, **cfg})
    return sorted(ms, key=lambda x: x['name'])

def scan_backgrounds():
    bgs = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif']:
        for f in glob.glob(os.path.join(BG_DIR, ext)): bgs.append(os.path.basename(f))
    return sorted(bgs)

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    last_id = GLOBAL_STATE.get("current_model_id")
    target = next((m for m in ms if m['id'] == last_id), None)
    if not target: target = next((m for m in ms if "hiyori" in m['id'].lower()), None)
    if not target and len(ms) > 0: target = ms[0]
    if target: 
        CURRENT_MODEL = target
        GLOBAL_STATE["current_model_id"] = target['id']
        save_state()

init_model()

# ================= TTS 逻辑 (纯 Python 实现) =================
# 这里解决了之前的 "Silence" 问题，通过手动创建事件循环
def run_edge_tts_python(text, output_path):
    print(f"🔄 [Edge Python] 生成中: {text[:10]}...")
    try:
        async def _gen():
            # 使用较新的晓晓音色
            communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural", rate="+10%", pitch="+0Hz")
            await communicate.save(output_path)
        
        # 关键：在线程中创建全新的事件循环，避免冲突
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(_gen())
        new_loop.close()
        print(f"✅ [Edge Python] 成功")
        return True
    except Exception as e:
        print(f"❌ [Edge Python] 失败: {e}")
        return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}.mp3"
    out_path = os.path.join(AUDIO_DIR, fname)
    success = False
    
    # 直接使用 Python 库，不依赖任何系统命令
    success = run_edge_tts_python(clean, out_path)

    if success:
        url = f"/static/audio/{fname}"
        payload = {'audio': url}
        print(f"🔊 推送音频: {url}")
        if room: socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', payload, to=sid, namespace='/')
    else:
        print("❌ TTS 生成失败")

# ================= 路由 =================
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

@app.route('/upload_bg', methods=['POST'])
def upload_bg():
    if 'file' not in request.files: return jsonify({'success': False})
    f = request.files['file']
    if f and '.' in f.filename:
        n = secure_filename(f.filename)
        f.save(os.path.join(BG_DIR, f"{int(time.time())}_{n}"))
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/update_key', methods=['POST'])
def update_key():
    data = request.json
    new_key = data.get('key', '').strip()
    if not new_key.startswith("AIza"): return jsonify({'success': False, 'msg': 'Key格式错误'})
    global client, CONFIG; CONFIG['GEMINI_API_KEY'] = new_key
    try: client = genai.Client(api_key=new_key)
    except: pass
    try:
        with open("config.json", "w", encoding='utf-8') as f: json.dump(CONFIG, f)
    except: pass
    return jsonify({'success': True})

@app.route('/upload_model', methods=['POST'])
def upload_model():
    if 'file' not in request.files: return jsonify({'success': False})
    f = request.files['file']
    if f.filename.endswith('.zip'):
        try:
            n = secure_filename(f.filename).rsplit('.', 1)[0].lower()
            p = os.path.join(MODELS_DIR, n); shutil.rmtree(p, ignore_errors=True)
            with zipfile.ZipFile(f, 'r') as z: z.extractall(p)
            for root, dirs, files in os.walk(p):
                if any(f.endswith('.model3.json') for f in files):
                    if root != p: 
                         for item in os.listdir(root): shutil.move(os.path.join(root, item), p)
                    break
            return jsonify({'success': True})
        except: return jsonify({'success': False})
    return jsonify({'success': False})

@app.route('/api/danmaku', methods=['POST'])
def api_danmaku():
    data = request.json
    if not data or 'text' not in data: return jsonify({'success': False})
    user = data.get('username', '弹幕'); msg = data.get('text', '')
    user_msg_obj = {'type': 'chat', 'sender': user, 'text': msg}
    GLOBAL_STATE['chat_history'].append(user_msg_obj)
    save_state()
    socketio.emit('chat_message', {'text': msg, 'sender': user}, to='lobby')
    socketio.start_background_task(process_ai_response, user, msg)
    return jsonify({'success': True})

def process_ai_response(sender, msg):
    try:
        if not chatroom_chat: init_chatroom()
        if not client: return
        resp = chatroom_chat.send_message(f"【{sender}】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        if match: emo=match.group(1); txt=resp.text.replace(match.group(0),'').strip()
        else: txt=resp.text
        ai_msg_obj = {'type': 'response', 'sender': 'Pico', 'text': txt, 'emotion': emo}
        GLOBAL_STATE['chat_history'].append(ai_msg_obj)
        save_state()
        socketio.emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        bg_tts(txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except Exception as e: print(f"AI Error: {e}")

users = {}; chatroom_chat = None
def init_chatroom():
    global chatroom_chat
    if not client: return
    sys_prompt = CURRENT_MODEL.get('persona', "") + EMOTION_INSTRUCTION
    try: chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": sys_prompt})
    except: pass

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})

@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL, 'current_background': GLOBAL_STATE.get('current_background', '')})
    emit('history_sync', {'history': GLOBAL_STATE['chat_history']})
    socketio.start_background_task(bg_tts, f"你好 {u}", "edge", "", "", sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid; 
    if sid not in users: return
    msg = d.get('text', ''); img_data = d.get('image', None); sender = users[sid]['username']
    if "/管理员" in msg and sender.lower()=="yk": users[sid]['is_admin']=True; emit('admin_unlocked'); return
    
    user_msg_obj = {'type': 'chat', 'sender': sender, 'text': msg}
    if img_data: user_msg_obj['image'] = True 
    GLOBAL_STATE['chat_history'].append(user_msg_obj)
    save_state()
    emit('chat_message', {'text': msg, 'sender': sender, 'image': img_data}, to='lobby')
    socketio.start_background_task(process_socket_ai, sid, msg, img_data)

def process_socket_ai(sid, msg, img_data):
    try:
        if not chatroom_chat: init_chatroom()
        if not client: return
        content_parts = []
        if msg: content_parts.append(msg)
        if img_data:
            try:
                if "," in img_data: header, encoded = img_data.split(",", 1); mime_type = header.split(":")[1].split(";")[0]
                else: encoded = img_data; mime_type = "image/jpeg"
                image_bytes = base64.b64decode(encoded)
                content_parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
            except: pass
        if content_parts:
            resp = chatroom_chat.send_message(content_parts)
            emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
            if match: emo=match.group(1); txt=resp.text.replace(match.group(0),'').strip()
            else: txt=resp.text
            ai_msg_obj = {'type': 'response', 'sender': 'Pico', 'text': txt, 'emotion': emo}
            GLOBAL_STATE['chat_history'].append(ai_msg_obj)
            save_state()
            socketio.emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
            bg_tts(txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except Exception as e:
        print(f"AI Error: {e}")

def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'backgrounds': scan_backgrounds(), 'current_bg': GLOBAL_STATE.get('current_background', '')})

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; GLOBAL_STATE["current_model_id"] = t['id']; save_state(); init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('switch_background')
def on_switch_bg(d):
    GLOBAL_STATE['current_background'] = d.get('name')
    save_state()
    emit('background_update', {'url': f"/static/backgrounds/{d.get('name')}" if d.get('name') else ""}, to='lobby')

@socketio.on('save_settings')
def on_save(d):
    if not is_admin(request.sid): return
    global CURRENT_MODEL
    try: d['scale']=float(d['scale']); d['x']=float(d['x']); d['y']=float(d['y'])
    except: pass
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL.update(updated); init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})

@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return
    if d['id']!=CURRENT_MODEL['id']: 
        shutil.rmtree(os.path.join(MODELS_DIR, d['id']), ignore_errors=True)
        emit('toast',{'text':'🗑️ 已删除'})
        on_get_data()

@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return
    name=d.get('name'); emit('toast',{'text':f'🚀 下载 {name}...','type':'info'}); socketio.start_background_task(bg_dl_task, name)

def bg_dl_task(name):
    u=f"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/{name}"
    t=os.path.join(MODELS_DIR,name.lower()); shutil.rmtree(t, ignore_errors=True); os.makedirs(t,exist_ok=True)
    try: os.system(f"svn export --force -q {u} {t}"); socketio.emit('toast',{'text':f'✅ {name} 完成!'},namespace='/')
    except: pass

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
