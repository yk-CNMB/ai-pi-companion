import os
import json
import glob
import shutil

# --- 配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE2D_DIR = os.path.join(BASE_DIR, "static", "live2d")
# 假设只有一个 miku 文件夹，自动寻找
miku_candidates = glob.glob(os.path.join(LIVE2D_DIR, "*miku*"))
if not miku_candidates:
    # 如果没找到带 miku 的，就找所有文件夹
    miku_candidates = [d for d in glob.glob(os.path.join(LIVE2D_DIR, "*")) if os.path.isdir(d)]

if not miku_candidates:
    print("❌ 错误：static/live2d 下没有找到任何模型文件夹！")
    exit()

MODEL_ROOT = miku_candidates[0] # 取第一个找到的
print(f"🔧 锁定模型目录: {MODEL_ROOT}")

# 1. 文件夹标准化 (把中文文件夹改名为 motions)
target_motion_dir = os.path.join(MODEL_ROOT, "motions")
if not os.path.exists(target_motion_dir):
    os.makedirs(target_motion_dir)

# 扫描目录下所有子文件夹，寻找存放 json 的那个（通常是中文名）
for item in os.listdir(MODEL_ROOT):
    full_path = os.path.join(MODEL_ROOT, item)
    if os.path.isdir(full_path) and item not in ["motions", "livehimeConfig", "MIKU.4096"]:
        # 检查里面是否有 json
        if glob.glob(os.path.join(full_path, "*.json")):
            print(f"📦 发现资源文件夹: {item} -> 正在迁移...")
            # 把里面的文件全部移到 motions
            for f in os.listdir(full_path):
                shutil.move(os.path.join(full_path, f), target_motion_dir)
            os.rmdir(full_path)
            print("✅ 迁移完成")

# 2. 读取配置文件
json_files = glob.glob(os.path.join(MODEL_ROOT, "*.model3.json"))
if not json_files:
    print("❌ 找不到 .model3.json")
    exit()
config_file = json_files[0]

try:
    with open(config_file, 'r', encoding='utf-8') as f: data = json.load(f)
except:
    with open(config_file, 'r', encoding='gbk', errors='ignore') as f: data = json.load(f)

# 3. 暴力重命名逻辑
def rename_and_update(file_list_obj, prefix):
    """
    遍历列表/字典，重命名物理文件，并更新 JSON 引用
    """
    count = 0
    
    # 统一转为列表处理 (因为 Motions 是字典，Expressions 是列表)
    items_to_process = []
    if isinstance(file_list_obj, dict):
        for group, items in file_list_obj.items():
            for item in items:
                items_to_process.append(item)
    elif isinstance(file_list_obj, list):
        items_to_process = file_list_obj

    for item in items_to_process:
        old_rel_path = item.get("File", "")
        if not old_rel_path: continue
        
        old_name = os.path.basename(old_rel_path)
        # 在 motions 目录下找文件
        old_abs_path = os.path.join(target_motion_dir, old_name)
        
        if os.path.exists(old_abs_path):
            new_name = f"{prefix}_{count:02d}.json"
            new_abs_path = os.path.join(target_motion_dir, new_name)
            
            # 重命名物理文件
            if old_abs_path != new_abs_path:
                shutil.move(old_abs_path, new_abs_path)
            
            # 更新 JSON
            item["File"] = f"motions/{new_name}"
            print(f"   ✨ {old_name} -> {new_name}")
            count += 1

# 执行重命名
print("\n🔄 处理动作 (Motions)...")
if "Motions" in data.get("FileReferences", {}):
    rename_and_update(data["FileReferences"]["Motions"], "motion")

print("\n🔄 处理表情 (Expressions)...")
if "Expressions" in data.get("FileReferences", {}):
    rename_and_update(data["FileReferences"]["Expressions"], "exp")

# 4. 保存配置
with open(config_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\n✅ 修复完毕！文件名已全部标准化。")
print("请刷新网页查看效果。")
