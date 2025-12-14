#!/bin/bash
# =======================================================================
# Pico AI 启动脚本 (最终全自动版)
# =======================================================================

# 0. 自愈
sed -i 's/\r$//' "$0" 2>/dev/null

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
MY_DOMAIN="yk-pico-project.site"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🤖 Pico AI 启动程序...${NC}"

# 1. 停止
echo -e "${YELLOW}🔄 清理旧进程...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
sleep 1

# 2. 同步 (解决冲突的核心)
echo -e "${YELLOW}⬇️ 拉取最新代码...${NC}"
# 防止文件格式被转为 Windows
git config --global core.autocrlf input
# 强制覆盖本地修改
git fetch --all
git reset --hard origin/main
git pull

# 3. 清洗
echo -e "${YELLOW}🧹 清洗格式...${NC}"
find . -type f \( -name "*.py" -o -name "*.txt" -o -name "*.html" -o -name "*.sh" -o -name "*.json" \) -exec sed -i 's/\r$//' {} +
chmod +x setup_and_run.sh

# 4. 激活
if [ -d "$VENV_DIR" ]; then
    sed -i 's/\r$//' "$VENV_DIR/bin/activate"
    source "$VENV_DIR/bin/activate"
else
    echo -e "${RED}❌ 虚拟环境未找到！${NC}"
    exit 1
fi

echo -e "${YELLOW}📦 检查依赖...${NC}"
pip install -r requirements.txt --quiet

# 5. 启动隧道
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

# 6. 启动后端
echo -e "🚀 启动 Gunicorn..."
chmod +x "$VENV_DIR/bin/gunicorn"
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

echo -e "${GREEN}✅ 启动成功！访问: https://${MY_DOMAIN}/pico${NC}"
echo -e "${BLUE}日志: tail -f ${LOG_FILE}${NC}"
