#!/bin/bash
# Piper 引擎 + GlaDOS 模型 一键安装脚本

CDIR="$(cd "$(dirname "$0")" && pwd)"
PIPER_DIR="$CDIR/piper_engine"
VOICE_DIR="$CDIR/static/voices"

echo -e "\033[0;32m🔧 开始部署 Piper 本地语音 (GlaDOS版)...\033[0m"

# 1. 准备目录
mkdir -p "$PIPER_DIR"
mkdir -p "$VOICE_DIR"

# 2. 下载 Piper 引擎 (Linux aarch64)
if [ ! -f "$PIPER_DIR/piper" ]; then
    echo "⬇️ 下载 Piper 引擎..."
    # 使用 2023.11.14 版本，稳定性最好
    wget -q -O piper.tar.gz https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    
    echo "📦 解压引擎..."
    tar -xf piper.tar.gz -C "$CDIR/"
    # 移动解压出来的 piper 文件夹内容到 piper_engine
    cp -r "$CDIR/piper/"* "$PIPER_DIR/"
    rm -rf "$CDIR/piper" piper.tar.gz
    chmod +x "$PIPER_DIR/piper"
    echo "✅ 引擎就绪"
else
    echo "✅ 引擎已存在"
fi

# 3. 下载 GlaDOS 模型
# 注意：我们下载的是适配 Piper 的 ONNX 和 JSON 版本
MODEL_NAME="glados"
if [ ! -f "$VOICE_DIR/$MODEL_NAME.onnx" ]; then
    echo "⬇️ 正在下载 GlaDOS 模型..."
    cd "$VOICE_DIR"
    
    # 使用 HuggingFace 的高质量 GlaDOS 移植版
    echo "  - 下载模型文件..."
    curl -L -o "$MODEL_NAME.onnx" "https://huggingface.co/dnhkng/glados/resolve/main/glados.onnx"
    
    echo "  - 下载配置文件..."
    # GlaDOS 原版 config 需要适配 Piper，这里使用兼容配置
    # 为了确保成功，我们使用一个通用的 Piper 英文配置作为底板
    curl -L -o "$MODEL_NAME.onnx.json" "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
    
    # 创建名字文件
    echo "GlaDOS (English)" > "$MODEL_NAME.txt"
    cd "$CDIR"
    echo "✅ GlaDOS 下载完成"
else
    echo "✅ GlaDOS 已存在"
fi

echo "----------------------------------------"
echo "🎉 安装完毕！"
echo "请重启服务器，并在工作室选择 'GlaDOS (English)'"
