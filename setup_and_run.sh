#!/bin/bash
# =======================================================================
# 核心功能启动脚本 (Final Restored Version)
# 职责：自动修复格式、清理进程、同步代码(可选)、启动服务
# =======================================================================

# --- 0. 格式自愈 (关键修复) ---
# 自动移除脚本自身和项目文件的 Windows 换行符 (\r)，解决 command not found 报错
current_file="$0"
sed -i 's/\r$//' "$current_file" 2>/dev/null
# 顺手修复一下目录下的其他核心文件
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
echo -e "${GREEN}🤖 Pico AI (核心启动与同步) 启动中...${NC}"

# --- 1. 强制杀死旧进程 ---
echo -e "${YELLOW}🔄 正在停止旧进程...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
sleep 1
echo -e "${GREEN}✅ 旧进程已清理。${NC}"

# --- 2. 虚拟环境激活 ---
if [ -d "$VENV_DIR" ]; then
    # 修复 activate 脚本格式（防止玄学报错）
    sed -i 's/\r$//' "$VENV_DIR/bin/activate"
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}✅ 虚拟环境已激活。${NC}"
else
    echo -e "${RED}❌ 错误：未找到虚拟环境 ${VENV_DIR}。${NC}"
    exit 1
fi

# --- 3. 强制代码同步检查 (已还原) ---
echo -e "${YELLOW}🔄 准备同步代码...${NC}"

# [警告]：如果您开启了下面的 git 命令，它会从远程仓库拉取代码。
# 这可能会覆盖掉我们刚才手动修改的 Edge-TTS 版 app.py！
# 建议先把现在的稳定版推送到远程，或者保持注释状态。

# git fetch --all
# git reset --hard origin/main  <-- 这就是您刚才想敲的重置命令
# git pull

echo -e "${GREEN}✅ 代码同步检查跳过 (防止覆盖本地 Edge-TTS 修复)。${NC}"

# --- 4. Cloudflare 隧道配置检查 ---
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
chmod +x "$VENV_DIR/bin/gunicorn"
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &
echo -e "${GREEN}✅ 后端已启动 (Port 5000)${NC}"

if [ -f "$CDIR/cloudflared" ] && [ -n "$TUNNEL_CRED" ]; then
    echo -e "🚇 启动 Cloudflare 隧道..."
    nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &
    echo -e "${GREEN}✅ 隧道已启动！访问: https://${MY_DOMAIN}/pico${NC}"
else
    echo -e "${RED}⚠️ Cloudflare 启动失败，请检查配置。${NC}"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}请检查 ${LOG_FILE} 获取详细日志。${NC}"
