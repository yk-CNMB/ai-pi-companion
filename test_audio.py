import requests
import msgpack # Fish Audio 推荐使用 msgpack，速度更快
import os

# ==============================
# 👇 填入你的信息
API_KEY = "167dd9e764d24454b69b12f28a0ee0a8"
MODEL_ID = "3d1cb00d75184099992ddbaf0fdd7387" # 你的流萤 ID
# ==============================

URL = "https://api.fish.audio/v1/tts"

def test():
    print(f"🐟 正在测试 Fish Audio 原生接口...")
    
    # 1. 构造原生请求
    # 注意：这里使用了 Content-Type: application/json 方便调试
    # 生产环境官方推荐 application/msgpack
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "text": "你好，我是流萤。这是原生接口测试。",
        "reference_id": MODEL_ID,
        "format": "mp3",
        "mp3_bitrate": 128,
        "latency": "normal" # normal, balanced, fast
    }
    
    try:
        response = requests.post(URL, json=payload, headers=headers, timeout=20)
        
        print(f"📡 状态码: {response.status_code}")
        
        if response.status_code == 200:
            with open("static/audio/fish_native.mp3", "wb") as f:
                f.write(response.content)
            print("✅ 成功！音频已保存到 static/audio/fish_native.mp3")
        else:
            print(f"❌ 失败: {response.text}")
            print("💡 分析：")
            if response.status_code == 401:
                print("   -> API Key 错误。请检查是否多复制了空格，或者 Key 已被删除。")
            elif response.status_code == 402:
                print("   -> 余额不足。请登录 fish.audio 控制台查看 Credit 余额。")
                print("   -> 注意：新注册账号可能需要验证邮箱才能获得免费额度。")
            elif response.status_code == 404:
                print("   -> 模型 ID 错误。请确认该模型是否已被作者删除或设为私有。")

    except Exception as e:
        print(f"❌ 网络错误: {e}")

if __name__ == "__main__":
    os.makedirs("static/audio", exist_ok=True)
    test()
