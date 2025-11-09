#!/bin/bash
# 终极批发下载脚本 - 使用 Git 一次性拉取所有官方模型

REPO_URL="https://github.com/Live2D/CubismWebSamples.git"
TEMP_DIR="temp_models_all"
TARGET_BASE="static/live2d"

echo "🚚 准备一次性批发所有官方模型..."

# 1. 清理工作区
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"
mkdir -p "$TARGET_BASE"
cd "$TEMP_DIR" || exit

# 2. 初始化 Git 并设置稀疏检出
echo "⚙️ 正在配置 Git..."
git init -q
git remote add -f origin "$REPO_URL"
git config core.sparseCheckout true

# 告诉 Git：我们只要 'Samples/Resources' 这个文件夹下的所有东西
echo "Samples/Resources" >> .git/info/sparse-checkout

# 3. 开始拉取 (因为模型多，可能需要几分钟)
echo "⬇️ 开始同步官方仓库 (请耐心等待 2-5 分钟)..."
# 尝试 master 分支，如果失败尝试 develop 分支 (官方有时会改默认分支)
if git pull --depth=1 origin master -q || git pull --depth=1 origin develop -q; then
    echo "✅ 同步成功！正在解压安装..."
    
    # 4. 将下载下来的所有模型文件夹移动到我们的 static/live2d 下
    # 使用 cp -rn 防止覆盖已经存在的 Hiyori (如果你刚才手动修好了她)
    cp -rn Samples/Resources/* "../$TARGET_BASE/"
    
    # 5. 清理临时文件
    cd ..
    rm -rf "$TEMP_DIR"
    
    echo "----------------------------------------"
    echo "🎉 大功告成！你现在拥有了以下模型："
    ls -F "$TARGET_BASE" | grep "/"
    echo "👉 快去网页右上角的⚙️齿轮里切换试试吧！"
else
    echo "❌ 同步失败！请检查树莓派的网络连接。"
    cd ..
    rm -rf "$TEMP_DIR"
    exit 1
fi
