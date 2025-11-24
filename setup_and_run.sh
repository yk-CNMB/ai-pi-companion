#!/bin/bash
# 自动修复 Windows 换行符
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
echo -e "${GREEN}🤖 Pico AI (防堵塞启动) ...${NC}"

# --- 0. 自动更新 ---
echo -e "🔄 检查更新..."
git fetch --all > /dev/null 2>&1
if git reset --hard origin/main > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 代码已同步${NC}"
else
    echo -e "${RED}⚠️ 更新跳过${NC}"
fi

# --- 1. 环境准备 ---
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"
# 确保 fuser 工具存在
if ! command -v fuser &> /dev/null; then sudo apt-get install psmisc -y > /dev/null; fi

# --- 2. 强力清理 (核心修复) ---
echo -e "🧹 清理战场..."
# 1. 杀名字
pkill -9 -f gunicorn
pkill -9 -f cloudflared
# 2. 杀端口 (双重保险)
fuser -k 5000/tcp > /dev/null 2>&1
# 3. 等待释放
sleep 2

# --- 3. 启动服务 ---
echo -e "🧠 启动 AI 大脑..."
# 清空旧日志
echo "--- New Session $(date) ---" > "$LOG_FILE"

nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

# 严格检查启动状态
sleep 5
if ! pgrep -f gunicorn > /dev/null; then
    echo -e "${RED}❌ Gunicorn 启动失败! 端口可能仍被占用或代码有误。${NC}"
    echo "👇 最新错误日志 👇"
    tail -n 15 "$LOG_FILE"
    exit 1
fi

echo -e "🌐 启动永久隧道..."
# 确保 Cloudflared 存在
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "⚠️ Cloudflared 丢失，尝试重新下载..."
    # (简化的下载逻辑，防止卡住)
    wget -q -O cf.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# 检查隧道凭证
TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -z "$TUNNEL_CRED" ]; then
    echo -e "${RED}❌ 隧道凭证丢失！请重新运行 'cloudflared tunnel create pico'${NC}"
    exit 1
fi
TUNNEL_ID=$(basename "$TUNNEL_CRED" .json)

# 重写配置
cat > "$CDIR/tunnel_config.yml" <<YAML
tunnel: $TUNNEL_ID
credentials-file: $TUNNEL_CRED
ingress:
  - hostname: $MY_DOMAIN
    service: http://localhost:5000
  - service: http_status:404
YAML

nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

# --- 4. 成功提示 & 监控 ---
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ 启动成功！${NC}"
echo -e "👉 https://${MY_DOMAIN}/pico"
echo -e "${YELLOW}👀 进入日志监控 (Ctrl+C 退出)...${NC}"
echo -e "${BLUE}========================================${NC}"

tail -f "$LOG_FILE"
