import asyncio
import edge_tts
import os

# 定义一个测试输出文件
OUTPUT_FILE = "static/audio/test_voice.mp3"
TEXT = "你好，听得到我的声音吗？我是Pico。"
VOICE = "zh-CN-XiaoxiaoNeural"

async def main():
    print(f"🎤 [1/3] 正在尝试使用 Edge-TTS 生成音频...")
    print(f"   - 文本: {TEXT}")
    print(f"   - 路径: {OUTPUT_FILE}")
    
    # 确保目录存在
    os.makedirs("static/audio", exist_ok=True)
    
    try:
        communicate = edge_tts.Communicate(TEXT, VOICE)
        await communicate.save(OUTPUT_FILE)
        print("✅ [2/3] 生成命令执行完毕。")
    except Exception as e:
        print(f"❌ [失败] Edge-TTS 报错: {e}")
        return

    # 检查文件
    if os.path.exists(OUTPUT_FILE):
        size = os.path.getsize(OUTPUT_FILE)
        print(f"📄 文件大小: {size} bytes")
        if size > 1000:
            print("✅ [3/3] 成功！音频文件已生成且大小正常。")
            print("👉 问题出在前端浏览器播放上！")
        else:
            print("❌ [失败] 文件生成了，但是是空的 (0KB)！")
            print("👉 问题出在网络连接或 Edge-TTS 库上！")
    else:
        print("❌ [失败] 文件根本没生成！")
        print("👉 问题出在文件权限或路径上！")

if __name__ == "__main__":
    asyncio.run(main())
