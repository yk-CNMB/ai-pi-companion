#!/bin/bash
# 一键修复 Shizuku 模型的纹理问题

# 定义路径和源
TEXTURE_DIR="static/live2d/shizuku/textures"
CDN_URL="https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display@master/test/assets/shizuku/textures"

echo "🔧 开始修复 Live2D 纹理..."

# 1. 清理旧目录 (无论它之前叫什么，先删了再说)
echo "🧹 清理旧文件..."
rm -rf "$TEXTURE_DIR"
mkdir -p "$TEXTURE_DIR"

# 2. 进入目录
cd "$TEXTURE_DIR" || exit

# 3. 强制下载三张标准纹理图
echo "⬇️ 正在下载纹理 1/3..."
wget -q --show-progress "$CDN_URL/shizuku_01.png"

echo "⬇️ 正在下载纹理 2/3..."
wget -q --show-progress "$CDN_URL/shizuku_02.png"

echo "⬇️ 正在下载纹理 3/3..."
wget -q --show-progress "$CDN_URL/shizuku_03.png"

# 4. 返回项目根目录并检查
cd - > /dev/null
echo "✅ 修复完成！请检查下方文件大小 (应为几百 KB)："
ls -lh "$TEXTURE_DIR"
```

**3. 运行脚本**
```bash
bash fix_textures.sh
