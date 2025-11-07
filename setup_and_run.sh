#!/bin/bash
# setup_and_run.sh
# 树莓派项目一键部署和运行脚本

PROJECT_DIR=$(pwd)
VENV_DIR=".venv"
ENV_FILE=".env"

echo "--- 🤖 Pico AI Companion 部署脚本 ---"

# 1. 拉取最新的 GitHub 内容 (实现更新功能)
echo "1. 正在拉取 GitHub 最新内容..."
git pull

# 2. 检查并创建/激活虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    echo "2. 正在创建 Python 虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

echo "3. 正在激活虚拟环境..."
source "$VENV_DIR/bin/activate"

# 4. 安装依赖
echo "4. 正在安装 Python 依赖 (可能需要几分钟)..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. 配置环境变量 (API Key)
if [ ! -f "$ENV_FILE" ]; then
    echo "5. 配置 Gemini API Key..."
    read -p "请输入您的 GEMINI_API_KEY: " API_KEY
    echo "GEMINI_API_KEY=\"$API_KEY\"" > "$ENV_FILE"
    echo "FLASK_SECRET_KEY=\"$(openssl rand -hex 16)\"" >> "$ENV_FILE"
    echo "API Key 已保存到 $ENV_FILE"
else
    echo "5. $ENV_FILE 文件已存在，跳过 Key 配置。"
fi

# 6. 获取树莓派的 IP 地址
IP_ADDRESS=$(hostname -I | awk '{print $1}')

# 7. 启动 Flask 服务器
echo "--- 🚀 准备启动服务器 ---"
echo "您可以从手机浏览器访问以下地址开始聊天："
echo "   -> http://$IP_ADDRESS:5000"
echo "----------------------------------"

# 使用 exec 确保如果脚本被停止，Python 进程也会停止
exec python app.py

# 退出虚拟环境 (当程序停止后执行)
# deactivate