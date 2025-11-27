import os
import json
import re

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIKU_DIR = os.path.join(BASE_DIR, "static", "live2d", "miku")
MOTIONS_DIR = os.path.join(MIKU_DIR, "Motions") # 默认大写

# 智能分组规则 (文件名关键词 -> 动作组名)
GROUP_RULES = [
    (r"(happy|smile|joy|laugh|02|04|love|cute)", "Happy"),
    (r"(angry|mad|01|10|愤怒)", "Angry"),
    (r"(sad|cry|06|悲伤)", "Sad"),
    (r"(shock|surprise|05|turn|吃惊)", "Shock"),
    (r"(idle|wait|stand|sleep|09|nod|07|14)", "Idle"),
    (r"(walk|run|08)", "Walk"),
    (r".*", "TapBody") 
]

def inject():
    # ★★★ 修正：必须在函数一开始就声明全局变量 ★★★
    global MOTIONS_DIR
    
    print(f"💉 准备向 Miku 注入灵魂...")
    print(f"📂 模型目录: {MIKU_DIR}")
    print(f"📂 默认动作目录: {MOTIONS_DIR}")

    # 检查目录是否存在
    if not os.path.exists(MOTIONS_DIR):
        print("❌ 错误：找不到 Motions 文件夹！")
        # 尝试找小写 motions
        lower_motions = os.path.join(MIKU_DIR, "motions")
        if os.path.exists(lower_motions):
            print("💡 发现小写 motions 文件夹，自动切换路径。")
            MOTIONS_DIR = lower_motions
        else:
            print("❌ 大写和小写的 motions 文件夹都不存在，请检查文件夹名称。")
            return

    # 1. 扫描所有动作文件
    motion_files = []
    print(f"📂 正在扫描: {MOTIONS_DIR}")
    
    for root, dirs, files in os.walk(MOTIONS_DIR):
        for f in files:
            if f.endswith(('.motion3.json', '.mtn')):
                # 计算相对路径
                full_path = os.path.join(root, f)
                # 关键：计算相对于 miku 模型根目录的路径
                rel_path = os.path.relpath(full_path, MIKU_DIR).replace("\\", "/")
                motion_files.append((f, rel_path))
    
    print(f"🔍 扫描到 {len(motion_files)} 个动作文件。")
    if len(motion_files) == 0:
        print("❌ 文件夹是空的！没有动作文件。")
        return

    # 2. 构建 JSON 结构
    new_motions = {}
    
    for fname, rel_path in motion_files:
        fname_lower = fname.lower()
        matched_group = "TapBody" # 默认组
        
        # 匹配分组
        for pattern, group_name in GROUP_RULES:
            if re.search(pattern, fname_lower):
                matched_group = group_name
                break
        
        if matched_group not in new_motions:
            new_motions[matched_group] = []
            
        # 写入结构
        new_motions[matched_group].append({"File": rel_path})
        print(f"   ➕ 添加: [{matched_group}] <- {rel_path}")

    # 3. 写入配置文件
    # 优先找 model3.json，没有再找 model.json
    target_json = None
    json_files = [f for f in os.listdir(MIKU_DIR) if f.endswith('.model3.json')]
    if json_files:
        target_json = os.path.join(MIKU_DIR, json_files[0])
    else:
        # 如果没有 model3，尝试找旧版 model.json 并升级它
        old_jsons = [f for f in os.listdir(MIKU_DIR) if f.endswith('.model.json')]
        if old_jsons:
            print("⚠️ 未找到 .model3.json，正在尝试升级 .model.json ...")
            target_json = os.path.join(MIKU_DIR, old_jsons[0])
        else:
            print("❌ 找不到任何配置文件 (.model3.json / .model.json)")
            return
    
    try:
        with open(target_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 确保 FileReferences 存在 (Cubism 3+ 标准)
        if 'FileReferences' not in data:
            data['FileReferences'] = {}
            
        # 覆盖/写入 Motions
        data['FileReferences']['Motions'] = new_motions
        
        # 同时为了兼容旧版，尝试写入顶级 motions 键
        # data['motions'] = new_motions 
        
        # 写入硬盘
        with open(target_json, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        print(f"\n✅ 注入成功！配置文件已更新: {os.path.basename(target_json)}")
        print("👉 请重启服务并刷新网页。")
        
    except Exception as e:
        print(f"❌ 写入失败: {e}")

if __name__ == "__main__":
    inject()
