# =======================================================================
# Pico AI Server - app.py (社交群聊版)
# 功能: 全局历史记录 | 社交感知 | 本地语音 | 纯净模式
# =======================================================================
import os
import json
import uuid
import asyncio
import time
import glob
import shutil
import subprocess
import threading
import requests

import edge_tts
from flask import Flask, render_template, request, make_response, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room
from google import genai

# --- 1. 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
SERVER_VERSION = str(int(time.time()))

# --- 2. 目录与文件 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")
HISTORY_FILE = os.path.join(BASE_DIR, "chat_history.json") # 全局聊天记录

for d in [AUDIO_DIR, MODELS_DIR, VOICES_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# --- 3. 配置加载 ---
CONFIG = {}
try:
    if os.path.exists("config.json"):
        with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key:
    try: client = genai.Client(api_key=api_key)
    except: pass

# --- 4. 全局记忆系统 (核心升级) ---
# 内存中的聊天记录缓存
GLOBAL_HISTORY = []
MAX_HISTORY_LEN = 50 # 记住最近 50 句话，太长会消耗 Token

def load_global_history():
    global GLOBAL_HISTORY
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                GLOBAL_HISTORY = json.load(f)
            # 截断旧的
            if len(GLOBAL_HISTORY) > MAX_HISTORY_LEN:
                GLOBAL_HISTORY = GLOBAL_HISTORY[-MAX_HISTORY_LEN:]
        except: GLOBAL_HISTORY = []

def save_global_history():
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(GLOBAL_HISTORY, f, indent=2, ensure_ascii=False)
    except: pass

# 启动时加载历史
load_global_history()

# 记录消息的辅助函数
def add_history(sender, text, role="user", emotion="NORMAL"):
    entry = {
        "timestamp": int(time.time()),
        "sender": sender,
        "text": text,
        "role": role, # user 或 pico
        "emotion": emotion
    }
    GLOBAL_HISTORY.append(entry)
    # 保持长度限制
    if len(GLOBAL_HISTORY) > MAX_HISTORY_LEN:
        GLOBAL_HISTORY.pop(0)
    # 异步保存（threading模式下直接保存也没事，量不大）
    save_global_history()
    return entry

# --- 5. 模型管理 ---
CURRENT_MODEL = {"id": "default", "name": "Default", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    d = {"persona":f"你是{mid}。", "voice":"zh-CN-XiaoxiaoNeural", "rate":"+0%", "pitch":"+0Hz", "scale":0.5, "x":0.5, "y":0.5}
    if os.path.exists(p):
        try: d.update(json.load(open(p))) 
        except: pass
    return d

def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    curr = get_model_config(mid); curr.update(data)
    with open(p, "w", encoding="utf-8") as f: json.dump(curr, f, indent=2)
    return curr

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

# --- 6. TTS ---
def run_piper_tts(text, model_file, output_path):
    model_path = model_file if os.path.isabs(model_file) else os.path.join(VOICES_DIR, model_file)
    if not os.path.exists(PIPER_BIN) or not os.path.exists(model_path): return False
    try:
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", output_path]
        subprocess.run(cmd, input=text.encode('utf-8'), check=True, capture_output=True)
        return True
    except: return False

def bg_tts(text, voice, rate, pitch, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}"
    success = False; url = ""
    
    if voice.endswith(".onnx"):
         if run_piper_tts(clean, voice, os.path.join(AUDIO_DIR, f"{fname}.wav")):
             success=True; url=f"/static/audio/{fname}.wav"

    if not success:
        safe_voice = voice if ("Neural" in voice) else "zh-CN-XiaoxiaoNeural"
        try:
            edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch).save_sync(os.path.join(AUDIO_DIR, f"{fname}.mp3"))
            success=True; url=f"/static/audio/{fname}.mp3"
        except: pass

    if success:
        # 广播给所有人听！直播间里大家都能听到 AI 说话
        socketio.emit('audio_response', {'audio': url}, to='lobby')

# --- 7. 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v): return render_template('chat.html')

# --- 8. SocketIO (社交核心) ---
users = {}
chatroom_chat = None

def get_ai_response(prompt, history_context):
    if not client: return "[系统] AI 未连接"
    try:
        # 重新构建 Chat Session，带入历史背景
        # 这里的 system_instruction 包含了人设 + 近期聊天记录
        system_prompt = f"{CURRENT_MODEL['persona']}\n\n【近期聊天记录(供参考，请记住这些信息以回答用户关于其他人的问题)】:\n{history_context}"
        
        chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": system_prompt})
        resp = chat.send_message(prompt)
        return resp.text
    except Exception as e: return f"[Error] {e}"

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})

@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    
    # 【关键】把服务器存的历史记录发给新用户
    # 这样A一进来就能看到 YK 之前说了什么
    emit('history_sync', GLOBAL_HISTORY)
    
    sys_msg = f"🎉 欢迎 {u} 进入直播间！"
    emit('system_message', {'text': sys_msg}, to='lobby')
    add_history("系统", sys_msg, "system") # 记录进场

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]['username']
    msg = d['text']
    # 用户的私有记忆 (Client -> Server)
    private_mems = d.get('memories', [])
    
    if "/管理员" in msg:
        if sender.lower() == "yk": users[sid]['is_admin']=True; emit('admin_unlocked'); return
    
    # 1. 广播用户消息给所有人
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    add_history(sender, msg, "user") # 存入历史

    # 2. 构建上下文 (Social Context)
    # 将最近的聊天记录拼接成文本，喂给 AI
    # 格式: [YK]: 大家好 / [Pico]: 你好呀
    recent_context = "\n".join([f"[{h['sender']}]: {h['text']}" for h in GLOBAL_HISTORY[-20:]])
    
    # 3. 私有记忆注入
    # 只有当前提问者(sender)的私有记忆会被加进去
    memory_context = ""
    if private_mems:
        memory_context = f"\n【{sender}的私有备注(仅你知道)】: {', '.join(private_mems)}"

    # 4. 生成回答
    full_prompt = f"[{sender} 说]: {msg}{memory_context}"
    
    # 异步处理 AI 回复
    threading.Thread(target=handle_ai_response, args=(full_prompt, recent_context, sender)).start()

def handle_ai_response(prompt, context, sender):
    # AI 思考
    reply_text = get_ai_response(prompt, context)
    
    # 解析表情
    emo='NORMAL'
    match = re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', reply_text)
    clean_text = reply_text.replace(match.group(0), '').strip() if match else reply_text
    if match: emo = match.group(1)
    
    # 广播 AI 回复
    socketio.emit('response', {'text': clean_text, 'sender': CURRENT_MODEL['name'], 'emotion': emo}, to='lobby')
    
    # 存入历史
    add_history(CURRENT_MODEL['name'], clean_text, "pico", emo)
    
    # 合成语音
    bg_tts(clean_text, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'])

# --- 其他接口 (保持不变) ---
@socketio.on('get_studio_data')
def on_get_data():
    voices = [{"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓"},{"id":"en-US-AnaNeural","name":"☁️ Ana"}]
    if os.path.exists(VOICES_DIR):
        for onnx in glob.glob(os.path.join(VOICES_DIR, "*.onnx")):
            name = os.path.basename(onnx).replace(".onnx", "")
            if os.path.exists(os.path.join(VOICES_DIR, f"{name}.txt")): 
                try: name = open(os.path.join(VOICES_DIR, f"{name}.txt")).read().strip()
                except: pass
            voices.append({"id": os.path.basename(onnx), "name": f"🏠 {name}"})
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'voices': voices})

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; emit('model_switched', CURRENT_MODEL, to='lobby')

@socketio.on('save_settings')
def on_save_settings(d):
    global CURRENT_MODEL
    if not users.get(request.sid, {}).get('is_admin'): return
    try: d['scale']=float(d['scale']); d['x']=float(d['x']); d['y']=float(d['y'])
    except: pass
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL.update(updated); emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})
# (下载/上传接口保持不变，省略)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
