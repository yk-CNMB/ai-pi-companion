# =======================================================================
# Pico AI Server - ACGN Online TTS 版
# 核心逻辑：优先调用 ACGN AI 在线 API (GPT-SoVITS)，失败则降级 Edge-TTS
# =======================================================================
import os
import json
import uuid
import time
import re
import threading
import base64
import logging
import asyncio
import edge_tts
import requests 

from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename

# 日志配置
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'pico_acgn_key'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 目录初始化 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
BG_DIR = os.path.join(BASE_DIR, "static", "backgrounds")
STATE_FILE = os.path.join(BASE_DIR, "server_state.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

for d in [AUDIO_DIR, MODELS_DIR, BG_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# --- 配置加载 ---
CONFIG = {
    "GEMINI_API_KEY": "",
    "DEFAULT_VOICE": "zh-CN-XiaoyiNeural",
    # ACGN AI 配置
    "ACGN_TOKEN": "",          # 用户提供的 Bearer Token
    "ACGN_CHARACTER": "流萤",   # 默认角色，可修改
    "ACGN_API_URL": "https://gsv2p.acgnai.top" 
}

def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding='utf-8') as f: 
                lines = [line for line in f.readlines() if not line.strip().startswith("//")]
                if lines: CONFIG.update(json.loads("\n".join(lines)))
    except: pass
load_config()

def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding='utf-8') as f: json.dump(CONFIG, f, indent=2, ensure_ascii=False)
    except: pass

# Gemini 初始化
gemini_client = None
chatroom_chat = None

def init_gemini():
    global gemini_client, chatroom_chat
    if CONFIG.get("GEMINI_API_KEY") and "AIza" in CONFIG["GEMINI_API_KEY"]:
        try:
            gemini_client = genai.Client(api_key=CONFIG["GEMINI_API_KEY"])
            chatroom_chat = None 
            logging.info("✅ Gemini 客户端就绪")
        except Exception as e:
            logging.error(f"Gemini 初始化失败: {e}")

init_gemini()

# --- 状态管理 ---
GLOBAL_STATE = { "current_model_id": "default", "current_background": "", "chat_history": [] }

def save_state():
    try: with open(STATE_FILE, 'w', encoding='utf-8') as f: json.dump(GLOBAL_STATE, f, ensure_ascii=False)
    except: pass

def load_state():
    global GLOBAL_STATE
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if saved: GLOBAL_STATE.update(saved)
                if len(GLOBAL_STATE["chat_history"]) > 100: GLOBAL_STATE["chat_history"] = GLOBAL_STATE["chat_history"][-100:]
        except: pass
load_state()

# 模型管理
CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "0", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5}
DEFAULT_INSTRUCTION = "\n【指令】回复开头标记心情：[HAPPY], [ANGRY], [SAD], [SHOCK], [NORMAL]。"

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    d = {"persona": f"你是{mid}。{DEFAULT_INSTRUCTION}", "voice": "0", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5}
    if os.path.exists(p):
        try: with open(p, "r", encoding="utf-8") as f: d.update(json.load(f))
        except: pass
    return d

def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    curr = get_model_config(mid)
    curr.update(data)
    try: with open(p, "w", encoding="utf-8") as f: json.dump(curr, f, indent=2, ensure_ascii=False)
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
                mid = os.path.basename(os.path.dirname(full_path))
                if any(m['id'] == mid for m in ms): continue
                ms.append({"id": mid, "name": mid, "path": rel_path, **get_model_config(mid)})
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    target = next((m for m in ms if m['id'] == GLOBAL_STATE.get("current_model_id")), ms[0] if ms else None)
    if target: 
        CURRENT_MODEL = target
        GLOBAL_STATE["current_model_id"] = target['id']
        save_state()
init_model()

# ================= 语音合成核心 (ACGN + Edge) =================

def cleanup_audio_dir():
    try:
        now = time.time()
        for f in os.listdir(AUDIO_DIR):
            if os.path.getmtime(os.path.join(AUDIO_DIR, f)) < now - 300: os.remove(os.path.join(AUDIO_DIR, f))
    except: pass

def generate_acgn_tts(text):
    """调用 ACGN AI 在线 API"""
    token = CONFIG.get("ACGN_TOKEN")
    char_name = CONFIG.get("ACGN_CHARACTER", "流萤") # 默认流萤
    
    if not token: 
        logging.warning("⚠️ ACGN Token 未配置，跳过在线合成")
        return None
    
    try:
        logging.info(f"📡 请求 ACGN 语音 ({char_name}): {text[:10]}...")
        
        # 构造请求 (基于通常 GSV2P 接口猜测，需要具体文档校准)
        # 这里假设它是一个兼容 GPT-SoVITS 协议的 API
        # 很多第三方 GSV 接口使用 GET /?text=...&text_language=zh&character=...
        
        # 注意：这里我们尝试最通用的 params 结构
        url = CONFIG.get("ACGN_API_URL")
        # 如果 URL 结尾没有 /，补上
        if not url.endswith("/"): url += "/"
        
        # 尝试 endpoint: /tts 或 直接根路径 (取决于服务商实现)
        # 既然是 gsv2p.acgnai.top，大概率是兼容 GPT-SoVITS 官方 API 格式
        # 尝试调用 / (根路径) 或者 /tts
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"  # 有些接口需要
        }
        
        # 尝试方案 A: GET 请求 (最常见)
        # 参数名通常是: text, text_language, refer_wav_path (或者 character/emotion)
        # 由于是公共库，可能有一个 'character' 参数或者 'speaker'
        params = {
            "text": text,
            "text_language": "zh",
            "character": char_name, # 关键参数：角色名
            "format": "wav"
        }
        
        # 发起请求 (这里假设是 GET 根路径，如果不行请尝试 /tts)
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        
        if resp.status_code == 200:
            # 检查返回是不是音频 (content-type)
            if "audio" in resp.headers.get("Content-Type", "") or len(resp.content) > 1000:
                filename = f"acgn_{uuid.uuid4().hex}.wav"
                filepath = os.path.join(AUDIO_DIR, filename)
                with open(filepath, 'wb') as f: f.write(resp.content)
                logging.info("✅ ACGN 语音生成成功")
                return f"/static/audio/{filename}"
            else:
                logging.warning(f"⚠️ ACGN 返回非音频数据: {resp.text[:50]}")
        else:
            logging.warning(f"⚠️ ACGN 请求失败: {resp.status_code} - {resp.text[:50]}")
            
    except Exception as e:
        logging.warning(f"⚠️ ACGN API 异常 ({e})，将降级到 Edge-TTS")
        
    return None

def run_edge_tts_sync(text, voice, output_file, rate="+0%", pitch="+0Hz"):
    async def _amain():
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(output_file)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_amain())
        loop.close()
        return True
    except: return False

def generate_audio_smart(text, voice_id, rate, pitch):
    cleanup_audio_dir()
    clean_text = re.sub(r'\[.*?\]', '', text).strip()
    if not clean_text: return None

    # 1. 优先尝试 ACGN 在线语音 (当 voice_id 选了 'acgn' 或配置了 Token 且 voice_id 为默认)
    if voice_id == "acgn" or (CONFIG.get("ACGN_TOKEN") and voice_id == "0"):
        url = generate_acgn_tts(clean_text)
        if url: return url

    # 2. Edge-TTS 兜底
    filename = f"edge_{uuid.uuid4().hex}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    
    voice_map = {"0": "zh-CN-XiaoyiNeural", "1": "zh-CN-XiaoxiaoNeural", "2": "zh-CN-YunxiNeural", "acgn": "zh-CN-XiaoyiNeural"}
    target_voice = voice_map.get(str(voice_id), "zh-CN-XiaoyiNeural")
    if "Neural" in str(voice_id): target_voice = voice_id

    logging.info(f"🎙️ Edge-TTS 请求: {clean_text[:10]}...")
    if run_edge_tts_sync(clean_text, target_voice, filepath, rate, pitch):
        return f"/static/audio/{filename}"
    return None

def bg_tts_task(text, voice, rate, pitch, room=None, sid=None):
    audio_url = generate_audio_smart(text, voice, rate, pitch)
    if audio_url:
        payload = {'audio': audio_url}
        if room: socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', payload, to=sid, namespace='/')

# ================= Flask 路由 =================
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))

@app.route('/pico/<v>')
def pico_v(v):
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

@app.route('/update_key', methods=['POST'])
def update_key():
    data = request.json
    new_key = data.get('key', '').strip()
    if data.get('type') == 'gemini':
        if not new_key.startswith("AIza"): return jsonify({'success': False, 'msg': 'Key 格式错误'})
        global gemini_client, chatroom_chat
        CONFIG['GEMINI_API_KEY'] = new_key
        save_config()
        init_gemini()
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/upload_bg', methods=['POST'])
def upload_bg():
    f = request.files.get('file')
    if f: f.save(os.path.join(BG_DIR, f"{int(time.time())}_{secure_filename(f.filename)}")); return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/upload_model', methods=['POST'])
def upload_model():
    f = request.files.get('file')
    if f and f.filename.endswith('.zip'):
        try:
            n = secure_filename(f.filename).rsplit('.', 1)[0].lower()
            p = os.path.join(MODELS_DIR, n)
            shutil.rmtree(p, ignore_errors=True)
            with zipfile.ZipFile(f, 'r') as z: z.extractall(p)
            for root, _, files in os.walk(p):
                if any(fn.endswith('.model3.json') for fn in files):
                    if root != p: 
                        for item in os.listdir(root): shutil.move(os.path.join(root, item), p)
                    break
            return jsonify({'success': True})
        except: pass
    return jsonify({'success': False})

@app.route('/api/danmaku', methods=['POST'])
def api_danmaku():
    data = request.json
    if not data or 'text' not in data: return jsonify({'success': False})
    user = data.get('username', 'B站弹幕')
    msg = data.get('text', '')
    GLOBAL_STATE['chat_history'].append({'type':'chat', 'sender': user, 'text': msg})
    save_state()
    socketio.emit('chat_message', {'text': msg, 'sender': user}, to='lobby')
    socketio.start_background_task(process_ai_response, user, msg)
    return jsonify({'success': True})

# ================= Socket 逻辑 =================
def init_chatroom():
    global chatroom_chat
    if not gemini_client: return
    sys_prompt = CURRENT_MODEL.get('persona', DEFAULT_INSTRUCTION)
    try: chatroom_chat = gemini_client.chats.create(model="gemini-2.5-flash", config={"system_instruction": sys_prompt})
    except: pass

def process_ai_response(sender, msg, img_data=None, sid=None):
    global chatroom_chat
    try:
        if not chatroom_chat: init_chatroom()
        if not gemini_client:
            if sid: socketio.emit('system_message', {'text': '请设置 Gemini Key'}, to=sid)
            return
        
        content = []
        if msg: content.append(f"【{sender}】: {msg}")
        if img_data:
            try:
                b64 = img_data.split(",", 1)[1] if "," in img_data else img_data
                content.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/jpeg"))
            except: pass
            
        try:
            resp = chatroom_chat.send_message(content)
            txt = resp.text
        except Exception as e:
            if "closed" in str(e).lower(): init_chatroom(); return # 简单重试
            txt = f"(系统: {str(e)[:50]})"

        emo='NORMAL'
        match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', txt)
        if match: 
            emo=match.group(1)
            txt=txt.replace(match.group(0),'').strip()
            
        GLOBAL_STATE['chat_history'].append({'type': 'response', 'sender': 'Pico', 'text': txt, 'emotion': emo})
        save_state()
        socketio.emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts_task, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
        
    except Exception as e: logging.error(f"AI Error: {e}")

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})

@socketio.on('login')
def on_login(d):
    u = d.get('username', 'User')
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL, 'current_background': GLOBAL_STATE.get('current_background', '')})
    emit('history_sync', {'history': GLOBAL_STATE['chat_history']})
    socketio.start_background_task(bg_tts_task, f"欢迎 {u}", CURRENT_MODEL['voice'], "+0%", "+0%", sid=request.sid)

@socketio.on('message')
def on_msg(d):
    msg = d.get('text', '')
    
    # ★★★ 新增：ACGN 配置指令 ★★★
    if msg.startswith("/acgn_token "):
        t = msg.replace("/acgn_token ", "").strip()
        CONFIG["ACGN_TOKEN"] = t
        save_config()
        emit('system_message', {'text': '✅ ACGN Token 已保存'})
        return
    if msg.startswith("/acgn_char "):
        c = msg.replace("/acgn_char ", "").strip()
        CONFIG["ACGN_CHARACTER"] = c
        save_config()
        emit('system_message', {'text': f'✅ ACGN 角色已设为: {c}'})
        return

    sender = "User"
    GLOBAL_STATE['chat_history'].append({'type':'chat', 'sender':sender, 'text':msg, 'image': bool(d.get('image'))})
    save_state()
    emit('chat_message', {'text':msg, 'sender':sender, 'image':d.get('image')}, to='lobby')
    socketio.start_background_task(process_ai_response, sender, msg, d.get('image'), request.sid)

@socketio.on('get_studio_data')
def on_get_data():
    # 增加 ACGN 选项
    voices = [
        {"id":"0", "name":"🎧 默认: 晓伊 (微软)"},
        {"id":"1", "name":"🎧 默认: 晓晓 (微软)"},
        {"id":"acgn", "name":"✨ ACGN 在线 (需配置)"}
    ]
    emit('studio_data', {
        'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 
        'voices': voices, 'backgrounds': scan_backgrounds(), 
        'current_bg': GLOBAL_STATE.get('current_background', ''),
        'gemini_key_status': 'OK' if gemini_client else 'MISSING',
    })

@socketio.on('switch_model')
def on_sw(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: 
        CURRENT_MODEL = t; GLOBAL_STATE["current_model_id"] = t['id']; save_state(); init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_settings')
def on_sav(d):
    global CURRENT_MODEL
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL.update(updated); init_chatroom()
    emit('toast', {'text': '✅ 保存成功'})

@socketio.on('switch_background')
def on_sw_bg(d):
    GLOBAL_STATE['current_background'] = d.get('name'); save_state()
    emit('background_update', {'url': f"/static/backgrounds/{d.get('name')}" if d.get('name') else ""}, to='lobby')

if __name__ == '__main__':
    logging.info("Starting Pico AI (ACGN Mode)...")
    socketio.run(app, host='0.0.0.0', port=5000)
