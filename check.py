import os
import json
import re

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIKU_DIR = os.path.join(BASE_DIR, "static", "live2d", "miku")

# 动作分组规则 (文件名关键词 -> 动作组名)
# 只要文件名里有 happy，就把它塞进 Happy 组
MOTION_RULES = [
    (r"(happy|smile|joy|laugh|02|04|love|cute)", "Happy"),
    (r"(angry|mad|01|10|愤怒)", "Angry"),
    (r"(sad|cry|06|悲伤)", "Sad"),
    (r"(shock|surprise|05|turn|吃惊)", "Shock"),
    (r"(idle|wait|stand|sleep|09|nod|07|14)", "Idle"),
    (r"(walk|run|08)", "Walk"),
    (r".*", "TapBody") # 剩下的都丢进去
]

def inject():
    print(f"💉 启动全能注入修复...")
    print(f"📂 目标目录: {MIKU_DIR}")

    if not os.path.exists(MIKU_DIR):
        print("❌ 错误：Miku 目录不存在！")
        return

    # --- 阶段一：扫描所有文件 ---
    found_motions = []
    found_expressions = []

    print("🔍 正在深度扫描目录...")
    for root, dirs, files in os.walk(MIKU_DIR):
        for f in files:
            full_path = os.path.join(root, f)
            # 计算出符合 Live2D 标准的相对路径
            rel_path = os.path.relpath(full_path, MIKU_DIR).replace("\\", "/")
            
            if f.endswith(('.motion3.json', '.mtn')):
                found_motions.append((f, rel_path))
            elif f.endswith(('.exp3.json', '.exp.json')):
                found_expressions.append((f, rel_path))

    print(f"📊 扫描结果: 动作 {len(found_motions)} 个, 表情 {len(found_expressions)} 个")

    if not found_motions:
        print("❌ 未找到动作文件，请检查文件夹结构！")
        return

    # --- 阶段二：构建 JSON 数据 ---
    
    # 1. 重组动作 (Motions)
    new_motions = {}
    for fname, rel_path in found_motions:
        fname_lower = fname.lower()
        matched_group = "TapBody"
        
        # 匹配分组
        for pattern, group_name in MOTION_RULES:
            if re.search(pattern, fname_lower):
                matched_group = group_name
                break
        
        if matched_group not in new_motions:
            new_motions[matched_group] = []
        
        new_motions[matched_group].append({"File": rel_path})

    # 2. 重组表情 (Expressions)
    new_expressions = []
    for fname, rel_path in found_expressions:
        # 表情名通常就是文件名去掉后缀
        name = fname.split('.')[0]
        # 针对 Miku 的特殊文件名做优化 (可选)
        if "01" in name or "happy" in name: name = "f01" 
        
        new_expressions.append({
            "Name": name,
            "File": rel_path
        })
        print(f"   😀 注册表情: [{name}] <- {rel_path}")

    # --- 阶段三：写入配置文件 ---
    target_json = None
    # 优先找 model3
    json_files = [f for f in os.listdir(MIKU_DIR) if f.endswith('.model3.json')]
    if json_files:
        target_json = os.path.join(MIKU_DIR, json_files[0])
    else:
        # 没有 model3 就找 model.json
        old_jsons = [f for f in os.listdir(MIKU_DIR) if f.endswith('.model.json')]
        if old_jsons:
            target_json = os.path.join(MIKU_DIR, old_jsons[0])
        else:
            print("❌ 找不到配置文件！")
            return

    try:
        with open(target_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 确保基本结构
        if 'FileReferences' not in data:
            data['FileReferences'] = {}
            
        # 暴力覆盖动作配置
        data['FileReferences']['Motions'] = new_motions
        print(f"✅ 已注入动作组: {list(new_motions.keys())}")

        # 暴力覆盖表情配置
        if found_expressions:
            data['FileReferences']['Expressions'] = new_expressions
            print(f"✅ 已注入表情: {len(new_expressions)} 个")
        
        # 写入硬盘
        with open(target_json, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        print("\n🎉 修复完成！现在 Miku 拥有标准的动作组了。")
        print("👉 请务必刷新网页，让前端加载新的配置。")
        
    except Exception as e:
        print(f"❌ 写入失败: {e}")

if __name__ == "__main__":
    inject()
