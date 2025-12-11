# =======================================================================
# Pico AI Server - ULTIMATE SAFEGUARD EDITION
# 包含：Gemini 429 错误自动处理、TTS 参数智能清洗、完整前端回退机制
# 解决：NoAudioReceived 错误 (通过强制传递合规参数)
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
import logging
import subprocess
import sys
import traceback

# 尝试导入 edge_tts
try:
    import edge_tts
    print("✅ Python 内部库 edge_tts 已加载")
except ImportError:
    print("⚠️ Python 内部库 edge_tts 未找到，将完全依赖命令行模式")

from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename

# 日志配置
logging.basicConfig(
    level=logging.INFO, 
    format='[%(asctime)s] %(levelname)s: %(message)s'
)

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'pico_safeguard_key'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# SocketIO 配置
socketio = SocketIO(app, 
    cors_allowed_origins="*", 
    async_mode='threading', 
    ping_timeout=60, 
    ping_interval=25,
    max_http_buffer_size=100*1024*1024
)

SERVER_VERSION = str(int(time.time()))

# --- 目录初始化 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
BG_DIR = os.path.join(BASE_DIR, "static", "backgrounds")
STATE_FILE = os.path.join(BASE_DIR, "server_state.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

for d in [AUDIO_DIR, MODELS_DIR, BG_DIR]:
    if not os.path.exists(d):
        try:
            os.makedirs(d)
            logging.info(f"创建目录: {d}")
        except Exception as e:
            logging.error(f"创建目录失败 {d}: {e}")

# --- 配置加载 ---
CONFIG = {
    "GEMINI_API_KEY": "",
    "TTS_VOICE": "zh-CN-XiaoxiaoNeural",
    "TTS_PROXY": ""  # 可选：HTTP代理地址
}

try:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding='utf-8') as f: 
            lines = [line for line in f.readlines() if not line.strip().startswith("//")]
            if lines: CONFIG.update(json.loads("\n".join(lines)))
except Exception as e:
    logging.error(f"加载配置文件出错: {e}")

# Gemini 初始化
client = None
api_key = CONFIG.get("GEMINI_API_KEY")
if api_key and "AIza" in api_key:
    try:
        client = genai.Client(api_key=api_key)
        logging.info("Gemini 客户端就绪")
    except Exception as e:
        logging.error(f"Gemini 初始化失败: {e}")

# --- 状态管理 ---
GLOBAL_STATE = { 
    "current_model_id": "default", 
    "current_background": "", 
    "chat_history": [] 
}

def save_state():
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(GLOBAL_STATE, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"保存状态失败: {e}")

def load_state():
    global GLOBAL_STATE
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if saved: GLOBAL_STATE.update(saved)
                if len(GLOBAL_STATE["chat_history"]) > 100:
                    GLOBAL_STATE["chat_history"] = GLOBAL_STATE["chat_history"][-100:]
        except: pass

load_state()

# 当前模型缓存
CURRENT_MODEL = {
    "id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", 
    "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5
}
DEFAULT_INSTRUCTION = "\n【指令】回复开头标记心情：[HAPPY], [ANGRY], [SAD], [SHOCK], [NORMAL]。"

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    d = {
        "persona": f"你是{mid}。{DEFAULT_INSTRUCTION}", 
        "voice": "zh-CN-XiaoxiaoNeural", 
        "rate": "+0%", "pitch": "+0Hz", 
        "scale": 0.5, "x": 0.5, "y": 0.5
    }
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f: 
                loaded = json.load(f)
                if loaded.get('persona'): d['persona'] = loaded['persona']
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
                model_id = os.path.basename(os.path.dirname(full_path))
                if any(m['id'] == model_id for m in ms): continue
                cfg = get_model_config(model_id)
                ms.append({"id": model_id, "name": model_id, "path": rel_path, **cfg})
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
    if not target and len(ms) > 0: target = ms[0]
    if target: 
        CURRENT_MODEL = target
        GLOBAL_STATE["current_model_id"] = target['id']
        save_state()

init_model()

# ================= TTS 核心 (带参数清洗 V2) =================

def clean_tts_param(val, unit):
    """
    强制清洗 TTS 参数，确保格式为 [+-]xxUNIT。
    """
    s = str(val).strip()
    
    # 提取数字和符号
    # 示例: "+0%" -> "+0"
    nums = re.sub(r'[^\d\+\-]', '', s)
    
    if not nums or nums in ['+', '-']:
        n = 0
    else:
        try:
            n = int(nums)
        except ValueError:
            n = 0
            
    # 强制格式化：带符号整数 + 单位
    return f"{n:+}{unit}"


def run_edge_tts_cmd(text, output_path, voice, rate, pitch):
    """
    执行 TTS 命令。使用清洗后的参数。
    """
    try:
        # ★★★ 关键修复：清洗参数，确保格式正确 ★★★
        # 即使值是 +0%，清洗后也会是 +0% 或 +0Hz
        safe_rate = clean_tts_param(rate, "%")
        safe_pitch = clean_tts_param(pitch, "Hz")
        
        logging.info(f"TTS 最终参数: Rate={safe_rate}, Pitch={safe_pitch}")

        cmd = [
            sys.executable, "-m", "edge_tts",
            "--text", text,
            "--write-media", output_path,
            "--voice", voice,
            "--rate", safe_rate,
            "--pitch", safe_pitch # 始终传递，确保兼容性
        ]
        
        # 注入代理配置
        my_env = os.environ.copy()
        proxy_url = CONFIG.get("TTS_PROXY", "").strip()
        if proxy_url:
            my_env["http_proxy"] = proxy_url
            my_env["https_proxy"] = proxy_url
        
        logging.info(f"执行 TTS 命令: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd, 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            timeout=60,
            env=my_env
        )
        
        # 检查是否收到音频 (如果 stderr 有内容，表示可能有非致命错误，但我们主要看 NoAudioReceived)
        if b"No audio was received" in result.stderr:
            return False, result.stderr.decode('utf-8', errors='ignore')
            
        return True, ""
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, 'stderr') and e.stderr: 
            err_msg = e.stderr.decode('utf-8', errors='ignore')
        logging.error(f"TTS 失败: {err_msg}")
        return False, err_msg

def bg_tts_task(text, voice, rate, pitch, room=None, sid=None):
    """后台任务：生成并推送，或者触发前端降级"""
    clean_text = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean_text: return

    fname = f"{uuid.uuid4()}.mp3"
    out_path = os.path.join(AUDIO_DIR, fname)
    
    # 尝试服务器生成
    success, err_reason = run_edge_tts_cmd(clean_text, out_path, voice, rate, pitch)

    if success and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        url = f"/static/audio/{fname}"
        payload = {'audio': url}
        logging.info(f"✅ 语音生成成功: {url}")
        
        if room: socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', payload, to=sid, namespace='/')
    else:
        # 生成失败，把文本发给前端，让浏览器读
        logging.error(f"❌ 语音生成失败，切换前端合成: {err_reason}")
        err_payload = {
            'msg': f'TTS网络超时，切换本地语音', 
            'text': clean_text,
            'type': 'warning' # 友好提示
        }
        if room: socketio.emit('audio_failed', err_payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_failed', err_payload, to=sid, namespace='/')

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
    if not new_key.startswith("AIza"): return jsonify({'success': False, 'msg': 'Key格式错误'})
    global client, CONFIG; CONFIG['GEMINI_API_KEY'] = new_key
    try: 
        client = genai.Client(api_key=new_key)
        with open(CONFIG_FILE, "w", encoding='utf-8') as f: json.dump(CONFIG, f, indent=2)
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'msg': str(e)})

@app.route('/upload_bg', methods=['POST'])
def upload_bg():
    if 'file' not in request.files: return jsonify({'success': False})
    f = request.files['file']
    if f and '.' in f.filename:
        n = secure_filename(f.filename)
        f.save(os.path.join(BG_DIR, f"{int(time.time())}_{n}"))
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/upload_model', methods=['POST'])
def upload_model():
    if 'file' not in request.files: return jsonify({'success': False})
    f = request.files['file']
    if f.filename.endswith('.zip'):
        try:
            n = secure_filename(f.filename).rsplit('.', 1)[0].lower()
            p = os.path.join(MODELS_DIR, n)
            shutil.rmtree(p, ignore_errors=True)
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
    user = data.get('username', 'B站弹幕')
    msg = data.get('text', '')
    user_msg_obj = {'type': 'chat', 'sender': user, 'text': msg}
    GLOBAL_STATE['chat_history'].append(user_msg_obj)
    save_state()
    socketio.emit('chat_message', {'text': msg, 'sender': user}, to='lobby')
    socketio.start_background_task(process_ai_response, user, msg)
    return jsonify({'success': True})

# ================= AI 逻辑 (带 429 保护) =================
users = {}
chatroom_chat = None

def init_chatroom():
    global chatroom_chat
    if not client: return
    sys_prompt = CURRENT_MODEL.get('persona', "")
    if not sys_prompt: sys_prompt = DEFAULT_INSTRUCTION
    try: chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": sys_prompt})
    except: pass

def process_ai_response(sender, msg, img_data=None, sid=None):
    try:
        if not chatroom_chat: init_chatroom()
        
        if not client: 
            if sid: socketio.emit('system_message', {'text': '请设置 API Key'}, to=sid)
            return
        
        content = []
        if msg: content.append(f"【{sender}】: {msg}")
        if img_data:
            try:
                if "," in img_data: _, encoded = img_data.split(",", 1)
                else: encoded = img_data
                content.append(types.Part.from_bytes(data=base64.b64decode(encoded), mime_type="image/jpeg"))
            except: pass
            
        # ★★★ 429 错误保护 ★★★
        try:
            resp = chatroom_chat.send_message(content)
            txt = resp.text
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                logging.error("AI 429 限流保护触发")
                txt = "（系统：API 调用次数已耗尽，请稍后或更换 Key 再试）"
            else:
                raise e # 其他错误继续抛出

        emo='NORMAL'
        match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', txt)
        if match: 
            emo=match.group(1)
            txt=txt.replace(match.group(0),'').strip()
            
        ai_msg = {'type': 'response', 'sender': 'Pico', 'text': txt, 'emotion': emo}
        GLOBAL_STATE['chat_history'].append(ai_msg)
        save_state()
        
        socketio.emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        bg_tts_task(txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
        
    except Exception as e:
        logging.error(f"AI Error: {e}")
        err_msg = str(e)
        if sid: socketio.emit('system_message', {'text': f'AI Error: {err_msg[:50]}...'}, to=sid)

# ================= Socket Events =================
@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})

@socketio.on('login')
def on_login(d):
    u = d.get('username', '').strip() or "User"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL, 'current_background': GLOBAL_STATE.get('current_background', '')})
    emit('history_sync', {'history': GLOBAL_STATE['chat_history']})
    socketio.start_background_task(bg_tts_task, f"欢迎 {u}", CURRENT_MODEL['voice'], "+0%", "+0%", sid=request.sid)

@socketio.on('message')
def on_msg(d):
    sid = request.sid
    if sid not in users: return
    msg = d.get('text', '')
    img = d.get('image', None)
    sender = users[sid]['username']
    
    if "/管理员" in msg and sender.lower() == "yk":
        users[sid]['is_admin'] = True
        emit('admin_unlocked')
        return

    GLOBAL_STATE['chat_history'].append({'type':'chat', 'sender':sender, 'text':msg, 'image': bool(img)})
    save_state()
    emit('chat_message', {'text':msg, 'sender':sender, 'image':img}, to='lobby')
    socketio.start_background_task(process_ai_response, sender, msg, img, sid)

def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    voices = [
        {"id":"zh-CN-XiaoxiaoNeural", "name":"🇨🇳 晓晓 (女声)"},
        {"id":"zh-CN-YunxiNeural", "name":"🇨🇳 云希 (少年)"},
        {"id":"zh-CN-YunjianNeural", "name":"🇨🇳 云健 (新闻)"},
        {"id":"zh-CN-XiaoyiNeural", "name":"🇨🇳 晓伊 (可爱)"},
        {"id":"zh-TW-HsiaoChenNeural", "name":"🇹🇼 晓臻 (台湾)"},
        {"id":"zh-HK-HiuMaanNeural", "name":"🇭🇰 晓曼 (粤语)"},
        {"id":"en-US-AnaNeural", "name":"🇺🇸 Ana (英文)"},
        {"id":"en-US-GuyNeural", "name":"🇺🇸 Guy (英文男)"},
        {"id":"ja-JP-NanamiNeural", "name":"🇯🇵 七海 (日语)"}
    ]
    emit('studio_data', {
        'models': scan_models(), 
        'current_id': CURRENT_MODEL['id'], 
        'voices': voices, 
        'backgrounds': scan_backgrounds(), 
        'current_bg': GLOBAL_STATE.get('current_background', '')
    })

@socketio.on('switch_model')
def on_sw(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: 
        CURRENT_MODEL = t
        GLOBAL_STATE["current_model_id"] = t['id']
        save_state()
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('switch_background')
def on_sw_bg(d):
    GLOBAL_STATE['current_background'] = d.get('name')
    save_state()
    emit('background_update', {'url': f"/static/backgrounds/{d.get('name')}" if d.get('name') else ""}, to='lobby')

@socketio.on('save_settings')
def on_sav(d):
    if not is_admin(request.sid): return
    global CURRENT_MODEL
    try: 
        d['scale']=float(d['scale'])
        d['x']=float(d['x'])
        d['y']=float(d['y'])
    except: pass
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: 
        CURRENT_MODEL.update(updated)
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 设置已保存'})

@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return
    if d['id'] != CURRENT_MODEL['id']:
        shutil.rmtree(os.path.join(MODELS_DIR, d['id']), ignore_errors=True)
        emit('toast', {'text': '🗑️ 已删除'})
        on_get_data()

@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return
    name = d.get('name')
    emit('toast', {'text': f'🚀 下载 {name}...', 'type':'info'})
    socketio.start_background_task(bg_dl_task, name)

def bg_dl_task(name):
    u = f"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/{name}"
    t = os.path.join(MODELS_DIR, name.lower())
    shutil.rmtree(t, ignore_errors=True)
    os.makedirs(t, exist_ok=True)
    try:
        os.system(f"svn export --force -q {u} {t}")
        socketio.emit('toast', {'text': f'✅ {name} 下载完成!'}, namespace='/')
    except: pass

if __name__ == '__main__':
    logging.info("Starting Pico AI Server...")
    socketio.run(app, host='0.0.0.0', port=5000)
