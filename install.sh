#!/bin/bash

# 定义颜色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# 目标目录 (根据 app.py 的逻辑)
VOICE_DIR="$(pwd)/static/voices"
mkdir -p "$VOICE_DIR"

echo -e "${BLUE}🎧 Pico 语音包下载器启动...${NC}"
echo -e "📂 目标目录: $VOICE_DIR"

# =======================================================
# 2. Tokin (日语 - 二次元/Miku 风格)
# =======================================================
echo -e "\n⬇️  [2/3] 正在下载 Tokin (Japanese - Miku Style)..."
rm -f "$VOICE_DIR/ja_JP-tokin"*

wget -q --show-progress -O "$VOICE_DIR/ja_JP-tokin.onnx" \
"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ja/ja_JP/tokin/medium/ja_JP-tokin-medium.onnx"

wget -q --show-progress -O "$VOICE_DIR/ja_JP-tokin.onnx.json" \
"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ja/ja_JP/tokin/medium/ja_JP-tokin-medium.onnx.json"

echo -e "${GREEN}✅ Tokin (Miku Style) 下载完成！${NC}"

# =======================================================
echo -e "\n${BLUE}🎉 所有语音包就绪！${NC}"
echo "👉 请刷新 Pico 网页，打开“工作室 (🛠️)”"
echo "👉 在“声线选择”下拉菜单中，你现在应该能看到它们了！"
