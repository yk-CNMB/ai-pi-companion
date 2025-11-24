import requests
import os

# ==========================================
# 👇 请在这里填入你的 Fish Audio 信息 👇
# ==========================================
API_KEY = "167dd9e764d24454b69b12f28a0ee0a8"
MODEL_ID = "3d1cb00d75184099992ddbaf0fdd7387" # 
TEXT = "你好，我是，听得到我的声音吗？"
# ==========================================

OUTPUT_FILE = "static/audio/fish_test.mp3"
API_URL = "https://api.fish.audio/v1/tts" # 注意：Fish Audio 最新版 API 路径可能变了

def test_fish():
    print(f"🐟 正在测试 Fish Audio API...")
    print(f"🔑 Key: {API_KEY[:5]}***")
    print(f"🆔 Model: {MODEL_ID}")

    # 尝试使用最新的官方推荐格式 (MessagePack 通常更快，但这里用 JSON 兼容性更好)
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    # Fish Audio 标准 Payload
    payload = {
        "text": TEXT,
        "reference_id": MODEL_ID, # 注意：有时是用 reference_id 而不是 model
        "format": "mp3",
        "mp3_bitrate": 128
    }

    try:
        print(f"📡 发送请求到: {API_URL}")
        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)

        print(f"📥 状态码: {response.status_code}")
        
        if response.status_code == 200:
            # 检查返回内容是否是音频
            content_type = response.headers.get('Content-Type', '')
            print(f"📄 返回类型: {content_type}")
            
            if 'audio' in content_type or len(response.content) > 1000:
                with open(OUTPUT_FILE, "wb") as f:
                    f.write(response.content)
                print(f"✅ 成功！音频已保存到: {OUTPUT_FILE}")
                print(f"📊 大小: {os.path.getsize(OUTPUT_FILE)} bytes")
            else:
                print(f"❌ 失败：返回的不是音频数据。内容预览：{response.text[:200]}")
        else:
            print(f"❌ API 报错: {response.text}")

    except Exception as e:
        print(f"❌ 网络或代码错误: {e}")

if __name__ == "__main__":
    os.makedirs("static/audio", exist_ok=True)
    test_fish()
```

### 🧪 步骤 2：运行测试

在树莓派终端运行：

```bash
source .venv/bin/activate
python test_fish.py
