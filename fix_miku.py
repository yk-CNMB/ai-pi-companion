import os
import json
import shutil
import glob

# --- 配置 ---
# 这里指向你的 miku 文件夹
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_ROOT = os.path.join(BASE_DIR, "static", "live2d", "miku")
# ----------------

print(f"🔧 正在修复 Miku 模型路径: {MODEL_ROOT}")

if not os.path.exists(MODEL_ROOT):
    print(f"❌ 错误：找不到目录 {MODEL_ROOT}")
    print("请确认你的 miku 文件夹名字是小写的 'miku' 还是大写的 'MIKU'？")
    # 尝试自动纠错大小写
    parent = os.path.dirname(MODEL_ROOT)
    if os.path.exists(os.path.join(parent, "MIKU")):
        MODEL_ROOT = os.path.join(parent, "MIKU")
        print(f"⚠️ 已自动修正为: {MODEL_ROOT}")
    else:
        exit()

# 1. 处理中文文件夹 "表情和动作"
# 目标是将它改名为 "motions"
CHINESE_DIR_NAME = "表情和动作"
TARGET_DIR_NAME = "motions"

old_motion_dir = os.path.join(MODEL_ROOT, CHINESE_DIR_NAME)
new_motion_dir = os.path.join(MODEL_ROOT, TARGET_DIR_NAME)

# 尝试寻找各种可能的乱码名，或者直接找中文名
found_dir = False
if os.path.exists(old_motion_dir):
    print(f"✅ 发现中文文件夹: {CHINESE_DIR_NAME}")
    if os.path.exists(new_motion_dir):
        print("   (motions 文件夹已存在，准备合并)")
    else:
        os.rename(old_motion_dir, new_motion_dir)
        print(f"✅ 已重命名为: {TARGET_DIR_NAME}")
    found_dir = True
elif os.path.exists(new_motion_dir):
    print("✅ 文件夹已经是 motions 了，继续检查文件...")
    found_dir = True
else:
    # 暴力搜索：找那个不是 livehimeConfig 且包含 json 的文件夹
    print("⚠️ 未找到标准中文文件夹，尝试智能搜索...")
    for item in os.listdir(MODEL_ROOT):
        full_path = os.path.join(MODEL_ROOT, item)
        if os.path.isdir(full_path) and item not in ["livehimeConfig", "MIKU.4096", "motions"]:
            # 检查里面有没有 json
            if glob.glob(os.path.join(full_path, "*.json")):
                print(f"🧐 发现疑似动作文件夹: {item}")
                os.rename(full_path, new_motion_dir)
                print(f"✅ 强制重命名为: {TARGET_DIR_NAME}")
                found_dir = True
                break

if not found_dir:
    print("❌ 无法定位动作文件夹，请手动检查目录结构。")
    exit()

# 2. 读取并修改 .model3.json
json_files = glob.glob(os.path.join(MODEL_ROOT, "*.model3.json"))
if not json_files:
    print("❌ 找不到 .model3.json 配置文件")
    exit()

config_file = json_files[0]
print(f"📄 读取配置: {os.path.basename(config_file)}")

try:
    with open(config_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
except:
    # 尝试 GBK (防乱码)
    with open(config_file, 'r', encoding='gbk', errors='ignore') as f:
        data = json.load(f)

# 3. 遍历动作和表情，重命名文件并更新引用
# 这一步最关键：我们要把 data 里的引用和磁盘上的文件同步修改

def process_files(file_list_dict, type_name):
    """
    file_list_dict: 比如 data['FileReferences']['Motions']
    type_name: 'motion' 或 'exp'
    """
    if not file_list_dict: return
    
    count = 1
    print(f"\n🔄 处理 {type_name}...")
    
    # 如果是 Motions，它是  Group -> List -> Item
    # 如果是 Expressions，它是 List -> Item
    
    # 统一处理逻辑：找到旧路径 -> 生成新路径 -> 重命名 -> 更新 JSON
    
    # 辅助函数：处理单个文件条目
    def handle_item(item_data):
        nonlocal count
        old_rel_path = item_data.get("File", "")
        if not old_rel_path: return
        
        # 无论旧路径写的是 "表情和动作/xx" 还是 "motions/xx"
        # 我们都去 new_motion_dir (也就是现在的 motions 文件夹) 里找
        old_filename = os.path.basename(old_rel_path)
        current_abs_path = os.path.join(new_motion_dir, old_filename)
        
        if not os.path.exists(current_abs_path):
            print(f"   ⚠️ 丢失: {old_filename} (跳过)")
            return

        # 生成纯英文新名字
        ext = old_filename.split('.')[-1]
        # 简单起见，动作叫 m_01.json, 表情叫 e_01.json
        # 实际上你的文件通常是 .motion3.json
        new_filename = f"{type_name}_{count:02d}_{uuid.uuid4().hex[:4]}.json"
        if "motion3.json" in old_filename:
             new_filename = f"{type_name}_{count:02d}.motion3.json"
        
        new_abs_path = os.path.join(new_motion_dir, new_filename)
        
        # 重命名文件
        os.rename(current_abs_path, new_abs_path)
        
        # 更新 JSON 配置
        item_data["File"] = f"{TARGET_DIR_NAME}/{new_filename}"
        print(f"   ✨ {old_filename} -> {new_filename}")
        count += 1

    # 开始遍历
    if isinstance(file_list_dict, dict): # Motions 是字典
        for group, items in file_list_dict.items():
            print(f"  📂 分组: {group}")
            for item in items:
                handle_item(item)
    elif isinstance(file_list_dict, list): # Expressions 是列表
        for item in file_list_dict:
            handle_item(item)

import uuid

# 处理动作
if "Motions" in data.get("FileReferences", {}):
    process_files(data["FileReferences"]["Motions"], "motion")

# 处理表情
if "Expressions" in data.get("FileReferences", {}):
    process_files(data["FileReferences"]["Expressions"], "exp")

# 4. 保存修改后的配置
with open(config_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\n✅ 修复完成！所有中文路径已标准化。")
print("请刷新网页，应该能看到模型了。")

