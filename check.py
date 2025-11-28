import requests
import time
import urllib.parse

# ==========================================
# 🔴 把您刚找到并拼凑好的 API 地址填在下面引号里
# ==========================================
# 记得保留 {text} 这个占位符
TARGET_URL = "https://ykout-vits-simple-api.hf.space/voice/vits?text={text}&id=165&format=wav&lang=zh"

def verify():
    print(f"🕵️‍♂️ 正在验证 API: {TARGET_URL}")
    
    # 构造测试链接
    test_text = "你好，我是初音未来。"
    final_url = TARGET_URL.replace("{text}", urllib.parse.quote(test_text))
    
    print("⏳ 发送请求中... (如果卡住超过 10 秒说明这个节点不行)")
    start = time.time()
    
    try:
        # 设置 10 秒超时，不惯着烂节点
        resp = requests.get(final_url, timeout=10)
        end = time.time()
        
        duration = end - start
        
        if resp.status_code == 200:
            content_type = resp.headers.get('Content-Type', '')
            size = len(resp.content)
            
            if size < 1000 or 'audio' not in content_type:
                print(f"❌ 失败：服务器返回了 200，但内容不对 (类型: {content_type}, 大小: {size}b)。")
                print("   可能原因：这是一个网页，不是 API 接口。请检查 URL 拼接格式。")
            else:
                print(f"\n✅ 成功！这个 API 是活的！")
                print(f"⚡ 耗时: {duration:.2f} 秒")
                print(f"📦 大小: {size/1024:.1f} KB")
                
                # 保存听听看
                with open("api_test.wav", "wb") as f:
                    f.write(resp.content)
                print("💾 已保存音频到 api_test.wav，快去听听是不是 Miku！")
                print("\n👉 确认无误后，把上面的 TARGET_URL 填进 config.json 即可！")
                
        elif resp.status_code == 503:
            print("❌ 失败：503 Service Unavailable")
            print("   原因：这个 Space 正在启动中（冷启动），或者挂了。")
            print("   建议：换一个 Space 试试。")
            
        else:
            print(f"❌ 失败：状态码 {resp.status_code}")
            print(f"   返回内容: {resp.text[:100]}")
            
    except Exception as e:
        print(f"❌ 连接超时或出错: {e}")

if __name__ == "__main__":
    verify()
