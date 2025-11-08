#!/bin/bash
# 下载并安装更高级的 Hiyori 模型

echo "🚚 开始下载 Hiyori 模型..."

# 1. 准备工作目录
rm -rf temp_live2d
mkdir -p temp_live2d
cd temp_live2d

# 2. 克隆包含 Hiyori 的仓库 (只克隆最近提交，速度快)
# 如果这个 GitHub 地址慢，可以尝试换成 gitclone.com 的镜像
git clone --depth=1 https://github.com/guansss/pixi-live2d-display.git

# 3. 检查是否克隆成功
if [ ! -d "pixi-live2d-display" ]; then
    echo "❌ 下载失败，请检查网络！"
    cd ..
    rm -rf temp_live2d
    exit 1
fi

# 4. 安装 Hiyori 模型
echo "📦 正在安装 Hiyori..."
TARGET_DIR="../../static/live2d/hiyori"
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"

# 复制 hiyori 文件夹下的所有内容
cp -r pixi-live2d-display/test/assets/hiyori/* "$TARGET_DIR/"

# 5. 清理临时文件
cd ../..
rm -rf temp_live2d

echo "✅ Hiyori 模型安装完成！"
echo "📂 模型位置: static/live2d/hiyori/"
