#!/bin/bash

# =======================================================================
# TTS 残留清理脚本
# 彻底移除 edge-tts 及其相关文件，为 pyttsx3 本地 TTS 方案做准备。
# =======================================================================

CDIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$CDIR/.venv"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}--- 🧹 TTS 残留清理程序启动 ---${NC}"

# 1. 停止所有相关服务
echo -e "${YELLOW}🔄 正在停止 Flask/Gunicorn 和 Cloudflare 隧道...${NC}"
pkill -f "gunicorn"
pkill -f "cloudflared"
echo -e "${GREEN}✅ 服务已停止。${NC}"

# 2. 激活虚拟环境
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}✅ 虚拟环境已激活。${NC}"
else
    echo -e "${RED}❌ 错误：未找到虚拟环境 ${VENV_DIR}。请先创建或进入项目目录。${NC}"
    exit 1
fi

# 3. 卸载 edge-tts
echo -e "${YELLOW}📦 正在卸载 edge-tts 包...${NC}"
pip uninstall edge-tts -y > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ edge-tts 已成功卸载。${NC}"
else
    echo -e "${YELLOW}⚠️ edge-tts 似乎未安装或已移除 (继续清理)。${NC}"
fi

# 4. 清理 hosts 文件中的硬编码 IP
TTS_DOMAIN="tts.speech.microsoft.com"
echo -e "${YELLOW}🧹 正在清除 /etc/hosts 中 ${TTS_DOMAIN} 的硬编码 IP...${NC}"
# 移除所有包含 tts.speech.microsoft.com 的行
sudo sed -i.tts_bak '/tts\.speech\.microsoft\.com/d' /etc/hosts 2>/dev/null

if [ -f "/etc/hosts.tts_bak" ]; then
    echo -e "${GREEN}✅ hosts 文件已清理。旧备份文件 /etc/hosts.tts_bak 已保留。${NC}"
else
    echo -e "${GREEN}✅ hosts 文件无需清理或已清理。${NC}"
fi

# 5. 删除所有临时 TTS 音频文件
AUDIO_DIR="$CDIR/static/audio"
echo -e "${YELLOW}🗑️ 正在删除所有临时 TTS 音频文件 (${AUDIO_DIR}/)...${NC}"
find "$AUDIO_DIR" -type f -name "*.mp3" -delete 2>/dev/null
find "$AUDIO_DIR" -type f -name "*.wav" -delete 2>/dev/null
echo -e "${GREEN}✅ 临时音频文件已清除。${NC}"

# 6. 清除所有可能的 patch 备份文件 (例如 constants.py.bak)
echo -e "${YELLOW}🧹 清理所有补丁备份文件...${NC}"
find "$VENV_DIR" -type f -name "*.bak" -delete 2>/dev/null
find "$CDIR" -type f -name "fix_*" -delete 2>/dev/null # 删除所有修复脚本
echo -e "${GREEN}✅ 补丁和脚本已清除。${NC}"

# 7. 退出虚拟环境
deactivate

echo -e "${BLUE}--- 🎉 清理完成。系统已完全切换到本地 TTS 方案。---${NC}"
