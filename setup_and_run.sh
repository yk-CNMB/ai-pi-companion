#!/bin/bash
# 自动修复换行符
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
URL_FILE="$CDIR/public_url.txt"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI 智能管家启动...${NC}"

# --- 0. 自动更新 ---
echo -e "🔄 检查更新..."
git fetch --all > /dev/null 2>&1
if git reset --hard origin/main > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 已同步到最新版本${NC}"
else
    echo -e "${YELLOW}⚠️ 更新跳过，使用当前版本${NC}"
fi

# --- 1. 环境检查 ---
if [ ! -d "$VENV_DIR" ]; then echo "📦 创建虚拟环境..."; python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 下载 Cloudflared..."
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# --- 2. 智能启动 ---
echo -e "🧠 重启 AI 大脑..."
pkill -9 -f gunicorn
sleep 1
# 清空旧日志，开始新的记录
echo "--- New Session ---" > "$LOG_FILE"
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &
sleep 3
if ! pgrep -f gunicorn > /dev/null; then echo -e "${RED}❌ Gunicorn 启动失败!${NC}"; cat "$LOG_FILE"; exit 1; fi

if pgrep -f "cloudflared tunnel" > /dev/null; then
    echo -e "${YELLOW}🌉 隧道保持不变。${NC}"
    if [ -f "$URL_FILE" ]; then CURRENT_URL=$(cat "$URL_FILE"); fi
else
    echo -e "${GREEN}🌐 新建公网隧道...${NC}"
    pkill -9 -f cloudflared
    nohup "$CDIR/cloudflared" tunnel --url http://127.0.0.1:5000 >> "$LOG_FILE" 2>&1 &
    echo "⏳ 等待网址 (15s)..."
    sleep 15
    CURRENT_URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | tail -n 1)/pico
    echo "$CURRENT_URL" > "$URL_FILE"
fi

# --- 3. 显示结果 & 开始监控 ---
echo -e "${BLUE}========================================${NC}"
if [[ "$CURRENT_URL" == *"trycloudflare.com/pico" ]]; then
    echo -e "${GREEN}✅ Pico 已在线！访问地址：${NC}\n\n    $CURRENT_URL\n"
    echo -e "${YELLOW}🔍 即将进入日志监控模式... (按 Ctrl+C 可退出监控，服务不会停)${NC}"
    echo -e "${BLUE}========================================${NC}"
    sleep 3
    # 【核心】实时显示日志文件的新增内容
    tail -f "$LOG_FILE"
else
    echo -e "${RED}❌ 启动失败，正在显示错误日志：${NC}"
    cat "$LOG_FILE"
fi
