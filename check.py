import os
import json

# 设定项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIKU_DIR = os.path.join(BASE_DIR, "static", "live2d", "miku")

def check_integrity():
    print(f"🕵️‍♂️ 正在检查 Miku 模型完整性: {MIKU_DIR}")
    
    if not os.path.exists(MIKU_DIR):
        print("❌ 错误：Miku 目录不存在！")
        return

    # 1. 寻找 .model3.json
    json_files = [f for f in os.listdir(MIKU_DIR) if f.endswith('.model3.json')]
    if not json_files:
        print("❌ 错误：找不到 .model3.json 配置文件！")
        return
    
    config_file = os.path.join(MIKU_DIR, json_files[0])
    print(f"📄 读取配置文件: {json_files[0]}")
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ JSON 读取失败: {e}")
        return

    # 2. 检查动作文件引用
    # 兼容 Live2D 不同的 JSON 结构
    motion_groups = {}
    if 'FileReferences' in data and 'Motions' in data['FileReferences']:
        motion_groups = data['FileReferences']['Motions']
    elif 'Motions' in data:
        motion_groups = data['Motions']
    
    if not motion_groups:
        print("⚠️ 警告：JSON 中没有找到 'Motions' 定义！")
        return

    missing_count = 0
    total_count = 0

    print("\n🔍 开始校验动作文件路径...")
    for group_name, motions in motion_groups.items():
        print(f"   📂 检查动作组: [{group_name}]")
        for motion in motions:
            # 获取文件名
            file_rel_path = motion.get('File') or motion.get('file')
            if not file_rel_path:
                continue
            
            total_count += 1
            # 拼接绝对路径
            full_path = os.path.join(MIKU_DIR, file_rel_path)
            
            # 检查是否存在
            if os.path.exists(full_path):
                print(f"      ✅ 正常: {file_rel_path}")
            else:
                print(f"      ❌ 丢失: {file_rel_path}")
                print(f"         (系统试图寻找: {full_path})")
                missing_count += 1

    print("\n" + "="*30)
    print(f"📊 检查结果: 共扫描 {total_count} 个动作。")
    if missing_count > 0:
        print(f"❌ 发现 {missing_count} 个文件丢失（断链）！")
        print("💡 建议：这意味着 json 里写的文件路径和实际文件位置不符。")
        print("   请手动打开 miku 文件夹，确认文件到底在哪，或者再次运行 fix_miku_final.py")
    else:
        print("✅ 所有文件引用均正常。")

if __name__ == "__main__":
    check_integrity()

