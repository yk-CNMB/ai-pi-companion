#!/bin/bash
# 自动修复当前脚本的 Windows 换行符 (自我修复)
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"

# === 👇 您的永久域名 ===
MY_DOMAIN="yk-pico-project.site"
# ======================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI (GitHub 同步启动) ...${NC}"

# --- 0. 强制同步 GitHub (核心) ---
echo -e "🔄 正在从 GitHub 强制拉取最新代码..."
# 获取最新元数据
git fetch --all > /dev/null 2>&1
# 强制重置本地代码，使其与 GitHub 完全一致 (丢弃本地修改)
if git reset --hard origin/main; then
    echo -e "${GREEN}✅ 代码已强制同步到最新 commit${NC}"
    # 同步后，再次确所有脚本没有 Windows 换行符
    find . -name "*.sh" -exec sed -i 's/\r$//' {} +
else
    echo -e "${RED}⚠️ 同步失败！请检查网络或 Git 配置。正在尝试使用现有代码启动...${NC}"
fi

# --- 1. 环境准备 ---
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# 确保安装原生线程模式需要的库
pip install flask flask-socketio python-socketio python-engineio google-genai edge-tts requests soundfile gunicorn -q 2>/dev/null || true

# 确保 Cloudflared 存在
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 下载 Cloudflared..."
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# --- 2. 隧道配置 ---
TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -z "$TUNNEL_CRED" ]; then
    echo -e "${RED}❌ 未找到隧道凭证！请先运行 'cloudflared tunnel create pico'${NC}"
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
echo -e "🧹 清理旧进程..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
# 确保端口释放
if command -v fuser &> /dev/null; then fuser -k 5000/tcp > /dev/null 2>&1; fi
sleep 2

echo "--- New Session $(date) ---" > "$LOG_FILE"

echo -e "🧠 启动 AI 大脑 (Gunicorn gthread)..."
# 【关键】使用 gthread 模式，兼容 Python 3.13
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

sleep 5
if ! pgrep -f gunicorn > /dev/null; then
    echo -e "${RED}❌ Gunicorn 启动失败!${NC}"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

echo -e "🌐 启动永久隧道..."
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

echo -e "${GREEN}✅ 启动成功！${NC}"
echo -e "👉 https://${MY_DOMAIN}/pico"
echo -e "${YELLOW}👀 正在监控日志 (Ctrl+C 退出监控)...${NC}"

tail -f "$LOG_FILE"
