#!/bin/bash
# 自我修复 Windows 换行符问题
sed -i 's/\r$//' "$0" || true

# 定义路径和颜色
CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$CDIR/.venv/bin"
LOG="$CDIR/gunicorn.log"
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🤖 正在启动 Pico AI...${NC}"

# 1. 清理旧进程
pkill -9 -f gunicorn
pkill -9 -f cloudflared
sleep 1

# 2. 启动 AI 大脑 (Gunicorn)
echo -n "🧠 启动 Gunicorn..."
# 使用 nohup 后台启动，并把日志写入文件
nohup "$VENV/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app > "$LOG" 2>&1 &
PID=$!
sleep 5

# 【关键】检查它是否还活着
if kill -0 $PID 2>/dev/null; then
    echo -e "${GREEN} [成功]${NC}"
else
    echo -e "${RED} [失败]${NC}"
    echo "👇👇👇 错误日志 👇👇👇"
    cat "$LOG"
    echo "👆👆👆 错误日志 👆👆👆"
    exit 1
fi

# 3. 启动公网隧道
echo -e "${GREEN}🌐 正在建立公网连接...${NC}"
echo -e "请耐心等待，复制下方出现的 trycloudflare.com 网址："
echo "========================================"
# 强制使用 IPv4 (127.0.0.1) 避免 502 错误
"$CDIR/cloudflared" tunnel --url http://127.0.0.1:5000 2>&1 | grep --line-buffered "trycloudflare.com"
