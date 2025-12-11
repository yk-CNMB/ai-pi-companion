#!/bin/bash

# =======================================================================
# 树莓派 DNS 诊断与自动修复脚本
# 目标：根治域名解析失败问题 (No address associated with hostname)
# =======================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}--- 🌐 自动 DNS 诊断与修复开始 ---${NC}"

# --- 1. 自动识别主网络接口 ---
INTERFACE_NAME=$(ip a | grep 'state UP' | awk '{print $2}' | sed 's/://' | head -n 1)

if [ -z "$INTERFACE_NAME" ]; then
    echo -e "${RED}❌ 错误：未检测到处于 'UP' 状态的主网络接口。请检查网络连接。${NC}"
    echo "请手动指定接口名称 (如 eth0 或 wlan0):"
    read -r INTERFACE_NAME
fi

echo -e "${YELLOW}✅ 检测到主网络接口: $INTERFACE_NAME ${NC}"

# --- 2. 安装/更新关键网络工具 ---
echo -e "${YELLOW}⚙️ 正在更新系统并安装 dnsutils...${NC}"
sudo apt update -qq
sudo apt install dnsutils resolvconf -y -qq

# --- 3. 强制清除 Hosts 文件中的临时 IP ---
echo -e "${YELLOW}🧹 清理 hosts 文件中的旧 IP 记录...${NC}"
# 删除所有包含 tts.speech.microsoft.com 的行
sudo sed -i '/tts\.speech\.microsoft\.com/d' /etc/hosts
echo -e "${GREEN}✅ hosts 文件已清理。${NC}"

# --- 4. 强制重置网络配置 ---
echo -e "${YELLOW}🔄 强制释放并重新获取 DHCP 租约... (可能导致 SSH 瞬断)${NC}"

# 尝试使用 dhclient 重置
if command -v dhclient &> /dev/null; then
    sudo dhclient -r "$INTERFACE_NAME" > /dev/null 2>&1
    sudo dhclient "$INTERFACE_NAME" > /dev/null 2>&1
    echo -e "${GREEN}✅ DHCP 租约已刷新。${NC}"
else
    # 尝试重启网络服务 (如 dhcpcd 或 networking)
    if systemctl is-active --quiet dhcpcd; then
        sudo systemctl restart dhcpcd
        echo -e "${GREEN}✅ dhcpcd 服务已重启。${NC}"
    elif systemctl is-active --quiet networking; then
        sudo systemctl restart networking
        echo -e "${GREEN}✅ networking 服务已重启。${NC}"
    else
        echo -e "${RED}⚠️ 警告：未找到常用的 DHCP 客户端服务，网络重置可能失败。${NC}"
    fi
fi

# --- 5. 最终 DNS 状态验证 ---
echo -e "${BLUE}--- 🌍 最终 DNS 状态验证 ---${NC}"

# 检查 resolv.conf 是否包含公共 DNS
RESOLV_CONTENT=$(cat /etc/resolv.conf)
if ! echo "$RESOLV_CONTENT" | grep -q "8.8.8.8" && ! echo "$RESOLV_CONTENT" | grep -q "1.1.1.1"; then
    echo -e "${YELLOW}⚠️ resolv.conf 文件可能不完整，正在添加公共 DNS...${NC}"
    echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf > /dev/null
    echo "nameserver 1.1.1.1" | sudo tee -a /etc/resolv.conf > /dev/null
fi
echo -e "${GREEN}✅ 当前 /etc/resolv.conf 内容：${NC}"
cat /etc/resolv.conf

# 权威测试：ping 谷歌 (测试基础互联网连接)
echo -e "${BLUE}1. 测试基础连接 (Ping Google):${NC}"
ping -c 4 google.com

# 权威测试：ping 微软 TTS (测试故障域名解析)
echo -e "${BLUE}2. 测试 TTS 域名解析 (Ping TTS 域名):${NC}"
TTS_PING_OUTPUT=$(ping -c 4 tts.speech.microsoft.com 2>&1)
echo "$TTS_PING_OUTPUT"

if echo "$TTS_PING_OUTPUT" | grep -q "from"; then
    echo -e "${GREEN}🥳 恭喜！TTS 域名解析已恢复！问题已根治！${NC}"
else
    echo -e "${RED}🛑 DNS 根治失败！域名仍然无法解析。${NC}"
    echo -e "${YELLOW}💡 解决方案：将采用 Hosts 应急措施，保证 TTS 功能立即可用。${NC}"
    
    # 应急措施：硬编码 IP
    echo '52.184.220.107 tts.speech.microsoft.com' | sudo tee -a /etc/hosts > /dev/null
    echo -e "${GREEN}✅ 已将 IP 写入 hosts 文件作为应急方案。${NC}"
    
    # 最终验证应急措施
    echo -e "${BLUE}3. 验证应急方案 (Ping 应急 IP):${NC}"
    ping -c 4 tts.speech.microsoft.com
    echo -e "${GREEN}TTS 功能现在应该可以工作了（通过 hosts 绕过）。${NC}"
fi

echo -e "${BLUE}--- 🌐 诊断与修复结束。请重新启动您的主应用。 ---${NC}"
