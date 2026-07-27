import os

def main():
    # 目录配置
    TEMPLATE_DIR = 'template'
    OUTPUT_DIR = 'release/configs'
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    def read_yaml(filename):
        filepath = os.path.join(TEMPLATE_DIR, filename)
        # 🚨 关键修复 1：使用 'utf-8-sig' 编码读取
        # 它的作用是：如果文件带有 Windows 记事本产生的隐藏 BOM 头，会自动将其安全剥离，防止污染合并后的文件。
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            return f.read().strip()

    print("开始合并 Mihomo 配置文件...")

    # 1. 读取基础模块
    anchors = read_yaml('anchors.yaml')
    providers = read_yaml('proxy-providers.yaml')
    rules = read_yaml('rule-providers&rules.yaml')
    
    # 🚨 关键修复 2：使用真实的换行符进行拼接，避免 f-string 极端情况下的转义失效
    base_config = anchors + "\n\n" + providers + "\n\n" + rules

    # 2. 读取差异化头部模块
    box_diff = read_yaml('box.diff.yaml')
    surfing_diff = read_yaml('surfing.diff.yaml')

    # 3. 拼接最终文件 (头部特征 + 基础配置)
    box_final = box_diff + "\n\n" + base_config
    surfing_final = surfing_diff + "\n\n" + base_config

    # 4. 写入输出目录 (输出时使用标准的无 BOM utf-8)
    with open(os.path.join(OUTPUT_DIR, 'box.yaml'), 'w', encoding='utf-8') as f:
        f.write(box_final)
    print(f"✅ 生成成功: {os.path.join(OUTPUT_DIR, 'box.yaml')}")

    with open(os.path.join(OUTPUT_DIR, 'surfing.yaml'), 'w', encoding='utf-8') as f:
        f.write(surfing_final)
    print(f"✅ 生成成功: {os.path.join(OUTPUT_DIR, 'surfing.yaml')}")

if __name__ == '__main__':
    main()
