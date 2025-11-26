import os
import json
import glob
import shutil
import re

# 自动定位 live2d 目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE2D_ROOT = os.path.join(BASE_DIR, "static", "live2d")

print("🔧 正在搜索 Miku 模型...")

# 1. 寻找 Miku 文件夹
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

# 2. 处理中文文件夹 "表情和动作"
motions_dir = os.path.join(target_dir, "motions")
if not os.path.exists(motions_dir):
    os.makedirs(motions_dir)

chinese_dir_candidates = ["表情和动作", "motions_chn"]
found_chinese_dir = None

for d in os.listdir(target_dir):
    # 尝试匹配中文文件夹，或者非标准的文件夹
    if os.path.isdir(os.path.join(target_dir, d)) and d not in ["livehimeConfig", "MIKU.4096", "motions"]:
        # 检查里面是不是有 .json 文件
        if glob.glob(os.path.join(target_dir, d, "*.json")):
            found_chinese_dir = os.path.join(target_dir, d)
            print(f"📂 发现资源文件夹: {d}")
            break

if found_chinese_dir:
    print("🚚 正在迁移文件...")
    for f in os.listdir(found_chinese_dir):
        shutil.move(os.path.join(found_chinese_dir, f), motions_dir)
    os.rmdir(found_chinese_dir)

# 3. 读取配置文件
config_file = glob.glob(os.path.join(target_dir, "*.model3.json"))[0]
try:
    with open(config_file, 'r', encoding='utf-8') as f: data = json.load(f)
except:
    with open(config_file, 'r', encoding='gbk', errors='ignore') as f: data = json.load(f)

# 4. 智能重命名映射表
# 将中文关键词映射为英文，方便前端调用
name_map = {
    "生气": "angry", "愤怒": "angry",
    "高兴": "happy", "开心": "happy", "爱情": "love",
    "大哭": "sad",
    "点头": "nod",
    "走路": "walk", "扭腰": "twist", "活动身体": "active", "转头": "turn",
    "渐入睡眠": "sleepy", "装可爱": "cute",
    "Saihong": "blush", "liuhan": "sweat", "Chijing": "shock", "Mimiyan": "squint", "Dazhihui": "smart"
}

def sanitize_files(file_list_obj, prefix):
    items = []
    if isinstance(file_list_obj, dict):
        for k, v in file_list_obj.items(): items.extend(v)
    else:
        items = file_list_obj
        
    for i, item in enumerate(items):
        old_path = item.get("File", "")
        old_filename = os.path.basename(old_path)
        
        # 在 motions 目录下找文件
        old_abs = os.path.join(motions_dir, old_filename)
        if not os.path.exists(old_abs):
            continue
        
        # 智能生成新名字
        new_base = f"{prefix}_{i}"
        for cn, en in name_map.items():
            if cn in old_filename:
                new_base = en # 比如 happy
                # 保留原文件名里的数字编号防止冲突
                num_match = re.search(r'\d+', old_filename)
                if num_match:
                    new_base += f"_{num_match.group()}"
                break
        
        new_filename = f"{new_base}.json"
        if "motion" in prefix: new_filename = f"{new_base}.motion3.json"
        elif "exp" in prefix: new_filename = f"{new_base}.exp3.json"

        new_abs = os.path.join(motions_dir, new_filename)
        
        # 重命名文件
        if old_abs != new_abs:
            shutil.move(old_abs, new_abs)
            print(f"✨ {old_filename} -> {new_filename}")
        
        # 更新 JSON 引用
        item["File"] = f"motions/{new_filename}"

print("\n🔄 处理动作文件...")
if "Motions" in data.get("FileReferences", {}):
    sanitize_files(data["FileReferences"]["Motions"], "motion")

print("\n🔄 处理表情文件...")
if "Expressions" in data.get("FileReferences", {}):
    sanitize_files(data["FileReferences"]["Expressions"], "exp")

# 保存
with open(config_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\n✅ Miku 修复完成！现在浏览器可以加载了。")
