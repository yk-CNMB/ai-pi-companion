#!/bin/bash
# Pico AI 紧急修复脚本 - 修复 JS 库和音频驱动

CDIR="$(cd "$(dirname "$0")" && pwd)"
echo -e "\033[0;31m🚑 开始紧急修复...\033[0m"

# --- 1. 修复 JS 核心库 (解决模型加载失败) ---
echo "🔧 [1/4] 正在修复前端 JS 引擎..."
mkdir -p "$CDIR/static/js"
cd "$CDIR/static/js"

# 强制重新下载 4 个核心文件 (使用最稳定的版本组合)
echo "  ⬇️ 下载 Live2D Cubism 2..."
curl -L -o live2d.min.js "https://cdn.jsdelivr.net/gh/dylanNew/live2d/webgl/Live2D/lib/live2d.min.js"
echo "  ⬇️ 下载 Live2D Cubism 4..."
curl -L -o live2dcubismcore.min.js "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"
echo "  ⬇️ 下载 PixiJS v6.5 (黄金稳定版)..."
curl -L -o pixi.min.js "https://cdnjs.cloudflare.com/ajax/libs/pixi.js/6.5.9/browser/pixi.min.js"
echo "  ⬇️ 下载 适配器插件..."
curl -L -o index.min.js "https://cdn.jsdelivr.net/npm/pixi-live2d-display/dist/index.min.js"

# 检查文件大小，确保不是 0KB
if [ ! -s "pixi.min.js" ] || [ ! -s "index.min.js" ]; then
    echo "❌ JS 下载失败！请检查网络并重新运行此脚本。"
    exit 1
else
    echo "✅ JS 引擎修复完成。"
fi

# --- 2. 修复系统音频驱动 (解决没声音) ---
echo "🔧 [2/4] 正在修复系统音频驱动 (需要 sudo 密码)..."
sudo apt-get update -q
sudo apt-get install libsndfile1 ffmpeg -y

# --- 3. 修复 Python 依赖 ---
echo "🔧 [3/4] 正在重装 Python 音频库..."
cd "$CDIR"
if [ -d ".venv" ]; then
    source .venv/bin/activate
    # 强制重装这几个关键库
    pip install --force-reinstall edge-tts soundfile requests
else
    echo "❌ 未找到虚拟环境！请先运行 setup_and_run.sh"
fi

# --- 4. 检查 Hiyori 模型 ---
echo "🔧 [4/4] 检查模型文件..."
MODEL_PATH="$CDIR/static/live2d/hiyori/Hiyori.model3.json"
if [ -f "$MODEL_PATH" ]; then
    echo "✅ Hiyori 模型存在。"
else
    echo "⚠️ Hiyori 模型缺失，正在重新下载..."
    bash install_hiyori_v4.sh  # 尝试调用之前的下载脚本
fi

echo "----------------------------------------"
echo "🎉 修复完成！"
echo "请运行: bash setup_and_run.sh 重启服务"

**3. 运行修复**
bash emergency_fix.sh
