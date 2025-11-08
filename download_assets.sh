#!/bin/bash
echo "🔧 开始修复损坏的 Live2D 文件..."

# 定义高速镜像源基地址
BASE_URL="https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display@master/test/assets/shizuku"

# 1. 重新下载纹理图片
echo "⬇️ 正在重新下载纹理 (1/3)..."
rm -f static/live2d/shizuku/textures/shizuku_01.png
wget -O static/live2d/shizuku/textures/shizuku_01.png "$BASE_URL/textures/shizuku_01.png"

echo "⬇️ 正在重新下载纹理 (2/3)..."
rm -f static/live2d/shizuku/textures/shizuku_02.png
wget -O static/live2d/shizuku/textures/shizuku_02.png "$BASE_URL/textures/shizuku_02.png"

echo "⬇️ 正在重新下载纹理 (3/3)..."
rm -f static/live2d/shizuku/textures/shizuku_03.png
wget -O static/live2d/shizuku/textures/shizuku_03.png "$BASE_URL/textures/shizuku_03.png"

# 2. 重新下载动作文件
echo "⬇️ 正在重新下载动作文件..."
rm -f static/live2d/shizuku/motions/tap_body_01.mtn
wget -O static/live2d/shizuku/motions/tap_body_01.mtn "$BASE_URL/motions/tap_body_01.mtn"

echo "✅ 修复完成！请检查下方文件大小是否大于 0："
ls -lh static/live2d/shizuku/textures/
ls -lh static/live2d/shizuku/motions/tap_body_01.mtn
```

#3. 运行修复脚本
```bash
bash fix_assets.sh
