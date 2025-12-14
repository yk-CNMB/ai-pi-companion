#!/bin/bash
# =======================================================================
# Pico AI 启动脚本 (健康检查版)
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
sleep 2 # 给多一点时间释放端口

# 2. 同步 (保留您的工作流)
echo -e "${YELLOW}⬇️ 拉取代码...${NC}"
git config --global core.autocrlf input
git fetch --all
git reset --hard origin/main
git pull

# 3. 清洗
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

echo -e "${YELLOW}📦 强制安装依赖 (防止缺包)...${NC}"
pip install -r requirements.txt

# 5. 启动后端 (带健康检查)
echo -e "🚀 启动 Gunicorn..."
chmod +x "$VENV_DIR/bin/gunicorn"
# 清空旧日志以便观察
> "$LOG_FILE"
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

# ★★★ 等待并检查 ★★★
echo -e "${YELLOW}⏳ 等待后端启动 (5秒)...${NC}"
sleep 5

# 检查 5000 端口是否被监听
if netstat -tuln | grep ":5000 " > /dev/null; then
    echo -e "${GREEN}✅ 后端启动成功！${NC}"
else
    echo -e "${RED}❌ 后端启动失败！正在输出错误日志：${NC}"
    echo "---------------------------------------------------"
    cat "$LOG_FILE"
    echo "---------------------------------------------------"
    exit 1 # 终止脚本，不启动 Cloudflare
fi

# 6. 启动隧道
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
    echo -e "${GREEN}✅ 服务已全线开通！访问: https://${MY_DOMAIN}/pico${NC}"
else
    echo -e "${RED}⚠️ 隧道启动失败 (缺凭证)${NC}"
fi
