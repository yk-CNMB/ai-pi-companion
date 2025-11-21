#!/bin/bash
# 纯净启动版 - 不会自动覆盖你的代码

# 自动修复 Windows 换行符
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
echo -e "${GREEN}🤖 Pico AI (本地代码版) 启动中...${NC}"

# --- 1. 环境检查 ---
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# 确保依赖安装 (但不会去拉取 GitHub 代码)
pip install -r requirements.txt -q 2>/dev/null || true

# 确保 cloudflared
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 下载 Cloudflared..."
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# --- 2. 自动配置隧道 ---
TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -z "$TUNNEL_CRED" ]; then
    echo -e "${RED}❌ 未找到隧道凭证！${NC}"
    exit 1
fi
TUNNEL_ID=$(basename "$TUNNEL_CRED" .json)

cat > "$CDIR/tunnel_config.yml" <<YAML
tunnel: $TUNNEL_ID
credentials-file: $TUNNEL_CRED
ingress:
  - hostname: $MY_DOMAIN
    service: http://localhost:5000
  - service: http_status:404
YAML

# --- 3. 启动服务 ---
echo -e "🧠 重启 AI 大脑..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
sleep 1

# 后台启动 Gunicorn
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

# 检查启动状态
sleep 5
if ! pgrep -f gunicorn > /dev/null; then 
    echo -e "${RED}❌ Gunicorn 启动失败!${NC}"
    echo "👇👇👇 错误日志 👇👇👇"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

echo -e "🌐 启动永久隧道..."
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

# --- 4. 成功提示 ---
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Pico 已上线！${NC}"
echo -e "\n    👉 https://${MY_DOMAIN}/pico\n"
echo -e "${BLUE}========================================${NC}"
