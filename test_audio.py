import requests
import os

# ==========================================
# 👇 请根据你的服务商填写 👇
# ==========================================

# 情况 A: 如果你是 SiliconFlow (硅基流动)
# API_URL = "https://api.siliconflow.cn/v1/audio/speech"
# MODEL_ID = "fishaudio/fish-speech-1.5"

# 情况 B: 如果你是 Fish Audio 官方 (但 Key 格式不同)
# API_URL = "https://api.fish.audio/v1/audio/speech"
# MODEL_ID = "8ef4a238714b45718ce04243307c57a7"

# 👇 填在这里：
API_KEY = "sk-167dd9e764d24454b69b12f28a0ee0a8" # 你的 Key
API_URL = "https://api.fish.audio/v1/tts" # 你的 API 地址 (请确保带上 /v1/audio/speech)
MODEL_ID = "fishaudio/fish-speech-1.5" # 你的模型 ID
TEXT = "你好，我是Pico，这是语音测试。"
# ==========================================

OUTPUT_FILE = "static/audio/universal_test.mp3"

def test():
    print(f"🧪 正在测试通用 OpenAI TTS 接口...")
    print(f"📍 URL: {API_URL}")
    print(f"🆔 Model: {MODEL_ID}")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 标准 OpenAI TTS 格式
    payload = {
        "model": MODEL_ID,
        "input": TEXT,
        "voice": MODEL_ID, # 某些非标准接口需要这个
        "response_format": "mp3"
    }

    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=20)
        
        print(f"📡 状态码: {response.status_code}")
        
        if response.status_code == 200:
            # 检查是否真的是音频
            if len(response.content) > 100:
                with open(OUTPUT_FILE, "wb") as f:
                    f.write(response.content)
                print(f"✅ 成功！音频已保存到: {OUTPUT_FILE}")
                print(f"📊 大小: {os.path.getsize(OUTPUT_FILE)} bytes")
            else:
                print(f"❌ 失败：返回数据太小，可能是错误信息。")
                print(response.text)
        else:
            print(f"❌ API 报错: {response.text}")

    except Exception as e:
        print(f"❌ 网络错误: {e}")

if __name__ == "__main__":
    os.makedirs("static/audio", exist_ok=True)
    test()
