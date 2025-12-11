#!/bin/bash
# 自我修复 Windows 换行符
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
MY_DOMAIN="yk-pico-project.site"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI (最终修复版) 启动中...${NC}"

# --- 0. 网络与 DNS 智能优化 ---
echo -e "🌐 正在检测网络环境..."
if ping -c 1 -W 2 8.8.8.8 > /dev/null 2>&1; then
    echo -e "${GREEN}🌍 国际网络：使用 Google DNS${NC}"
    if [ ! -f /etc/resolv.conf.bak ]; then sudo cp /etc/resolv.conf /etc/resolv.conf.bak; fi
    sudo bash -c 'echo -e "nameserver 8.8.8.8\nnameserver 1.1.1.1" > /etc/resolv.conf'
else
    echo -e "${BLUE}🇨🇳 国内网络：使用阿里/腾讯 DNS${NC}"
    if [ ! -f /etc/resolv.conf.bak ]; then sudo cp /etc/resolv.conf /etc/resolv.conf.bak; fi
    sudo bash -c 'echo -e "nameserver 223.5.5.5\nnameserver 119.29.29.29" > /etc/resolv.conf'
fi

# --- 1. 强制系统依赖修复 (关键步骤) ---
# 很多 crash 是因为缺这个。尝试静默安装，如果没权限会跳过并提示。
echo "🔧 检查关键系统音频库..."
if ! dpkg -s libsndfile1 >/dev/null 2>&1; then
    echo -e "${BLUE}📦 正在安装 libsndfile1 和 ffmpeg...${NC}"
    sudo apt update -qq && sudo apt install libsndfile1 ffmpeg -y
fi

# --- 2. 代码同步 ---
echo -e "🔄 从 GitHub 拉取最新代码..."
git fetch --all > /dev/null 2>&1
if git reset --hard origin/main > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 代码已同步到最新${NC}"
    find . -name "*.sh" -exec sed -i 's/\r$//' {} +
else
    echo -e "${RED}⚠️ 网络波动，使用本地代码${NC}"
fi

# --- 3. Python 环境 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

# 确保 pip 最新并安装依赖
pip install -r requirements.txt -q 2>/dev/null || true
# 二次确认关键包
pip install soundfile edge-tts gunicorn flask-socketio -q 2>/dev/null

# --- 4. Cloudflared 安装 ---
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "⬇️ 安装 Cloudflare Tunnel..."
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
    if [[ "$ARCH" == "arm64" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"; fi
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# --- 5. 生成隧道配置 (强制 IPv4 + HTTP2) ---
TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -n "$TUNNEL_CRED" ]; then
    TUNNEL_ID=$(basename "$TUNNEL_CRED" .json)
    # 关键修改：service 指向 127.0.0.1 而不是 localhost，防止 IPv6 歧义
    cat > "$CDIR/tunnel_config.yml" <<YAML
tunnel: $TUNNEL_ID
credentials-file: $TUNNEL_CRED
protocol: http2
ingress:
  - hostname: $MY_DOMAIN
    service: http://127.0.0.1:5000
  - service: http_status:404
YAML
fi

# --- 6. 启动服务 ---
echo -e "🧹 清理旧进程..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
if command -v fuser &> /dev/null; then fuser -k 5000/tcp > /dev/null 2>&1; fi
sleep 2

echo "--- Session $(date) ---" > "$LOG_FILE"

echo -e "🚀 启动后端服务..."
# 增加线程数，确保并发处理能力
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

# 真实的健康检查 (等待 8 秒再看死没死)
echo -e "⏳ 等待服务启动 (8s)..."
sleep 8

if ! pgrep -f gunicorn > /dev/null; then
    echo -e "${RED}❌ 致命错误：后端启动失败！${NC}"
    echo -e "${RED}👇 下面是错误日志 (最后 15 行):${NC}"
    echo "----------------------------------------"
    tail -n 15 "$LOG_FILE"
    echo "----------------------------------------"
    echo -e "💡 提示：如果是 OSError: sndfile library not found，请手动运行: sudo apt install libsndfile1"
    exit 1
fi

echo -e "🚇 启动隧道..."
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

echo -e "${GREEN}✅ 服务已稳定运行！${NC}"
echo -e "👉 访问地址: https://${MY_DOMAIN}/pico"
echo -e "${BLUE}日志监控: tail -f server.log${NC}"
