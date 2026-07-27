import os

def main():
    # 目录配置
    TEMPLATE_DIR = 'template'
    OUTPUT_DIR = 'release/configs'
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    def read_yaml(filename):
        filepath = os.path.join(TEMPLATE_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read().strip()

    print("开始合并 Mihomo 配置文件...")

    # 1. 读取公共基础模块
    # 注意拼接顺序：先注入锚点，再注入其他，避免引用失败
    anchors = read_yaml('anchors.yaml')
    providers = read_yaml('proxy-providers.yaml')
    rules = read_yaml('rule-providers&rules.yaml')
    
    base_config = f"{anchors}\\n\\n{providers}\\n\\n{rules}"

    # 2. 读取差异化头部模块
    box_diff = read_yaml('box.diff.yaml')
    surfing_diff = read_yaml('surfing.diff.yaml')

    # 3. 拼接最终文件 (头部特征 + 基础配置)
    box_final = f"{box_diff}\\n\\n{base_config}"
    surfing_final = f"{surfing_diff}\\n\\n{base_config}"

    # 4. 写入输出目录
    with open(os.path.join(OUTPUT_DIR, 'box.yaml'), 'w', encoding='utf-8') as f:
        f.write(box_final)
    print(f"✅ 生成成功: {os.path.join(OUTPUT_DIR, 'box.yaml')}")

    with open(os.path.join(OUTPUT_DIR, 'surfing.yaml'), 'w', encoding='utf-8') as f:
        f.write(surfing_final)
    print(f"✅ 生成成功: {os.path.join(OUTPUT_DIR, 'surfing.yaml')}")

if __name__ == '__main__':
    main()