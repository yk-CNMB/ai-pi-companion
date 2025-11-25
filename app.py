# =======================================================================
# Pico AI Server - app.py (Piper 强制显示版)
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
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
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

CONFIG = {}
try:
    if os.path.exists("config.json"):
        with open("config.json", "r") as f: CONFIG = json.load(f)
    print("✅ 配置文件加载成功")
except: pass

client = None
api_key = CONFIG.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key and "在这里" not in api_key:
    try: client = genai.Client(api_key=api_key)
    except: pass

def load_user_memories(u): return []

CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.5, "y": 0.5}

def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    data = {"persona":f"你是{mid}。","voice":"zh-CN-XiaoxiaoNeural","rate":"+0%","pitch":"+0Hz","scale":0.5,"x":0.5,"y":0.5}
    if os.path.exists(p):
        try: data.update(json.load(open(p))) 
        except: pass
    return data

def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    curr = get_model_config(mid); curr.update(data)
    with open(p, "w", encoding="utf-8") as f: json.dump(curr, f, ensure_ascii=False, indent=2)
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

# --- Piper 核心逻辑 ---
def run_piper_tts(text, model_file, output_path):
    # 自动修正路径
    if not os.path.isabs(model_file):
        model_path = os.path.join(VOICES_DIR, model_file)
    else:
        model_path = model_file

    # 必须要有对应的 json 配置文件，Piper 才能运行
    json_path = model_path + ".json"
    
    if not os.path.exists(PIPER_BIN): 
        print(f"❌ [Piper] 引擎未找到: {PIPER_BIN}"); return False
    if not os.path.exists(model_path): 
        print(f"❌ [Piper] 模型文件未找到: {model_path}"); return False
    if not os.path.exists(json_path):
        print(f"❌ [Piper] 缺少配置文件: {json_path}"); 
        print("👉 请运行 fix_glados_piper.sh 修复！"); return False

    try:
        print(f"🎤 [Piper] 正在生成: {text[:10]}...")
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", output_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate(input=text.encode('utf-8'))
        if proc.returncode == 0:
            print(f"✅ [Piper] 生成成功！")
            return True
        else:
            print(f"❌ [Piper] 报错: {err.decode()}")
            return False
    except Exception as e:
        print(f"❌ [Piper] 异常: {e}")
        return False

def bg_tts(text, voice, rate, pitch, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}"
    success = False
    url = ""
    
    # 1. Piper
    if voice.endswith(".onnx"):
         out_path = os.path.join(AUDIO_DIR, f"{fname}.wav")
         if run_piper_tts(clean, voice, out_path):
             success=True; url=f"/static/audio/{fname}.wav"

    # 2. Edge-TTS
    if not success:
        out_path = os.path.join(AUDIO_DIR, f"{fname}.mp3")
        safe_voice = voice if ("Neural" in voice) else "zh-CN-XiaoxiaoNeural"
        if safe_voice != voice: print(f"☁️ [Edge] 降级使用: {safe_voice}")
        try:
            async def _run():
                cm = edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch)
                await cm.save(out_path)
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); loop.run_until_complete(_run()); loop.close()
            success=True; url=f"/static/audio/{fname}.mp3"
        except Exception as e: print(f"❌ TTS Error: {e}")

    if success:
        if room: socketio.emit('audio_response', {'audio': url}, to=room, namespace='/')
        elif sid: socketio.emit('audio_response', {'audio': url}, to=sid, namespace='/')

# --- 路由 ---
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

# --- SocketIO ---
users = {}
chatroom_chat = None
def init_chatroom():
    global chatroom_chat
    if not client: return
    try: chatroom_chat = client.chats.create(model="gemini-2.5-flash", config={"system_instruction": CURRENT_MODEL['persona']})
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

@socketio.on('get_studio_data')
def on_get_data():
    # 1. 基础 Edge-TTS
    voices = [{"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓 (默认)"},{"id":"zh-CN-YunxiNeural","name":"☁️ 云希 (少年)"}]
    
    # 2. 扫描本地 Piper (.onnx)
    print(f"🔍 [System] 正在扫描语音目录: {VOICES_DIR}")
    if os.path.exists(VOICES_DIR):
        # 强制扫描所有 onnx
        onnx_files = glob.glob(os.path.join(VOICES_DIR, "*.onnx"))
        print(f"🔍 [System] 找到 {len(onnx_files)} 个 .onnx 文件")
        
        for onnx in onnx_files:
            mid = os.path.basename(onnx)
            name = mid.replace(".onnx", "")
            # 读取名字
            if os.path.exists(os.path.join(VOICES_DIR, f"{name}.txt")):
                try: name = open(os.path.join(VOICES_DIR, f"{name}.txt")).read().strip()
                except: pass
            
            # 添加到列表
            voices.append({"id": mid, "name": f"🏠 {name} (本地)"})
            print(f"   -> 已添加: {name} (ID: {mid})")
            
    emit('studio_data', {'models': scan_models(), 'current_id': CURRENT_MODEL['id'], 'voices': voices})

@socketio.on('switch_model')
def on_switch(d):
    global CURRENT_MODEL
    t = next((m for m in scan_models() if m['id'] == d['id']), None)
    if t: CURRENT_MODEL = t; init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
@socketio.on('save_settings')
def on_save_settings(d):
    global CURRENT_MODEL
    if not is_admin(request.sid): return emit('toast', {'text': '❌ 无权限', 'type': 'error'})
    try: d['scale']=float(d['scale']); d['x']=float(d['x']); d['y']=float(d['y'])
    except: pass
    updated = save_model_config(d['id'], d)
    if CURRENT_MODEL['id'] == d['id']: CURRENT_MODEL.update(updated); init_chatroom(); emit('model_switched', CURRENT_MODEL, to='lobby')
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
