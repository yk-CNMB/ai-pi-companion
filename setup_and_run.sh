#!/bin/bash

# ============================================
# Pico AI 全能管家脚本
# 功能：环境安装、依赖更新、一键启动
# ============================================

# 定义颜色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# 获取脚本所在目录
CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 欢迎使用 Pico AI 全能管家${NC}"
echo -e "${BLUE}========================================${NC}"

# --- 阶段 1: 环境检查与安装 ---

# 1.1 检查 Python 虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    echo -e "📦 正在创建 Python 虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

# 1.2 激活虚拟环境
source "$VENV_DIR/bin/activate"

# 1.3 安装/更新依赖 (每次都检查一下，确保是最新版)
echo -e "📦 正在检查依赖库..."
# 临时创建一个 requirements.txt，包含所有需要的库
cat > "$CDIR/requirements.txt" <<EOF
flask
flask-socketio
python-socketio
python-engineio
google-genai
edge-tts
eventlet
gunicorn
EOF
pip install -r "$CDIR/requirements.txt" | grep -v "Requirement already satisfied"

# 1.4 检查 Cloudflared
if [ ! -f "$CDIR/cloudflared" ]; then
    echo -e "🌐 未检测到 Cloudflared，正在下载..."
    # 自动判断架构 (arm64 或 armhf/32位)
    ARCH=$(dpkg --print-architecture)
    if [ "$ARCH" == "arm64" ]; then
        wget -O cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
    else
        wget -O cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb
    fi
    # 解压出二进制文件，不进行系统级安装，保持绿色环保
    dpkg-deb -x cloudflared.deb temp_cf
    mv temp_cf/usr/local/bin/cloudflared "$CDIR/"
    rm -rf cloudflared.deb temp_cf
    chmod +x "$CDIR/cloudflared"
    echo -e "${GREEN}✅ Cloudflared 下载完成！${NC}"
fi

# --- 阶段 2: 启动服务 ---

echo -e "\n${BLUE}--- 🚀 准备启动 ---${NC}"

# 2.1 清理旧进程
pkill -f "gunicorn.*app:app"
pkill -f "$CDIR/cloudflared tunnel"

# 2.2 启动 Gunicorn (AI 大脑)
echo -e "🧠 正在启动 AI 大脑..."
"$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app --daemon

# 等待 Gunicorn 启动
for i in {1..5}; do
    if pgrep -f "gunicorn.*app:app" > /dev/null; then
        echo -e "${GREEN}✅ AI 大脑启动成功！${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 5 ]; then
        echo -e "${RED}❌ AI 大脑启动失败！请手动检查 'gunicorn app:app' 命令。${NC}"
        exit 1
    fi
done

# 2.3 启动 Cloudflare 隧道
echo -e "${GREEN}🌐 正在建立公网隧道... 请稍等片刻...${NC}"
echo -e "${BLUE}👇 复制下方出现的 trycloudflare.com 网址即可访问 👇${NC}"
echo -e "${BLUE}========================================${NC}"

# 启动隧道并实时过滤日志，只显示网址
"$CDIR/cloudflared" tunnel --url http://localhost:5000 2>&1 | grep --line-buffered "trycloudflare.com"

# 脚本到这里会一直运行，直到你按 Ctrl+C
# 当你按 Ctrl+C 时，cloudflared 会停止，但后台的 Gunicorn 还在。
# 下次运行脚本时会自动清理旧的 Gunicorn。
```

---

### 🚀 如何使用新版管家

非常简单，以后你无论什么时候想玩 Pico，只需要做一件事：

```bash
./setup_and_run.sh
