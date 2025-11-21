#!/bin/bash
# 最终版 - 永久域名支持
# 自动修复换行符
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"

# === 👇 在这里填你的域名 ===
MY_DOMAIN="yk-pico-project.site"
# =========================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI (永久域名版) 启动中...${NC}"

# --- 1. 环境与更新 ---
echo "🔄 检查环境..."
if [ ! -d "$VENV_DIR" ]; then 
    echo "📦 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# 确保 cloudflared 存在
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 正在下载 Cloudflared..."
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# --- 2. 自动配置永久隧道 ---
# 查找刚才创建的隧道 UUID (凭证文件)
TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -z "$TUNNEL_CRED" ]; then
    echo -e "${RED}❌ 未找到隧道凭证！请确保你已经运行了 'cloudflared tunnel create pico'${NC}"
    exit 1
fi
TUNNEL_ID=$(basename "$TUNNEL_CRED" .json)

echo "⚙️ 生成隧道配置..."
# 生成配置文件，告诉隧道把流量转发到本地 5000 端口
cat > "$CDIR/tunnel_config.yml" <<YAML
tunnel: $TUNNEL_ID
credentials-file: $TUNNEL_CRED
ingress:
  - hostname: $MY_DOMAIN
    service: http://localhost:5000
  - service: http_status:404
YAML

# --- 3. 启动服务 ---
echo -e "🧠 重启 AI 大脑..."
pkill -9 -f gunicorn
pkill -9 -f cloudflared
sleep 1
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &
sleep 5
if ! pgrep -f gunicorn > /dev/null; then echo -e "${RED}❌ Gunicorn 启动失败!${NC}"; cat "$LOG_FILE"; exit 1; fi

echo -e "🌐 启动永久隧道..."
# 使用配置文件启动，不再是临时 URL
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

# --- 4. 成功提示 ---
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Pico 已在永久地址上线！${NC}"
echo -e "\n    👉 https://${MY_DOMAIN}/pico\n"
echo -e "💡 提示：此网址永久有效，不受重启影响。"
echo -e "${BLUE}========================================${NC}"
