#!/bin/bash
# 下载 Live2D 所需的所有本地资源

echo "📦 开始下载本地资源..."

# 1. 创建目录
mkdir -p static/js
mkdir -p static/live2d/shizuku

# 2. 下载核心 JS 库 (保存到 static/js)
echo "⬇️ 正在下载 JS 引擎..."
wget -O static/js/live2dcubismcore.min.js https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js
wget -O static/js/pixi.min.js https://cdnjs.cloudflare.com/ajax/libs/pixi.js/7.3.2/pixi.min.js
wget -O static/js/pixi-live2d-display.min.js https://cdn.jsdelivr.net/npm/pixi-live2d-display/dist/index.min.js

# 3. 下载一个简单的 Live2D 模型 (Shizuku)
# 我们换一个文件少、更容易下载的模型，确保成功率
echo "⬇️ 正在下载 Live2D 模型 (Shizuku)..."
BASE_URL="https://raw.githubusercontent.com/guansss/pixi-live2d-display/master/test/assets/shizuku"

# 必须下载的文件列表
wget -O static/live2d/shizuku/shizuku.model.json "$BASE_URL/shizuku.model.json"
wget -O static/live2d/shizuku/shizuku.moc "$BASE_URL/shizuku.moc"
wget -O static/live2d/shizuku/shizuku.physics.json "$BASE_URL/shizuku.physics.json"
wget -O static/live2d/shizuku/shizuku.pose.json "$BASE_URL/shizuku.pose.json"

# 下载纹理图片
mkdir -p static/live2d/shizuku/textures
wget -O static/live2d/shizuku/textures/shizuku_01.png "$BASE_URL/textures/shizuku_01.png"
wget -O static/live2d/shizuku/textures/shizuku_02.png "$BASE_URL/textures/shizuku_02.png"
wget -O static/live2d/shizuku/textures/shizuku_03.png "$BASE_URL/textures/shizuku_03.png"

# 下载部分动作 (可选，为了让它能动)
mkdir -p static/live2d/shizuku/motions
wget -O static/live2d/shizuku/motions/idle_01.mtn "$BASE_URL/motions/idle_01.mtn"
wget -O static/live2d/shizuku/motions/tap_body_01.mtn "$BASE_URL/motions/tap_body_01.mtn"

echo "✅ 所有资源下载完成！"
```

3.  运行脚本：
    ```bash
    bash download_assets.sh
