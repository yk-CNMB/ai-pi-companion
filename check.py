import os
import json
import re

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIKU_DIR = os.path.join(BASE_DIR, "static", "live2d", "miku")

# 1. 动作分组规则 (文件名关键词 -> 动作组名)
MOTION_RULES = [
    (r"(happy|smile|joy|laugh|02|04|love|cute)", "Happy"),
    (r"(angry|mad|01|10|愤怒)", "Angry"),
    (r"(sad|cry|06|悲伤)", "Sad"),
    (r"(shock|surprise|05|turn|吃惊)", "Shock"),
    (r"(idle|wait|stand|sleep|09|nod|07|14)", "Idle"),
    (r"(walk|run|08)", "Walk"),
    (r".*", "TapBody") 
]

def inject():
    print(f"💉 全能注入脚本启动...")
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
            # 计算相对路径
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, MIKU_DIR).replace("\\", "/")
            
            # 识别动作文件
            if f.endswith(('.motion3.json', '.mtn')):
                found_motions.append((f, rel_path))
            
            # 识别表情文件
            elif f.endswith(('.exp3.json', '.exp.json')):
                found_expressions.append((f, rel_path))

    print(f"📊 扫描结果: 动作 {len(found_motions)} 个, 表情 {len(found_expressions)} 个")

    # --- 阶段二：构建 JSON 数据 ---
    
    # 1. 处理动作 (Motions)
    new_motions = {}
    for fname, rel_path in found_motions:
        fname_lower = fname.lower()
        matched_group = "TapBody"
        for pattern, group_name in MOTION_RULES:
            if re.search(pattern, fname_lower):
                matched_group = group_name
                break
        if matched_group not in new_motions:
            new_motions[matched_group] = []
        new_motions[matched_group].append({"File": rel_path})

    # 2. 处理表情 (Expressions)
    new_expressions = []
    for fname, rel_path in found_expressions:
        # 提取表情名称 (去掉扩展名)
        # 例如: f01.exp3.json -> Name: f01
        name = fname.split('.')[0]
        # 如果文件名里包含情感词，也可以优化 Name，但保持文件名通常最安全
        new_expressions.append({
            "Name": name,
            "File": rel_path
        })
        print(f"   😀 添加表情: [{name}] <- {rel_path}")

    # --- 阶段三：写入配置文件 ---
    json_files = [f for f in os.listdir(MIKU_DIR) if f.endswith('.model3.json')]
    target_json = None
    
    if json_files:
        target_json = os.path.join(MIKU_DIR, json_files[0])
    else:
        # 尝试升级旧版
        old_jsons = [f for f in os.listdir(MIKU_DIR) if f.endswith('.model.json')]
        if old_jsons:
            target_json = os.path.join(MIKU_DIR, old_jsons[0])
            print("⚠️ 警告: 正在修改旧版 .model.json")
        else:
            print("❌ 找不到配置文件！")
            return

    try:
        with open(target_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'FileReferences' not in data:
            data['FileReferences'] = {}
            
        # 写入动作
        data['FileReferences']['Motions'] = new_motions
        print(f"✅ 已注入 {len(found_motions)} 个动作")

        # 写入表情
        if found_expressions:
            data['FileReferences']['Expressions'] = new_expressions
            print(f"✅ 已注入 {len(found_expressions)} 个表情")
        
        # 写入硬盘
        with open(target_json, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        print("\n🎉 完美！配置文件已更新。请重启服务并刷新网页。")
        
    except Exception as e:
        print(f"❌ 写入失败: {e}")

if __name__ == "__main__":
    inject()
