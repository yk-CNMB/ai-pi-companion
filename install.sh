#!/bin/bash
# Hiyori 下载脚本 (核弹版) - 完整克隆官方仓库

TARGET_DIR="static/live2d/hiyori"
TEMP_REPO="temp_official_repo"

echo "🚚 准备完整克隆 Live2D 官方仓库..."

# 1. 清理环境
rm -rf "$TARGET_DIR" "$TEMP_REPO"
mkdir -p "$(dirname "$TARGET_DIR")"

# 2. 完整克隆 (深度为1，只取最新版，速度最快)
echo "⬇️ 开始克隆 (可能需要 1-3 分钟，请耐心等待)..."
if git clone --depth=1 https://github.com/Live2D/CubismWebSamples.git "$TEMP_REPO"; then
    echo "✅ 仓库克隆成功！"
    
    # 3. 提取 Hiyori
    echo "📦 正在提取 Hiyori 模型..."
    # 官方仓库中 Hiyori 的位置
    HIYORI_SRC="$TEMP_REPO/Samples/Resources/Hiyori"
    
    if [ -d "$HIYORI_SRC" ]; then
        mv "$HIYORI_SRC" "$TARGET_DIR"
        echo "✅ Hiyori 提取成功！"
    else
        echo "❌ 严重错误：在仓库中没找到 Hiyori 文件夹！"
        # 列出目录结构帮忙调试
        ls -R "$TEMP_REPO" | grep Hiyori
        exit 1
    fi
    
    # 4. 清理临时仓库
    echo "🧹 清理临时文件..."
    rm -rf "$TEMP_REPO"
    
    # 5. 最终验证
    echo "----------------------------------------"
    echo "🎉 安装完毕！"
    MODEL_FILE=$(find "$TARGET_DIR" -name "*.model3.json" | head -n 1)
    if [ -n "$MODEL_FILE" ]; then
        echo -e "🔍 模型主文件名为: \033[0;31m$(basename "$MODEL_FILE")\033[0m"
        echo "👉 请确保 templates/chat.html 里用的是这个名字！"
    else
        echo "❌ 依然没找到 .model3.json 文件，太奇怪了。"
    fi

else
    echo "❌ 克隆失败！请检查网络连接。"
    exit 1
fi
