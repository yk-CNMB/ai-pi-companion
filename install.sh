#!/bin/bash

# =======================================================================
# edge-tts 域名硬编码修复脚本
# 目的：将硬编码的域名 tts.speech.microsoft.com 替换为已知的 IP 地址，
#       彻底绕过 DNS 故障，实现 TTS 功能的根治。
# =======================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 已知可用的微软 TTS IP 地址
TTS_IP="52.184.220.107"
# edge-tts 内部硬编码的域名
OLD_DOMAIN="tts.speech.microsoft.com"

echo -e "${BLUE}--- 🛠️ TTS 域名硬编码补丁开始 ---${NC}"

# 1. 查找 edge_tts 库路径
VENV_PATH=$(realpath .venv)
TARGET_FILE="$VENV_PATH/lib/$(ls $VENV_PATH/lib)/site-packages/edge_tts/constants.py"

if [ ! -f "$TARGET_FILE" ]; then
    echo -e "${RED}❌ 错误：未找到目标文件 $TARGET_FILE。请确认虚拟环境已激活且 edge-tts 已安装。${NC}"
    exit 1
fi

echo -e "${YELLOW}✅ 目标文件路径: $TARGET_FILE ${NC}"

# 2. 创建备份
BACKUP_FILE="${TARGET_FILE}.bak"
if [ ! -f "$BACKUP_FILE" ]; then
    cp "$TARGET_FILE" "$BACKUP_FILE"
    echo -e "${YELLOW}✅ 已创建备份文件: $BACKUP_FILE ${NC}"
fi

# 3. 执行替换操作
# 使用 sed 查找硬编码的 DOMAIN 变量，并将其替换为 IP 地址
# 注意: 我们替换的是 Python 源代码中的字符串常量，需要保留引号。
# 将 'tts.speech.microsoft.com' 替换为 '52.184.220.107'
sed_command="s/${OLD_DOMAIN}/${TTS_IP}/g"
sudo sed -i.tmp "$sed_command" "$TARGET_FILE"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}🥳 恭喜！源代码文件已成功打补丁。${NC}"
    echo -e "${GREEN}   ${OLD_DOMAIN} 已被替换为 ${TTS_IP}${NC}"
else
    echo -e "${RED}❌ 错误：应用补丁失败，请手动检查 $TARGET_FILE 文件。${NC}"
    # 恢复备份
    mv "${TARGET_FILE}.tmp" "$TARGET_FILE"
    exit 1
fi

# 4. 清理临时文件
if [ -f "${TARGET_FILE}.tmp" ]; then
    rm "${TARGET_FILE}.tmp"
fi

echo -e "${BLUE}---  TTS 故障已在底层根治。请重新启动主应用。 ---${NC}"
