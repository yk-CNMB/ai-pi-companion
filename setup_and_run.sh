#!/bin/bash
# Pico 智能管家 (Gevent 稳定版)
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
echo -e "${GREEN}🤖 Pico AI (Gevent 引擎) 启动中...${NC}"

# --- 1. 环境检查与依赖安装 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

echo "📦 检查依赖 (包含 gevent)..."
# 创建依赖清单
cat > requirements.txt <<EOF
flask
flask-socketio
python-socketio
python-engineio
gevent
gevent-websocket
google-genai
edge-tts
requests
soundfile
EOF
# 安装依赖
pip install -r requirements.txt -q 2>/dev/null || true

# Cloudflared 检查
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 下载 Cloudflared..."
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

# --- 3. 启动服务 ---
echo -e "🧹 清理战场..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
sleep 2

echo -e "🧠 启动 AI 大脑 (Gunicorn + Gevent)..."
echo "--- New Session $(date) ---" > "$LOG_FILE"

# 【关键】使用 gevent worker class
nohup "$VENV_DIR/bin/gunicorn" --worker-class gevent -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

sleep 5
if ! pgrep -f gunicorn > /dev/null; then
    echo -e "${RED}❌ Gunicorn 启动失败!${NC}"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

echo -e "🌐 启动永久隧道..."
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

# --- 4. 结果 ---
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ 启动成功！${NC}"
echo -e "👉 https://${MY_DOMAIN}/pico"
echo -e "${YELLOW}👀 进入日志监控... (Ctrl+C 退出)${NC}"
echo -e "${BLUE}========================================${NC}"

tail -f "$LOG_FILE"
```

**执行：**
```bash
bash setup_and_run.sh
