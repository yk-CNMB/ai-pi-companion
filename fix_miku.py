import os
import json
import glob
import shutil

# 自动定位 live2d 目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE2D_ROOT = os.path.join(BASE_DIR, "static", "live2d")

print("🔧 正在搜索 Miku 模型...")

# 寻找包含 .model3.json 的 miku 文件夹
target_dir = None
for root, dirs, files in os.walk(LIVE2D_ROOT):
    for f in files:
        if f.lower().endswith(".model3.json") and "miku" in root.lower():
            target_dir = root
            print(f"✅ 找到模型目录: {target_dir}")
            break
    if target_dir: break

if not target_dir:
    print("❌ 未找到 Miku 模型，请确认已上传。")
    exit()

# 1. 处理中文文件夹
chinese_dir = None
for d in os.listdir(target_dir):
    # 寻找那个乱码或者叫"表情和动作"的文件夹
    if os.path.isdir(os.path.join(target_dir, d)) and d not in ["livehimeConfig", "MIKU.4096", "motions"]:
        chinese_dir = os.path.join(target_dir, d)
        print(f"📂 发现资源文件夹: {d}")
        break

motions_dir = os.path.join(target_dir, "motions")
if not os.path.exists(motions_dir):
    os.makedirs(motions_dir)

if chinese_dir:
    print("🚚 正在迁移文件...")
    for f in os.listdir(chinese_dir):
        shutil.move(os.path.join(chinese_dir, f), motions_dir)
    os.rmdir(chinese_dir)

# 2. 读取并修改配置文件
config_file = glob.glob(os.path.join(target_dir, "*.model3.json"))[0]
try:
    with open(config_file, 'r', encoding='utf-8') as f: data = json.load(f)
except:
    with open(config_file, 'r', encoding='gbk', errors='ignore') as f: data = json.load(f)

# 3. 重命名文件并更新引用
# 映射关系：我们将根据文件名前面的数字来保持顺序
# 例如 "01_生气.json" -> "motion_01.motion3.json"

def sanitize_files(file_list_obj, prefix):
    if isinstance(file_list_obj, dict):
        items = []
        for k, v in file_list_obj.items(): items.extend(v)
    else:
        items = file_list_obj
        
    for item in items:
        old_path = item.get("File", "")
        old_name = os.path.basename(old_rel_path := old_path.replace("\\", "/"))
        
        # 在 motions 目录下找
        old_abs = os.path.join(motions_dir, old_name)
        if not os.path.exists(old_abs):
            # 尝试模糊匹配 (忽略乱码)
            candidates = glob.glob(os.path.join(motions_dir, f"*{old_name[-5:]}")) # 匹配后缀
            # 还是找不到就算了
            continue
        
        # 提取序号 (如果文件名开头是数字)
        match = re.match(r"(\d+)_", old_name)
        idx = match.group(1) if match else "00"
        
        # 新名字
        new_name = f"{prefix}_{idx}.json"
        if "motion" in prefix: new_name = f"{prefix}_{idx}.motion3.json"
        
        new_abs = os.path.join(motions_dir, new_name)
        os.rename(old_abs, new_abs)
        
        # 更新 JSON
        item["File"] = f"motions/{new_name}"
        print(f"✨ 重命名: {old_name} -> motions/{new_name}")

import re
print("\n🔄 处理动作...")
if "Motions" in data.get("FileReferences", {}):
    sanitize_files(data["FileReferences"]["Motions"], "motion")

print("\n🔄 处理表情...")
if "Expressions" in data.get("FileReferences", {}):
    sanitize_files(data["FileReferences"]["Expressions"], "exp")

# 保存
with open(config_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\n✅ Miku 修复完成！")
