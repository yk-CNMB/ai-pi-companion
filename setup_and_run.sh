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
echo -e "${GREEN}🤖 Pico AI (离线 TTS 最终模式) 启动中...${NC}"

# --- 1. 虚拟环境 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

# --- 2. 强制安装系统依赖 (TTS 核心) ---
echo -e "${YELLOW}⚙️ 正在安装系统级 TTS 引擎和音频库 (eSpeak, libasound, portaudio)...${NC}"
# 安装 eSpeak (TTS 引擎) 和 libasound2-dev, portaudio19-dev (Pyaudio依赖)
sudo apt update -qq
sudo apt install espeak libasound2-dev portaudio19-dev -y -qq
echo -e "${GREEN}✅ 系统依赖安装完成。${NC}"

# --- 3. 强制安装 Python 依赖 (pyttsx3, pyaudio) ---
echo "📦 正在使用清华源强制安装 Python 依赖..."
PIP_CMD="pip install -i https://pypi.tuna.tsinghua.edu.cn/simple"

$PIP_CMD --upgrade pip -q
$PIP_CMD -r requirements.txt -q 
echo -e "${GREEN}✅ Python 依赖安装完成。${NC}"

# --- 4. Cloudflare 隧道 (确保存在) ---
if [ ! -f "$CDIR/cloudflared" ]; then
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
    if [[ "$ARCH" == "arm64" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"; fi
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -n "$TUNNEL_CRED" ]; then
    TUNNEL_ID=$(basename "$TUNNEL_CRED" .json)
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

# --- 5. 启动服务 ---
echo "--- Session $(date) ---" > "$LOG_FILE"

echo -e "🚀 启动后端..."
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

echo -e "🚇 启动隧道..."
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

echo -e "${GREEN}✅ 服务已启动！访问: https://${MY_DOMAIN}/pico${NC}"
