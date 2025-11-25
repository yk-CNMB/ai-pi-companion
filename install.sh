#!/bin/bash
# 全能语音安装包：Piper 引擎 + Sherpa 环境 + GlaDOS 模型

CDIR="$(cd "$(dirname "$0")" && pwd)"
PIPER_DIR="$CDIR/piper_engine"
VOICE_DIR="$CDIR/static/voices"

echo -e "\033[0;32m🔧 开始部署全能本地语音环境...\033[0m"

# 1. 准备目录
mkdir -p "$PIPER_DIR"
mkdir -p "$VOICE_DIR"
# 激活虚拟环境以安装 python 库
source "$CDIR/.venv/bin/activate"

# 2. 安装 Sherpa-Onnx (Python 库，用于跑 GlaDOS)
echo "⬇️ 安装 Sherpa-onnx 支持库..."
pip install sherpa-onnx soundfile

# 3. 下载 Piper 引擎 (备用)
if [ ! -f "$PIPER_DIR/piper" ]; then
    echo "⬇️ 下载 Piper 引擎..."
    wget -q -O piper.tar.gz https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar -xf piper.tar.gz -C "$CDIR/"
    cp -r "$CDIR/piper/"* "$PIPER_DIR/"
    rm -rf "$CDIR/piper" piper.tar.gz
    chmod +x "$PIPER_DIR/piper"
    echo "✅ Piper 引擎就绪"
fi

# 4. 下载 GlaDOS 模型 (Sherpa 格式)
GLADOS_DIR="$VOICE_DIR/glados"
if [ ! -f "$GLADOS_DIR/en_US-glados.onnx" ]; then
    echo "⬇️ 正在下载 GlaDOS (Sherpa版)..."
    mkdir -p "$GLADOS_DIR"
    cd "$GLADOS_DIR"
    
    # 使用你提供的官方链接
    wget -O glados.tar.bz2 "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-glados.tar.bz2"
    
    echo "📦 解压模型..."
    tar -xf glados.tar.bz2
    
    # 整理文件结构 (解压后会在子目录里，我们要拿出来)
    cp vits-piper-en_US-glados/*.onnx .
    cp vits-piper-en_US-glados/tokens.txt .
    # 注意：Sherpa 需要 espeak-ng-data
    if [ -d "vits-piper-en_US-glados/espeak-ng-data" ]; then
        cp -r vits-piper-en_US-glados/espeak-ng-data .
    fi
    
    # 清理垃圾
    rm -rf vits-piper-en_US-glados glados.tar.bz2
    
    # 创建识别文件
    echo "GlaDOS (Sherpa)" > name.txt
    
    cd "$CDIR"
    echo "✅ GlaDOS 模型安装完成"
else
    echo "✅ GlaDOS 已存在"
fi

echo "----------------------------------------"
echo "🎉 全部安装完毕！"
echo "请更新 app.py 以启用 Sherpa 支持。"
