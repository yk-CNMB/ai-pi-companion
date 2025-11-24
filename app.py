# =======================================================================
# Pico AI Server - app.py (原生线程版 - 兼容 Python 3.13)
# =======================================================================
import os, json, uuid, asyncio, time, glob, shutil, re, zipfile, subprocess, requests, threading

# 【关键】这里不再导入 eventlet 或 gevent！纯原生！

import edge_tts
import soundfile as sf
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from google import genai

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# 【关键】async_mode='threading'，使用原生线程，最稳定
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)
SERVER_VERSION = str(int(time.time()))

# --- 目录配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORIES_DIR = os.path.join(BASE_DIR, "memories")
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audio")
MODELS_DIR = os.path.join(BASE_DIR, "static", "live2d")
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")
for d in [MEMORIES_DIR, AUDIO_DIR, MODELS_DIR, VOICES_DIR]: os.makedirs(d, exist_ok=True)

# --- API ---
CONFIG = {}
try: with open("config.json", "r") as f: CONFIG = json.load(f)
except: pass
client = None
if CONFIG.get("GEMINI_API_KEY"):
    try: client = genai.Client(api_key=CONFIG.get("GEMINI_API_KEY"))
    except Exception as e: print(f"API Error: {e}")

# --- 核心函数 ---
def load_user_memories(u): return []

CURRENT_MODEL = {"id": "default", "path": "", "persona": "", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+0Hz", "scale": 0.5, "x": 0.0, "y": 0.0, "api_url": "", "api_key": "", "model_id": ""}
def get_model_config(mid):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    d = {"persona":f"你是{mid}。","voice":"zh-CN-XiaoxiaoNeural","rate":"+0%","pitch":"+0Hz","scale":0.5,"x":0.0,"y":0.0,"api_url":"","api_key":"","model_id":""}
    if os.path.exists(p):
        try: d.update(json.load(open(p))) 
        except: pass
    return d
def save_model_config(mid, data):
    p = os.path.join(MODELS_DIR, mid, "config.json")
    c = get_model_config(mid); c.update(data)
    with open(p, "w", encoding="utf-8") as f: json.dump(c, f, indent=2)
    return c
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

# --- TTS ---
def run_openai_tts(text, api_url, api_key, model_id, output_path):
    try:
        if not api_url.endswith("/v1/audio/speech"):
             if "fish.audio" in api_url: api_url = "https://api.fish.audio/v1/audio/speech"
             else: api_url = api_url.rstrip("/") + "/v1/audio/speech"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model_id, "input": text, "voice": model_id, "response_format": "mp3"}
        resp = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            with open(output_path, "wb") as f: f.write(resp.content)
            return True
        return False
    except: return False

def run_piper_tts(text, model_file, output_path):
    model_path = os.path.join(VOICES_DIR, model_file)
    if not os.path.exists(PIPER_BIN): return False
    try:
        subprocess.run(f'echo "{text}" | "{PIPER_BIN}" --model "{model_path}" --output_file "{output_path}"', shell=True, check=True)
        return True
    except: return False

def bg_tts(text, voice, rate, pitch, api_url, api_key, model_id, room=None, sid=None):
    clean = re.sub(r'\[(.*?)\]', '', text).strip()
    if not clean: return
    fname = f"{uuid.uuid4()}"
    success = False
    
    if api_url and api_key and model_id:
        if run_openai_tts(clean, api_url, api_key, model_id, os.path.join(AUDIO_DIR, f"{fname}.mp3")):
            success=True; url=f"/static/audio/{fname}.mp3"

    if not success and voice.endswith(".onnx"):
         if run_piper_tts(clean, voice, os.path.join(AUDIO_DIR, f"{fname}.wav")):
             success=True; url=f"/static/audio/{fname}.wav"

    if not success:
        safe_voice = voice if voice and "Neural" in voice else "zh-CN-XiaoxiaoNeural"
        try:
            async def _run():
                cm = edge_tts.Communicate(clean, safe_voice, rate=rate, pitch=pitch)
                await cm.save(os.path.join(AUDIO_DIR, f"{fname}.mp3"))
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); loop.run_until_complete(_run()); loop.close()
            success=True; url=f"/static/audio/{fname}.mp3"
        except: pass

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
    if f and f.filename.endswith('.zip'):
        try:
            n = secure_filename(f.filename).rsplit('.', 1)[0].lower()
            p = os.path.join(MODELS_DIR, n); shutil.rmtree(p, ignore_errors=True)
            with zipfile.ZipFile(f, 'r') as z: z.extractall(p)
            items = os.listdir(p)
            if len(items)==1 and os.path.isdir(os.path.join(p, items[0])):
                sub = os.path.join(p, items[0]); 
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
    emit('system_message', {'text': f"🎉 欢迎 {u} 加入！"}, to='lobby', include_self=False)
    welcome = f"[HAPPY] 嗨 {u}！我是{CURRENT_MODEL['name']}。"
    emit('response', {'text': welcome, 'sender': 'Pico', 'emotion': 'HAPPY'}, to=request.sid)
    socketio.start_background_task(bg_tts, welcome, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], CURRENT_MODEL.get('api_url'), CURRENT_MODEL.get('api_key'), CURRENT_MODEL.get('model_id'), sid=request.sid)

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
        socketio.start_background_task(bg_tts, txt, CURRENT_MODEL['voice'], CURRENT_MODEL['rate'], CURRENT_MODEL['pitch'], CURRENT_MODEL.get('api_url'), CURRENT_MODEL.get('api_key'), CURRENT_MODEL.get('model_id'), room='lobby')
    except Exception as e: print(f"AI: {e}"); init_chatroom()

# --- 工作室 ---
def is_admin(sid): return users.get(sid, {}).get('is_admin', False)
@socketio.on('get_studio_data')
def on_get_data():
    voices = [{"id":"zh-CN-XiaoxiaoNeural","name":"☁️ 晓晓"},{"id":"zh-CN-YunxiNeural","name":"☁️ 云希"}]
    for onnx in glob.glob(os.path.join(VOICES_DIR, "*.onnx")):
        mid = os.path.basename(onnx); name = mid.replace(".onnx", "")
        if os.path.exists(os.path.join(VOICES_DIR, f"{name}.txt")): name=open(os.path.join(VOICES_DIR, f"{name}.txt")).read().strip()
        voices.append({"id": mid, "name": f"🏠 {name} (本地)"})
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

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
```

---

### ⚙️ 第三步：重建 `setup_and_run.sh` (Gthread 适配版)

为了配合原生线程版代码，启动命令也必须修改为 **`gthread`**，绝对不能再用 `eventlet` 了。

1.  在终端输入 `cat > setup_and_run.sh <<'EOF'`
2.  粘贴以下内容：

```bash
#!/bin/bash
# 自动修复 Windows 换行符
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
MY_DOMAIN="yk-pico-project.site"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI (原生线程稳如狗版) 启动...${NC}"

# --- 1. 环境 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"
pip install -r requirements.txt -q 2>/dev/null || true

# --- 2. 隧道 ---
TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -n "$TUNNEL_CRED" ]; then
    TUNNEL_ID=$(basename "$TUNNEL_CRED" .json)
    cat > "$CDIR/tunnel_config.yml" <<YAML
tunnel: $TUNNEL_ID
credentials-file: $TUNNEL_CRED
ingress:
  - hostname: $MY_DOMAIN
    service: http://localhost:5000
  - service: http_status:404
YAML
fi

# --- 3. 启动 ---
echo -e "🧠 重启服务..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
fuser -k 5000/tcp > /dev/null 2>&1
sleep 2

echo "--- Session $(date) ---" > "$LOG_FILE"

# 【关键】使用 gthread 模式，彻底避开兼容性问题
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

sleep 5
if ! pgrep -f gunicorn > /dev/null; then
    echo -e "${RED}❌ 启动失败!${NC}"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

echo -e "${GREEN}✅ 启动成功！${NC}"
echo -e "👉 https://${MY_DOMAIN}/pico"
echo -e "${YELLOW}👀 监控日志...${NC}"

tail -f "$LOG_FILE"
