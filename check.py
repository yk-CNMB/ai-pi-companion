import requests
import time
import os

# 目标 API (Miku 模型 ID 165)
API_URL = "https://artrajz-vits-simple-api.hf.space/voice/vits?text=你好&id=165&format=wav&lang=zh"

def test():
    print(f"📡 正在连接 VITS API...")
    print(f"🔗 地址: {API_URL}")
    print("⏳ 等待响应中 (HuggingFace 空间可能需要 1-2 分钟唤醒，请耐心等待)...")
    
    start_time = time.time()
    
    try:
        # 设置超长超时时间 (120秒)
        response = requests.get(API_URL, timeout=120)
        
        end_time = time.time()
        duration = end_time - start_time
        
        if response.status_code == 200:
            size_kb = len(response.content) / 1024
            print(f"\n✅ 成功连通！")
            print(f"⏱️ 耗时: {duration:.2f} 秒")
            print(f"📦 数据大小: {size_kb:.2f} KB")
            
            # 保存试听
            with open("test_miku.wav", "wb") as f:
                f.write(response.content)
            print("💾 已保存测试音频到: test_miku.wav (可以用播放器听一下)")
            
            if duration > 15:
                print(f"\n⚠️ 警告：响应时间 ({duration:.2f}s) 超过了 app.py 的默认限制 (15s)！")
                print("👉 这就是为什么您之前听到的是 Edge-TTS。必须增加超时时间。")
            else:
                print("\n🚀 速度很棒！API 当前是活跃状态。")
                
        else:
            print(f"\n❌ 服务器返回错误: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"\n❌ 连接失败: {e}")

if __name__ == "__main__":
    test()
