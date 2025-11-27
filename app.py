# =======================================================================
# Pico AI Server - app.py (电子歌姬特效版)
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

import edge_tts
import soundfile as sf
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# 兼容 Python 3.13
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")

for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# 加载配置
CONFIG = {}
try:
    if os.path.exists("config.json"):
        with open("config.json", "r") as f: 
            content = "\n".join([line for line in f.readlines() if not line.strip().startswith("//")])
            try: CONFIG = json.loads(content)
            except: CONFIG = json.load(open("config.json"))
except: pass

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "AIza" in api_key:
    try: client = genai.Client(api_key=api_key)
    except: pass

# --- 情感核心 ---
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

CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "miku_auto", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    default_persona = f"你是{mid}。{EMOTION_INSTRUCTION}"
    d = {"persona": default_persona, "voice":"miku_auto", "rate":"+0%", "pitch":"+0Hz", "scale":0.5, "x":0.5, "y":0.5}
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

# 模型扫描
def scan_models():
    ms = []
    for root, dirs, files in os.walk(MODELS_DIR):
        for file in files:
            if file.endswith(('.model3.json', '.model.json')):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, BASE_DIR).replace("\\", "/")
                if not rel_path.startswith("/"): rel_path = "/" + rel_path
                folder_name = os.path.basename(os.path.dirname(full_path))
                model_id = folder_name
                if any(m['id'] == model_id for m in ms):
                    model_id = f"{folder_name}_{os.path.splitext(file)[0]}"
                cfg = get_model_config(model_id)
                ms.append({"id": model_id, "name": model_id.capitalize(), "path": rel_path, **cfg})
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = None
    for m in ms:
        if "hiyori" in m['id'].lower(): t = m; break
    if t is None and len(ms) > 0: t = ms[0]
    if t: CURRENT_MODEL = t

init_model()

# ===================================================================
# 核心：电子歌姬滤镜 (Vocaloid Effect)
# ===================================================================

def contains_japanese(text):
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text))

def morph_voice(input_path, output_path, pitch_factor=1.2):
    """ 
    使用 ffmpeg 打造 '电子歌姬' 音效 
    1. asetrate: 提高音调 (变幼)
    2. chorus: 添加电子合唱效果 (机械感)
    3. equalizer: 增强高频 (空气感)
    """
    target_rate = int(22050 * pitch_factor)
    
    # 复杂的滤镜链
    # chorus=0.5:0.9:50|60:0.4|0.32:0.25|0.4:2|1.2 -> 模拟轻微的金属共鸣
    # equalizer=f=3000:t=q:w=1:g=3 -> 提升3000Hz附近的高频，增加清晰度
    filter_complex = (
        f"asetrate={target_rate},"
        f"aresample=22050,"
        f"chorus=0.5:0.9:50|60:0.4|0.32:0.25|0.4:2|1.2,"
        f"equalizer=f=3000:t=q:w=1:g=3"
    )
    
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", input_path,
        "-filter:a", filter_complex,
        output_path
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:
        print(f"❌ 变声失败: {e}")
        shutil.copy(input_path, output_path)
        return True

def run_piper_tts(text, model_name, output_path):
    model_path = os.path.join(VOICES_DIR, model_name)
    if not os.path.exists(PIPER_BIN) or not os.path.exists(model_path): return False
    
    try:
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", output_path]
        subprocess.run(cmd, input=text.encode('utf-8'), check=True, capture_output=True)
        return True
    except: return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    
    raw_fname = f"raw_{uuid.uuid4()}.wav"
    final_fname = f"{uuid.uuid4()}.wav"
    raw_path = os.path.join(AUDIO_DIR, raw_fname)
    final_path = os.path.join(AUDIO_DIR, final_fname)
    
    success = False
    
    # === 智能 Miku 模式 ===
    if voice == "miku_auto":
        is_jp = contains_japanese(clean)
        
        if is_jp:
            # 日语 -> 用 Tokin (稍微加一点点电子感)
            print(f"🔊 Miku (日语): {clean[:10]}...")
            if run_piper_tts(clean, "ja_JP-tokin.onnx", raw_path):
                # 日语原声已经很好了，只加一点点音调(1.05)和特效
                morph_voice(raw_path, final_path, pitch_factor=1.05)
                success = True
                try: os.remove(raw_path)
                except: pass
        else:
            # 中文 -> 用 Huayan + 强力电子滤镜
            print(f"🔊 Miku (中文): {clean[:10]}...")
            if run_piper_tts(clean, "zh_CN-huayan.onnx", raw_path):
                # 中文底模比较沉稳，需要拉高 1.25 倍
                morph_voice(raw_path, final_path, pitch_factor=1.25)
                success = True
                try: os.remove(raw_path)
                except: pass

    # === 兜底模式 (Edge-TTS) ===
    if not success:
        try:
            print("⚠️ 切换到 Edge-TTS 兜底")
            edge_voice = "zh-CN-XiaoxiaoNeural"
            if contains_japanese(clean): edge_voice = "ja-JP-NanamiNeural"
            
            async def _run():
                # Edge 直接生成，不做后期处理（太慢）
                cm = edge_tts.Communicate(clean, edge_voice, rate="+10%")
                await cm.save(final_path)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.close()
            success = True
        except: pass

    if success:
        url = f"/static/audio/{final_fname}"
        payload = {'audio': url}
        if room: socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', payload, to=sid, namespace='/')

# 路由和 WebSocket 保持不变
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
                         for item in os.listdir(root): 
                             try: shutil.move(os.path.join(root, item), p)
                             except: pass
                    break
            return jsonify({'success': True})
        except: return jsonify({'success': False})
    return jsonify({'success': False})

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
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    socketio.start_background_task(bg_tts, f"Hi {u}", CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    msg = d['text']
    if "/管理员" in msg and users[sid]['username'].lower()=="yk": users[sid]['is_admin']=True; emit('admin_unlocked'); return
    emit('chat_message', {'text': msg, 'sender': users[sid]['username']}, to='lobby')
    try:
        if not chatroom_chat: init_chatroom()
        resp = chatroom_chat.send_message(f"【{users[sid]['username']}】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        if match: emo=match.group(1); txt=resp.text.replace(match.group(0),'').strip()
        else: txt=resp.text
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except: init_chatroom()

def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    voices = [
        {"id":"miku_auto", "name":"🎧 电子歌姬滤镜 (Miku Style)"},
        {"id":"zh-CN-XiaoxiaoNeural", "name":"☁️ 微软晓晓 (原声)"}
    ]
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'voices': voices})

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
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
