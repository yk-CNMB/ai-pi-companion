#!/bin/bash
# 最终完美版 - 自动修复 + 完整功能

# 1. 自我修复 Windows 换行符 (关键!)
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI 智能管家启动...${NC}"

# --- 0. 自动更新 ---
echo -e "🔄 检查更新..."
if git pull --rebase --autostash; then
    echo -e "${GREEN}✅ 已是最新版本${NC}"
else
    echo -e "${RED}⚠️ 更新失败，继续使用当前版本${NC}"
fi

# --- 1. 环境检查 ---
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 下载 Cloudflared..."
    ARCH=$(dpkg --print-architecture)
    if [[ "$ARCH" == "arm64" ]]; then
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    else
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"
    fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp
    chmod +x "$CDIR/cloudflared"
fi

# --- 2. 启动服务 ---
echo -e "🧠 重启 AI 大脑..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
sleep 2
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app > "$LOG_FILE" 2>&1 &
sleep 5
if ! pgrep -f gunicorn > /dev/null; then echo -e "${RED}❌ Gunicorn 启动失败!${NC}"; exit 1; fi

echo -e "🌐 建立公网隧道..."
nohup "$CDIR/cloudflared" tunnel --url http://127.0.0.1:5000 >> "$LOG_FILE" 2>&1 &
echo "⏳ 等待网址 (15秒)..."
sleep 15

# --- 3. 显示结果 ---
URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | tail -n 1)/pico
echo -e "${BLUE}========================================${NC}"
if [[ "$URL" == *"trycloudflare.com/pico" ]]; then
    echo -e "${GREEN}✅ 成功！访问地址：${NC}\n\n    $URL\n"
else
    echo -e "${RED}❌ 获取失败，请检查 server.log${NC}"
fi
echo -e "${BLUE}========================================${NC}"
