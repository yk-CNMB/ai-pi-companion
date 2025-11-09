#!/bin/bash
# Hiyori 表情补全脚本

TARGET_DIR="static/live2d/hiyori/expressions"
BASE_URL="https://cdn.jsdelivr.net/gh/Eikanya/Live2d-model@master/Live2D%20v3/Hiyori/expressions"

echo "🔧 开始为 Hiyori 安装表情包..."

# 1. 创建缺失的目录
if [ ! -d "$TARGET_DIR" ]; then
    echo "📂 创建 expressions 文件夹..."
    mkdir -p "$TARGET_DIR"
fi

# 2. 定义下载函数
download_exp() {
    file="$1"
    echo -n "⬇️ 下载 $file... "
    # 使用 curl -L -f -s (静音但失败时报错)
    if curl -L -f -s -o "$TARGET_DIR/$file" "$BASE_URL/$file"; then
        echo "✅ 成功"
    else
        echo "❌ 失败!"
    fi
}

# 3. 开始下载 8 个标准表情
download_exp "f01.exp3.json" # 平静
download_exp "f02.exp3.json" # 认真/悲伤
download_exp "f03.exp3.json" # 害羞
download_exp "f04.exp3.json" # 生气
download_exp "f05.exp3.json" # 开心
download_exp "f06.exp3.json" # 惊讶
download_exp "f07.exp3.json" # 鄙视
download_exp "f08.exp3.json" # 严肃

echo "----------------------------------------"
echo "🎉 表情安装完毕！当前表情列表："
ls -lh "$TARGET_DIR"
```
