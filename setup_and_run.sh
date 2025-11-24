#!/bin/bash
# 最终稳定版 (Threading Mode)
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
echo -e "${GREEN}🤖 Pico AI (原生线程版) 启动中...${NC}"

# --- 0. 自动更新 ---
echo -e "🔄 检查更新..."
git fetch --all > /dev/null 2>&1
if git reset --hard origin/main > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 代码已同步${NC}"
else
    echo -e "${YELLOW}⚠️ 更新跳过${NC}"
fi

# --- 1. 环境 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

# 确保依赖 (移除 gevent/eventlet，防止干扰)
pip uninstall eventlet gevent -y -q 2>/dev/null || true
pip install flask flask-socketio python-socketio python-engineio google-genai edge-tts requests soundfile gunicorn -q 2>/dev/null || true

# Cloudflared
if [ ! -f "$CDIR/cloudflared" ]; then
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# --- 2. 隧道配置 ---
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
# 强力清理端口
if command -v fuser &> /dev/null; then fuser -k 5000/tcp > /dev/null 2>&1; fi
sleep 2

echo "--- Session $(date) ---" > "$LOG_FILE"

# 【关键】使用 gthread 模式，4 线程
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

sleep 5
if ! pgrep -f gunicorn > /dev/null; then
    echo -e "${RED}❌ Gunicorn 启动失败!${NC}"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

echo -e "${GREEN}✅ 启动成功！${NC}"
echo -e "👉 https://${MY_DOMAIN}/pico"
echo -e "${YELLOW}👀 正在监控日志...${NC}"

tail -f "$LOG_FILE"
