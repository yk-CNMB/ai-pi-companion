#!/bin/bash
# 更换为最稳定的 Pixi v6 引擎组合

JS_DIR="static/js"
mkdir -p "$JS_DIR"

echo "🔧 正在更换图形引擎..."

# 1. 下载 PixiJS v6.5 (黄金稳定版)
echo "⬇️ 下载 PixiJS v6.5..."
curl -L -o "$JS_DIR/pixi.min.js" "https://cdnjs.cloudflare.com/ajax/libs/pixi.js/6.5.9/browser/pixi.min.js"

# 2. 下载 Cubism 2.1 核心 (用于旧模型，如 Shizuku)
echo "⬇️ 下载 Cubism 2 Core..."
curl -L -o "$JS_DIR/live2d.min.js" "https://cdn.jsdelivr.net/gh/dylanNew/live2d/webgl/Live2D/lib/live2d.min.js"

# 3. 下载 Cubism 4 核心 (用于新模型)
echo "⬇️ 下载 Cubism 4 Core..."
curl -L -o "$JS_DIR/live2dcubismcore.min.js" "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"

# 4. 下载适配器插件 (兼容版)
echo "⬇️ 下载 Live2D 适配器..."
curl -L -o "$JS_DIR/index.min.js" "https://cdn.jsdelivr.net/npm/pixi-live2d-display/dist/index.min.js"

echo "✅ 引擎更换完毕！"
