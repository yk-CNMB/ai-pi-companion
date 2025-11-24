#!/bin/bash
# 最终智能版：保护你的修改 + 自动更新

# 1. 自动修复 Windows 换行符
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
MY_DOMAIN="yk-pico-project.site"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI 智能启动...${NC}"

# --- 0. 智能更新 (保护模式) ---
echo -e "🔄 正在同步代码..."

# 1. 先把你手动粘贴的代码“藏起来” (Stash)
if [[ -n $(git status -s) ]]; then
    echo -e "${YELLOW}⚠️ 检测到你有手动修改的文件，正在保护它们...${NC}"
    git stash save "User manual changes" > /dev/null 2>&1
    STASHED=1
else
    STASHED=0
fi

# 2. 拉取 GitHub 最新版
echo "⬇️ 拉取 GitHub 更新..."
git pull --rebase > /dev/null 2>&1

# 3. 把你的修改“放回去” (Pop)
if [ $STASHED -eq 1 ]; then
    echo -e "${GREEN}🛡️ 正在恢复你的手动修改...${NC}"
    git stash pop > /dev/null 2>&1
    echo -e "${GREEN}✅ 你的代码已生效 (覆盖了 GitHub 的旧版本)${NC}"
fi

# --- 1. 环境检查 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

# 依赖与工具检查
if ! dpkg -s libsndfile1 >/dev/null 2>&1; then sudo apt-get install libsndfile1 ffmpeg -y; fi
pip install -r requirements.txt -q 2>/dev/null || true

if [ ! -f "$CDIR/cloudflared" ]; then
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
echo -e "🧠 重启服务..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
if command -v fuser &> /dev/null; then fuser -k 5000/tcp > /dev/null 2>&1; fi
sleep 2

echo "--- Session $(date) ---" > "$LOG_FILE"

# 启动 Gunicorn (threading 模式)
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
echo -e "${YELLOW}👀 正在监控日志... (Ctrl+C 退出)${NC}"

tail -f "$LOG_FILE"
