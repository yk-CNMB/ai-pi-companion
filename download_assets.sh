#!/bin/bash
# 直连 GitHub 源站下载 Shizuku 模型

# 使用 GitHub Raw 源站
BASE_URL="https://raw.githubusercontent.com/Eikanya/Live2d-model/master/Shizuku"
TARGET_DIR="static/live2d/shizuku"

echo "🗑️ 清理旧文件..."
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR/textures"
mkdir -p "$TARGET_DIR/motions"
mkdir -p "$TARGET_DIR/expressions"

echo "⬇️ 开始从 GitHub 源站下载..."

# 定义下载函数 (去掉 -s 以便看到错误信息)
download() {
    local url="$1"
    local dest="$2"
    echo "📦 正在下载 $(basename "$dest")..."
    # -L: 跟随重定向, -f: 失败报错, --retry 3: 重试3次
    if curl -L -f --retry 3 --retry-delay 2 -o "$dest" "$url"; then
        echo "✅ OK"
    else
        echo "❌ 失败! (请看上面的错误信息)"
        exit 1
    fi
}

# 1. 核心模型文件
download "$BASE_URL/shizuku.moc" "$TARGET_DIR/shizuku.moc"
download "$BASE_URL/shizuku.model.json" "$TARGET_DIR/shizuku.model.json"
download "$BASE_URL/shizuku.physics.json" "$TARGET_DIR/shizuku.physics.json"
download "$BASE_URL/shizuku.pose.json" "$TARGET_DIR/shizuku.pose.json"

# 2. 纹理图片
download "$BASE_URL/textures/shizuku_01.png" "$TARGET_DIR/textures/shizuku_01.png"
download "$BASE_URL/textures/shizuku_02.png" "$TARGET_DIR/textures/shizuku_02.png"
download "$BASE_URL/textures/shizuku_03.png" "$TARGET_DIR/textures/shizuku_03.png"

# 3. 动作文件
download "$BASE_URL/motions/idle_01.mtn" "$TARGET_DIR/motions/idle_01.mtn"
download "$BASE_URL/motions/tap_body_01.mtn" "$TARGET_DIR/motions/tap_body_01.mtn"
download "$BASE_URL/motions/pinch_01.mtn" "$TARGET_DIR/motions/pinch_01.mtn"
download "$BASE_URL/motions/shake_01.mtn" "$TARGET_DIR/motions/shake_01.mtn"

# 4. 表情文件
download "$BASE_URL/expressions/f01.exp.json" "$TARGET_DIR/expressions/f01.exp.json"
download "$BASE_URL/expressions/f02.exp.json" "$TARGET_DIR/expressions/f02.exp.json"
download "$BASE_URL/expressions/f03.exp.json" "$TARGET_DIR/expressions/f03.exp.json"
download "$BASE_URL/expressions/f04.exp.json" "$TARGET_DIR/expressions/f04.exp.json"

echo "----------------------------------------"
echo "🎉 下载完成！最终检查："
ls -lhR "$TARGET_DIR" | grep "\.png\|\.moc"
