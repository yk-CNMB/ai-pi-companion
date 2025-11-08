#!/bin/bash
# V3 稳定版下载脚本 - 只下载核心文件

GH_RAW="https://raw.githubusercontent.com/guansss/pixi-live2d-display/master/test/assets/shizuku"
TARGET="static/live2d/shizuku"

echo "🗑️ 清理旧文件..."
rm -rf "$TARGET"
mkdir -p "$TARGET/shizuku.1024"
mkdir -p "$TARGET/motions"

dl() {
    echo -e "\n⬇️ 下载: $2"
    # 增加 -f 参数，遇到 404 直接报错退出
    if curl -fL# -o "$TARGET/$2" "$GH_RAW/$1"; then
        echo "✅ 成功"
    else
        echo "❌ 失败！源文件不存在: $1"
        # 这里我们不退出，而是继续下载其他文件，确保能用的都下载下来
    fi
}

# 1. 核心文件
dl "shizuku.moc" "shizuku.moc"
dl "shizuku.model.json" "shizuku.model.json"
dl "shizuku.physics.json" "shizuku.physics.json"
dl "shizuku.pose.json" "shizuku.pose.json"

# 2. 纹理 (shizuku.1024)
dl "shizuku.1024/texture_00.png" "shizuku.1024/texture_00.png"
dl "shizuku.1024/texture_01.png" "shizuku.1024/texture_01.png"
dl "shizuku.1024/texture_02.png" "shizuku.1024/texture_02.png"
dl "shizuku.1024/texture_03.png" "shizuku.1024/texture_03.png"
dl "shizuku.1024/texture_04.png" "shizuku.1024/texture_04.png"
dl "shizuku.1024/texture_05.png" "shizuku.1024/texture_05.png"

# 3. 动作 (只下载确定的 idle)
dl "motions/idle_01.mtn" "motions/idle_01.mtn"

echo -e "\n🎉 下载结束！快去刷新网页！"
