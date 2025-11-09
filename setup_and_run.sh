#!/bin/bash
# Pico AI 智能管家 (最终修复版)

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

# --- 0. 简易自动更新 ---
# 如果需要强制更新，取消下面两行的注释
git reset --hard HEAD
git pull

# --- 1. 环境检查 ---
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 下载 Cloudflared..."
    ARCH=$(dpkg --print-architecture)
    # 简化判断逻辑
    if [[ "$ARCH" == "arm64" ]]; then
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    else
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"
    fi
    wget -q -O cloudflared.deb "$URL"
    dpkg-deb -x cloudflared.deb temp_cf
    find temp_cf -name cloudflared -type f -exec mv {} "$CDIR/" \;
    chmod +x "$CDIR/cloudflared"
    rm -rf cloudflared.deb temp_cf
fi

# --- 2. 优先重启 AI 大脑 ---
echo -e "🧠 正在重启 AI 大脑..."
pkill -9 -f "gunicorn"
sleep 1
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

# --- 3. 智能处理隧道 ---
if pgrep -f "cloudflared_linux" > /dev/null || pgrep -f "cloudflared tunnel" > /dev/null; then
    echo -e "🌉 隧道已在运行，保持连接。"
    if [ -f "$URL_FILE" ]; then CURRENT_URL=$(cat "$URL_FILE"); fi
else
    echo -e "🌐 正在新建隧道..."
    pkill -9 -f cloudflared # 确保旧的死透了
    nohup "$CDIR/cloudflared" tunnel --url http://127.0.0.1:5000 >> "$LOG_FILE" 2>&1 &
    echo "⏳ 等待获取新网址 (约 15 秒)..."
    sleep 15
    CURRENT_URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | tail -n 1)/pico
    echo "$CURRENT_URL" > "$URL_FILE"
fi

# --- 4. 结果 ---
echo -e "${BLUE}========================================${NC}"
if [[ "$CURRENT_URL" == *"trycloudflare.com/pico" ]]; then
    echo -e "${GREEN}✅ Pico 已在线！访问地址：${NC}"
    echo -e "\n    $CURRENT_URL\n"
else
    echo -e "❌ 获取网址失败，请稍后重新运行脚本，或查看 server.log"
fi
echo -e "${BLUE}========================================${NC}"
```

### 🛡️ 步骤 2：执行“驱魔仪式” (非常重要！)


sed -i 's/\r$//' setup_and_run.sh




