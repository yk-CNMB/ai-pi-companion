import os
import requests
import sys

# 目标目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_DIR = os.path.join(BASE_DIR, "static", "voices")

if not os.path.exists(VOICE_DIR):
    os.makedirs(VOICE_DIR)

# 100% 可用的官方模型列表
MODELS = {
    "1": {
        "name": "Ami (强烈推荐 🔥) - 标准二次元少女音",
        "file": "ja_JP-ami-medium",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/ja/ja_JP/ami/medium/ja_JP-ami-medium.onnx"
    },
    "2": {
        "name": "Hina (温柔版) - 比较软萌",
        "file": "ja_JP-hina-medium",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/ja/ja_JP/hina/medium/ja_JP-hina-medium.onnx"
    },
    "3": {
        "name": "Maki (成熟版) - 稍微御姐一点",
        "file": "ja_JP-maki-medium",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/ja/ja_JP/maki/medium/ja_JP-maki-medium.onnx"
    }
}

def download(url, filename):
    filepath = os.path.join(VOICE_DIR, filename)
    print(f"   ⬇️  正在下载: {filename}...")
    try:
        response = requests.get(url, stream=True, timeout=15)
        response.raise_for_status() # 确保链接有效 (404会报错)
        total = int(response.headers.get('content-length', 0))
        with open(filepath, 'wb') as f:
            if total == 0:
                f.write(response.content)
            else:
                downloaded = 0
                for data in response.iter_content(chunk_size=4096):
                    downloaded += len(data)
                    f.write(data)
                    done = int(20 * downloaded / total)
                    sys.stdout.write(f"\r   [{'#' * done}{' ' * (20-done)}] {downloaded//1024}KB")
                    sys.stdout.flush()
        print(f"\n   ✅ 完成")
        return True
    except Exception as e:
        print(f"\n   ❌ 下载失败 ({e})")
        # 失败则删除空文件
        if os.path.exists(filepath): os.remove(filepath)
        return False

def main():
    print("=== 🎌 Piper 日语模型修复版 ===")
    for k, v in MODELS.items():
        print(f"{k}. {v['name']}")
    
    choice = input("\n请选择 (输入 1-3): ").strip()
    target = MODELS.get(choice)
    
    if not target:
        print("❌ 选择无效")
        return

    print(f"\n🚀 正在下载: {target['name']}")
    
    # 下载 .onnx
    if download(target['url'], target['file'] + ".onnx"):
        # 只有主文件成功了才下配置文件
        json_url = target['url'] + ".json"
        download(json_url, target['file'] + ".onnx.json")
        print("\n✨ 搞定！请刷新网页的“工作室”查看。")
        print("💡 记得把“语速”调快一点 (+10%) 会更像 Miku！")

if __name__ == "__main__":
    main()
