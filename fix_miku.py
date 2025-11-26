import os
import json
import shutil
import glob

# --- 配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIKU_DIR = os.path.join(BASE_DIR, "static", "live2d", "miku")
# ----------------

print(f"🔧 正在修复 Miku 模型: {MIKU_DIR}")

# 1. 找到配置文件
json_files = glob.glob(os.path.join(MIKU_DIR, "*.model3.json"))
if not json_files:
    print("❌ 错误：找不到 .model3.json 配置文件")
    exit()

config_file = json_files[0]
print(f"📄 读取配置: {os.path.basename(config_file)}")

with open(config_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 2. 准备新的动作目录
new_motion_dir = os.path.join(MIKU_DIR, "motions")
os.makedirs(new_motion_dir, exist_ok=True)

# 3. 找到那个乱码文件夹 (通常是唯一的子文件夹)
garbled_dir = None
for item in os.listdir(MIKU_DIR):
    full_path = os.path.join(MIKU_DIR, item)
    if os.path.isdir(full_path) and item != "motions" and item != "livehimeConfig" and item != "MIKU.4096":
        garbled_dir = full_path
        print(f"🗑️ 发现乱码文件夹: {item}")
        break

# 4. 遍历并重命名动作
motions = data.get("FileReferences", {}).get("Motions", {})
print(f"\n🤖 正在重构动作路径...")

new_motions = {}
count = 1

for group, list_motions in motions.items():
    new_list = []
    print(f"  📂 分组 [{group}]:")
    for m in list_motions:
        old_rel_path = m.get("File", "")
        old_filename = os.path.basename(old_rel_path)
        
        # 在乱码文件夹里找这个文件
        if garbled_dir:
            old_abs_path = os.path.join(garbled_dir, old_filename)
        else:
            old_abs_path = os.path.join(MIKU_DIR, old_rel_path)
            
        # 如果找不到，尝试模糊匹配 (忽略乱码差异)
        if not os.path.exists(old_abs_path) and garbled_dir:
             # 简单策略：按顺序对应？还是尝试匹配扩展名？
             # 这里为了稳妥，我们尝试在 garbled_dir 里找 .motion3.json
             candidates = glob.glob(os.path.join(garbled_dir, "*.motion3.json"))
             # 这里简化处理：假设 json 里的顺序和文件夹里的文件能对应上是很难的
             # 我们采用保守策略：如果文件存在，就搬运；不存在，就跳过
             pass

        if os.path.exists(old_abs_path):
            # 重命名为英文
            new_filename = f"{group.lower()}_{count:02d}.motion3.json"
            new_abs_path = os.path.join(new_motion_dir, new_filename)
            
            shutil.copy(old_abs_path, new_abs_path)
            
            # 更新 JSON
            m["File"] = f"motions/{new_filename}"
            new_list.append(m)
            print(f"    ✅ {old_filename} -> motions/{new_filename}")
            count += 1
        else:
            print(f"    ⚠️ 文件丢失: {old_filename} (跳过)")
            
    if new_list:
        new_motions[group] = new_list

# 5. 保存新的配置文件
data["FileReferences"]["Motions"] = new_motions
with open(config_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\n✅ 模型修复完成！")
print("="*30)
print("🎬 可用的动作分组 (请复制发给 AI):")
for g in new_motions.keys():
    print(f" - {g}")
print("="*30)
