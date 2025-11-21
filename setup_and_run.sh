#!/bin/bash
# 自动修复 Windows 换行符
sed -i 's/\r$//' "$0" 2>/dev/null || true

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"

# === 👇 请确认您的域名 ===
MY_DOMAIN="yk-pico-project.site"
# =========================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI (永久域名版) 启动中...${NC}"

# --- 0. 自动更新 (已找回!) ---
echo -e "🔄 检查 GitHub 更新..."
# 强制丢弃本地修改，以 GitHub 为准，确保代码最新
git fetch --all > /dev/null 2>&1
if git reset --hard origin/main > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 代码已同步到最新${NC}"
else
    echo -e "${RED}⚠️ 更新失败，使用当前版本继续${NC}"
fi

# --- 1. 环境检查 ---
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# 确保依赖最新
pip install -r requirements.txt -q 2>/dev/null || true

# 确保 cloudflared 存在
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 下载 Cloudflared..."
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# --- 2. 自动配置永久隧道 ---
TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -z "$TUNNEL_CRED" ]; then
    echo -e "${RED}❌ 未找到隧道凭证！请先运行 'cloudflared tunnel create pico' 并确保成功${NC}"
    exit 1
fi
TUNNEL_ID=$(basename "$TUNNEL_CRED" .json)

# 动态生成配置文件
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

# 后台启动 Gunicorn
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

# 检查启动状态
sleep 5
if ! pgrep -f gunicorn > /dev/null; then 
    echo -e "${RED}❌ Gunicorn 启动失败!${NC}"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

echo -e "🌐 启动永久隧道..."
# 使用配置文件启动
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

# --- 4. 成功提示 ---
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Pico 已上线！${NC}"
echo -e "\n    👉 https://${MY_DOMAIN}/pico\n"
echo -e "💡 提示：\n1. 此网址永久有效。\n2. 每次运行此脚本都会拉取最新代码。\n3. 管理员请使用 /管理员 激活权限。"
echo -e "${BLUE}========================================${NC}"
