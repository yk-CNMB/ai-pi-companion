#!/bin/bash
# Hiyori 完整版下载 (包含表情包) - 使用 SVN

TARGET_DIR="static/live2d/hiyori"
echo "🚚 准备下载完整版 Hiyori (含表情包)..."

# 1. 清理旧文件
echo "🗑️ 清理旧模型..."
rm -rf "$TARGET_DIR"
mkdir -p "$(dirname "$TARGET_DIR")"

# 2. 使用 SVN 下载完整文件夹
# 这个源包含了 motions, expressions, textures 等所有必要文件
SVN_URL="https://github.com/imuncle/live2d-models/trunk/models/hiyori"

echo "⬇️ 开始下载 (可能需要一分钟)..."
if svn export --force -q "$SVN_URL" "$TARGET_DIR"; then
    echo "✅ Hiyori 完整版下载成功！"
    
    # 3. 验证关键文件
    echo "----------------------------------------"
    echo "🔍 检查表情包..."
    ls -1 "$TARGET_DIR/expressions" | head -n 3
    echo "... (应显示 F01.exp3.json 等)"
    
    echo "----------------------------------------"
    # 自动查找主模型文件名
    MODEL_FILE=$(find "$TARGET_DIR" -name "*.model3.json" | head -n 1)
    if [ -n "$MODEL_FILE" ]; then
        echo -e "🎉 主文件锁定: \033[0;32m$(basename "$MODEL_FILE")\033[0m"
    fi
else
    echo "❌ 下载失败！请检查网络。"
    exit 1
fi
