#!/bin/bash
# =======================================================================
# 核心功能启动脚本 (加强版)
# 职责：自动修复文件格式、清理旧进程、启动服务
# =======================================================================

# --- 0. 格式自愈 (关键修改) ---
# 自动移除所有项目文件的 Windows 换行符 (\r)，防止报错
# $0 代表脚本自己，所以它甚至会尝试修复自己
current_file="$0"
sed -i 's/\r$//' "$current_file" 2>/dev/null
# 修复核心代码文件
find . -type f \( -name "*.py" -o -name "*.txt" -o -name "*.html" -o -name "*.json" \) -exec sed -i 's/\r$//' {} +

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
echo -e "${GREEN}🤖 Pico AI (核心启动与同步) 启动中...${NC}"

# --- 1. 强制杀死旧进程 ---
echo -e "${YELLOW}🔄 正在停止旧进程...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
sleep 1
echo -e "${GREEN}✅ 旧进程已清理。${NC}"

# --- 2. 虚拟环境激活 ---
if [ -d "$VENV_DIR" ]; then
    # 临时修复 activate 脚本可能的格式问题
    sed -i 's/\r$//' "$VENV_DIR/bin/activate"
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}✅ 虚拟环境已激活。${NC}"
else
    echo -e "${RED}❌ 未找到虚拟环境，请检查安装。${NC}"
    exit 1
fi

# --- 3. 隧道配置 ---
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
else
    echo -e "${RED}❌ 未找到 Cloudflare 凭证，隧道将无法启动。${NC}"
fi

# --- 4. 启动服务 ---
echo "--- Session $(date) ---" >> "$LOG_FILE"
echo -e "🚀 启动后端..."

# 确保 gunicorn 也是可执行的
chmod +x "$VENV_DIR/bin/gunicorn"

nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &
echo -e "${GREEN}✅ 后端已启动 (Port 5000)${NC}"

if [ -f "$CDIR/cloudflared" ] && [ -n "$TUNNEL_CRED" ]; then
    echo -e "🚇 启动隧道..."
    nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &
    echo -e "${GREEN}✅ 隧道已建立: https://${MY_DOMAIN}/pico${NC}"
else
    echo -e "${RED}⚠️ 隧道未启动 (缺少 cloudflared 文件或凭证)${NC}"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}日志文件: ${LOG_FILE}${NC}"
