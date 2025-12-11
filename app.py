# =======================================================================
# Pico AI Server - ULTIMATE FULL VERSION
# 包含：全功能 TTS、双模调用、完整错误处理、详细日志、人设保护
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
import traceback  # 增加错误堆栈打印

# 核心依赖库检查
try:
    import edge_tts
    print("✅ edge_tts 库加载成功")
except ImportError:
    print("❌ 警告: 未找到 edge_tts 库，将尝试使用命令行模式")

from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename

# 配置详细日志
logging.basicConfig(
    level=logging.INFO, 
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'pico_ultimate_secret_key_2025'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB 上传限制

# SocketIO 配置 - 增加 buffer 防止大图断连
socketio = SocketIO(app, 
    cors_allowed_origins="*", 
    async_mode='threading', 
    ping_timeout=60, 
    ping_interval=25,
    max_http_buffer_size=100*1024*1024
)

SERVER_VERSION = str(int(time.time()))

# --- 目录结构初始化 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
BG_DIR = os.path.join(BASE_DIR, "static", "backgrounds")
STATE_FILE = os.path.join(BASE_DIR, "server_state.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# 确保所有必要的目录存在
for d in [AUDIO_DIR, MODELS_DIR, BG_DIR]:
    if not os.path.exists(d):
        try:
            os.makedirs(d)
            logging.info(f"创建目录: {d}")
        except Exception as e:
            logging.error(f"创建目录失败 {d}: {e}")

# --- 全局配置加载 ---
CONFIG = {
    "GEMINI_API_KEY": "",
    "TTS_VOICE": "zh-CN-XiaoxiaoNeural",
    "TTS_RATE": "+0%",
    "TTS_PITCH": "+0Hz"
}

try:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding='utf-8') as f: 
            # 过滤掉注释行 (以 // 开头的行)
            lines = [line for line in f.readlines() if not line.strip().startswith("//")]
            if lines:
                CONFIG.update(json.loads("\n".join(lines)))
                logging.info("配置文件加载成功")
except Exception as e:
    logging.error(f"加载配置文件出错: {e}")

# 初始化 Gemini 客户端
client = None
api_key = CONFIG.get("GEMINI_API_KEY")
if api_key and "AIza" in api_key:
    try:
        client = genai.Client(api_key=api_key)
        logging.info("Gemini 客户端初始化成功")
    except Exception as e:
        logging.error(f"Gemini 初始化失败: {e}")

# --- 默认人设指令 (仅作为 fallback) ---
DEFAULT_INSTRUCTION = """
【系统指令】
你是一个虚拟主播。
请在每次回复的开头，必须明确标记你当前的心情标签。
标签必须是以下之一：[HAPPY], [ANGRY], [SAD], [SHOCK], [NORMAL]。
"""

# --- 全局状态管理 (放在最前防止 NameError) ---
GLOBAL_STATE = { 
    "current_model_id": "default", 
    "current_background": "", 
    "chat_history": [] 
}

def save_state():
    """保存服务器状态到 JSON 文件"""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(GLOBAL_STATE, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"保存状态失败: {e}")

def load_state():
    """从 JSON 文件加载服务器状态"""
    global GLOBAL_STATE
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if saved:
                    GLOBAL_STATE.update(saved)
                    # 限制历史记录长度，防止文件过大
                    if len(GLOBAL_STATE["chat_history"]) > 100:
                        GLOBAL_STATE["chat_history"] = GLOBAL_STATE["chat_history"][-100:]
            logging.info("服务器状态加载成功")
        except Exception as e:
            logging.error(f"加载状态失败: {e}")

# 立即执行加载
load_state()

# 当前运行的模型配置缓存
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
    """
    读取特定模型的 config.json。
    如果文件不存在，返回默认配置。
    如果文件存在，完全信任文件内容，不随意覆盖。
    """
    p = os.path.join(MODELS_DIR, mid, "config.json")
    
    # 默认配置
    d = {
        "persona": f"你是{mid}。{DEFAULT_INSTRUCTION}", 
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
                # 只有当加载的配置中没有 persona 时，才使用默认值
                # 这样可以保护用户修改过的人设
                if loaded.get('persona'):
                    d['persona'] = loaded['persona']
                
                # 更新其他字段
                d.update(loaded)
        except Exception as e:
            logging.error(f"读取模型配置失败 {mid}: {e}")
            
    return d

def save_model_config(mid, data):
    """保存配置到模型的 config.json"""
    p = os.path.join(MODELS_DIR, mid, "config.json")
    
    # 先读取现有配置，确保不丢失未修改的字段
    curr = get_model_config(mid)
    curr.update(data)
    
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(curr, f, indent=2, ensure_ascii=False)
        logging.info(f"模型配置已保存: {mid}")
    except Exception as e:
        logging.error(f"保存模型配置失败 {mid}: {e}")
        
    return curr

def scan_models():
    """扫描所有 Live2D 模型文件夹"""
    ms = []
    # 遍历 live2d 目录
    for root, dirs, files in os.walk(MODELS_DIR):
        for file in files:
            # 寻找模型入口文件
            if file.endswith(('.model3.json', '.model.json')):
                full_path = os.path.join(root, file)
                
                # 计算相对路径
                rel_path = os.path.relpath(full_path, BASE_DIR).replace("\\", "/")
                if not rel_path.startswith("/"): rel_path = "/" + rel_path
                
                folder_name = os.path.basename(os.path.dirname(full_path))
                model_id = folder_name
                
                # 避免重复添加同一个模型 ID
                if any(m['id'] == model_id for m in ms): continue
                
                # 获取该模型的详细配置
                cfg = get_model_config(model_id)
                
                ms.append({
                    "id": model_id, 
                    "name": model_id, 
                    "path": rel_path, 
                    **cfg
                })
    # 按名称排序
    return sorted(ms, key=lambda x: x['name'])

def scan_backgrounds():
    """扫描背景图片"""
    bgs = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif']:
        for f in glob.glob(os.path.join(BG_DIR, ext)): 
            bgs.append(os.path.basename(f))
    return sorted(bgs)

def init_model():
    """初始化加载模型"""
    global CURRENT_MODEL
    ms = scan_models()
    
    # 尝试恢复上次使用的模型
    last_id = GLOBAL_STATE.get("current_model_id")
    target = next((m for m in ms if m['id'] == last_id), None)
    
    # 如果找不到，尝试找默认的
    if not target and len(ms) > 0: 
        target = ms[0]
        
    if target: 
        CURRENT_MODEL = target
        GLOBAL_STATE["current_model_id"] = target['id']
        save_state()
        logging.info(f"当前模型初始化为: {target['id']}")

# 初始化模型
init_model()

# ================= TTS 核心 (双模冗余设计) =================

def run_edge_tts_cmd(text, output_path, voice, rate, pitch):
    """
    方式1：命令行调用
    优点：进程隔离，不占用 Python GIL，极其稳定
    缺点：需要系统安装 edge-tts 命令
    """
    try:
        logging.info(f"[TTS CMD] 开始生成: {text[:10]}...")
        cmd = [
            "edge-tts",
            "--text", text,
            "--write-media", output_path,
            "--voice", voice,
            "--rate", rate,
            "--pitch", pitch
        ]
        # 设置超时时间，防止卡死
        subprocess.run(cmd, check=True, timeout=15)
        logging.info(f"[TTS CMD] 生成成功")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"[TTS CMD] 命令执行错误: {e}")
    except Exception as e:
        logging.error(f"[TTS CMD] 未知错误: {e}")
    return False

def run_edge_tts_python(text, output_path, voice, rate, pitch):
    """
    方式2：Python 库调用
    优点：无需配置环境变量，直接调用库函数
    缺点：在 Flask 线程中需要小心处理 asyncio 事件循环
    """
    try:
        logging.info(f"[TTS LIB] 开始生成: {text[:10]}...")
        async def _gen():
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await communicate.save(output_path)
        
        # 创建独立的事件循环，避免与 Flask/SocketIO 冲突
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(_gen())
        new_loop.close()
        
        logging.info(f"[TTS LIB] 生成成功")
        return True
    except Exception as e:
        logging.error(f"[TTS LIB] 错误: {e}")
        return False

def bg_tts_task(text, voice, rate, pitch, room=None, sid=None):
    """后台 TTS 任务"""
    # 清理文本中的表情标签
    clean_text = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean_text: return

    # 生成唯一文件名
    fname = f"{uuid.uuid4()}.mp3"
    out_path = os.path.join(AUDIO_DIR, fname)
    
    success = False
    
    # 策略：优先尝试命令行，如果失败则回退到 Python 库
    if run_edge_tts_cmd(clean_text, out_path, voice, rate, pitch):
        success = True
    else:
        logging.warning("TTS 命令行模式失败，尝试使用 Python 库模式...")
        if run_edge_tts_python(clean_text, out_path, voice, rate, pitch):
            success = True

    if success and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        url = f"/static/audio/{fname}"
        payload = {'audio': url}
        logging.info(f"🔊 推送音频事件: {url}")
        
        if room: 
            socketio.emit('audio_response', payload, to=room, namespace='/')
        elif sid: 
            socketio.emit('audio_response', payload, to=sid, namespace='/')
    else:
        logging.error("❌ 最终：音频生成失败")

# ================= Flask 路由 =================
@app.route('/')
def idx(): 
    return redirect(url_for('pico_v', v=SERVER_VERSION))

@app.route('/pico/<v>')
def pico_v(v):
    r = make_response(render_template('chat.html'))
    # 禁用缓存，确保前端更新
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

@app.route('/update_key', methods=['POST'])
def update_key():
    data = request.json
    new_key = data.get('key', '').strip()
    if not new_key.startswith("AIza"): 
        return jsonify({'success': False, 'msg': 'Key 格式错误，必须以 AIza 开头'})
    
    global client, CONFIG
    CONFIG['GEMINI_API_KEY'] = new_key
    
    try: 
        client = genai.Client(api_key=new_key)
        # 写入配置文件
        with open(CONFIG_FILE, "w", encoding='utf-8') as f: 
            json.dump(CONFIG, f, indent=2)
        return jsonify({'success': True})
    except Exception as e: 
        return jsonify({'success': False, 'msg': str(e)})

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
            
            # 解压
            with zipfile.ZipFile(f, 'r') as z: 
                z.extractall(p)
            
            # 智能修正路径 (如果解压后多了一层文件夹)
            for root, dirs, files in os.walk(p):
                if any(f.endswith('.model3.json') for f in files):
                    if root != p: 
                         for item in os.listdir(root): 
                             shutil.move(os.path.join(root, item), p)
                    break
            return jsonify({'success': True})
        except Exception as e: 
            logging.error(f"模型上传失败: {e}")
            return jsonify({'success': False})
    return jsonify({'success': False})

@app.route('/api/danmaku', methods=['POST'])
def api_danmaku():
    """B站直播弹幕对接接口"""
    data = request.json
    if not data or 'text' not in data: return jsonify({'success': False})
    
    user = data.get('username', 'B站弹幕')
    msg = data.get('text', '')
    
    # 记录到历史
    user_msg_obj = {'type': 'chat', 'sender': user, 'text': msg}
    GLOBAL_STATE['chat_history'].append(user_msg_obj)
    save_state()
    
    # 广播到前端
    socketio.emit('chat_message', {'text': msg, 'sender': user}, to='lobby')
    
    # 触发 AI 回复
    socketio.start_background_task(process_ai_response, user, msg)
    return jsonify({'success': True})

# ================= AI 逻辑 =================
users = {}
chatroom_chat = None

def init_chatroom():
    global chatroom_chat
    if not client: return
    # 使用当前配置的人设
    sys_prompt = CURRENT_MODEL.get('persona', "")
    if not sys_prompt: sys_prompt = DEFAULT_INSTRUCTION
    
    try: 
        chatroom_chat = client.chats.create(
            model="gemini-2.5-flash", 
            config={"system_instruction": sys_prompt}
        )
        logging.info("AI 聊天室初始化成功")
    except Exception as e:
        logging.error(f"AI 聊天室初始化失败: {e}")

def process_ai_response(sender, msg, img_data=None, sid=None):
    try:
        if not chatroom_chat: init_chatroom()
        if not client: 
            if sid: socketio.emit('system_message', {'text': '请先设置 API Key'}, to=sid)
            return
        
        content = []
        if msg: content.append(f"【{sender}】: {msg}")
        
        # 处理图片
        if img_data:
            try:
                if "," in img_data: _, encoded = img_data.split(",", 1)
                else: encoded = img_data
                content.append(types.Part.from_bytes(data=base64.b64decode(encoded), mime_type="image/jpeg"))
            except Exception as e:
                logging.error(f"图片处理错误: {e}")
            
        resp = chatroom_chat.send_message(content)
        
        # 解析情感标签
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text
        if match: 
            emo = match.group(1)
            txt = resp.text.replace(match.group(0), '').strip()
            
        ai_msg = {'type': 'response', 'sender': 'Pico', 'text': txt, 'emotion': emo}
        GLOBAL_STATE['chat_history'].append(ai_msg)
        save_state()
        
        socketio.emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        
        # 触发语音合成
        bg_tts_task(txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
        
    except Exception as e:
        logging.error(f"AI 回复生成错误: {e}")
        if sid: socketio.emit('system_message', {'text': f'AI Error: {e}'}, to=sid)

# ================= Socket.IO 事件 =================
@socketio.on('connect')
def on_connect():
    emit('server_ready', {'status': 'ok'})

@socketio.on('login')
def on_login(d):
    u = d.get('username', '').strip() or "User"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    
    if not chatroom_chat: init_chatroom()
    
    emit('login_success', {
        'username': u, 
        'current_model': CURRENT_MODEL, 
        'current_background': GLOBAL_STATE.get('current_background', '')
    })
    
    emit('history_sync', {'history': GLOBAL_STATE['chat_history']})
    
    # 欢迎语音
    socketio.start_background_task(bg_tts_task, f"欢迎 {u}", CURRENT_MODEL['voice'], "+0%", "+0%", sid=request.sid)

@socketio.on('message')
def on_msg(d):
    sid = request.sid
    if sid not in users: return
    
    msg = d.get('text', '')
    img = d.get('image', None)
    sender = users[sid]['username']
    
    # 管理员后门指令
    if "/管理员" in msg and sender.lower() == "yk":
        users[sid]['is_admin'] = True
        emit('admin_unlocked')
        return

    # 记录用户消息
    GLOBAL_STATE['chat_history'].append({'type':'chat', 'sender':sender, 'text':msg, 'image': bool(img)})
    save_state()
    
    emit('chat_message', {'text':msg, 'sender':sender, 'image':img}, to='lobby')
    socketio.start_background_task(process_ai_response, sender, msg, img, sid)

def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

# ★★★ 找回丢失的语音列表逻辑 (完整版) ★★★
@socketio.on('get_studio_data')
def on_get_data():
    # 完整的 Edge-TTS 推荐列表
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
        'voices': voices, # 这里把语音列表返回给前端
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
