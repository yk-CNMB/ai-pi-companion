!/bin/bash
# Hiyori 下载脚本 V3 - 官方源 + 双重保障

TARGET_DIR="static/live2d/hiyori"
echo "🚚 准备从 Live2D 官方仓库下载 Hiyori..."

# 清理旧文件
rm -rf "$TARGET_DIR"
mkdir -p "$(dirname "$TARGET_DIR")"

# --- 方法 A: 尝试 SVN (最快) ---
SVN_URL="https://github.com/Live2D/CubismWebSamples/trunk/Samples/Resources/Hiyori"
echo "🔄 尝试方法 A (SVN)..."
if command -v svn &> /dev/null && svn export --force -q "$SVN_URL" "$TARGET_DIR"; then
    echo "✅ 方法 A 成功！"
else
    echo "⚠️ 方法 A 失败，自动切换到方法 B (Git)..."
    
    # --- 方法 B: 尝试 Git Clone (备用) ---
    # 临时目录
    TEMP_GIT="temp_live2d_official"
    rm -rf "$TEMP_GIT"
    
    if git clone --depth=1 --filter=blob:none --sparse https://github.com/Live2D/CubismWebSamples.git "$TEMP_GIT"; then
        cd "$TEMP_GIT"
        # 只拉取 Hiyori 文件夹，节省流量
        git sparse-checkout set Samples/Resources/Hiyori
        cd ..
        # 移动到目标位置
        mv "$TEMP_GIT/Samples/Resources/Hiyori" "$TARGET_DIR"
        rm -rf "$TEMP_GIT"
        echo "✅ 方法 B 成功！"
    else
        echo "❌ 全部失败！请检查网络连接是否能访问 GitHub。"
        exit 1
    fi
fi

# --- 最终检查 ---
echo "----------------------------------------"
MODEL_FILE=$(find "$TARGET_DIR" -name "*.model3.json" | head -n 1)
if [ -n "$MODEL_FILE" ]; then
    FILE_NAME=$(basename "$MODEL_FILE")
    echo -e "🎉 \033[0;32mHiyori 安装成功！\033[0m"
    echo -e "🔍 模型主文件名为: \033[0;31m$FILE_NAME\033[0m"
    echo "👉 请务必确保你的 templates/chat.html 里用的是这个名字！"
else
    echo "❌ 严重错误：文件夹已下载，但没找到 .model3.json 文件。"
fi
```

运行它：
```bash
bash install_hiyori_v3.sh
```

### ⚠️ 重要提示

脚本运行成功后，它会用**红字**告诉你模型的文件名（很有可能是 `Hiyori.model3.json`，注意首字母大写）。

你**必须**去 `templates/chat.html` 里，找到加载模型的那一行，把它改成和你看到的**一模一样**：

```javascript
// 如果脚本显示是 Hiyori.model3.json，你就得改成这样：
model = await PIXI.live2d.Live2DModel.from('/static/live2d/hiyori/Hiyori.model3.json');
