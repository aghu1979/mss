import os
import re

def clean_yaml_text(text):
    # 暴力清洗：移除文件开头所有潜伏的 BOM 和零宽幽灵字符
    text = re.sub(r'^[\ufeff\u200b\u200d\u200c\xef\xbb\xbf]+', '', text)
    return text.strip()

def main():
    TEMPLATE_DIR = 'template'
    OUTPUT_DIR = 'release/configs'
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    def read_yaml(filename):
        filepath = os.path.join(TEMPLATE_DIR, filename)
        # 忽略系统默认编码差异，强行读取并清洗文本
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return clean_yaml_text(f.read())

    print("开始合并 Mihomo 配置文件...")

    # 1. 读取基础模块
    anchors = read_yaml('anchors.yaml')
    providers = read_yaml('proxy-providers.yaml')
    rules = read_yaml('rule-providers&rules.yaml')
    
    # 使用纯净的换行符拼接
    base_config = anchors + "\n\n" + providers + "\n\n" + rules

    # 2. 读取差异化模块
    box_diff = read_yaml('box.diff.yaml')
    surfing_diff = read_yaml('surfing.diff.yaml')

    # 3. 组装最终配置
    box_final = box_diff + "\n\n" + base_config
    surfing_final = surfing_diff + "\n\n" + base_config

    # 4. 强制以标准的无 BOM UTF-8 格式输出
    with open(os.path.join(OUTPUT_DIR, 'box.yaml'), 'w', encoding='utf-8') as f:
        f.write(box_final)
    print(f"✅ 生成成功: box.yaml")

    with open(os.path.join(OUTPUT_DIR, 'surfing.yaml'), 'w', encoding='utf-8') as f:
        f.write(surfing_final)
    print(f"✅ 生成成功: surfing.yaml")

if __name__ == '__main__':
    main()
