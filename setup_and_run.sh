#!/bin/bash
# =======================================================================
# 核心功能启动脚本 (Final Version)
# 职责：杀死旧进程，激活环境，启动服务。
# 假设：所有 Python/系统依赖已在环境中安装完成。
# =======================================================================

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

# --- 1. 强制杀死旧进程 (解决 Address already in use) ---
echo -e "${YELLOW}🔄 正在停止所有旧的 Flask/Gunicorn 和 Cloudflare 进程...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
sleep 1 # 等待端口释放
echo -e "${GREEN}✅ 旧进程已清理。${NC}"


# --- 2. 虚拟环境激活 ---
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}✅ 虚拟环境已激活。${NC}"
else
    echo -e "${RED}❌ 错误：未找到虚拟环境 ${VENV_DIR}。请先手动运行 setup_and_run.sh。${NC}"
    exit 1
fi

# --- 3. 强制代码同步检查 ---
# 这一步保证 Gunicorn 加载的是最新的 app.py 文件。
echo -e "${YELLOW}🔄 准备同步并加载最新的 app.py 代码...${NC}"

# --- 4. Cloudflare 隧道配置检查 (仅用于启动) ---
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
    echo -e "${RED}❌ Cloudflare 凭证未找到。无法启动隧道。${NC}"
fi

# --- 5. 启动服务 ---
echo "--- Session $(date) ---" >> "$LOG_FILE"

echo -e "🚀 启动后端 Gunicorn..."
# 使用 nohup 异步启动 Gunicorn (它会加载最新的 app.py)
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &
echo -e "${GREEN}✅ Gunicorn 后端已在端口 5000 启动。${NC}"

# 启动隧道
if [ -f "$CDIR/cloudflared" ] && [ -n "$TUNNEL_CRED" ]; then
    echo -e "🚇 启动 Cloudflare 隧道..."
    nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &
    echo -e "${GREEN}✅ 隧道已启动！访问: https://${MY_DOMAIN}/pico${NC}"
else
    echo -e "${RED}⚠️ Cloudflare 启动失败，请检查 cloudflared 文件和凭证。${NC}"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}请检查 ${LOG_FILE} 获取详细日志。${NC}"
