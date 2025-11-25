# =======================================================================
# Pico AI Server - app.py (Piper 纯净增强版)
# 仅支持: Piper (本地) + Edge-TTS (在线)
# 兼容: Python 3.13 (原生线程)
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

import edge_tts
import soundfile as sf
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from google import genai

# --- 1. 初始化 ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# 使用 threading 模式
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 2. 目录配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")

for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# --- 3. API 配置 ---
CONFIG = {}
try:
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            CONFIG = json.load(f)
    print("✅ 配置加载成功")
except:
    pass

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里" not in api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ Gemini API 就绪")
    except Exception as e:
        print(f"❌ API 初始化失败: {e}")
else:
    print("❌ 未找到有效 API KEY")

# --- 4. 核心功能 ---
def load_user_memories(u): return []

CURRENT_MODEL = {
    "id": "default", "path": "", "persona": "", 
    "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", 
    "scale": 0.5, "x": 0.5, "y": 0.5
}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    data = {"persona":f"你是{mid}。","voice":"zh-CN-XiaoxiaoNeural","rate":"+0%","pitch":"+0Hz","scale":0.5,"x":0.5,"y":0.5}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except: pass
    # 清理旧的 Fish Audio 字段
    for k in ['api_key', 'api_url', 'model_id']:
        if k in data: del data[k]
    return data

def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    curr = get_model_config(mid); curr.update(data)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(curr, f, ensure_ascii=False, indent=2)
    return curr

def scan_models():
    ms = []
    for j in glob.glob(os.path.join(MODELS_DIR, "**", "*.model3.json"), recursive=True):
        mid = os.path.basename(os.path.dirname(j))
        cfg = get_model_config(mid)
        ms.append({
            "id": mid, "name": mid.capitalize(),
            "path": "/" + os.path.relpath(j, BASE_DIR).replace("\\", "/"),
            **cfg
        })
    return sorted(ms, key=lambda x: x['name'])

def init_model():
    global CURRENT_MODEL
    ms = scan_models()
    t = next((m for m in ms if "hiyori" in m['id'].lower()), ms[0] if ms else None)
    if t: CURRENT_MODEL = t
init_model()

# --- 5. TTS (Piper + Edge) ---
def run_piper_tts(text, model_file, output_path):
    # 自动处理路径：如果是文件名，加上目录；如果是绝对路径，直接用
    if not os.path.isabs(model_file):
        model_path = os.path.join(VOICES_DIR, model_file)
    else:
        model_path = model_file
        
    if not os.path.exists(PIPER_BIN): 
        print(f"❌ Piper 引擎缺失: {PIPER_BIN}"); return False
    if not os.path.exists(model_path):
        print(f"❌ 模型文件缺失: {model_path}"); return False
        
    try:
        print(f"🏠 [Piper] 生成中... (模型: {os.path.basename(model_path)})")
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", output_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate(input=text.encode('utf-8'))
        
        if proc.returncode == 0:
            return True
        else:
            print(f"❌ Piper 内部错误: {err.decode()}")
            return False
    except Exception as e:
        print(f"❌ Piper 调用异常: {e}")
        return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}"
    success = False
    url = ""
    
    # 1. Piper (本地优先)
    # 只要 voice 是以 .onnx 结尾，就认定是 Piper 模型
    if voice.endswith(".onnx"):
         out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
         if run_piper_tts(clean, voice, out_path):
             success = True
             url = f"/static/audio/{fname}.wav"

    # 2. Edge-TTS (兜底)
    if not success:
        out_path = os.path.join(AUDIO_DIR, f"{fname}.mp3")
        safe_voice = voice
        # 如果 voice 是无效的(比如 piper 失败了)，强制切回晓晓
        if not safe_voice or ".onnx" in safe_voice:
            safe_voice = "zh-CN-XiaoxiaoNeural"
            print(f"☁️ [Edge] 兜底使用: {safe_voice}")
            
        try:
            async def _run():
                cm = edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); loop.run_until_complete(_run()); loop.close()
            success = True
            url = f"/static/audio/{fname}.mp3"
        except: pass

    if success:
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')

# --- 6. 路由 ---
@app.route('/')
def idx(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico')
def pico_legacy(): return redirect(url_for('pico_v', v=SERVER_VERSION))
@app.route('/pico/<v>')
def pico_v(v):
    if v!=SERVER_VERSION: return redirect(url_for('pico_v', v=SERVER_VERSION))
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
            items = os.listdir(p)
            if len(items)==1 and os.path.isdir(os.path.join(p, items[0])):
                sub = os.path.join(p, items[0])
                for i in os.listdir(sub): shutil.move(os.path.join(sub, i), p)
                os.rmdir(sub)
            return jsonify({'success': True})
        except Exception as e: return jsonify({'success': False, 'msg': str(e)})
    return jsonify({'success': False})

# --- 7. SocketIO ---
users = {}
chatroom_chat = None
def init_chatroom():
    global chatroom_chat
    if not client: return
    try:
        chatroom_chat = client.chats.create(
            model="gemini-2.5-flash",
            config={"system_instruction": CURRENT_MODEL['persona']}
        )
        print(f"🏠 聊天室重置: {CURRENT_MODEL['name']}")
    except: pass

@socketio.on('connect')
def on_connect(): emit('server_ready', {'status': 'ok'})
@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users: emit('system_message', {'text': f"💨 {users.pop(request.sid)['username']} 离开了。"}, to='lobby')
@socketio.on('login')
def on_login(d):
    u = d.get('username','').strip() or "匿名"
    users[request.sid] = {"username": u, "is_admin": False}
    join_room('lobby')
    if not chatroom_chat: init_chatroom()
    emit('login_success', {'username': u, 'current_model': CURRENT_MODEL})
    emit('system_message', {'text': f"🎉 欢迎 {u} 加入！"}, to='lobby', include_self=False)
    welcome = f"[HAPPY] 嗨 {u}！"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], sid=request.sid)

@socketio.on('message')
def on_message(d):
    sid = request.sid
    if sid not in users: return
    sender = users[sid]['username']
    msg = d['text']
    user_memories = d.get('memories', [])
    if "/管理员" in msg:
        if sender.lower() == "yk": users[sid]['is_admin']=True; emit('admin_unlocked'); emit('system_message', {'text': f"👑 管理员上线"}, to=sid)
        else: emit('system_message', {'text': "🤨 拒绝"}, to=sid)
        return
    emit('chat_message', {'text': msg, 'sender': sender}, to='lobby')
    try:
        if not chatroom_chat: init_chatroom()
        mem_ctx = f" (记忆: {', '.join(user_memories)})" if user_memories else ""
        resp = chatroom_chat.send_message(f"【{sender}说{mem_ctx}】: {msg}")
        emo='NORMAL'; match=re.search(r'\[(HAPPY|ANGRY|SAD|SHOCK|NORMAL)\]', resp.text)
        txt=resp.text.replace(match.group(0),'').strip() if match else resp.text
        if match: emo=match.group(1)
        emit('response', {'text': txt, 'sender': 'Pico', 'emotion': emo}, to='lobby')
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], room='lobby')
    except Exception as e: print(f"AI: {e}"); init_chatroom()

def is_admin(sid): return users.get(sid, {}).get('is_admin', False)

# --- 8. 工作室接口 (核心逻辑) ---
@socketio.on('get_studio_data')
def on_get_data():
    # 1. 基础 Edge-TTS 列表 (硬编码)
    voices = [
        {"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓 (默认)"},
        {"id":"zh-CN-YunxiNeural","name":"☁️ 云希 (少年)"},
        {"id":"zh-TW-HsiaoChenNeural","name":"☁️ 晓臻 (台湾)"}
    ]
    
    # 2. 扫描本地 Piper (.onnx)
    print(f"🔍 正在扫描: {VOICES_DIR}")
    if os.path.exists(VOICES_DIR):
        # 递归扫描，防止文件藏在子目录里
        onnx_files = glob.glob(os.path.join(VOICES_DIR, "**", "*.onnx"), recursive=True)
        print(f"🔍 找到 {len(onnx_files)} 个模型")
        
        for onnx in onnx_files:
            # 计算相对路径，确保 app.py 能找到它
            rel_path = os.path.relpath(onnx, VOICES_DIR)
            # 显示名称
            name = os.path.basename(onnx).replace(".onnx", "")
            # 尝试找同名 txt 获取好听的名字
            txt_path = os.path.splitext(onnx)[0] + ".txt"
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, 'r') as f:
                        name = f.read().strip()
                except: pass
            
            # 这里的 id 就是相对路径，例如 "glados/glados.onnx" 或 "glados.onnx"
            voices.append({"id": rel_path, "name": f"🏠 {name}"})
            print(f"   -> 添加: {name} (ID: {rel_path})")

    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'voices': voices})

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t:
        CURRENT_MODEL = t
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_settings')
def on_save_settings(d):
    global CURRENT_MODEL
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 无权限', 'type': 'error'})
    try: d['scale']=float(d['scale']); d['x']=float(d['x']); d['y']=float(d['y'])
    except: pass
    # 只保存需要的字段，不保存 api_key
    valid_keys = ['persona', 'voice', 'rate', 'pitch', 'scale', 'x', 'y']
    clean_data = {k: d[k] for k in valid_keys if k in d}
    
    updated = save_model_config(d['id'], clean_data)
    if CURRENT_MODEL['id'] == d['id']:
        CURRENT_MODEL.update(updated)
        init_chatroom()
        emit('model_switched', CURRENT_MODEL, to='lobby')
    emit('toast', {'text': '✅ 保存成功'})

@socketio.on('delete_model')
def on_del(d):
    if not is_admin(request.sid): return
    if d['id']==CURRENT_MODEL['id']: return emit('toast',{'text':'❌ 占用中','type':'error'})
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
