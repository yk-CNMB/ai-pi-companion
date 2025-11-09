#!/bin/bash

# ============================================
# Pico AI 全能管家脚本 (IPv4 强制修复版)
# ============================================

# 定义颜色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 获取当前脚本所在的绝对路径
CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 欢迎使用 Pico AI 全能管家${NC}"
echo -e "${BLUE}========================================${NC}"

# --- 阶段 0: 自动更新 ---
echo -e "🔄 正在检查 GitHub 更新..."
# 尝试拉取更新。如果本地有冲突，强制以远程为准进行覆盖。
git fetch --all
if git reset --hard origin/main; then
    echo -e "${GREEN}✅ 项目已强制同步到最新版本${NC}"
else
    echo -e "${RED}⚠️ 更新失败，将尝试使用当前版本启动。${NC}"
fi
echo -e "${BLUE}----------------------------------------${NC}"

# --- 阶段 1: 环境检查与安装 ---

# 1.1 检查并创建 Python 虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    echo -e "📦 未检测到虚拟环境，正在创建..."
    python3 -m venv "$VENV_DIR"
fi

# 1.2 激活虚拟环境
source "$VENV_DIR/bin/activate"

# 1.3 安装/更新依赖库
# 这里列出了所有需要的库，确保一个都不少
echo -e "📦 正在检查依赖库完整性..."
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
# 使用清华源加速下载，提高成功率
pip install -r "$CDIR/requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ 依赖库检查完毕${NC}"
else
    echo -e "${RED}❌ 依赖安装失败！请检查网络连接。${NC}"
    # 询问用户是否强行继续
    read -p "是否尝试强行启动? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 1.4 智能安装 Cloudflared
# 如果本地没有 cloudflared 文件，才去下载
if [ ! -f "$CDIR/cloudflared" ]; then
    echo -e "🌐 未检测到 Cloudflared，准备下载..."
    ARCH=$(dpkg --print-architecture)
    if [ "$ARCH" == "arm64" ]; then
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    elif [ "$ARCH" == "armhf" ]; then
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"
    else
        echo -e "${RED}❌ 不支持的架构: $ARCH${NC}"
        exit 1
    fi
    
    echo -e "⬇️ 正在下载..."
    wget -O cloudflared.deb "$URL"
    
    echo -e "📦 正在解压..."
    dpkg-deb -x cloudflared.deb temp_cf
    
    # 自动寻找解压后的二进制文件
    CF_BIN=$(find temp_cf -name cloudflared -type f | head -n 1)
    if [ -n "$CF_BIN" ]; then
        mv "$CF_BIN" "$CDIR/cloudflared"
        chmod +x "$CDIR/cloudflared"
        echo -e "${GREEN}✅ Cloudflared 安装成功！${NC}"
    else
        echo -e "${RED}❌ Cloudflared 安装失败：找不到文件${NC}"
        exit 1
    fi
    # 清理临时文件
    rm -rf cloudflared.deb temp_cf
fi

# --- 阶段 2: 启动服务 ---

echo -e "\n${BLUE}--- 🚀 准备启动 ---${NC}"

# 2.1 深度清理旧进程 (防止端口占用)
echo -e "🧹 正在清理旧进程..."
# 杀死所有相关的 Gunicorn 和 Cloudflared 进程
pkill -9 -f "gunicorn.*app:app"
pkill -9 -f "$CDIR/cloudflared tunnel"
# 等待 2 秒让操作系统回收端口
sleep 2

# 2.2 启动 Gunicorn (AI 大脑)
echo -e "🧠 正在启动 AI 大脑..."
# 使用 nohup 在后台运行，并将日志输出到文件以便排查错误
nohup "$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app > gunicorn.log 2>&1 &

# 循环检查 Gunicorn 是否成功启动
for i in {1..10}; do
    sleep 1
    # 检查 5000 端口是否被监听
    if ss -tuln | grep ":5000" > /dev/null; then
        echo -e "${GREEN}✅ AI 大脑启动成功！(端口 5000 已就绪)${NC}"
        break
    fi
    if [ $i -eq 10 ]; then
        echo -e "${RED}❌ AI 大脑启动超时！请查看 gunicorn.log 了解详情。${NC}"
        echo -e "最后的日志内容："
        tail -n 5 gunicorn.log
        exit 1
    fi
done

# 2.3 启动 Cloudflare 隧道
echo -e "${GREEN}🌐 正在建立公网隧道...${NC}"
echo -e "请耐心等待，下方即将出现 ${BLUE}trycloudflare.com${NC} 网址..."
echo -e "${BLUE}========================================${NC}"

# 【核心修复】使用 127.0.0.1 而不是 localhost，强制使用 IPv4
"$CDIR/cloudflared" tunnel --url http://127.0.0.1:5000 2>&1 | grep --line-buffered "trycloudflare.com"

# 脚本会停在这里显示日志。当你按 Ctrl+C 时，它会退出。
