#!/bin/bash
# Live2D 官方模型扩展包下载脚本

BASE_URL="https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources"
TARGET_DIR="static/live2d"

# 确保 SVN 已安装
if ! command -v svn &> /dev/null; then
    echo "📦 正在安装 SVN..."
    sudo apt update && sudo apt install subversion -y
fi

mkdir -p "$TARGET_DIR"
echo "🚀 开始下载模型扩展包..."

# 定义下载函数
get_model() {
    MODEL_NAME=$1
    echo -e "\n⬇️ 正在下载: $MODEL_NAME ..."
    # 先清理旧的
    rm -rf "$TARGET_DIR/$MODEL_NAME"
    # 使用 SVN 下载
    if svn export --force -q "$BASE_URL/$MODEL_NAME" "$TARGET_DIR/$MODEL_NAME"; then
        echo "✅ $MODEL_NAME 下载成功！"
    else
        echo "❌ $MODEL_NAME 下载失败！"
    fi
}

# 开始批量下载
get_model "Haru"
get_model "Mao"
get_model "Natori"
get_model "Rice"
# Hiyori 你之前下过了，这里就不重复下了，除非你想覆盖

echo -e "\n🎉 所有模型下载完毕！"
echo "📂 当前模型列表："
ls -1 "$TARGET_DIR"
```
