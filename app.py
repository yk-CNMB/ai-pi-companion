# =======================================================================
# Pico AI Server - app.py (终极全功能版)
# 集成功能：多用户记忆 + 情感语音 + 聊天室 + 完整引导
# =======================================================================

import os
import json
import uuid
import asyncio
import time
import glob
import shutil
import re

# 【关键】导入 eventlet 并打补丁
import eventlet
eventlet.monkey_patch()

import edge_tts
from flask import Flask, render_template, request, make_response, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

# --- 1. 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 2. 目录配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")

for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR]:
    os.makedirs(d, exist_ok=True)

# --- 3. API 配置 ---
CONFIG = {}
try:
    with open("config.json", "r") as f: CONFIG = json.load(f)
    print("✅ 已加载 config.json")
except: pass

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini API 就绪")
    except Exception as e: print(f"❌ API 初始化失败: {e}")
else:
    print("❌ 未找到有效 API KEY")

# --- 4. 核心功能函数 ---

# 记忆管理
def load_user_memories(username):
    safe_name = "".join([c for c in username if c.isalnum() or c in ('-','_')]).lower() or "default"
    try:
        with open(os.path.join(MEMORIES_DIR, f"{safe_name}.json"), "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_user_memory(username, fact):
    safe_name = "".join([c for c in username if c.isalnum() or c in ('-','_')]).lower() or "default"
    memories = load_user_memories(username)
    if fact not in memories:
        memories.append(fact)
        with open(os.path.join(MEMORIES_DIR, f"{safe_name}.json"), "w", encoding="utf-8") as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        return True
    return False

# 模型管理
CURRENT_MODEL = {"id": "default", "path": "", "persona": ""}
def get_default_persona(name):
    return f"你是一个名为'{name}'的AI虚拟主播。请用中文简短回复，性格活泼。每句话开头加上情感标签如 [HAPPY], [ANGRY] 等。"

def scan_models():
    models = []
    for m_json in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        m_dir = os.path.dirname(m_json)
        m_id = os.path.basename(m_dir)
        p_path = os.path.join(m_dir, "persona.txt")
        if not os.path.exists(p_path):
            with open(p_path, "w", encoding="utf-8") as f: f.write(get_default_persona(m_id.capitalize()))
        with open(p_path, "r", encoding="utf-8") as f: p = f.read()
        models.append({"id": m_id, "name": m_id.capitalize(), "path": "/"+os.path.relpath(m_json, BASE_DIR).replace("\\","/"), "persona": p})
    return sorted(models, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
    print(f"🤖 当前模型: {CURRENT_MODEL.get('id')}")
init_model()

# 语音合成
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
def bg_tts(text, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}.mp3"
    try:
        async def _run():
            cm = edge_tts.Communicate(clean, TTS_VOICE)
            await cm.save(os.path.join(AUDIO_DIR, fname))
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
        loop.close()
        url = f"/static/audio/{fname}"
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')
    except: pass

# --- 5. 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_dynamic', version=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_dynamic', version=SERVER_VERSION))
@app.route('/pico/<version>')
def pico_dynamic(version):
    if version != SERVER_VERSION: return redirect(url_for('pico_dynamic', version=SERVER_VERSION))
    r = make_response(render_template('chat.html'))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r

# --- 6. Socket.IO 事件 ---
users = {}

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        emit('system_message', {'text': f"💨 {users.pop(request.sid)} 离开了。"}, to='lobby')

@socketio.on('login')
def on_login(data):
    username = data.get('username', 'Anonymous').strip() or "匿名"
    users[request.sid] = username
    join_room('lobby')
    
    emit('login_success', {'username': username, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 欢迎 {username} 加入直播间！"}, to='lobby', include_self=False)
    
    # 【核心修改】全新的固定开场白
    welcome_text = (
        f"[HAPPY] 嗨 {username}，欢迎来到AI妙妙屋！🎉\n"
        "我是你的专属（？） AI 。教你几个互动小技巧：\n"
        "1️⃣ 发送【/记 你的内容】可以让我记住重要信息。\n"
        "2️⃣ 如果我位置歪了，点右上角的【🎯】我就能归位。\n"
        "3️⃣ 点【🛠️】可以带我去换衣服哦！\n"
        "现在，快发弹幕和我聊天吧！"
    )
    
    # 发送开场白文字和语音 (只发给当前登录用户)
    emit('response', {'text': welcome_text, 'sender': 'Pico', 'emotion': 'HAPPY'})
    socketio.start_background_task(bg_tts, welcome_text, sid=request.sid)

@socketio.on('message')
def on_message(data):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]
    msg = data['text']
    
    # 处理记忆指令
    if msg.startswith("/记 "):
        fact = msg[3:].strip()
        if fact and save_user_memory(sender, fact):
             emit('response', {'text': f"🧠 好的 {sender}，我记住了：{fact}", 'sender': 'Pico'})
        return

    # 广播用户消息
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    
    try:
        # 读取记忆并构建 Prompt
        memories = load_user_memories(sender)
        mem_ctx = f"({CURRENT_MODEL['name']}记得关于{sender}: {', '.join(memories[-3:])})" if memories else ""
        
        # 创建临时会话
        chat = client.chats.create(
            model="gemini-2.5-flash",
            config={"system_instruction": CURRENT_MODEL['persona']}
        )
        resp = chat.send_message(f"【{sender}说】: {msg} {mem_ctx}")
        
        # 解析情感
        emo = 'NORMAL'
        match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt = resp.text.replace(match.group(0), '').strip() if match else resp.text
        if match: emo = match.group(1)

        # 广播回复
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, room='lobby')
        
    except Exception as e:
        print(f"AI Error: {e}")
        emit('system_message', {'text': "⚠️ 大脑短路中..."}, to='lobby')

# --- 7. 工作室接口 ---
@socketio.on('get_studio_data')
def on_get_data(): emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t:
        CURRENT_MODEL = t
        emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_persona')
def on_save_p(d):
    p = os.path.join(MODELS_DIR, d['id'], "persona.txt")
    if os.path.exists(os.path.dirname(p)):
        with open(p, "w", encoding="utf-8") as f: f.write(d['text'])
        if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL['persona'] = d['text']
        emit('toast', {'text': '✅ 人设已保存'})
@socketio.on('delete_model')
def on_del(d):
    if d['id'] == CURRENT_MODEL['id']: return emit('toast', {'text': '❌ 不能删除当前模型', 'type': 'error'})
    try:
        shutil.rmtree(os.path.join(MODELS_DIR, d['id']))
        emit('toast', {'text': '🗑️ 已删除'})
        emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id']})
    except: emit('toast', {'text': '删除失败', 'type': 'error'})
def bg_dl(url, name):
    try:
        t = os.path.join(MODELS_DIR, name.lower())
        if os.path.exists(t): shutil.rmtree(t)
        os.makedirs(t, exist_ok=True)
        # 使用更稳健的 git sparse-checkout 而不是 svn
        temp_git = os.path.join(BASE_DIR, f"temp_{uuid.uuid4()}")
        os.makedirs(temp_git)
        os.system(f"cd {temp_git} && git init -q && git remote add -f origin https://github.com/Live2D/CubismWebSamples.git && git config core.sparseCheckout true && echo 'Samples/Resources/{name}' >> .git/info/sparse-checkout && git pull origin master -q")
        os.system(f"mv {temp_git}/Samples/Resources/{name}/* {t}/ && rm -rf {temp_git}")
        
        socketio.emit('toast', {'text': f'🎉 {name} 下载完成!'}, namespace='/')
    except Exception as e:
        print(f"DL Error: {e}")
        socketio.emit('toast', {'text': f'❌ {name} 下载失败', 'type': 'error'}, namespace='/')
@socketio.on('download_model')
def on_dl(d):
    # 这里只列出名字，具体 URL 在后台处理
    if d['name'] in ["Mao", "Natori", "Rice", "Wanko"]:
        emit('toast', {'text': f'🚀 开始下载 {d["name"]}...', 'type': 'info'})
        socketio.start_background_task(bg_dl, "", d['name'])
