#!/bin/bash
# =======================================================================
# Pico AI 启动脚本 (自动清洗版)
# 核心逻辑：拉取代码 -> 暴力清洗所有文件格式 -> 启动
# =======================================================================

# --- 0. 启动时尝试自愈 ---
# 尽最大努力修复自己，防止运行中途报错
sed -i 's/\r$//' "$0" 2>/dev/null

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
MY_DOMAIN="yk-pico-project.site"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🤖 Pico AI 启动程序...${NC}"

# --- 1. 清理旧进程 ---
echo -e "${YELLOW}🔄 清理旧进程...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
sleep 1

# --- 2. 强制同步 GitHub ---
echo -e "${YELLOW}⬇️ 正在拉取 GitHub 最新代码...${NC}"
git fetch --all
git reset --hard origin/main
git pull

# --- 3. [关键] 暴力清洗格式 (自动 Sed) ---
# 拉取完后，不管文件是不是坏的，全部强制转为 Linux 格式
# 排除 .git 和 .venv 目录，只处理代码文件
echo -e "${YELLOW}🧹 正在自动清洗所有文件的换行符...${NC}"
find . -path ./.git -prune -o -path ./.venv -prune -o -type f \( -name "*.py" -o -name "*.sh" -o -name "*.html" -o -name "*.txt" -o -name "*.json" \) -exec sed -i 's/\r$//' {} +
echo -e "${GREEN}✅ 格式清洗完成。${NC}"

# 再次确保脚本本身可执行
chmod +x "$0"

# --- 4. 激活环境 ---
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
else
    echo -e "${RED}❌ 虚拟环境未找到！${NC}"
    exit 1
fi

# --- 5. 依赖更新 ---
echo -e "${YELLOW}📦 检查依赖...${NC}"
pip install -r requirements.txt --quiet

# --- 6. 启动服务 ---
echo "--- Session $(date) ---" >> "$LOG_FILE"

# Cloudflare
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
    echo -e "🚇 启动隧道..."
    nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &
fi

# 后端
echo -e "🚀 启动 Gunicorn..."
chmod +x "$VENV_DIR/bin/gunicorn"
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

echo -e "${GREEN}✅ 服务已启动！访问: https://${MY_DOMAIN}/pico${NC}"
echo -e "${BLUE}日志: tail -f ${LOG_FILE}${NC}"
