#!/bin/bash
# Pico AI 智能管家 (网址保持版)

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
URL_FILE="$CDIR/public_url.txt"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI 智能启动中...${NC}"

# --- 1. 优先处理 AI 大脑 (Gunicorn) ---
# 大脑需要经常重启以应用更新，所以我们总是先杀掉旧的
echo -e "🧠 正在重启 AI 大脑..."
pkill -9 -f "gunicorn"
sleep 1
# 后台启动新的大脑
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

# --- 2. 智能处理公网隧道 (Cloudflared) ---
# 检查隧道是否已经在运行
if pgrep -f "cloudflared tunnel" > /dev/null; then
    echo -e "🌉 检测到隧道已在运行，将保持现有连接 (网址不变)。"
    # 尝试从之前的记录文件中读取网址
    if [ -f "$URL_FILE" ]; then
        CURRENT_URL=$(cat "$URL_FILE")
    fi
else
    echo -e "🌐 未检测到隧道，正在新建..."
    # 启动新隧道，日志追加到文件
    nohup "$CDIR/cloudflared" tunnel --url http://127.0.0.1:5000 >> "$LOG_FILE" 2>&1 &
    echo "⏳ 等待获取新网址 (约 10 秒)..."
    sleep 12
    # 从日志中提取最新的 trycloudflare 网址
    CURRENT_URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | tail -n 1)/pico
    # 保存到文件
    echo "$CURRENT_URL" > "$URL_FILE"
fi

# --- 3. 显示结果 ---
echo -e "${BLUE}========================================${NC}"
if [ -n "$CURRENT_URL" ]; then
    echo -e "${GREEN}✅ Pico 已在线！你的访问地址是：${NC}"
    echo -e "\n    $CURRENT_URL\n"
    echo -e "💡 提示：只要不重启树莓派，这个网址通常不会变。"
else
    echo -e "❌ 获取网址失败，请查看 server.log 排查问题。"
fi
echo -e "${BLUE}========================================${NC}"
