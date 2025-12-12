#!/bin/bash
# =======================================================================
# Pico AI 启动脚本 (全自动托管版)
# 1. 自动修复 Windows 换行符
# 2. 自动从 Git 拉取最新代码
# 3. 自动启动服务
# =======================================================================

# --- [自愈模块] 自动修复格式错误 (\r command not found) ---
# $0 是脚本自己的名字。这行命令会让脚本在运行时"自己修自己"
current_file="$0"
sed -i 's/\r$//' "$current_file" 2>/dev/null

# 顺手把目录下的 python, html, txt 文件也修一遍，防止报错
find . -maxdepth 3 -type f \( -name "*.py" -o -name "*.txt" -o -name "*.html" -o -name "*.sh" \) -exec sed -i 's/\r$//' {} +

# --- [环境配置] ---
CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"
LOG_FILE="$CDIR/server.log"
MY_DOMAIN="yk-pico-project.site"

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 Pico AI 智能启动程序${NC}"

# --- 1. 清理旧进程 ---
echo -e "${YELLOW}🔄 正在清理旧进程...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
sleep 1
echo -e "${GREEN}✅ 进程清理完毕。${NC}"

# --- 2. 激活虚拟环境 ---
if [ -d "$VENV_DIR" ]; then
    # 修复 activate 脚本可能的格式问题
    sed -i 's/\r$//' "$VENV_DIR/bin/activate"
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}✅ 虚拟环境已激活。${NC}"
else
    echo -e "${RED}❌ 致命错误：未找到虚拟环境 ${VENV_DIR}。请检查安装。${NC}"
    exit 1
fi

# --- 3. 同步代码 (Git Pull) ---
echo -e "${YELLOW}⬇️ 正在检查代码更新 (Git Pull)...${NC}"
git pull
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ 代码已同步至最新。${NC}"
else
    echo -e "${RED}⚠️ 代码同步失败 (可能是网络问题或本地冲突)，尝试继续使用当前版本启动...${NC}"
fi

# --- 4. 安装/更新依赖 ---
# 这一步是为了防止 requirements.txt 有变动但环境没更新
echo -e "${YELLOW}📦 检查依赖更新...${NC}"
pip install -r requirements.txt --quiet
echo -e "${GREEN}✅ 依赖检查完成。${NC}"

# --- 5. 启动服务 ---
echo "--- Session $(date) ---" >> "$LOG_FILE"

# 生成 Cloudflare 配置文件 (如果不存在)
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

echo -e "🚀 正在启动后端服务..."
# 确保 gunicorn 可执行
chmod +x "$VENV_DIR/bin/gunicorn"
# 后台启动 Gunicorn
nohup "$VENV_DIR/bin/gunicorn" --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:5000 app:app >> "$LOG_FILE" 2>&1 &
echo -e "${GREEN}✅ 后端服务已在端口 5000 启动。${NC}"

# 启动 Cloudflare 隧道
if [ -f "$CDIR/cloudflared" ] && [ -n "$TUNNEL_CRED" ]; then
    echo -e "🚇 正在建立 Cloudflare 隧道..."
    nohup "$CDIR/cloudflared" tunnel --config "$CDIR/tunnel_config.yml" run >> "$LOG_FILE" 2>&1 &
    echo -e "${GREEN}✅ 隧道已启动！公网地址: https://${MY_DOMAIN}/pico${NC}"
else
    echo -e "${RED}⚠️ Cloudflare 启动失败 (缺少文件或凭证)，仅本地访问可用。${NC}"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}详细日志请查看: ${LOG_FILE}${NC}"
