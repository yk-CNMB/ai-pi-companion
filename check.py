import os
import json
import requests
from google import genai

# 颜色
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

def check():
    print("🚑 Pico 全身检查启动...\n")
    
    # 1. 检查配置文件
    if not os.path.exists("config.json"):
        print(f"{RED}❌ 错误：找不到 config.json 文件！{RESET}")
        return
    
    try:
        # 能够处理带注释的 JSON
        with open("config.json", "r") as f:
            lines = [line for line in f.readlines() if not line.strip().startswith("//")]
            config = json.loads("\n".join(lines))
    except Exception as e:
        print(f"{RED}❌ 错误：config.json 格式不对！请检查逗号或引号。{RESET}")
        print(f"   详情: {e}")
        return

    gemini_key = config.get("GEMINI_API_KEY", "")
    fish_key = config.get("FISH_API_KEY", "")
    fish_id = config.get("FISH_VOICE_ID", "")

    # 2. 测试 Gemini (大脑)
    print("🧠 [1/2] 正在测试 Gemini API...")
    if "..." in gemini_key or len(gemini_key) < 20:
        print(f"{RED}❌ 失败：Gemini Key 看起来是无效的占位符。请填入真实的 Key！{RESET}")
    else:
        try:
            client = genai.Client(api_key=gemini_key)
            resp = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents="你好，测试一下。"
            )
            print(f"{GREEN}✅ 成功：Gemini 回复了 -> {resp.text}{RESET}")
        except Exception as e:
            print(f"{RED}❌ 失败：Gemini 报错。可能 Key 不对或网络不通。{RESET}")
            print(f"   错误信息: {e}")

    print("-" * 30)

    # 3. 测试 Fish Audio (嘴巴)
    print("👄 [2/2] 正在测试 Fish Audio API...")
    if "..." in fish_key or len(fish_key) < 10:
        print(f"{RED}❌ 失败：Fish Audio Key 看起来是无效的占位符。{RESET}")
    else:
        url = "https://api.fish.audio/v1/tts"
        headers = {
            "Authorization": f"Bearer {fish_key}",
            "Content-Type": "application/json"
        }
        data = {
            "text": "测试语音合成。",
            "reference_id": fish_id,
            "format": "mp3"
        }
        try:
            resp = requests.post(url, json=data, headers=headers, timeout=10)
            if resp.status_code == 200:
                print(f"{GREEN}✅ 成功：Fish Audio 生成了音频 ({len(resp.content)} bytes){RESET}")
            else:
                print(f"{RED}❌ 失败：Fish Audio 返回错误代码 {resp.status_code}{RESET}")
                print(f"   服务器回应: {resp.text}")
        except Exception as e:
            print(f"{RED}❌ 失败：无法连接 Fish Audio 服务器。{RESET}")
            print(f"   错误信息: {e}")

if __name__ == "__main__":
    check()
