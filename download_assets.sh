#!/bin/bash
# 终极决战 V2 - 精准匹配 GitHub 仓库结构

GH_RAW="https://raw.githubusercontent.com/guansss/pixi-live2d-display/master/test/assets/shizuku"
TARGET="static/live2d/shizuku"

echo "🗑️ 清理旧战场..."
rm -rf "$TARGET"
# 注意：我们创建的是 shizuku.1024 文件夹
mkdir -p "$TARGET/shizuku.1024"
mkdir -p "$TARGET/motions"

# 定义下载函数
dl() {
    # $1 是 GitHub 上的源路径, $2 是本地的目标路径
    echo -e "\n⬇️ 下载: $2"
    if curl -fL# -o "$TARGET/$2" "$GH_RAW/$1"; then
        echo "✅ 成功"
    else
        echo -e "\n❌ 失败! 无法下载 $1 (可能是文件名错了)"
        exit 1
    fi
}

# --- 1. 核心文件 ---
dl "shizuku.moc" "shizuku.moc"
dl "shizuku.model.json" "shizuku.model.json"
dl "shizuku.physics.json" "shizuku.physics.json"
dl "shizuku.pose.json" "shizuku.pose.json"

# --- 2. 纹理图片 (精准匹配仓库里的名字) ---
dl "shizuku.1024/texture_00.png" "shizuku.1024/texture_00.png"
dl "shizuku.1024/texture_01.png" "shizuku.1024/texture_01.png"
dl "shizuku.1024/texture_02.png" "shizuku.1024/texture_02.png"
dl "shizuku.1024/texture_03.png" "shizuku.1024/texture_03.png"
dl "shizuku.1024/texture_04.png" "shizuku.1024/texture_04.png"
dl "shizuku.1024/texture_05.png" "shizuku.1024/texture_05.png"

# --- 3. 动作文件 ---
dl "motions/idle_01.mtn" "motions/idle_01.mtn"
dl "motions/tap_body_01.mtn" "motions/tap_body_01.mtn"

echo -e "\n🎉 下载全部完成！快去刷新网页吧！"
