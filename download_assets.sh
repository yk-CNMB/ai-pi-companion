#!/bin/bash
# 终极决战下载脚本 - 使用官方源

# 定义源地址和目标地址
GH_RAW="https://raw.githubusercontent.com/guansss/pixi-live2d-display/master/test/assets/shizuku"
TARGET="static/live2d/shizuku"

echo "🗑️ 清理旧战场..."
rm -rf "$TARGET"
mkdir -p "$TARGET/textures"
mkdir -p "$TARGET/motions"

# 定义下载函数 (使用 curl -fL# 显示进度条并在失败时报错)
dl() {
    src_file="$1"
    dest_file="$2"
    echo -e "\n⬇️ 正在下载: $dest_file"
    if curl -fL# -o "$TARGET/$dest_file" "$GH_RAW/$src_file"; then
        echo "✅ 成功"
    else
        echo -e "\n❌ 失败! 无法下载 $src_file"
        exit 1
    fi
}

# --- 开始下载 ---
# 1. 核心文件
dl "shizuku.moc" "shizuku.moc"
dl "shizuku.model.json" "shizuku.model.json"
dl "shizuku.physics.json" "shizuku.physics.json"
dl "shizuku.pose.json" "shizuku.pose.json"

# 2. 纹理图片
dl "textures/shizuku_01.png" "textures/shizuku_01.png"
dl "textures/shizuku_02.png" "textures/shizuku_02.png"
dl "textures/shizuku_03.png" "textures/shizuku_03.png"

# 3. 动作文件
dl "motions/idle_01.mtn" "motions/idle_01.mtn"
dl "motions/tap_body_01.mtn" "motions/tap_body_01.mtn"

echo -e "\n🎉 所有文件下载完成！最终检查："
find "$TARGET" -type f -exec ls -lh {} \;
