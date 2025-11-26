
import os
import json
import glob
import shutil

# --- 配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE2D_ROOT = os.path.join(BASE_DIR, "static", "live2d")

print("🔧 正在定位 Miku 模型...")
target_dir = None
# 优先找名字里带 miku 的文件夹
for root, dirs, files in os.walk(LIVE2D_ROOT):
    if "miku" in os.path.basename(root).lower():
        # 确认里面有 model3.json
        if glob.glob(os.path.join(root, "*.model3.json")):
            target_dir = root
            break

# 如果还没找到，就找任何包含 model3.json 的文件夹
if not target_dir:
    for root, dirs, files in os.walk(LIVE2D_ROOT):
        if glob.glob(os.path.join(root, "*.model3.json")):
            target_dir = root
            break

if not target_dir:
    print("❌ 未找到模型文件夹！")
    exit()

print(f"📂 锁定目录: {target_dir}")

# 1. 归拢动作文件夹
motions_dir = os.path.join(target_dir, "motions")
if not os.path.exists(motions_dir):
    os.makedirs(motions_dir)

# 查找并迁移 "表情和动作" (或者乱码文件夹)
for item in os.listdir(target_dir):
    full_path = os.path.join(target_dir, item)
    if os.path.isdir(full_path) and item not in ["motions", "livehimeConfig", "MIKU.4096", "Wrapper"]:
        # 只要里面有json，就认为是动作文件夹，全部移出来
        if glob.glob(os.path.join(full_path, "*.json")):
            print(f"📦 正在迁移文件夹: {item} -> motions")
            for f in os.listdir(full_path):
                shutil.move(os.path.join(full_path, f), motions_dir)
            os.rmdir(full_path)

# 2. 翻译映射表 (根据你上传的文件)
TRANS_MAP = {
    # 中文 -> 英文
    "生气": "angry",
    "愤怒": "angry",
    "高兴": "happy",
    "开心": "happy",
    "爱情": "love",
    "大哭": "cry",
    "点头": "nod",
    "走路": "walk",
    "扭腰": "twist",
    "活动身体": "active",
    "转头": "turn",
    "渐入睡眠": "sleep",
    "装可爱": "cute",
    
    # 拼音 -> 英文
    "Saihong": "blush",
    "liuhan": "sweat",
    "Chijing": "shock",
    "Mimiyan": "squint",
    "Dazhihui": "wisdom", # 大智慧? 暂时映射为 idle 类
    "Yanjing": "glasses"
}

# 3. 重命名文件 & 更新 JSON
config_file = glob.glob(os.path.join(target_dir, "*.model3.json"))[0]
try:
    with open(config_file, 'r', encoding='utf-8') as f: data = json.load(f)
except:
    with open(config_file, 'r', encoding='gbk', errors='ignore') as f: data = json.load(f)

def process_list(file_list):
    for item in file_list:
        old_path = item.get("File", "")
        old_name = os.path.basename(old_path)
        
        # 寻找对应的物理文件
        old_abs_path = os.path.join(motions_dir, old_name)
        
        # 如果找不到，尝试模糊匹配 (处理乱码)
        if not os.path.exists(old_abs_path):
            # 尝试匹配数字编号 (如 01, 02)
            num_prefix = old_name.split('_')[0] if '_' in old_name else ""
            if num_prefix.isdigit():
                 candidates = glob.glob(os.path.join(motions_dir, f"{num_prefix}_*.json"))
                 if candidates: old_abs_path = candidates[0]
        
        if not os.path.exists(old_abs_path):
            print(f"⚠️ 文件丢失: {old_name}")
            continue

        # 开始翻译文件名
        new_base_name = old_name
        
        # 1. 先匹配字典
        for k, v in TRANS_MAP.items():
            if k in old_name:
                # 保留编号: 01_生气.json -> angry_01.json
                num = "".join(filter(str.isdigit, old_name))
                if num:
                    new_base_name = f"{v}_{num}"
                else:
                    new_base_name = v
                break
        
        # 2. 如果没匹配到字典，保留原名但转为纯英文数字 (防止乱码残留)
        if new_base_name == old_name:
             # 简单的清理：只保留字母数字
             import re
             clean = re.sub(r'[^a-zA-Z0-9]', '', old_name.split('.')[0])
             new_base_name = f"motion_{clean}"

        # 加上后缀
        if "motion3" in old_name: suffix = ".motion3.json"
        elif "exp3" in old_name: suffix = ".exp3.json"
        else: suffix = ".json"
        
        new_filename = new_base_name + suffix
        new_abs_path = os.path.join(motions_dir, new_filename)
        
        # 执行重命名
        if old_abs_path != new_abs_path:
            shutil.move(old_abs_path, new_abs_path)
            print(f"✨ [重命名] {os.path.basename(old_abs_path)} -> {new_filename}")
        
        # 更新 JSON
        item["File"] = f"motions/{new_filename}"

# 执行处理
print("🔄 处理 Motions...")
if "Motions" in data["FileReferences"]:
    motions = data["FileReferences"]["Motions"]
    # Motions 是字典结构: {"Idle": [...], "Tap": [...]}
    if isinstance(motions, dict):
        for group, items in motions.items():
            process_list(items)
    else:
        process_list(motions)

print("🔄 处理 Expressions...")
if "Expressions" in data["FileReferences"]:
    process_list(data["FileReferences"]["Expressions"])

# 保存配置
with open(config_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\n✅ 汉化修复完成！")
EOF
