#!/bin/bash
# =======================================================================
# Pico AI 启动脚本 (GitHub 强制同步版)
# 核心逻辑：本地有任何修改都丢弃 -> 强制拉取 GitHub -> 启动
# =======================================================================

# --- 0. 格式自愈 ---
# 防止 Windows 换行符报错
current_file="$0"
sed -i 's/\r$//' "$current_file" 2>/dev/null
find . -maxdepth 3 -type f \( -name "*.py" -o -name "*.txt" -o -name "*.html" -o -name "*.sh" \) -exec sed -i 's/\r$//' {} +

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
echo -e "${GREEN}🤖 Pico AI 启动中 (GitHub 托管模式)${NC}"

# --- 1. 清理旧进程 ---
echo -e "${YELLOW}🔄 清理旧进程...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
sleep 1

# --- 2. 激活环境 ---
if [ -d "$VENV_DIR" ]; then
    sed -i 's/\r$//' "$VENV_DIR/bin/activate"
    source "$VENV_DIR/bin/activate"
else
    echo -e "${RED}❌ 错误：未找到虚拟环境。${NC}"
    exit 1
fi

# --- 3. 强制同步代码 (关键修改) ---
echo -e "${YELLOW}⬇️ 正在强制同步 GitHub 代码...${NC}"

# 获取远程最新状态
git fetch --all

# [粗暴模式]：强制重置本地代码到远程状态，丢弃本地所有修改
# 这能解决 "error: Your local changes... would be overwritten by merge"
git reset --hard origin/main

# 再次拉取确保万无一失
git pull

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ 代码已强制同步至最新。${NC}"
else
    echo -e "${RED}⚠️ 同步失败 (请检查网络)，将尝试运行现有代码...${NC}"
fi

# --- 4. 依赖检查 ---
# 既然代码变了，依赖可能也变了，静默检查一下
pip install -r requirements.txt --quiet

# --- 5. 启动服务 ---
echo "--- Session $(date) ---" >> "$LOG_FILE"

# 生成隧道配置
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
fi

echo -e "🚀 启动后端..."
chmod +x "$VENV_DIR/bin/gunicorn"
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &
echo -e "${GREEN}✅ 后端运行中 (Port 5000)${NC}"

if [ -f "$CDIR/cloudflared" ] && [ -n "$TUNNEL_CRED" ]; then
    echo -e "🚇 启动隧道..."
    nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &
    echo -e "${GREEN}✅ 隧道公网地址: https://${MY_DOMAIN}/pico${NC}"
else
    echo -e "${RED}⚠️ 隧道启动失败。${NC}"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}日志: ${LOG_FILE}${NC}"
