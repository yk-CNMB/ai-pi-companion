#!/bin/bash
# 自动修复 Windows 换行符
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
MY_DOMAIN="yk-pico-project.site"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI (原生线程版) 启动...${NC}"

# --- 1. 环境准备 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

# 确保依赖 (移除了 gevent/eventlet)
pip install flask flask-socketio python-socketio python-engineio google-genai edge-tts requests soundfile gunicorn -q 2>/dev/null || true

# 确保 cloudflared
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 下载 Cloudflared..."
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# --- 2. 配置 ---
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
echo -e "🧹 清理..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
sleep 2

echo -e "🧠 启动 Gunicorn (gthread 模式)..."
echo "--- New Session $(date) ---" > "$LOG_FILE"

# 【关键】使用 gthread 模式，4个线程
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

sleep 5
if ! pgrep -f gunicorn > /dev/null; then
    echo -e "${RED}❌ 启动失败!${NC}"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

echo -e "🌐 启动隧道..."
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

echo -e "${GREEN}✅ 成功！${NC}"
echo -e "👉 https://${MY_DOMAIN}/pico"
tail -f "$LOG_FILE"
```

**运行方法：**
```bash
bash setup_and_run.sh
