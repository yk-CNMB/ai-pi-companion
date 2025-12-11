#!/bin/bash
# 自我修复 Windows 换行符
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
# 这里填您的域名
MY_DOMAIN="yk-pico-project.site"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI (全球通用自适应版) 启动中...${NC}"

# --- 0. 智能网络环境检测 ---
echo -e "🌐 正在检测地理位置与网络环境..."

# 尝试 Ping 谷歌 DNS (超时设置 2秒)
if ping -c 1 -W 2 8.8.8.8 > /dev/null 2>&1; then
    echo -e "${GREEN}🌍 识别为：国际网络 (德国/海外)${NC}"
    echo -e "👉 自动优化：切换至 Google(8.8.8.8) + Cloudflare(1.1.1.1) DNS"
    
    if [ ! -f /etc/resolv.conf.bak ]; then sudo cp /etc/resolv.conf /etc/resolv.conf.bak; fi
    # 写入国际 DNS
    sudo bash -c 'echo -e "nameserver 8.8.8.8\nnameserver 1.1.1.1" > /etc/resolv.conf'
else
    echo -e "${RED}🇨🇳 识别为：国内网络 (中国)${NC}"
    echo -e "👉 自动优化：切换至 阿里(223.5.5.5) + 腾讯(119.29.29.29) DNS"
    
    if [ ! -f /etc/resolv.conf.bak ]; then sudo cp /etc/resolv.conf /etc/resolv.conf.bak; fi
    # 写入国内 DNS
    sudo bash -c 'echo -e "nameserver 223.5.5.5\nnameserver 119.29.29.29" > /etc/resolv.conf'
fi

# --- 1. 代码同步 ---
echo -e "🔄 从 GitHub 拉取最新代码..."
git fetch --all > /dev/null 2>&1
if git reset --hard origin/main > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 代码已同步到最新${NC}"
    find . -name "*.sh" -exec sed -i 's/\r$//' {} +
else
    echo -e "${RED}⚠️ 更新失败 (网络波动)，将使用本地代码${NC}"
fi

# --- 2. 环境安装 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

echo "📦 检查依赖库..."
pip install -r requirements.txt > /dev/null 2>&1
# 再次确保 Pillow 存在
if ! python3 -c "import PIL" 2>/dev/null; then
    echo "📦 补装 Pillow..."
    pip install Pillow > /dev/null
fi

# --- 3. Cloudflare 隧道 (全球强制 HTTP2) ---
if ! command -v cloudflared &> /dev/null; then
    echo "⬇️ 安装 Cloudflare Tunnel..."
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
    if [[ "$ARCH" == "arm64" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"; fi
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# 生成配置文件 (HTTP2 协议在全球都很稳)
TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -n "$TUNNEL_CRED" ]; then
    TUNNEL_ID=$(basename "$TUNNEL_CRED" .json)
    echo "🔧 生成隧道配置 (HTTP2 协议)..."
    cat > "$CDIR/tunnel_config.yml" <<YAML
tunnel: $TUNNEL_ID
credentials-file: $TUNNEL_CRED
protocol: http2  # 无论在哪里，TCP(http2) 都比 UDP(quic) 更不容易断流
ingress:
  - hostname: $MY_DOMAIN
    service: http://localhost:5000
  - service: http_status:404
YAML
fi

# --- 4. 启动服务 ---
echo -e "🧹 清理旧进程..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
if command -v fuser &> /dev/null; then fuser -k 5000/tcp > /dev/null 2>&1; fi
sleep 2

echo "--- Session $(date) ---" >> "$LOG_FILE"

echo -e "🚀 启动 Gunicorn 后端..."
gunicorn -k gevent -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

echo -e "🚇 启动 Cloudflare 隧道..."
if [ -f "$CDIR/tunnel_config.yml" ]; then
    cloudflared tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &
    echo -e "${GREEN}✅ 服务已启动! 访问地址: https://$MY_DOMAIN ${NC}"
else
    # 临时隧道兜底
    cloudflared tunnel --url http://localhost:5000 --protocol http2 >> "$LOG_FILE" 2>&1 &
    echo -e "${GREEN}⚠️ 使用临时随机域名 (请查看日志获取 URL)${NC}"
fi

echo -e "${BLUE}正在后台运行... 查看日志请用: tail -f server.log${NC}"
