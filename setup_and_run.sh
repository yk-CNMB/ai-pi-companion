#!/bin/bash

# ============================================
# Pico AI 全能管家腳本 (修復版)
# 功能：自動更新、環境安裝、智能啟動
# ============================================

# 定義顏色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# 獲取腳本所在目錄絕對路徑
CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🤖 歡迎使用 Pico AI 全能管家${NC}"
echo -e "${BLUE}========================================${NC}"

# --- 階段 0: 自動更新 ---
echo -e "🔄 正在檢查 GitHub 更新..."
# 嘗試拉取，如果失敗（比如有本地修改衝突），則強制重置並拉取
if ! git pull; then
    echo -e "${RED}⚠️ 檢測到更新衝突，正在強制同步...${NC}"
    git reset --hard
    git pull
fi
echo -e "${GREEN}✅ 項目已同步到最新版本${NC}"
echo -e "${BLUE}----------------------------------------${NC}"

# --- 階段 1: 環境檢查與安裝 ---

# 1.1 檢查 Python 虛擬環境
if [ ! -d "$VENV_DIR" ]; then
    echo -e "📦 正在創建 Python 虛擬環境..."
    python3 -m venv "$VENV_DIR"
fi

# 1.2 激活虛擬環境
source "$VENV_DIR/bin/activate"

# 1.3 安裝/更新依賴
echo -e "📦 正在檢查依賴庫..."
cat > "$CDIR/requirements.txt" <<EOF
flask
flask-socketio
python-socketio
python-engineio
google-genai
edge-tts
eventlet
gunicorn
EOF
# 安靜安裝，只顯示錯誤
pip install -r "$CDIR/requirements.txt" -q
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ 依賴庫檢查完畢${NC}"
else
    echo -e "${RED}❌ 依賴安裝失敗，請檢查網絡！${NC}"
    read -p "是否嘗試繼續啟動? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then exit 1; fi
fi

# 1.4 智能安裝 Cloudflared (修復路徑問題)
if [ ! -f "$CDIR/cloudflared" ]; then
    echo -e "🌐 未檢測到 Cloudflared，正在下載..."
    ARCH=$(dpkg --print-architecture)
    # 根據架構選擇下載鏈接
    if [ "$ARCH" == "arm64" ]; then
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    else
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf.deb"
    fi
    
    wget -O cloudflared.deb "$URL"
    
    # 解壓並自動尋找二進制文件
    echo -e "📦 正在解壓..."
    dpkg-deb -x cloudflared.deb temp_cf
    
    # 使用 find 命令自動尋找 cloudflared 文件，避免路徑錯誤
    CF_BIN=$(find temp_cf -name cloudflared -type f | head -n 1)
    
    if [ -n "$CF_BIN" ]; then
        mv "$CF_BIN" "$CDIR/cloudflared"
        chmod +x "$CDIR/cloudflared"
        echo -e "${GREEN}✅ Cloudflared 安裝成功！${NC}"
    else
        echo -e "${RED}❌ Cloudflared 安裝失敗：找不到解壓後的文件${NC}"
        exit 1
    fi
    
    # 清理臨時文件
    rm -rf cloudflared.deb temp_cf
fi

# --- 階段 2: 啟動服務 ---

echo -e "\n${BLUE}--- 🚀 準備啟動 ---${NC}"

# 2.1 清理舊進程
pkill -f "gunicorn.*app:app"
pkill -f "$CDIR/cloudflared tunnel"

# 2.2 啟動 Gunicorn (AI 大腦)
echo -e "🧠 正在啟動 AI 大腦..."
"$VENV_DIR/bin/gunicorn" --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app --daemon

# 等待 Gunicorn 啟動
for i in {1..5}; do
    if pgrep -f "gunicorn.*app:app" > /dev/null; then
        echo -e "${GREEN}✅ AI 大腦啟動成功！${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 5 ]; then
        echo -e "${RED}❌ AI 大腦啟動失敗！請手動運行檢查。${NC}"
        exit 1
    fi
done

# 2.3 啟動 Cloudflare 隧道
echo -e "${GREEN}🌐 正在建立公網隧道... 請稍等片刻...${NC}"
echo -e "${BLUE}👇 複製下方出現的 trycloudflare.com 網址即可訪問 👇${NC}"
echo -e "${BLUE}========================================${NC}"

# 啟動隧道並過濾日誌
"$CDIR/cloudflared" tunnel --url http://localhost:5000 2>&1 | grep --line-buffered "trycloudflare.com"
```

覆蓋後，請再次運行：
```bash
bash setup_and_run.sh
