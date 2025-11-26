import os
import json
import glob
import shutil
import re

# 定位 Miku 目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE2D_ROOT = os.path.join(BASE_DIR, "static", "live2d")

print("🔧 正在定位 Miku 模型...")
target_dir = None
for root, dirs, files in os.walk(LIVE2D_ROOT):
    for f in files:
        if f.lower().endswith(".model3.json") and "miku" in root.lower():
            target_dir = root
            break
    if target_dir: break

if not target_dir:
    print("❌ 未找到 Miku 文件夹")
    exit()
print(f"📂 锁定目录: {target_dir}")

# 1. 归拢文件夹 (处理乱码目录)
motions_dir = os.path.join(target_dir, "motions")
if not os.path.exists(motions_dir): os.makedirs(motions_dir)

# 扫描所有子文件夹，把里面的 json 提出来
for item in os.listdir(target_dir):
    full_path = os.path.join(target_dir, item)
    if os.path.isdir(full_path) and item not in ["motions", "livehimeConfig", "MIKU.4096"]:
        print(f"📦 处理资源文件夹: {item}")
        for f in os.listdir(full_path):
            shutil.move(os.path.join(full_path, f), motions_dir)
        os.rmdir(full_path)

# 2. 读取配置
config_file = glob.glob(os.path.join(target_dir, "*.model3.json"))[0]
try:
    with open(config_file, 'r', encoding='utf-8') as f: data = json.load(f)
except:
    with open(config_file, 'r', encoding='gbk', errors='ignore') as f: data = json.load(f)

# 3. 智能匹配重命名
# 逻辑：读取 JSON 里的旧文件名 -> 提取特征(数字) -> 在磁盘里找对应文件 -> 重命名
disk_files = os.listdir(motions_dir)

def sanitize(file_list_obj, type_prefix):
    items = []
    if isinstance(file_list_obj, dict):
        for k, v in file_list_obj.items(): items.extend(v)
    else:
        items = file_list_obj
        
    for item in items:
        old_path = item.get("File", "")
        old_name = os.path.basename(old_path) # e.g. "01_生气.json"
        
        # 提取特征：开头的数字 (01, 14...) 或 英文关键词 (Saihong)
        # 如果有数字，优先用数字匹配
        match_num = re.match(r"^(\d+)", old_name)
        target_file_on_disk = None
        
        if match_num:
            num_prefix = match_num.group(1) # "01"
            # 在磁盘文件里找以 "01" 开头的文件
            for df in disk_files:
                if df.startswith(num_prefix):
                    target_file_on_disk = df
                    break
        else:
            # 尝试模糊匹配 (比如 Saihong)
            clean_name = re.sub(r'[^\w]', '', old_name.split('.')[0]) # 去掉符号
            for df in disk_files:
                if clean_name in df or old_name[:3] in df:
                    target_file_on_disk = df
                    break
        
        if target_file_on_disk:
            # 生成标准新名字
            ext = ".json"
            if "motion3" in target_file_on_disk: ext = ".motion3.json"
            elif "exp3" in target_file_on_disk: ext = ".exp3.json"
            
            # 保留数字前缀以便人类阅读，或者用纯英文
            safe_name = f"{type_prefix}_{target_file_on_disk}"
            # 简单化：直接用 hash 或者是标准命名
            # 如果找到了数字，就用 motion_01.json
            if match_num:
                safe_name = f"{type_prefix}_{match_num.group(1)}{ext}"
            else:
                # 拼音/英文文件直接保留原名的小写版，去乱码
                safe_base = re.sub(r'[^a-zA-Z0-9]', '', target_file_on_disk.split('.')[0])
                safe_name = f"{type_prefix}_{safe_base}{ext}"

            # 执行重命名
            src = os.path.join(motions_dir, target_file_on_disk)
            dst = os.path.join(motions_dir, safe_name)
            
            if os.path.exists(src):
                if src != dst: shutil.move(src, dst)
                # 更新磁盘缓存列表，防止重复处理
                if target_file_on_disk in disk_files:
                    disk_files.remove(target_file_on_disk)
                    disk_files.append(safe_name)
                
                # 更新 JSON
                item["File"] = f"motions/{safe_name}"
                print(f"✨ 修复: {old_name} -> {safe_name}")
        else:
            print(f"⚠️ 丢失: {old_name} (磁盘上没找到对应文件)")

print("🔄 处理动作...")
if "Motions" in data.get("FileReferences", {}):
    sanitize(data["FileReferences"]["Motions"], "motion")

print("🔄 处理表情...")
if "Expressions" in data.get("FileReferences", {}):
    sanitize(data["FileReferences"]["Expressions"], "exp")

# 4. 保存
with open(config_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\n✅ 修复完成！")
