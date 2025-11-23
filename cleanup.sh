#!/bin/bash
# Pico 工厂重置脚本 - 修复一切配置错误

CDIR="$(cd "$(dirname "$0")" && pwd)"
echo -e "\033[0;31m🧨 正在执行工厂重置...\033[0m"

# 1. 清除所有配置文件 (这是病根)
echo "🧹 删除旧配置文件..."
rm -f "$CDIR/config.json"
# 删除所有模型的独立配置文件
find "$CDIR/static/live2d" -name "config.json" -delete
find "$CDIR/static/live2d" -name "voice.txt" -delete

# 2. 重置模型文件夹 (只保留 Hiyori，防止坏模型干扰)
echo "🧹 清理模型文件夹..."
rm -rf "$CDIR/static/live2d/"*

# 3. 重新下载官方 Hiyori (确保至少有一个能用的)
echo "⬇️ 重新下载标准 Hiyori..."
TARGET_DIR="$CDIR/static/live2d/hiyori"
mkdir -p "$TARGET_DIR"
# 使用最稳的 SVN 下载
if command -v svn &> /dev/null; then
    svn export --force -q "https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Hiyori" "$TARGET_DIR"
else
    echo "❌ 缺少 SVN，尝试用 git..."
    git clone --depth=1 https://github.com/Live2D/CubismWebSamples.git temp_reset
    mv temp_reset/Samples/Resources/Hiyori "$TARGET_DIR"
    rm -rf temp_reset
fi

# 4. 验证下载
MODEL_FILE=$(find "$TARGET_DIR" -name "*.model3.json" | head -n 1)
if [ -n "$MODEL_FILE" ]; then
    echo -e "\033[0;32m✅ Hiyori 恢复成功！\033[0m"
    echo "文件名: $(basename "$MODEL_FILE")"
else
    echo -e "\033[0;31m❌ Hiyori 下载失败，请检查网络！\033[0m"
fi

echo "----------------------------------------"
echo "✅ 重置完成！请重新填入 Gemini API Key，然后重启服务器。"
```

运行：
```bash
bash factory_reset.sh
