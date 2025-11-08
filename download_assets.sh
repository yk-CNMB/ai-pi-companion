#!/bin/bash
# 智能下载 Hiyori - 自动搜寻正确路径

echo "🚚 开始下载 Hiyori 模型 (来源: Eikanya)..."

# 1. 准备临时目录
rm -rf temp_models_dir
mkdir -p temp_models_dir
cd temp_models_dir

# 2. 克隆大型模型仓库 (仅最近提交，减少等待)
echo "⏳ 正在克隆仓库，可能需要几分钟，请耐心等待..."
if git clone --depth=1 https://github.com/Eikanya/Live2d-model.git; then
    echo "✅ 仓库克隆成功！"
else
    echo "❌ 克隆失败！请检查网络 (可能需要科学上网)。"
    cd ..
    rm -rf temp_models_dir
    exit 1
fi

# 3. 智能搜寻 Hiyori
echo "🔍 正在仓库中搜寻 Hiyori..."
# 查找包含 .model3.json 的 Hiyori 文件夹
HIYORI_SRC=$(find Live2d-model -type f -name "*.model3.json" | grep -i "Hiyori" | head -n 1)

if [ -z "$HIYORI_SRC" ]; then
    echo "❌ 未找到 Hiyori 模型文件！"
    cd ..
    rm -rf temp_models_dir
    exit 1
fi

# 获取该文件所在的目录路径
HIYORI_DIR=$(dirname "$HIYORI_SRC")
echo "✅ 锁定目标: $HIYORI_DIR"

# 4. 安装到我们的项目
TARGET_DIR="../../static/live2d/hiyori"
echo "📦 正在安装到 $TARGET_DIR ..."
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -r "$HIYORI_DIR/"* "$TARGET_DIR/"

# 5. 清理战场
cd ..
rm -rf temp_models_dir

echo "----------------------------------------"
echo "🎉 Hiyori 安装完毕！请检查下方是否有 .model3.json 文件："
ls -lh static/live2d/hiyori/ | grep ".model3.json"
