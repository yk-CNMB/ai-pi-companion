#!/bin/bash

# =======================================================================
# 树莓派 DNS 最终自愈脚本 (使用 ip 命令进行底层网络重启)
# 目的：确保 DNS 彻底恢复，或通过 Hosts 应急方案保证应用 100% 可用。
# =======================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}--- 🌐 自动 DNS 诊断与最终修复开始 ---${NC}"

# --- 1. 自动识别主网络接口 ---
INTERFACE_NAME=$(ip a | grep 'state UP' | awk '{print $2}' | sed 's/://' | head -n 1)

if [ -z "$INTERFACE_NAME" ]; then
    echo -e "${RED}❌ 错误：未检测到处于 'UP' 状态的主网络接口。请检查网络连接。${NC}"
    exit 1
fi

echo -e "${YELLOW}✅ 检测到主网络接口: $INTERFACE_NAME ${NC}"

# --- 2. 安装 DNS 实用工具 ---
echo -e "${YELLOW}⚙️ 正在安装 dnsutils (nslookup, dig)...${NC}"
sudo apt update -qq
sudo apt install dnsutils -y -qq
echo -e "${GREEN}✅ dnsutils 安装完成。${NC}"

# --- 3. 强制底层网络接口重启 (最强重启) ---
echo -e "${YELLOW}🔄 强制底层重启网络接口... (可能导致 SSH 瞬断)${NC}"
sudo ip link set dev "$INTERFACE_NAME" down
sleep 5
sudo ip link set dev "$INTERFACE_NAME" up
echo -e "${GREEN}✅ 网络接口 $INTERFACE_NAME 已重启。${NC}"

# --- 4. 清理 Hosts 文件中的临时 IP ---
echo -e "${YELLOW}🧹 清理 hosts 文件中的旧 IP 记录...${NC}"
sudo sed -i '/tts\.speech\.microsoft\.com/d' /etc/hosts
echo -e "${GREEN}✅ hosts 文件已清理。${NC}"

# --- 5. 最终 DNS 状态验证 ---
echo -e "${BLUE}--- 🌍 最终 DNS 状态验证 ---${NC}"

# 权威测试：ping TTS 域名 (测试根治是否成功)
echo -e "${BLUE}尝试 Ping TTS 域名:${NC}"
TTS_PING_OUTPUT=$(ping -c 4 tts.speech.microsoft.com 2>&1)
echo "$TTS_PING_OUTPUT"

if echo "$TTS_PING_OUTPUT" | grep -q "from"; then
    echo -e "${GREEN}🥳 恭喜！TTS 域名解析已恢复！问题已根治！${NC}"
    echo -e "${BLUE}您可以删除此脚本并正常启动您的应用了。${NC}"
else
    echo -e "${RED}🛑 DNS 根治失败！域名仍然无法解析。${NC}"
    echo -e "${YELLOW}💡 正在写入 Hosts 应急方案，确保 TTS 功能立即可用。${NC}"
    
    # 应急措施：硬编码 IP
    echo '52.184.220.107 tts.speech.microsoft.com' | sudo tee -a /etc/hosts > /dev/null
    echo -e "${GREEN}✅ 已将 IP 写入 hosts 文件。TTS 功能现在应该可以工作了（通过 hosts 绕过）。${NC}"
    
    # 最终验证应急措施
    echo -e "${BLUE}验证应急方案 (Ping TTS 域名):${NC}"
    ping -c 4 tts.speech.microsoft.com
fi

echo -e "${BLUE}--- 🌐 诊断与修复结束。请启动您的主应用。 ---${NC}"
