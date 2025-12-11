# =======================================================================
# Pico AI Server - "Heavy Armor" Stable Edition
# 恢复了完整的错误处理、独立事件循环和文件管理逻辑
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

# 只使用纯 Python 库，不依赖系统底层音频库
import edge_tts

from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'pico_secret_key_2025'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB 上传限制

# 增加 buffer size 防止图片传输断连，启用 ping/pong 保活
socketio = SocketIO(app, 
    cors_allowed_origins="*", 
    async_mode='threading', 
    ping_timeout=60, 
    ping_interval=25,
    max_http_buffer_size=10*1024*1024
)

SERVER_VERSION = str(int(time.time()))

# --- 目录结构初始化 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
BG_DIR = os.path.join(BASE_DIR, "static", "backgrounds")
STATE_FILE = os.path.join(BASE_DIR, "server_state.json")

# 确保所有目录存在
for d in [AUDIO_DIR, MODELS_DIR, BG_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)
        logging.info(f"Created directory: {d}")

# --- 全局配置 ---
CONFIG = {
    "GEMINI_API_KEY": "",
    "TTS_VOICE": "zh-CN-XiaoxiaoNeural", # 默认好听的中文女声
    "TTS_RATE": "+0%",
    "TTS_PITCH": "+0Hz"
}

# 尝试加载配置文件
try:
    if os.path.exists("config.json"):
        with open("config.json", "r", encoding='utf-8') as f: 
            # 过滤注释行
            content = "\n".join([line for line in f.readlines() if not line.strip().startswith("//")])
            CONFIG.update(json.loads(content))
            logging.info("Config loaded successfully.")
except Exception as e:
    logging.error(f"Config load error: {e}")

# 初始化 Gemini 客户端
client = None
api_key = CONFIG.get("GEMINI_API_KEY")
if api_key and "AIza" in api_key:
    try:
        client = genai.Client(api_key=api_key)
        logging.info("Gemini Client initialized.")
    except Exception as e:
        logging.error(f"Gemini init failed: {e}")

# --- 系统指令 ---
EMOTION_INSTRUCTION = """
【系统指令】
你是一个拥有 Live2D 形象的虚拟主播。
1. 请在每次回复的开头，必须明确标记你当前的心情标签。
2. 标签必须是以下之一：[HAPPY], [ANGRY], [SAD], [SHOCK], [NORMAL]。
3. 标签后紧跟你的回复内容。

例如：
[HAPPY] 哇！这也太棒了吧！
[ANGRY] 哼，我不理你了。
[SHOCK] 真的假的？完全没想到！
"""

# --- 全局状态管理 ---
GLOBAL_STATE = {
    "current_model_id": "default",
    "current_background": "",
    "chat_history": []
}

def load_state():
    global GLOBAL_STATE
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                GLOBAL_STATE.update(saved)
                # 只保留最近 100 条历史
                GLOBAL_STATE["chat_history"] = GLOBAL_STATE["chat_history"][-100:]
        except Exception as e:
            logging.error(f"Load state error: {e}")

def save_state():
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(GLOBAL_STATE, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Save state error: {e}")

load_state()

# 当前模型配置缓存
CURRENT_MODEL = {
    "id": "default", 
    "path": "", 
    "persona": "", 
    "voice": "zh-CN-XiaoxiaoNeural", 
    "rate": "+0%", 
    "pitch": "+0Hz", 
    "scale": 0.5, 
    "x": 0.5, 
    "y": 0.5
}

def get_model_config(mid):
    """读取特定模型的 config.json"""
    p = os.path.join(MODELS_DIR, mid, "config.json")
    # 默认值
    default_persona = f"你是{mid}。{EMOTION_INSTRUCTION}"
    d = {
        "persona": default_persona, 
        "voice": "zh-CN-XiaoxiaoNeural", 
        "rate": "+0%", 
        "pitch": "+0Hz", 
        "scale": 0.5, 
        "x": 0.5, 
        "y": 0.5
    }
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f: 
                loaded = json.load(f)
                # 确保人设包含情感指令
                if 'persona' in loaded and EMOTION_INSTRUCTION not in loaded['persona']:
                    loaded['persona'] += EMOTION_INSTRUCTION
                d.update(loaded)
        except: pass
    return d

def save_model_config(mid, data):
    """保存特定模型的配置"""
    p = os.path.join(MODELS_DIR, mid, "config.json")
    curr = get_model_config(mid)
    curr.update(data)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(curr, f, indent=2, ensure_ascii=False)
    except: pass
    return curr

def scan_models():
    """扫描所有 Live2D 模型"""
    ms = []
    for root, dirs, files in os.walk(MODELS_DIR):
        for file in files:
            if file.endswith(('.model3.json', '.model.json')):
                full_path = os.path.join(root, file)
                # 计算相对路径
                rel_path = os.path.relpath(full_path, BASE_DIR).replace("\\", "/")
                if not rel_path.startswith("/"): rel_path = "/" + rel_path
                
                folder_name = os.path.basename(os.path.dirname(full_path))
                model_id = folder_name
                
                # 避免重复
                if any(m['id'] == model_id for m in ms): continue
                
                cfg = get_model_config(model_id)
                ms.append({
                    "id": model_id, 
                    "name": model_id, 
                    "path": rel_path, 
                    **cfg
                })
    return sorted(ms, key=lambda x: x['name'])

def scan_backgrounds():
    bgs = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif']:
        for f in glob.glob(os.path.join(BG_DIR, ext)): 
            bgs.append(os.path.basename(f))
    return sorted(bgs)

def init_model():
    """初始化加载上次使用的模型"""
    global CURRENT_MODEL
    ms = scan_models()
    last_id = GLOBAL_STATE.get("current_model_id")
    target = next((m for m in ms if m['id'] == last_id), None)
    
    # 如果找不到上次的，找一个包含 hiyori 的，或者第一个
    if not target: target = next((m for m in ms if "hiyori" in m['id'].lower()), None)
    if not target and len(ms) > 0: target = ms[0]
    
    if target: 
        CURRENT_MODEL = target
        GLOBAL_STATE["current_model_id"] = target['id']
        save_state()
        logging.info(f"Initialized model: {target['id']}")

init_model()

# =======================================================================
# TTS 核心逻辑 (纯 Python 实现，独立事件循环)
# =======================================================================
def run_edge_tts_python(text, output_path, voice="zh-CN-XiaoxiaoNeural", rate="+0%", pitch="+0Hz"):
    """
    使用 edge-tts 库生成音频。
    关键点：在线程中创建全新的 asyncio event loop，防止 Flask/SocketIO 冲突。
    """
    logging.info(f"TTS Generating: {text[:15]}... | Voice: {voice}")
    try:
        async def _gen():
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await communicate.save(output_path)
        
        # 创建新的事件循环
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(_gen())
        new_loop.close()
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logging.info(f"TTS Success: {output_path}")
            return True
        else:
            logging.error("TTS File created but empty.")
            return False
    except Exception as e:
        logging.error(f"TTS Failed: {e}")
        return False

def bg_tts_task(text, voice, rate, pitch, room=None, sid=None):
    """后台 TTS 任务"""
    # 清理标签
    clean_text = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean_text: return

    fname = f"{uuid.uuid4()}.mp3"
    out_path = os.path.join(AUDIO_DIR, fname)
    
    # 默认参数兜底
    v = voice if voice else "zh-CN-XiaoxiaoNeural"
    r = rate if rate else "+0%"
    p = pitch if pitch else "+0Hz"

    success = run_edge_tts_python(clean_text, out_path, v, r, p)

    if success:
        url = f"/static/audio/{fname}"
        payload = {'audio': url}
        logging.info(f"Emitting audio event: {url}")
        if room: 
            socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: 
            socketio.emit('audio_response', payload, to=sid, namespace='/')
    else:
        logging.error("TTS generation failed completely.")

# ================= 路由定义 =================
@app.route('/')
def idx(): 
    return redirect(url_for('pico_v', v=SERVER_VERSION))

@app.route('/pico/<v>')
def pico_v(v):
    r = make_response(render_template('chat.html'))
    # 禁用缓存，确保前端代码更新立即生效
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

@app.route('/upload_bg', methods=['POST'])
def upload_bg():
    if 'file' not in request.files: return jsonify({'success': False})
    f = request.files['file']
    if f and '.' in f.filename:
        n = secure_filename(f.filename)
        # 添加时间戳防止重名
        final_name = f"{int(time.time())}_{n}"
        f.save(os.path.join(BG_DIR, final_name))
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/update_key', methods=['POST'])
def update_key():
    data = request.json
    new_key = data.get('key', '').strip()
    if not new_key.startswith("AIza"): 
        return jsonify({'success': False, 'msg': 'Key 格式不正确 (必须以 AIza 开头)'})
    
    global client, CONFIG
    CONFIG['GEMINI_API_KEY'] = new_key
    
    # 尝试重新初始化
    try: 
        client = genai.Client(api_key=new_key)
        # 保存到文件
        try:
            with open("config.json", "w", encoding='utf-8') as f: 
                json.dump(CONFIG, f, indent=2)
        except: pass
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)})

@app.route('/upload_model', methods=['POST'])
def upload_model():
    if 'file' not in request.files: return jsonify({'success': False})
    f = request.files['file']
    if f.filename.endswith('.zip'):
        try:
            n = secure_filename(f.filename).rsplit('.', 1)[0].lower()
            p = os.path.join(MODELS_DIR, n)
            # 清理旧目录
            shutil.rmtree(p, ignore_errors=True)
            
            with zipfile.ZipFile(f, 'r') as z: 
                z.extractall(p)
            
            # 智能修正路径：如果解压后多了一层目录
            for root, dirs, files in os.walk(p):
                if any(f.endswith('.model3.json') for f in files):
                    if root != p: 
                         for item in os.listdir(root): 
                             shutil.move(os.path.join(root, item), p)
                    break
            
            return jsonify({'success': True})
        except Exception as e: 
            logging.error(f"Upload model failed: {e}")
            return jsonify({'success': False})
    return jsonify({'success': False})

@app.route('/api/danmaku', methods=['POST'])
def api_danmaku():
    """B站直播弹幕对接接口"""
    data = request.json
    if not data or 'text' not in data: return jsonify({'success': False})
    user = data.get('username', '弹幕观众')
    msg = data.get('text', '')
    
    # 记录
    user_msg_obj = {'type': 'chat', 'sender': user, 'text': msg}
    GLOBAL_STATE['chat_history'].append(user_msg_obj)
    save_state()
    
    # 广播
    socketio.emit('chat_message', {'text': msg, 'sender': user}, to='lobby')
    
    # AI 响应
    socketio.start_background_task(process_ai_response, user, msg)
    return jsonify({'success': True})

# ================= AI 处理逻辑 =================
users = {}
chatroom_chat = None

def init_chatroom():
    global chatroom_chat
    if not client: return
    # 组合 System Prompt
    sys_prompt = CURRENT_MODEL.get('persona', "") + EMOTION_INSTRUCTION
    try: 
        chatroom_chat = client.chats.create(
            model="gemini-2.5-flash", 
            config={"system_instruction": sys_prompt}
        )
        logging.info("Chatroom initialized.")
    except Exception as e:
        logging.error(f"Chatroom init failed: {e}")

def process_ai_response(sender, msg, img_data=None, sid=None):
    """统一的 AI 响应处理函数"""
    try:
        if not chatroom_chat: init_chatroom()
        if not client: 
            if sid: socketio.emit('system_message', {'text': '请先设置 API Key'}, to=sid)
            return

        content_parts = []
        if msg: content_parts.append(f"【{sender}】: {msg}")
        
        # 处理图片
        if img_data:
            try:
                if "," in img_data: 
                    header, encoded = img_data.split(",", 1)
                    mime_type = header.split(":")[1].split(";")[0]
                else: 
                    encoded = img_data
                    mime_type = "image/jpeg"
                
                image_bytes = base64.b64decode(encoded)
                content_parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
            except Exception as e:
                logging.error(f"Image decode error: {e}")

        if content_parts:
            # 调用 Gemini
            resp = chatroom_chat.send_message(content_parts)
            
            # 解析情感标签
            emo = 'NORMAL'
            match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
            txt = resp.text
            if match: 
                emo = match.group(1)
                txt = resp.text.replace(match.group(0), '').strip()
            
            # 记录 AI 回复
            ai_msg_obj = {'type': 'response', 'sender': 'Pico', 'text': txt, 'emotion': emo}
            GLOBAL_STATE['chat_history'].append(ai_msg_obj)
            save_state()
            
            # 广播回复
            socketio.emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
            
            # 触发 TTS (声音的关键！)
            bg_tts_task(txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
            
    except Exception as e:
        logging.error(f"AI Process Error: {e}")
        if sid: socketio.emit('system_message', {'text': f'AI Error: {e}'}, to=sid)

# ================= Socket.IO 事件 =================
@socketio.on('connect')
def on_connect():
    emit('server_ready', {'status': 'ok'})

@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or f"User{str(uuid.uuid4())[:4]}"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    
    if not chatroom_chat: init_chatroom()
    
    # 发送初始化数据
    emit('login_success', {
        'username': u, 
        'current_model': CURRENT_MODEL, 
        'current_background': GLOBAL_STATE.get('current_background', '')
    })
    
    # 同步历史记录
    emit('history_sync', {'history': GLOBAL_STATE['chat_history']})
    
    # 欢迎语音
    socketio.start_background_task(bg_tts_task, f"欢迎 {u} 进入直播间", "zh-CN-XiaoxiaoNeural", "+0%", "+0%", sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    
    msg = d.get('text', '')
    img_data = d.get('image', None)
    sender = users[sid]['username']
    
    # 管理员后门
    if "/管理员" in msg and sender.lower() == "yk": 
        users[sid]['is_admin'] = True
        emit('admin_unlocked')
        return
    
    # 记录用户消息
    user_msg_obj = {'type': 'chat', 'sender': sender, 'text': msg}
    if img_data: user_msg_obj['image'] = True 
    GLOBAL_STATE['chat_history'].append(user_msg_obj)
    save_state()
    
    # 广播用户消息
    emit('chat_message', {'text': msg, 'sender': sender, 'image': img_data}, to='lobby')
    
    # 触发 AI
    socketio.start_background_task(process_ai_response, sender, msg, img_data, sid)

def is_admin(sid): 
    return users.get(sid, {}).get('is_admin', False)

@socketio.on('get_studio_data')
def on_get_data():
    emit('studio_data', {
        'models': scan_models(), 
        'current_id': CURRENT_MODEL['id'], 
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

@socketio.on('switch_background')
def on_switch_bg(d):
    GLOBAL_STATE['current_background'] = d.get('name')
    save_state()
    emit('background_update', {'url': f"/static/backgrounds/{d.get('name')}" if d.get('name') else ""}, to='lobby')

@socketio.on('save_settings')
def on_save(d):
    if not is_admin(request.sid): return
    global CURRENT_MODEL
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
    emit('toast', {'text': '✅ 设置已保存'})

@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return
    if d['id'] != CURRENT_MODEL['id']: 
        shutil.rmtree(os.path.join(MODELS_DIR, d['id']), ignore_errors=True)
        emit('toast',{'text':'🗑️ 模型已删除'})
        on_get_data()

@socketio.on('download_model')
def on_dl(d):
    if not is_admin(request.sid): return
    name = d.get('name')
    emit('toast', {'text': f'🚀 开始下载 {name}...', 'type':'info'})
    socketio.start_background_task(bg_dl_task, name)

def bg_dl_task(name):
    # 简单的下载逻辑，这里使用 svn export 
    u = f"https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/{name}"
    t = os.path.join(MODELS_DIR, name.lower())
    shutil.rmtree(t, ignore_errors=True)
    os.makedirs(t, exist_ok=True)
    try: 
        os.system(f"svn export --force -q {u} {t}")
        socketio.emit('toast', {'text': f'✅ {name} 下载完成!'}, namespace='/')
    except Exception as e:
        socketio.emit('toast', {'text': f'❌ 下载失败: {e}', 'type':'error'}, namespace='/')

if __name__ == '__main__':
    logging.info("Starting Pico AI Server...")
    socketio.run(app, host='0.0.0.0', port=5000)
