#!/bin/bash
# 修复 GlaDOS 模型，使其兼容 Piper 引擎

CDIR="$(cd "$(dirname "$0")" && pwd)"
VOICE_DIR="$CDIR/static/voices"

echo -e "\033[0;32m🔧 正在为 Piper 修复 GlaDOS 模型...\033[0m"

cd "$VOICE_DIR"

# 1. 确认 ONNX 文件存在
if [ -f "en_US-glados.onnx" ]; then
    echo "✅ 找到模型本体: en_US-glados.onnx"
else
    # 如果名字不对，尝试找一下并改名
    FOUND=$(find . -name "*glados*.onnx" | head -n 1)
    if [ -n "$FOUND" ]; then
        mv "$FOUND" "en_US-glados.onnx"
        echo "✅ 已重命名模型为: en_US-glados.onnx"
    else
        echo "❌ 没找到 GlaDOS 模型！正在重新下载..."
        curl -L -o en_US-glados.onnx "https://huggingface.co/dnhkng/glados/resolve/main/glados.onnx"
    fi
fi

# 2. 【核心修复】下载缺失的 JSON 配置文件
# 我们使用 lessac 的配置作为替身，因为架构兼容
echo "⬇️ 下载 Piper 配置文件..."
curl -L -o "en_US-glados.onnx.json" "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

# 3. 创建名字标签
echo "GlaDOS (Piper本地)" > "en_US-glados.txt"

# 4. 检查 Piper 引擎是否可执行
chmod +x "$CDIR/piper_engine/piper"

echo "----------------------------------------"
echo "✅ 修复完成！"
echo "现在目录下有: $(ls en_US-glados.onnx*)"
echo "请重启服务器，然后在工作室里选择 'GlaDOS (Piper本地)'"
