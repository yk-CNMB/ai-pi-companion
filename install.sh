#!/bin/bash
# 安装 GlaDOS 英文模型 (替换当前的 Sherpa 模型)

BASE_DIR="static/voices/sherpa"
mkdir -p "$BASE_DIR"

echo "🧪 正在下载 GlaDOS 模型..."

# 1. 清空旧模型
rm -rf "$BASE_DIR"/*

# 2. 下载并解压
cd "$BASE_DIR"
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-glados.tar.bz2
tar xvf vits-piper-en_US-glados.tar.bz2

# 3. 整理文件 (app.py 默认读取 model.onnx)
# 解压后文件在 vits-piper-en_US-glados 子目录里，我们需要把它们拿出来
mv vits-piper-en_US-glados/*.onnx model.onnx
mv vits-piper-en_US-glados/tokens.txt .
# 注意：Piper 模型通常不需要 lexicon.txt，或者它集成在里面了，或者我们需要 espeak-ng-data
# 为了兼容我们的通用加载器，我们把 espeak 数据也放好
mv vits-piper-en_US-glados/espeak-ng-data .

# 清理
rm vits-piper-en_US-glados.tar.bz2
rm -rf vits-piper-en_US-glados

echo "⚠️ 注意：此模型只能说英语！请在工作室选择 'Sherpa VITS' 并发送英文测试。"
