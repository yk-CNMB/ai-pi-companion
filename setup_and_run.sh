#!/bin/bash
# GlaDOS 重新安装脚本

CDIR="$(cd "$(dirname "$0")" && pwd)"
VOICE_DIR="$CDIR/static/voices"

echo -e "\033[0;32m🔧 正在修复 GlaDOS 语音包...\033[0m"

# 1. 清理旧文件 (防止损坏的文件占位)
rm -f "$VOICE_DIR/glados.onnx"
rm -f "$VOICE_DIR/glados.onnx.json"
rm -f "$VOICE_DIR/glados.txt"
mkdir -p "$VOICE_DIR"

# 2. 下载模型 (使用 huggingface 镜像或直连)
echo "⬇️ 正在下载模型文件 (glados.onnx)..."
# 使用 curl -L 自动跳转，-f 失败报错
curl -L -f -o "$VOICE_DIR/glados.onnx" "https://huggingface.co/dnhkng/glados/resolve/main/glados.onnx"

if [ $? -ne 0 ]; then
    echo -e "\033[0;31m❌ 模型下载失败！请检查网络连接。\033[0m"
    exit 1
fi

echo "⬇️ 正在下载配置文件..."
# 使用一个兼容的配置文件
curl -L -f -o "$VOICE_DIR/glados.onnx.json" "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

# 3. 创建名称标签
echo "GlaDOS (English)" > "$VOICE_DIR/glados.txt"

# 4. 验证
SIZE=$(ls -lh "$VOICE_DIR/glados.onnx" | awk '{print $5}')
echo "----------------------------------------"
echo -e "\033[0;32m✅ 安装完成！\033[0m"
echo "文件大小: $SIZE"
echo "📂 位置: $VOICE_DIR/glados.onnx"

bash reinstall_glados.sh

