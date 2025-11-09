#!/bin/bash
# Hiyori 下载脚本 (最终版) - 使用 Git Sparse-Checkout

REPO_URL="https://github.com/imuncle/live2d-models.git"
TARGET_DIR="static/live2d/hiyori"
TEMP_DIR="temp_hiyori_git"

echo "🚚 准备通过 Git 稀疏检出下载 Hiyori..."

# 1. 清理环境
rm -rf "$TARGET_DIR" "$TEMP_DIR"
mkdir -p "$(dirname "$TARGET_DIR")"
mkdir -p "$TEMP_DIR"
cd "$TEMP_DIR" || exit

# 2. 初始化 Git 并设置过滤
echo "⚙️ 正在配置 Git..."
git init -q
git remote add -f origin "$REPO_URL"

# 开启稀疏检出功能
git config core.sparseCheckout true

# 告诉 Git 我们只想要 models/hiyori 这个文件夹
echo "models/hiyori" >> .git/info/sparse-checkout

# 3. 开始拉取 (只拉取最近一次提交，速度最快)
echo "⬇️ 开始拉取 (可能需要 1-2 分钟，请耐心等待)..."
if git pull --depth=1 origin master -q; then
    echo "✅ 拉取成功！"
    
    # 4. 移动到目标位置
    cd ..
    mv "$TEMP_DIR/models/hiyori" "$TARGET_DIR"
    rm -rf "$TEMP_DIR"
    
    # 5. 最终验证
    echo "----------------------------------------"
    echo "🎉 Hiyori 安装完毕！"
    echo "📂 表情包检查 (应显示 F01.exp3.json 等):"
    ls -1 "$TARGET_DIR/expressions" | head -n 3
    
    MODEL_FILE=$(find "$TARGET_DIR" -name "*.model3.json" | head -n 1)
    if [ -n "$MODEL_FILE" ]; then
        echo -e "🔍 模型主文件名为: \033[0;31m$(basename "$MODEL_FILE")\033[0m"
        echo "👉 请确保 templates/chat.html 里用的是这个名字！"
    fi
else
    echo "❌ 下载失败！请检查网络连接。"
    cd ..
    rm -rf "$TEMP_DIR"
    exit 1
fi
