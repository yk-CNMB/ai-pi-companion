# -*- coding: utf-8 -*-
# =======================================================================
# TTS 诊断工具：用于独立测试 edge-tts 的核心功能
# 步骤 1: 确保在您的虚拟环境 (.venv) 中运行此脚本
# 步骤 2: 观察输出，特别是任何 'Error' 或 'Exception' 信息
# =======================================================================
import os
import sys
import subprocess
import time
import json

# --- 1. 读取配置 (如果有代理，确保读取) ---
CONFIG_FILE = "config.json"
PROXY_URL = ""
try:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding='utf-8') as f: 
            cfg = json.load(f)
            PROXY_URL = cfg.get("TTS_PROXY", "").strip()
            print(f"配置加载成功。代理 (PROXY): {PROXY_URL if PROXY_URL else '无'}")
except Exception as e:
    print(f"警告：无法加载 {CONFIG_FILE}，忽略代理配置: {e}")

# --- 2. 定义测试参数 ---
TEST_TEXT = "你好，这是一次 TTS 语音诊断测试，请检查是否成功生成文件。"
TEST_VOICE = "zh-CN-XiaoxiaoNeural"  # 您的默认语音
OUTPUT_FILE = f"tts_output_{int(time.time())}.mp3"
TTS_TIMEOUT = 30 # 缩短超时时间，快速失败

# --- 3. 构建 TTS 命令 ---
# 使用最基本、最兼容的参数
cmd = [
    sys.executable, "-m", "edge_tts",
    "--text", TEST_TEXT,
    "--write-media", OUTPUT_FILE,
    "--voice", TEST_VOICE,
    # 强制合规参数，虽然我们已经知道它们可能被 edge_tts 忽略或内部处理
    "--rate", "+0%", 
    "--pitch", "+0Hz"
]

# --- 4. 准备环境变量 (用于代理) ---
env = os.environ.copy()
if PROXY_URL:
    env["http_proxy"] = PROXY_URL
    env["https_proxy"] = PROXY_URL
    env["all_proxy"] = PROXY_URL # 尝试所有代理类型

# --- 5. 执行诊断 ---
print("\n--- 🤖 开始执行 TTS 诊断 ---")
print(f"测试文本: {TEST_TEXT}")
print(f"输出文件: {OUTPUT_FILE}")
print(f"执行命令: {' '.join(cmd)}")
print(f"Python 路径: {sys.executable}")
print("-" * 30)

try:
    start_time = time.time()
    result = subprocess.run(
        cmd, 
        check=True, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        timeout=TTS_TIMEOUT,
        env=env
    )
    duration = time.time() - start_time

    # 检查执行结果
    if result.returncode == 0 and os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 0:
        print("\n✅ 诊断成功！")
        print(f"文件大小: {os.path.getsize(OUTPUT_FILE)} 字节")
        print(f"耗时: {duration:.2f} 秒")
        print(f"请检查文件 {OUTPUT_FILE} 是否存在并可播放。")
    else:
        print("\n❌ 诊断失败 (执行成功但无音频)。")
        print(f"文件存在: {os.path.exists(OUTPUT_FILE)}")
        print(f"文件大小: {os.path.getsize(OUTPUT_FILE) if os.path.exists(OUTPUT_FILE) else 'N/A'} 字节")

    print("\n--- 详细输出 (stdout) ---")
    print(result.stdout.decode('utf-8', errors='ignore'))
    print("\n--- 错误输出 (stderr) ---")
    print(result.stderr.decode('utf-8', errors='ignore'))

except subprocess.CalledProcessError as e:
    print("\n❌ 诊断失败 (命令执行错误)。")
    print(f"错误码: {e.returncode}")
    print("\n--- 详细输出 (stdout) ---")
    print(e.stdout.decode('utf-8', errors='ignore'))
    print("\n--- 错误输出 (stderr) ---")
    print(e.stderr.decode('utf-8', errors='ignore'))

except subprocess.TimeoutExpired:
    print("\n❌ 诊断失败 (超时)。")
    print(f"TTS 在 {TTS_TIMEOUT} 秒内未能完成。")

except Exception as e:
    print(f"\n❌ 诊断失败 (未知异常): {e}")

print("\n--- 诊断结束 ---")
