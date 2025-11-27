import os
import json

# 寻找模型目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIKU_DIR = os.path.join(BASE_DIR, "static", "live2d", "miku")

def inspect():
    print(f"🕵️‍♂️ 正在透视 Miku 模型: {MIKU_DIR}")
    
    if not os.path.exists(MIKU_DIR):
        print("❌ 目录不存在！")
        return

    # 1. 寻找配置文件 (兼容 .model.json 和 .model3.json)
    json_files = [f for f in os.listdir(MIKU_DIR) if f.endswith(('.model.json', '.model3.json'))]
    if not json_files:
        print("❌ 找不到任何配置文件 (.model.json 或 .model3.json)")
        return
    
    target_file = os.path.join(MIKU_DIR, json_files[0])
    print(f"📄 找到配置文件: {json_files[0]}")
    
    try:
        with open(target_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ JSON 损坏: {e}")
        return

    # 2. 暴力搜索动作字段
    print("\n🔍 JSON 结构分析:")
    print(f"   顶级键: {list(data.keys())}")
    
    motions = None
    motion_key_found = None

    # 尝试各种可能的键名
    if 'FileReferences' in data and 'Motions' in data['FileReferences']:
        print("   ✅ 识别为 Cubism 3/4 结构 (FileReferences.Motions)")
        motions = data['FileReferences']['Motions']
    elif 'Motions' in data:
        print("   ✅ 识别为 Cubism 3 结构 (Motions)")
        motions = data['Motions']
    elif 'motions' in data:
        print("   ✅ 识别为 Cubism 2 结构 (motions - 小写)")
        motions = data['motions']
    
    if motions:
        print(f"\n🎬 发现动作组 (共 {len(motions)} 组):")
        for group_name, motion_list in motions.items():
            print(f"   📂 组名: [{group_name}]")
            # 打印前3个文件作为示例
            for i, m in enumerate(motion_list[:3]):
                fname = m.get('file') or m.get('File') or "???"
                print(f"      - {fname}")
            if len(motion_list) > 3:
                print("      ... (更多)")
        
        print("\n💡 诊断建议:")
        print("   请检查上面的【组名】和【文件名】。")
        print("   如果文件名已经是 happy_01.mtn 这种英文格式，说明修复成功。")
        print("   如果还是中文，请重新运行 fix_miku_final.py")
    else:
        print("❌ 严重警告：在 JSON 里没找到任何动作定义！模型可能是个只会站桩的空壳。")

if __name__ == "__main__":
    inspect()
