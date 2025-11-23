#!/bin/bash
# 最终版：自动更新 + 自动修复 + 实时监控

# 1. 自我修复 Windows 换行符 (防止报错)
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
echo -e "${GREEN}🤖 Pico AI 正在启动...${NC}"

# --- 0. 核心：强制自动更新 ---
echo -e "🔄 正在从 GitHub 拉取最新代码..."
# 强制重置本地修改，确保与 GitHub 完全一致
git fetch --all > /dev/null 2>&1
if git reset --hard origin/main > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 代码已同步到最新版本${NC}"
else
    echo -e "${RED}⚠️ 更新失败 (可能是网络问题)，使用当前版本继续${NC}"
fi

# --- 1. 环境与依赖 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

# 自动补全可能缺失的音频库
if ! dpkg -s libsndfile1 >/dev/null 2>&1; then
    echo "🔧 安装系统音频驱动..."
    sudo apt-get update && sudo apt-get install libsndfile1 ffmpeg -y
fi
pip install soundfile edge-tts requests -q 2>/dev/null || true
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

# --- 3. 重启服务 ---
echo -e "🧠 重启服务..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
sleep 2

# 清空日志
echo "--- New Session $(date) ---" > "$LOG_FILE"

# 启动 Gunicorn
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

sleep 5
if ! pgrep -f gunicorn > /dev/null; then
    echo -e "${RED}❌ Gunicorn 启动失败!${NC}"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

# 启动隧道
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

# --- 4. 成功 & 监控 ---
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ 启动成功！已更新到最新代码。${NC}"
echo -e "👉 https://${MY_DOMAIN}/pico"
echo -e "${YELLOW}👀 进入日志监控模式 (按 Ctrl+C 退出监控)...${NC}"
echo -e "${BLUE}========================================${NC}"

# 实时显示日志
tail -f "$LOG_FILE"
