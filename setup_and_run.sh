#!/bin/bash
# 自我修复 Windows 换行符
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
MY_DOMAIN="yk-pico-project.site"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI (GitHub 同步版) 启动中...${NC}"

# --- 0. 强制更新 ---
echo -e "🔄 从 GitHub 拉取最新代码..."
git fetch --all > /dev/null 2>&1
if git reset --hard origin/main > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 代码已同步到最新${NC}"
    # 再次确保所有 .sh 文件没有 \r
    find . -name "*.sh" -exec sed -i 's/\r$//' {} +
else
    echo -e "${RED}⚠️ 更新失败 (请检查网络)，将使用本地代码${NC}"
fi

# --- 1. 环境 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

# 安装依赖 (确保 soundfile, requests 等都在)
pip install flask flask-socketio python-socketio python-engineio google-genai edge-tts requests soundfile gunicorn -q 2>/dev/null || true

# Cloudflared
if [ ! -f "$CDIR/cloudflared" ]; then
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

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
echo -e "🧹 清理旧进程..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
if command -v fuser &> /dev/null; then fuser -k 5000/tcp > /dev/null 2>&1; fi
sleep 2

echo "--- Session $(date) ---" > "$LOG_FILE"

# 使用 gthread 模式，兼容 Python 3.13
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
echo -e "${BLUE}========================================${NC}"

tail -f "$LOG_FILE"
