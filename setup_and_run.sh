#!/bin/bash
# [自我修复] 自动清除 Windows 换行符，防止报错
sed -i 's/\r$//' "$0" 2>/dev/null || true

# --- 定义变量 ---
CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
URL_FILE="$CDIR/public_url.txt"
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI 智能启动中...${NC}"

# --- 0. 自动更新 (已找回!) ---
echo -e "🔄 检查更新..."
# 尝试拉取最新代码，如果失败（比如没网）则跳过，继续运行旧版
if git pull --rebase --autostash; then
    echo -e "${GREEN}✅ 已是最新版本${NC}"
else
    echo -e "${RED}⚠️ 更新失败，将使用当前版本启动${NC}"
fi
echo -e "${BLUE}----------------------------------------${NC}"

# --- 1. 环境检查 ---
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# 确保 Cloudflared 存在
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

# --- 2. 清理与启动 ---
echo -e "🧹 清理旧进程..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
sleep 2

echo -e "🧠 启动 AI 大脑 (Gunicorn)..."
# 使用 nohup 后台运行
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app > "$LOG_FILE" 2>&1 &

sleep 5
if ! pgrep -f gunicorn > /dev/null; then
    echo -e "${RED}❌ Gunicorn 启动失败！请查看 server.log${NC}"
    exit 1
fi

echo -e "🌐 建立公网隧道..."
# 【关键】强制使用 127.0.0.1 避免 502 错误
nohup "$CDIR/cloudflared" tunnel --url http://127.0.0.1:5000 >> "$LOG_FILE" 2>&1 &

echo -e "⏳ 正在获取公网地址，请稍候 (约 15 秒)..."
sleep 15

# --- 3. 显示网址 ---
CURRENT_URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | tail -n 1)/pico

echo -e "${BLUE}========================================${NC}"
if [[ "$CURRENT_URL" == *"trycloudflare.com/pico" ]]; then
    echo "$CURRENT_URL" > "$URL_FILE"
    echo -e "${GREEN}✅ Pico 已在线！访问地址：${NC}"
    echo -e "\n    $CURRENT_URL\n"
else
    echo -e "${RED}❌ 获取网址失败，请稍后再次运行，或检查 server.log${NC}"
fi
echo -e "${BLUE}========================================${NC}"
