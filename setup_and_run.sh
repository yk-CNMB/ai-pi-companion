#!/bin/bash
# =======================================================================
# 核心功能启动脚本 (Git Pull 恢复版)
# 职责：自动修复格式 -> 停止旧进程 -> 激活环境 -> 拉取代码 -> 启动服务
# =======================================================================

# --- 0. 格式自愈 (防止 Windows \r 报错) ---
current_file="$0"
sed -i 's/\r$//' "$current_file" 2>/dev/null
# 修复核心文件格式
find . -maxdepth 2 -type f \( -name "*.py" -o -name "*.txt" -o -name "*.html" \) -exec sed -i 's/\r$//' {} +

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
echo -e "${GREEN}🤖 Pico AI 启动中...${NC}"

# --- 1. 强制杀死旧进程 ---
echo -e "${YELLOW}🔄 正在停止旧进程...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
sleep 1
echo -e "${GREEN}✅ 旧进程已清理。${NC}"

# --- 2. 虚拟环境激活 ---
if [ -d "$VENV_DIR" ]; then
    # 修复 activate 脚本格式
    sed -i 's/\r$//' "$VENV_DIR/bin/activate"
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}✅ 虚拟环境已激活。${NC}"
else
    echo -e "${RED}❌ 错误：未找到虚拟环境 ${VENV_DIR}。${NC}"
    exit 1
fi

# --- 3. 强制代码同步 (已恢复) ---
# 既然您在 GitHub 上更新，这里必须执行拉取
echo -e "${YELLOW}⬇️ 正在从 GitHub 拉取最新代码...${NC}"
git pull
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ 代码同步完成。${NC}"
else
    echo -e "${RED}⚠️ 代码拉取遇到问题 (可能是本地有冲突)，尝试继续启动...${NC}"
fi

# --- 4. Cloudflare 隧道配置 ---
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
    echo -e "${RED}❌ Cloudflare 凭证未找到。${NC}"
fi

# --- 5. 启动服务 ---
echo "--- Session $(date) ---" >> "$LOG_FILE"

echo -e "🚀 启动后端 Gunicorn..."
chmod +x "$VENV_DIR/bin/gunicorn"
# 使用 gthread 模式以支持 Edge-TTS 的异步操作
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &
echo -e "${GREEN}✅ 后端已启动 (Port 5000)${NC}"

if [ -f "$CDIR/cloudflared" ] && [ -n "$TUNNEL_CRED" ]; then
    echo -e "🚇 启动 Cloudflare 隧道..."
    nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &
    echo -e "${GREEN}✅ 隧道已启动！访问: https://${MY_DOMAIN}/pico${NC}"
else
    echo -e "${RED}⚠️ Cloudflare 启动失败。${NC}"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}日志文件: ${LOG_FILE}${NC}"
