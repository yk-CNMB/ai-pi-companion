#!/bin/bash
# Pico 项目专用深度清理脚本

echo -e "\033[0;31m🗑️  开始深度清理...\033[0m"

# 1. 清理项目内的临时垃圾 (这些是之前失败的下载残留)
echo "正在清理临时下载文件..."
rm -rf temp_*
rm -rf pixi-live2d-display
rm -rf Live2d-model
rm -f *.deb
rm -f *.zip

# 2. 删除旧模型 (Shizuku)
# 如果你确定只要 Hiyori，这个旧模型就可以删了，能腾出好几 MB
if [ -d "static/live2d/shizuku" ]; then
    echo "正在删除旧模型 (Shizuku)..."
    rm -rf static/live2d/shizuku
fi

# 3. 系统级清理 (需要 sudo 权限)
echo "正在执行系统级清理 (apt)..."
sudo apt autoremove -y  # 删除不再需要的依赖包
sudo apt clean          # 删除已下载的安装包缓存

# 4. 清理用户缓存 (可选，经常能腾出不少空间)
echo "正在清理用户缓存..."
rm -rf ~/.cache/thumbnails/*
rm -rf ~/.cache/pip/*

echo -e "\033[0;32m✅ 清理完成！\033[0m"
echo "当前剩余空间："
df -h . | grep /
