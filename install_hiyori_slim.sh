#!/bin/bash
# 瘦身版 Hiyori 下载 - 使用 SVN

if ! command -v svn &> /dev/null; then
    echo "📦 正在安装 SVN..."
    sudo apt update && sudo apt install subversion -y
fi

echo "🚚 开始精准下载 Hiyori 模型..."
TARGET_DIR="static/live2d/hiyori"

# 清理旧的
rm -rf "$TARGET_DIR"
mkdir -p "$(dirname "$TARGET_DIR")"

# 使用 SVN 只下载 Hiyori 子目录
SVN_URL="https://github.com/Eikanya/Live2d-model/trunk/Live2D%20v3/Hiyori"

if svn export --force -q "$SVN_URL" "$TARGET_DIR"; then
    echo "✅ Hiyori 下载成功！"
    # 自动检查模型文件名
    MODEL_FILE=$(find "$TARGET_DIR" -name "*.model3.json" | head -n 1)
    if [ -n "$MODEL_FILE" ]; then
        echo -e "\033[0;32m🔍 找到模型文件: $(basename "$MODEL_FILE")\033[0m"
        echo "👉 请记住这个文件名，稍后可能需要修改 chat.html"
    fi
else
    echo "❌ 下载失败！请检查网络。"
    exit 1
fi
```

运行它：
```bash
bash install_hiyori_slim.sh
```

### 2️⃣ 第二步：确认 `chat.html` 配置

脚本运行完后，会告诉你找到的模型文件名（通常是 `Hiyori.model3.json` 或 `hiyori_pro_t10.model3.json`）。

请打开 `templates/chat.html`：
```bash
nano templates/chat.html
```
找到这一行（大约在 165 行左右）：
```javascript
model = await PIXI.live2d.Live2DModel.from('/static/live2d/hiyori/hiyori_pro_t10.model3.json');
```
**如果脚本告诉你的文件名不一样，请在这里修改它！**（例如改成 `Hiyori.model3.json`）

### 3️⃣ 第三步：一键修复并启动

最后，修复并运行我们的全能管家：

```bash
# 1. 修复 Windows 换行符
sed -i 's/\r$//' setup_and_run.sh

# 2. 启动！
bash setup_and_run.sh
