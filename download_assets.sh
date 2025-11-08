#!/bin/bash
# 使用 Git 克隆方式获取资源，比 curl/wget 更稳定

echo "🚚 开始整箱搬运 Live2D 模型..."

# 1. 创建一个临时目录
mkdir -p temp_assets
cd temp_assets

# 2. 克隆包含 Shizuku 模型的仓库 (只克隆最近一次提交，减少下载量)
# 如果 GitHub 慢，可以尝试用 fastgit 等镜像，但在德国应该没问题
echo "⬇️ 正在克隆仓库 (可能需要一分钟)..."
git clone --depth=1 https://github.com/guansss/pixi-live2d-display.git

# 3. 检查是否克隆成功
if [ ! -d "pixi-live2d-display" ]; then
    echo "❌ 克隆失败！请检查网络或尝试不带 --depth=1 参数重新运行。"
    exit 1
fi

# 4. 回到项目根目录
cd ..

# 5. 创建目标目录
mkdir -p static/live2d

# 6. 复制我们需要的部分 (Shizuku 模型)
echo "📦 正在安装模型..."
cp -r temp_assets/pixi-live2d-display/test/assets/shizuku static/live2d/

# 7. 清理临时文件
echo "🧹 清理垃圾..."
rm -rf temp_assets

echo "✅ 模型安装完成！请检查下方文件大小："
ls -lh static/live2d/shizuku/
