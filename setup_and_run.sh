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
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI (永久域名版) 启动中...${NC}"

# --- 0. 智能自动更新 (已找回!) ---
echo -e "🔄 检查 GitHub 更新..."
# 使用 --rebase --autostash：
# 这会自动“保护”您手动粘贴的代码，拉取更新后，再把您的代码应用上去。
if git pull --rebase --autostash; then
    echo -e "${GREEN}✅ 代码同步完成${NC}"
else
    echo -e "${YELLOW}⚠️ 自动更新遇到冲突，保留您当前的本地代码继续启动。${NC}"
    # 如果更新失败，取消变基，防止仓库损坏
    git rebase --abort 2>/dev/null
fi

# --- 1. 环境检查 ---
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# 确保依赖安装
pip install -r requirements.txt -q 2>/dev/null || true

# 确保 cloudflared 存在
if [ ! -f "$CDIR/cloudflared" ]; then
    echo "🌐 下载 Cloudflared..."
    ARCH=$(dpkg --print-architecture)
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    if [[ "$ARCH" == "armhf" ]]; then URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"; fi
    wget -q -O cf.deb "$URL" && dpkg-deb -x cf.deb tmp && mv tmp/usr/local/bin/cloudflared "$CDIR/" && rm -rf cf.deb tmp && chmod +x "$CDIR/cloudflared"
fi

# --- 2. 自动配置隧道 ---
TUNNEL_CRED=$(find ~/.cloudflared -name "*.json" | head -n 1)
if [ -z "$TUNNEL_CRED" ]; then
    echo -e "${RED}❌ 未找到隧道凭证！请先运行 'cloudflared tunnel create pico'${NC}"
    exit 1
fi
TUNNEL_ID=$(basename "$TUNNEL_CRED" .json)

# 生成配置文件
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
    echo "👇 错误日志 👇"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

echo -e "🌐 启动永久隧道..."
nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &

# --- 4. 成功提示 ---
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Pico 已在永久地址上线！${NC}"
echo -e "\n    👉 https://${MY_DOMAIN}/pico\n"
echo -e "💡 提示：此网址永久有效。"
echo -e "${BLUE}========================================${NC}"
