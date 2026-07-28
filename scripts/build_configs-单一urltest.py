import yaml
import os

# 定义相对路径
SRC_DIR = "src"
OUTPUT_DIR = "configs"

def load_yaml(filename):
    """读取 YAML 文件并返回字典"""
    filepath = os.path.join(SRC_DIR, filename)
    if not os.path.exists(filepath):
        print(f"⚠️ 警告: 找不到文件 {filepath}")
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def merge_dicts(dict1, dict2):
    """递归合并两个字典"""
    for k, v in dict2.items():
        if k in dict1 and isinstance(dict1[k], dict) and isinstance(v, dict):
            merge_dicts(dict1[k], v)
        elif k in dict1 and isinstance(dict1[k], list) and isinstance(v, list):
            dict1[k].extend(v)
        else:
            dict1[k] = v
    return dict1

def build_profile(module_name):
    print(f"🔧 正在构建 {module_name} 模块...")
    
    # 1. 依次加载所有基础模块
    base = load_yaml("base.yaml")
    providers = load_yaml("providers.yaml")
    groups = load_yaml("groups.yaml")
    rules = load_yaml("rules.yaml")
    
    # 2. 深度合并基础模块
    combined = merge_dicts(base, providers)
    combined = merge_dicts(combined, groups)
    combined = merge_dicts(combined, rules)
    
    # 3. 合并对应模块的端口差异配置 (Diff)
    diff = load_yaml(f"diffs/{module_name}.diff.yaml")
    final_config = merge_dicts(combined, diff)
    
    # 4. 清理以 'x-' 开头的辅助锚点键 (防止污染最终配置)
    keys_to_remove = [k for k in final_config.keys() if k.startswith('x-')]
    for k in keys_to_remove:
        del final_config[k]
    
    # 5. 输出文件
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{module_name}.yaml")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        # allow_unicode=True 保证中文正常显示，sort_keys=False 保持合并时的字典顺序
        yaml.dump(final_config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print(f"✅ 构建完成: {output_path}")

if __name__ == "__main__":
    # 执行构建
    build_profile("box")
    build_profile("surfing")