#!/bin/bash
# =======================================================================
# Pico AI 自动化启动脚本
# 流程：强制同步 -> 自动清洗格式 -> 启动服务
# =======================================================================

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
MY_DOMAIN="yk-pico-project.site"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🤖 Pico AI 正在启动...${NC}"

# --- 1. 停止旧进程 ---
echo -e "${YELLOW}🔄 清理旧进程...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
sleep 1

# --- 2. 强制同步 GitHub 代码 (解决冲突) ---
echo -e "${YELLOW}⬇️ 正在从 GitHub 强制拉取最新代码...${NC}"
git fetch --all
# 强制重置本地代码，丢弃本地修改，以远程为准
git reset --hard origin/main
git pull

# --- 3. [核心] 自动格式清洗 (这就是您要的自动写) ---
# 拉取完代码后，立刻把所有文件的 Windows 换行符干掉
echo -e "${YELLOW}🧹 正在自动清洗文件格式...${NC}"
find . -type f \( -name "*.py" -o -name "*.txt" -o -name "*.html" -o -name "*.sh" -o -name "*.json" \) -exec sed -i 's/\r$//' {} +
chmod +x setup_and_run.sh # 确保自己下次还能跑

# --- 4. 激活环境与依赖 ---
if [ -d "$VENV_DIR" ]; then
    sed -i 's/\r$//' "$VENV_DIR/bin/activate" # 顺手修一下 activate
    source "$VENV_DIR/bin/activate"
else
    echo -e "${RED}❌ 虚拟环境未找到！${NC}"
    exit 1
fi

echo -e "${YELLOW}📦 检查依赖更新...${NC}"
pip install -r requirements.txt --quiet

# --- 5. 启动 Cloudflare ---
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
else
    echo -e "${RED}⚠️ 无法启动隧道 (缺凭证)${NC}"
fi

# --- 6. 启动后端 ---
echo -e "🚀 启动 Gunicorn..."
chmod +x "$VENV_DIR/bin/gunicorn"
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &

echo -e "${GREEN}✅ 服务已启动！请访问: https://${MY_DOMAIN}/pico${NC}"
