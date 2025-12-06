#!/bin/bash

echo "🚑 开始修复网络连接问题..."

# 1. 强制修改 DNS (使用阿里 DNS + 谷歌 DNS)
echo "🌐 正在优化 DNS 设置..."
sudo cp /etc/resolv.conf /etc/resolv.conf.bak
# 写入稳定的 DNS 服务器
sudo bash -c 'echo "nameserver 223.5.5.5" > /etc/resolv.conf'
sudo bash -c 'echo "nameserver 8.8.8.8" >> /etc/resolv.conf'
echo "✅ DNS 已切换为阿里(223.5.5.5)和谷歌(8.8.8.8)"

# 2. 强制 Cloudflare 使用 HTTP2 协议 (更稳定)
# 找到 tunnel_config.yml 并插入 protocol: http2
CONFIG_FILE="$(pwd)/tunnel_config.yml"

if [ -f "$CONFIG_FILE" ]; then
    echo "🔧 正在修改隧道协议为 http2..."
    # 检查是否已经存在 protocol 配置
    if grep -q "protocol:" "$CONFIG_FILE"; then
        # 如果有，替换它
        sed -i 's/protocol:.*/protocol: http2/' "$CONFIG_FILE"
    else
        # 如果没有，在 tunnel: ID 下面插入一行
        sed -i '/tunnel: .*/a protocol: http2' "$CONFIG_FILE"
    fi
    echo "✅ 隧道配置已更新"
else
    echo "⚠️ 未找到 tunnel_config.yml，请确保您在项目根目录运行此脚本。"
fi

echo "\n🚀 正在重启服务以应用更改..."
# 杀掉旧进程
pkill -f cloudflared
pkill -f gunicorn

# 重启
bash setup_and_run.sh
