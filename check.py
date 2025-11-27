import os
import subprocess

# 颜色定义
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BASE_DIR, "static", "voices")
PIPER_BIN = os.path.join(BASE_DIR, "piper_engine", "piper")

def test_voice(model_name, test_text, lang_desc):
    model_path = os.path.join(VOICES_DIR, model_name)
    print(f"\n🎧 正在测试: {YELLOW}{model_name}{RESET} ({lang_desc})")
    
    # 1. 检查文件是否存在
    if not os.path.exists(model_path):
        print(f"   {RED}❌ 文件丢失！{RESET}")
        return

    # 2. 检查文件大小 (防止下载失败产生的空文件)
    size = os.path.getsize(model_path) / (1024 * 1024) # MB
    if size < 10:
        print(f"   {RED}❌ 文件过小 ({size:.2f} MB)，可能是坏文件！{RESET}")
        print("   建议重新运行 install_voices.sh")
        return
    else:
        print(f"   ✅ 文件大小正常: {size:.2f} MB")

    # 3. 尝试运行 Piper 生成音频
    print(f"   🧪 正在尝试合成文本: \"{test_text}\" ...")
    cmd = [PIPER_BIN, "--model", model_path, "--output_file", "/dev/null"]
    
    try:
        # 运行并捕获输出
        result = subprocess.run(
            cmd, 
            input=test_text.encode('utf-8'), 
            capture_output=True, 
            check=True
        )
        print(f"   {GREEN}✅ 引擎运行成功！模型可用。{RESET}")
    except subprocess.CalledProcessError as e:
        print(f"   {RED}❌ 引擎运行失败！{RESET}")
        print(f"   错误日志:\n{e.stderr.decode('utf-8')}")
        if "Phonemization error" in e.stderr.decode('utf-8') or "vector" in e.stderr.decode('utf-8'):
            print(f"   {YELLOW}💡 提示：这通常是因为输入了模型不支持的语言字符。{RESET}")

def main():
    print("🤖 Pico 语音医生正在启动...")
    
    if not os.path.exists(PIPER_BIN):
        print(f"{RED}❌ 致命错误：找不到 Piper 引擎！请运行 install_piper.sh{RESET}")
        return

    # 测试列表
    # 格式: (文件名, 测试文本, 描述)
    targets = [
        ("ja_JP-tokin.onnx", "こんにちは", "日语模型 - 必须用日语测试"),
        ("en_US-glados.onnx", "Hello world.", "英语模型 - 必须用英语测试"),
        ("zh_CN-huayan.onnx", "你好，我是测试员。", "中文模型 - 本地中文"),
    ]

    for fname, text, desc in targets:
        test_voice(fname, text, desc)

    print("\n========================================")
    print("📋 诊断总结：")
    print("1. 如果上面显示 ✅，说明模型没问题，是你发的文字语言不对。")
    print("2. 日语模型(Tokin) 只能读日语/罗马音。")
    print("3. 如果想让 Miku 说中文，只能用【Edge-TTS 晓晓】或者本地的【华岩】。")

if __name__ == "__main__":
    main()
