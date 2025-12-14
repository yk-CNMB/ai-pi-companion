# =======================================================================
# Pico AI Server - 重装装甲版 (Heavy Armor Edition)
# 核心原则：逻辑冗余保护、详细日志记录、拒绝任何不稳定精简
# 功能：Live2D Only + ACGN TTS + Edge-TTS + 完整后台管理
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
import base64
import logging
import sys
import asyncio
import edge_tts
import requests

from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename

# 配置日志：不仅打印到控制台，确保格式清晰
logging.basicConfig(
    level=logging.INFO, 
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'pico_heavy_armor_key_v1'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 允许大文件上传

# SocketIO 配置：使用 threading 模式以获得最佳兼容性
socketio = SocketIO(app, 
    cors_allowed_origins="*", 
    async_mode='threading', 
    ping_timeout=60, 
    ping_interval=25, 
    max_http_buffer_size=100*1024*1024
)

SERVER_VERSION = str(int(time.time()))

# --- 目录初始化与检查 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d") 
BG_DIR = os.path.join(BASE_DIR, "static", "backgrounds")
STATE_FILE = os.path.join(BASE_DIR, "server_state.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# 强制检查并创建目录
for d in [AUDIO_DIR, MODELS_DIR, BG_DIR]:
    if not os.path.exists(d):
        try:
            os.makedirs(d)
            logging.info(f"📁 创建目录: {d}")
        except Exception as e:
            logging.error(f"❌ 创建目录失败 {d}: {e}")

# --- 配置加载 (Robust Loading) ---
CONFIG = {
    "GEMINI_API_KEY": "",
    "DEFAULT_VOICE": "zh-CN-XiaoyiNeural",
    "ACGN_TOKEN": "",
    "ACGN_CHARACTER": "流萤",
    "ACGN_API_URL": "https://gsv2p.acgnai.top"
}

def load_config():
    """加载配置文件，带容错处理"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding='utf-8') as f: 
                # 过滤注释行
                lines = [line for line in f.readlines() if not line.strip().startswith("//")]
                if lines: 
                    loaded_config = json.loads("\n".join(lines))
                    CONFIG.update(loaded_config)
            logging.info("✅ 配置文件加载成功")
        except Exception as e:
            logging.error(f"⚠️ 配置文件加载失败: {e}")

load_config()

def save_config():
    """保存配置文件，严格分行写法"""
    try:
        with open(CONFIG_FILE, "w", encoding='utf-8') as f:
            json.dump(CONFIG, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"❌ 保存配置失败: {e}")

# --- Gemini 初始化 ---
gemini_client = None
chatroom_chat = None

def init_gemini():
    global gemini_client, chatroom_chat
    api_key = CONFIG.get("GEMINI_API_KEY")
    if api_key and "AIza" in api_key:
        try:
            gemini_client = genai.Client(api_key=api_key)
            chatroom_chat = None 
            logging.info("✅ Gemini 客户端初始化完成")
        except Exception as e:
            logging.error(f"❌ Gemini 初始化失败: {e}")
    else:
        logging.warning("⚠️ Gemini API Key 未设置或格式错误")

init_gemini()

# --- 状态管理 ---
GLOBAL_STATE = { 
    "current_model_id": "default", 
    "current_background": "", 
    "chat_history": [] 
}

def save_state():
    """保存服务器状态，严格分行"""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(GLOBAL_STATE, f, ensure_ascii=False)
    except Exception as e:
        logging.error(f"保存状态出错: {e}")

def load_state():
    global GLOBAL_STATE
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if saved: GLOBAL_STATE.update(saved)
                # 截断历史记录防止过大
                if len(GLOBAL_STATE["chat_history"]) > 100: 
                    GLOBAL_STATE["chat_history"] = GLOBAL_STATE["chat_history"][-100:]
        except Exception as e:
            logging.error(f"加载状态出错: {e}")

load_state()

# --- 模型管理 ---
CURRENT_MODEL = {
    "id": "default", "type": "live2d", "path": "", "persona": "", 
    "voice": "0", "rate": "+0%", "pitch": "+0Hz", 
    "scale": 0.5, "x": 0.0, "y": 0.0
}
DEFAULT_INSTRUCTION = "\n【指令】回复开头标记心情：[HAPPY], [ANGRY], [SAD], [SHOCK], [NORMAL]。"

def get_model_config(mid):
    """读取单个模型的配置"""
    # 既然回滚到 Live2D，模型配置一定在模型文件夹内
    cfg_dir = os.path.join(MODELS_DIR, mid)
    p = os.path.join(cfg_dir, "config.json")
    
    d = {"persona": f"你是{mid}。{DEFAULT_INSTRUCTION}", "voice": "0", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.0, "y": 0.0}
    
    if os.path.exists(p):
        try: 
            with open(p, "r", encoding="utf-8") as f: 
                loaded = json.load(f)
                d.update(loaded)
        except: pass
    return d

def save_model_config(mid, data):
    """保存模型配置"""
    cfg_dir = os.path.join(MODELS_DIR, mid)
    if not os.path.exists(cfg_dir):
        os.makedirs(cfg_dir, exist_ok=True)
        
    p = os.path.join(cfg_dir, "config.json")
    curr = get_model_config(mid)
    curr.update(data)
    
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(curr, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"保存模型配置失败: {e}")
    return curr

def scan_models():
    """
    扫描 Live2D 模型 (增强版)
    遍历 static/live2d 下的所有子文件夹，寻找 .model3.json 文件
    """
    ms = []
    if not os.path.exists(MODELS_DIR):
        logging.warning(f"模型目录不存在: {MODELS_DIR}")
        return []
    
    logging.info(f"🔍 开始扫描模型目录: {MODELS_DIR}")
    
    for root, dirs, files in os.walk(MODELS_DIR):
        for file in files:
            # 只认 Live2D 标准入口文件
            if file.endswith('.model3.json') or file.endswith('.model.json'):
                full_path = os.path.join(root, file)
                
                # 计算相对路径，供前端访问
                rel_path = os.path.relpath(full_path, BASE_DIR).replace("\\", "/")
                if not rel_path.startswith("/"): 
                    rel_path = "/" + rel_path
                
                # 模型 ID 默认为文件夹名称
                mid = os.path.basename(os.path.dirname(full_path))
                
                # 防止重复添加
                if any(m['id'] == mid for m in ms): 
                    continue
                
                # 读取该模型的个性化配置
                cfg = get_model_config(mid)
                
                ms.append({
                    "id": mid, 
                    "name": mid, 
                    "type": "live2d", 
                    "path": rel_path, 
                    **cfg
                })
                logging.info(f"   -> 发现模型: {mid} ({rel_path})")

    logging.info(f"✅ 扫描结束，共找到 {len(ms)} 个模型")
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    """初始化当前模型"""
    global CURRENT_MODEL
    ms = scan_models()
    
    # 尝试恢复上次使用的模型
    last_id = GLOBAL_STATE.get("current_model_id")
    target = next((m for m in ms if m['id'] == last_id), None)
    
    # 如果找不到上次的，就用第一个；如果一个都没有，就不动
    if not target and ms: 
        target = ms[0]
    
    if target: 
        CURRENT_MODEL = target
        GLOBAL_STATE["current_model_id"] = target['id']
        save_state()
        logging.info(f"✅ 当前加载模型: {CURRENT_MODEL['id']}")

init_model()

# ================= 语音合成核心 (ACGN + Edge) =================

def cleanup_audio_dir():
    """清理旧音频缓存"""
    try:
        now = time.time()
        for f in os.listdir(AUDIO_DIR):
            fp = os.path.join(AUDIO_DIR, f)
            # 清理 5 分钟前的文件
            if os.path.getmtime(fp) < now - 300: 
                os.remove(fp)
    except: pass

def generate_acgn_tts(text):
    """调用 ACGN AI 在线接口"""
    token = CONFIG.get("ACGN_TOKEN")
    char_name = CONFIG.get("ACGN_CHARACTER", "流萤")
    
    if not token: 
        return None
        
    try:
        url = CONFIG.get("ACGN_API_URL", "https://gsv2p.acgnai.top")
        if not url.endswith("/"): url += "/"
        
        headers = {
            "Authorization": f"Bearer {token}", 
            "Content-Type": "application/json"
        }
        params = {
            "text": text, 
            "text_language": "zh", 
            "character": char_name, 
            "format": "wav"
        }
        
        logging.info(f"📡 ACGN TTS 请求 ({char_name}): {text[:15]}...")
        resp = requests.get(url, headers=headers, params=params, timeout=12)
        
        if resp.status_code == 200:
            # 简单校验返回是否为音频
            content_type = resp.headers.get("Content-Type", "")
            if "audio" in content_type or len(resp.content) > 1000:
                filename = f"acgn_{uuid.uuid4().hex}.wav"
                filepath = os.path.join(AUDIO_DIR, filename)
                with open(filepath, 'wb') as f: 
                    f.write(resp.content)
                logging.info("✅ ACGN 生成成功")
                return f"/static/audio/{filename}"
            else:
                logging.warning(f"⚠️ ACGN 返回非音频数据: {resp.text[:100]}")
        else:
            logging.warning(f"⚠️ ACGN 请求失败 Code: {resp.status_code}")
    except Exception as e: 
        logging.warning(f"⚠️ ACGN 连接异常: {e}")
        
    return None

def run_edge_tts_sync(text, voice, output_file, rate="+0%", pitch="+0Hz"):
    """同步执行 Edge-TTS"""
    async def _amain():
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(output_file)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_amain())
        loop.close()
        return True
    except Exception as e:
        logging.error(f"Edge-TTS Loop Error: {e}")
        return False

def generate_audio_smart(text, voice_id, rate, pitch):
    cleanup_audio_dir()
    clean_text = re.sub(r'\[.*?\]', '', text).strip()
    if not clean_text: return None

    # 1. 优先尝试 ACGN (如果选中 acgn 或 默认选中0且配了token)
    if voice_id == "acgn" or (CONFIG.get("ACGN_TOKEN") and voice_id == "0"):
        url = generate_acgn_tts(clean_text)
        if url: return url

    # 2. Edge-TTS 兜底
    filename = f"edge_{uuid.uuid4().hex}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)
    
    # 语音映射表
    voice_map = {
        "0": "zh-CN-XiaoyiNeural", 
        "1": "zh-CN-XiaoxiaoNeural", 
        "2": "zh-CN-YunxiNeural", 
        "acgn": "zh-CN-XiaoyiNeural" # ACGN失败时的替补
    }
    
    target_voice = voice_map.get(str(voice_id), "zh-CN-XiaoyiNeural")
    if "Neural" in str(voice_id): target_voice = voice_id

    logging.info(f"🎙️ Edge-TTS 兜底请求: {clean_text[:10]}...")
    if run_edge_tts_sync(clean_text, target_voice, filepath, rate, pitch):
        return f"/static/audio/{filename}"
    return None

def bg_tts_task(text, voice, rate, pitch, room=None, sid=None):
    """后台 TTS 任务"""
    audio_url = generate_audio_smart(text, voice, rate, pitch)
    if audio_url:
        payload = {'audio': audio_url}
        if room: socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', payload, to=sid, namespace='/')
    else:
        # 失败不弹窗，仅记录
        logging.warning("⚠️ TTS 最终生成失败")

# ================= Flask 路由 =================
@app.route('/')
def idx(): 
    return redirect(url_for('pico_v', v=SERVER_VERSION))

@app.route('/pico/<v>')
def pico_v(v):
    r = make_response(render_template('chat.html'))
    # 禁止缓存，防止前端代码更新不及时
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

@app.route('/update_key', methods=['POST'])
def update_key():
    data = request.json
    new_key = data.get('key', '').strip()
    if data.get('type') == 'gemini':
        if not new_key.startswith("AIza"): 
            return jsonify({'success': False, 'msg': 'Key 格式错误'})
        
        global gemini_client, chatroom_chat
        CONFIG['GEMINI_API_KEY'] = new_key
        save_config()
        init_gemini()
        return jsonify({'success': True})
    return jsonify({'success': False, 'msg': '未知类型'})

@app.route('/upload_bg', methods=['POST'])
def upload_bg():
    f = request.files.get('file')
    if f: 
        f.save(os.path.join(BG_DIR, f"{int(time.time())}_{secure_filename(f.filename)}"))
        return jsonify({'success': True})
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
            # 简单整理文件结构：如果解压后套了一层文件夹，移动出来
            for root, dirs, files in os.walk(p):
                if any(fn.endswith('.model3.json') for fn in files):
                    if root != p: 
                        for item in os.listdir(root): 
                            shutil.move(os.path.join(root, item), p)
                    break
            return jsonify({'success': True})
        except Exception as e:
            logging.error(f"上传失败: {e}")
    return jsonify({'success': False})

@app.route('/api/danmaku', methods=['POST'])
def api_danmaku():
    data = request.json
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
    try: 
        # 恢复 Gemini 2.5 Flash
        chatroom_chat = gemini_client.chats.create(model="gemini-2.5-flash", config={"system_instruction": sys_prompt})
        logging.info("✅ 聊天会话已重置")
    except Exception as e:
        logging.error(f"创建会话失败: {e}")

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
            if "closed" in str(e).lower(): 
                init_chatroom(); return # 简单重试
            txt = f"(系统错误: {str(e)[:50]})"

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
    
    # 异步欢迎语
    socketio.start_background_task(bg_tts_task, f"欢迎 {u}", CURRENT_MODEL['voice'], "+0%", "+0%", sid=request.sid)

@socketio.on('message')
def on_msg(d):
    msg = d.get('text', '')
    if msg == '/管理员': emit('admin_unlocked'); return
    sender = "User"
    GLOBAL_STATE['chat_history'].append({'type':'chat', 'sender':sender, 'text':msg, 'image': bool(d.get('image'))})
    save_state()
    emit('chat_message', {'text':msg, 'sender':sender, 'image':d.get('image')}, to='lobby')
    socketio.start_background_task(process_ai_response, sender, msg, d.get('image'), request.sid)

@socketio.on('get_studio_data')
def on_get_data():
    logging.info("📺 正在处理 get_studio_data 请求...")
    
    voices = [
        {"id":"0", "name":"🎧 默认: 晓伊 (微软)"},
        {"id":"1", "name":"🎧 默认: 晓晓 (微软)"},
        {"id":"acgn", "name":"✨ ACGN 在线 (需配置)"}
    ]
    
    acgn_config = {
        "token": CONFIG.get("ACGN_TOKEN", ""),
        "url": CONFIG.get("ACGN_API_URL", "https://gsv2p.acgnai.top"),
        "char": CONFIG.get("ACGN_CHARACTER", "流萤")
    }
    
    models = scan_models()
    # 兜底：如果没有模型，给一个假的，防止前端崩
    if not models:
        logging.warning("⚠️ 未找到任何 Live2D 模型，前端将显示为空")
        models = []

    emit('studio_data', {
        'models': models, 
        'current_id': CURRENT_MODEL['id'], 
        'voices': voices, 
        'backgrounds': scan_backgrounds(), 
        'current_bg': GLOBAL_STATE.get('current_background', ''),
        'gemini_key_status': 'OK' if gemini_client else 'MISSING',
        'acgn_config': acgn_config
    })
    logging.info("📺 Studio 数据已发送")

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
    
    # 保存 ACGN 全局配置
    if 'acgn_token' in d: CONFIG['ACGN_TOKEN'] = d['acgn_token']
    if 'acgn_url' in d: CONFIG['ACGN_API_URL'] = d['acgn_url']
    if 'acgn_char' in d: CONFIG['ACGN_CHARACTER'] = d['acgn_char']
    save_config()
    emit('toast', {'text': '✅ 保存成功'})

@socketio.on('switch_background')
def on_sw_bg(d):
    GLOBAL_STATE['current_background'] = d.get('name'); save_state()
    emit('background_update', {'url': f"/static/backgrounds/{d.get('name')}" if d.get('name') else ""}, to='lobby')

if __name__ == '__main__':
    logging.info("🚀 Starting Pico AI Server (Heavy Armor Edition)...")
    socketio.run(app, host='0.0.0.0', port=5000)
