import yaml
import os

SRC_DIR = "src"
OUTPUT_DIR = "configs"

def load_yaml(filename):
    filepath = os.path.join(SRC_DIR, filename)
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def merge_dicts(dict1, dict2):
    """递归合并字典"""
    for k, v in dict2.items():
        if k in dict1 and isinstance(dict1[k], dict) and isinstance(v, dict):
            merge_dicts(dict1[k], v)
        elif k in dict1 and isinstance(dict1[k], list) and isinstance(v, list):
            dict1[k].extend(v)
        else:
            dict1[k] = v
    return dict1

def build_profile(module_name, strategy_type):
    print(f"🔧 正在构建 {module_name} 模块 ({strategy_type} 策略)...")
    
    # 加载基础模块
    base = load_yaml("base.yaml")
    providers = load_yaml("providers.yaml")
    groups = load_yaml("groups.yaml")
    rules = load_yaml("rules.yaml")
    
    # 深度合并
    combined = merge_dicts(base, providers)
    combined = merge_dicts(combined, groups)
    combined = merge_dicts(combined, rules)
    
    diff = load_yaml(f"diffs/{module_name}.diff.yaml")
    final_config = merge_dicts(combined, diff)
    
    # ==========================================
    # 核心：策略组动态注入逻辑
    # ==========================================
    for group in final_config.get('proxy-groups', []):
        # 仅针对引用了订阅源 (use) 且不是用于 UI 手动选择的 (-All) 策略组
        if 'use' in group and not group['name'].endswith('-All'):
            if strategy_type == 'smart':
                group['type'] = 'smart'
                group['uselightgbm'] = True
                group['collectdata'] = False
                group['prefer-asn'] = True
                group['interval'] = 120
                # 清理可能残留的 url-test 字段
                group.pop('tolerance', None)
            
            elif strategy_type == 'urltest':
                group['type'] = 'url-test'
                group['tolerance'] = 50   # 注入 50ms 的防抖动容差值
                group['interval'] = 300   # 延长测速间隔，进一步省电
                # 清理 smart 专属字段
                group.pop('uselightgbm', None)
                group.pop('collectdata', None)
                group.pop('prefer-asn', None)

    # 清理 x- 开头的辅助锚点字典
    keys_to_remove = [k for k in final_config.keys() if k.startswith('x-')]
    for k in keys_to_remove:
        del final_config[k]
        
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{module_name}-{strategy_type}.yaml")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(final_config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print(f"✅ 构建完成: {output_path}")

if __name__ == "__main__":
    # 一键交叉编译 4 套配置文件
    build_profile("box", "smart")
    build_profile("box", "urltest")
    build_profile("surfing", "smart")
    build_profile("surfing", "urltest")