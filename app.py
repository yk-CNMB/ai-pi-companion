# =======================================================================
# Pico AI Server - app.py (背景功能增强版)
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
import threading
import requests
import urllib.parse

import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
BG_DIR = os.path.join(BASE_DIR, "static", "backgrounds") # 背景目录
STATE_FILE = os.path.join(BASE_DIR, "server_state.json")

for d in [AUDIO_DIR, MODELS_DIR, BG_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# --- 配置加载 ---
CONFIG = {
    "TTS_MODE": "vits", 
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

# --- 情感指令 ---
EMOTION_INSTRUCTION = """
【重要系统指令】
你必须在每次回复的开头，明确标记你当前的心情。
请严格从以下标签中选择一个，放在句首：
[HAPPY] - 开心、兴奋、害羞、爱意 (对应高兴、大笑、害羞等)
[ANGRY] - 生气、愤怒、烦躁 (对应愤怒、不满)
[SAD] - 悲伤、哭泣、失望 (对应大哭、沮丧)
[SHOCK] - 惊讶、震惊、困惑 (对应吃惊、转头)
[NORMAL] - 平静、普通、思考 (对应点头、发呆)

例如：
[HAPPY] 哇！真的吗？太棒了！
[ANGRY] 哼，我不理你了！

请务必遵守格式，否则无法驱动虚拟形象。
"""

# --- 全局状态 ---
GLOBAL_STATE = {
    "current_model_id": "default",
    "current_background": "", # 当前背景文件名
    "chat_history": [] 
}

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
    curr = get_model_config(mid); curr.update(data)
    with open(p, "w", encoding="utf-8") as f: json.dump(curr, f, indent=2, ensure_ascii=False)
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
                if not any(m['id'] == folder_name for m in ms):
                    model_id = folder_name
                cfg = get_model_config(model_id)
                ms.append({"id": model_id, "name": model_id.capitalize(), "path": rel_path, **cfg})
    return sorted(ms, key=lambda x: x['name'])

def scan_backgrounds():
    """ 扫描背景图片 """
    bgs = []
    # 支持常见图片格式
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif']:
        for f in glob.glob(os.path.join(BG_DIR, ext)):
            bgs.append(os.path.basename(f))
    return sorted(bgs)

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    last_id = GLOBAL_STATE.get("current_model_id")
    target = next((m for m in ms if m['id'] == last_id), None)
    if not target:
        target = next((m for m in ms if "hiyori" in m['id'].lower()), None)
    if not target and len(ms) > 0:
        target = ms[0]
        
    if target: 
        CURRENT_MODEL = target
        GLOBAL_STATE["current_model_id"] = target['id']
        save_state()

init_model()

# --- TTS ---
def run_vits_api(text, output_path):
    api_url = CONFIG.get("VITS_API_URL")
    if not api_url: return False
    target_url = api_url.replace("{text}", urllib.parse.quote(text)).replace("{lang}", "zh")
    try:
        resp = requests.get(target_url, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 1000:
            with open(output_path, "wb") as f: f.write(resp.content)
            return True
    except: pass
    return False

def run_edge_tts(text, voice, output_path):
    try:
        async def _run():
            comm = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural", rate="+15%", pitch="+25Hz")
            await comm.save(output_path)
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); loop.run_until_complete(_run()); loop.close()
        return True
    except: return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}.wav"
    out_path = os.path.join(AUDIO_DIR, fname)
    success = False
    
    if "api" in voice or CONFIG.get("TTS_MODE") == "vits":
        success = run_vits_api(clean, out_path)
    if not success:
        success = run_edge_tts(clean, "edge", out_path)

    if success:
        url = f"/static/audio/{fname}"
        payload = {'audio': url}
        if room: socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', payload, to=sid, namespace='/')

# --- 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

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
                if any(f.endswith(('.model3.json', '.model.json')) for f in files):
                    if root != p: 
                         for item in os.listdir(root): shutil.move(os.path.join(root, item), p)
                    break
            return jsonify({'success': True})
        except: return jsonify({'success': False})
    return jsonify({'success': False})

# 新增：上传背景路由
@app.route('/upload_bg', methods=['POST'])
def upload_bg():
    if 'file' not in request.files: return jsonify({'success': False, 'msg': '无文件'})
    f = request.files['file']
    if f.filename == '': return jsonify({'success': False, 'msg': '文件名为空'})
    
    if f and '.' in f.filename and f.filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
        filename = secure_filename(f.filename)
        # 防止重名覆盖，加个时间戳
        name_part, ext_part = os.path.splitext(filename)
        final_name = f"{name_part}_{int(time.time())}{ext_part}"
        
        f.save(os.path.join(BG_DIR, final_name))
        return jsonify({'success': True})
    return jsonify({'success': False, 'msg': '格式不支持'})

# --- 聊天交互 ---
users = {}
chatroom_chat = None
def init_chatroom():
    global chatroom_chat
    if not client: return
    sys_prompt = CURRENT_MODEL.get('persona', "")
    if EMOTION_INSTRUCTION not in sys_prompt: sys_prompt += EMOTION_INSTRUCTION
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
    
    emit('login_success', {
        'username': u, 
        'current_model': CURRENT_MODEL,
        'current_background': GLOBAL_STATE.get('current_background', '') # 发送当前背景
    })
    emit('history_sync', {'history': GLOBAL_STATE['chat_history']})
    socketio.start_background_task(bg_tts, f"Hi {u}", "api_miku", "", "", sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    msg = d['text']
    sender = users[sid]['username']
    
    if "/管理员" in msg and sender.lower()=="yk": 
        users[sid]['is_admin']=True; emit('admin_unlocked'); return
    
    user_msg_obj = {'type': 'chat', 'sender': sender, 'text': msg}
    GLOBAL_STATE['chat_history'].append(user_msg_obj)
    save_state()
    
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    
    try:
        if not chatroom_chat: init_chatroom()
        resp = chatroom_chat.send_message(f"【{sender}】: {msg}")
        
        emo='NORMAL'
        match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        if match: emo=match.group(1); txt=resp.text.replace(match.group(0),'').strip()
        else: txt=resp.text
        
        ai_msg_obj = {'type': 'response', 'sender': 'Pico', 'text': txt, 'emotion': emo}
        GLOBAL_STATE['chat_history'].append(ai_msg_obj)
        save_state()
        
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except: init_chatroom()

def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    voices = [
        {"id":"api_miku", "name":"🎵 Miku VITS (HuggingFace API)"},
        {"id":"edge_backup", "name":"☁️ 微软 Edge (兜底)"}
    ]
    # 发送模型列表和背景列表
    emit('studio_data', {
        'models': scan_models(), 
        'current_id': CURRENT_MODEL['id'], 
        'voices': voices,
        'backgrounds': scan_backgrounds(),
        'current_bg': GLOBAL_STATE.get('current_background', '')
    })

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: 
        CURRENT_MODEL = t
        GLOBAL_STATE["current_model_id"] = t['id']
        save_state()
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')

# 新增：切换背景
@socketio.on('switch_background')
def on_switch_background(d):
    bg_name = d.get('name')
    GLOBAL_STATE['current_background'] = bg_name
    save_state()
    # 广播给所有人
    emit('background_update', {'url': f"/static/backgrounds/{bg_name}" if bg_name else ""}, to='lobby')

@socketio.on('save_settings')
def on_save_settings(d):
    global CURRENT_MODEL
    if not is_admin(request.sid): return
    try: d['scale']=float(d['scale']); d['x']=float(d['x']); d['y']=float(d['y'])
    except: pass
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL.update(updated); init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})

@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return
    if d['id']==CURRENT_MODEL['id']: return
    try: shutil.rmtree(os.path.join(MODELS_DIR, d['id'])); emit('toast',{'text':'🗑️ 已删除'}); on_get_data()
    except: pass

@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return
    name=d.get('name'); emit('toast',{'text':f'🚀 下载 {name}...','type':'info'}); socketio.start_background_task(bg_dl_task, name)

def bg_dl_task(name):
    u={"Mao":".../Mao","Natori":".../Natori"}.get(name,"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/"+name)
    t=os.path.join(MODELS_DIR,name.lower()); shutil.rmtree(t, ignore_errors=True); os.makedirs(t,exist_ok=True)
    try: os.system(f"svn export --force -q {u} {t}"); socketio.emit('toast',{'text':f'✅ {name} 完成!'},namespace='/')
    except: pass

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
