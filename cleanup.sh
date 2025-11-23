#!/bin/bash
# Pico 工厂重置脚本 (Git 强力版) - 修复一切配置错误

CDIR="$(cd "$(dirname "$0")" && pwd)"
echo -e "\033[0;31m🧨 正在执行工厂重置...\033[0m"

# 1. 清除配置文件
echo "🧹 删除旧配置文件..."
rm -f "$CDIR/config.json"
find "$CDIR/static/live2d" -name "config.json" -delete
find "$CDIR/static/live2d" -name "voice.txt" -delete

# 2. 重置模型文件夹
echo "🧹 清理模型文件夹..."
rm -rf "$CDIR/static/live2d/"*
# 确保目录存在
mkdir -p "$CDIR/static/live2d"

# 3. 使用 Git 强力下载 Hiyori
echo "⬇️ 正在从官方仓库拉取 Hiyori..."
TEMP_GIT="temp_reset_git"
rm -rf "$TEMP_GIT"
mkdir -p "$TEMP_GIT"
cd "$TEMP_GIT" || exit

# 初始化 Git
git init -q
git remote add -f origin https://github.com/Live2D/CubismWebSamples.git
git config core.sparseCheckout true

# 指定只下载 Hiyori
echo "Samples/Resources/Hiyori" >> .git/info/sparse-checkout

# 拉取 (尝试 master 分支)
if git pull --depth=1 origin master -q; then
    echo "✅ 拉取成功！"
    # 移动文件
    mv Samples/Resources/Hiyori "$CDIR/static/live2d/"
else
    echo "⚠️ master 分支失败，尝试 develop 分支..."
    if git pull --depth=1 origin develop -q; then
        echo "✅ 拉取成功 (develop)！"
        mv Samples/Resources/Hiyori "$CDIR/static/live2d/"
    else
        echo "❌ 严重错误：无法连接到 GitHub 官方仓库。"
        cd ..
        rm -rf "$TEMP_GIT"
        exit 1
    fi
fi

# 清理
cd ..
rm -rf "$TEMP_GIT"

# 4. 验证下载
MODEL_FILE=$(find "$CDIR/static/live2d/hiyori" -name "*.model3.json" | head -n 1)
if [ -n "$MODEL_FILE" ]; then
    echo -e "\033[0;32m✅ Hiyori 恢复成功！\033[0m"
    echo "文件名: $(basename "$MODEL_FILE")"
else
    echo -e "\033[0;31m❌ Hiyori 下载失败，文件不完整！\033[0m"
fi

echo "----------------------------------------"
echo "✅ 重置完成！请务必重新填入 config.json 中的 API Key。"
echo "然后运行 bash setup_and_run.sh 重启服务器。"
