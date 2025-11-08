#!/bin/bash
# 强制重新下载损坏的 Live2D 文件

# 定义基础 URL (使用 jsdelivr CDN，全球加速)
BASE_URL="https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display@master/test/assets/shizuku"

echo "🔧 开始修复 Live2D 模型文件..."

# 确保目录存在
mkdir -p static/live2d/shizuku/textures
mkdir -p static/live2d/shizuku/motions

# 定义一个下载函数，使用 curl
download_file() {
    local url="$1"
    local dest="$2"
    echo -e "⬇️ 正在下载: $dest"
    # -L: 跟随重定向
    # -f: HTTP错误时不写入文件
    # -# 显示进度条
    curl -L -f -# "$url" -o "$dest"
    
    if [ $? -eq 0 ]; then
        echo "✅ 成功"
    else
        echo "❌ 失败! 请检查网络"
    fi
}

# 1. 修复纹理图片 (之前的 0 字节文件)
download_file "$BASE_URL/textures/shizuku_01.png" "static/live2d/shizuku/textures/shizuku_01.png"
download_file "$BASE_URL/textures/shizuku_02.png" "static/live2d/shizuku/textures/shizuku_02.png"
download_file "$BASE_URL/textures/shizuku_03.png" "static/live2d/shizuku/textures/shizuku_03.png"

# 2. 修复动作文件
download_file "$BASE_URL/motions/tap_body_01.mtn" "static/live2d/shizuku/motions/tap_body_01.mtn"

echo "----------------------------------------"
echo "🔍 检查修复结果 (文件大小不应为 0):"
ls -lh static/live2d/shizuku/textures/
ls -lh static/live2d/shizuku/motions/
```

**3. 运行修复**
```bash
bash force_fix.sh
