#!/bin/bash
# 最终智能版 - 保持网址不变 + 自动更新

# 1. 自我修复 Windows 换行符
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

# --- 2. 智能启动服务 ---

# [大脑] Gunicorn 需要经常重启以应用代码更新
echo -e "🧠 重启 AI 大脑..."
pkill -9 -f gunicorn
sleep 1
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &
sleep 3
if ! pgrep -f gunicorn > /dev/null; then echo -e "${RED}❌ Gunicorn 启动失败! 请检查 server.log${NC}"; exit 1; fi

# [桥梁] Cloudflared 尽量保持不动，以锁定网址
if pgrep -f "cloudflared tunnel" > /dev/null; then
    echo -e "${YELLOW}🌉 隧道正在运行，保持连接不变。${NC}"
    # 尝试从之前的记录读取网址
    if [ -f "$URL_FILE" ]; then
        CURRENT_URL=$(cat "$URL_FILE")
    fi
else
    echo -e "${GREEN}🌐 正在新建公网隧道...${NC}"
    pkill -9 -f cloudflared # 确保杀干净
    nohup "$CDIR/cloudflared" tunnel --url http://127.0.0.1:5000 > "$LOG_FILE" 2>&1 &
    echo "⏳ 等待网址生成 (约15秒)..."
    sleep 15
    # 提取新网址并保存
    CURRENT_URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | tail -n 1)/pico
    echo "$CURRENT_URL" > "$URL_FILE"
fi

# --- 3. 显示结果 ---
echo -e "${BLUE}========================================${NC}"
if [[ "$CURRENT_URL" == *"trycloudflare.com/pico" ]]; then
    echo -e "${GREEN}✅ 成功！访问地址：${NC}\n\n    $CURRENT_URL\n"
    echo -e "💡 提示：只要不重启树莓派，这个网址通常不会变。"
else
    echo -e "${RED}❌ 获取失败，请尝试手动重启脚本${NC}"
fi
echo -e "${BLUE}========================================${NC}"
