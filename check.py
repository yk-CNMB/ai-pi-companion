import os
import json
from google import genai

# 颜色
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

def check():
    print("🚑 Pico 脑科检查启动...\n")
    
    # 1. 检查配置文件
    if not os.path.exists("config.json"):
        print(f"{RED}❌ 错误：找不到 config.json 文件！{RESET}")
        return
    
    try:
        # 兼容带注释的 json
        with open("config.json", "r") as f:
            lines = [line for line in f.readlines() if not line.strip().startswith("//")]
            config = json.loads("\n".join(lines))
    except Exception as e:
        print(f"{RED}❌ 错误：config.json 格式不对！{RESET}")
        print(f"   详情: {e}")
        return

    gemini_key = config.get("GEMINI_API_KEY", "")

    # 2. 测试 Gemini (大脑)
    print(f"🧠 正在测试 Gemini API (Key长度: {len(gemini_key)})...")
    
    if "..." in gemini_key or len(gemini_key) < 20:
        print(f"{RED}❌ 失败：Gemini Key 看起来是无效的占位符。请填入真实的 Key！{RESET}")
        return

    try:
        # 尝试建立连接
        client = genai.Client(api_key=gemini_key)
        print("   正在发送测试消息...")
        resp = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents="你好，Pico，听到请回答。"
        )
        print(f"{GREEN}✅ 成功：Gemini 回复了 -> {resp.text}{RESET}")
        print("\n🎉 诊断通过！如果网页还是没反应，请刷新网页或检查网络代理。")
        
    except Exception as e:
        print(f"{RED}❌ 失败：Gemini 报错。{RESET}")
        print(f"   错误信息: {e}")
        print("\n💡 建议：")
        print("   1. 检查 Key 是否抄错了。")
        print("   2. 树莓派是否能访问外网 (谷歌服务)。")

if __name__ == "__main__":
    check()
