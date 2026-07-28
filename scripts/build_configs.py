import os
import re
import yaml
import json
import gzip
import shutil
import platform
import urllib.request
import subprocess

SRC_DIR = "src"
OUTPUT_DIR = "configs"

def clean_yaml_text(text):
    """暴力清洗：移除文件开头所有潜伏的 BOM 和零宽幽灵字符"""
    text = re.sub(r'^[\ufeff\u200b\u200d\u200c\xef\xbb\xbf]+', '', text)
    return text.strip()

def load_yaml(filename):
    filepath = os.path.join(SRC_DIR, filename)
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        # 优化：读取为文本，清洗 BOM 后再解析为字典
        clean_text = clean_yaml_text(f.read())
        return yaml.safe_load(clean_text) or {}

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

import time

def get_mihomo_core():
    """动态获取并准备当前平台最新的 Mihomo Smart Alpha 内核 (带网络容错与精准匹配)"""
    core_name = "mihomo.exe" if platform.system() == "Windows" else "./mihomo"
    if os.path.exists(core_name):
        return os.path.abspath(core_name)

    print("\n⬇️ 未检测到 Mihomo 内核，正在从 vernesong/mihomo 抓取 Smart 专属内核...")
    arch_map = {"x86_64": "amd64", "AMD64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    sys_arch = arch_map.get(platform.machine(), "amd64")
    
    is_windows = platform.system() == "Windows"
    sys_os = "windows" if is_windows else "linux"
    target_ext = ".zip" if is_windows else ".gz"
    
    # 坚决使用带有 smart 编译特性的 vernesong 仓库
    api_url = "https://api.github.com/repos/vernesong/mihomo/releases/tags/Prerelease-Alpha"
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    # 引入重试补偿机制，硬抗 504 Gateway Timeout
    max_retries = 3
    data = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode())
            break
        except urllib.error.URLError as e:
            print(f"⚠️ API 请求失败 ({attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise Exception("❌ 获取内核下载链接失败，API 网关持续超时，请稍后重试！")
            time.sleep(3)
        
    download_url = None
    for asset in data.get('assets', []):
        name = asset['name']
        # 精准匹配策略：必须包含系统、架构、"smart"关键字，且排除不兼容的衍生版
        if (sys_os in name and 
            sys_arch in name and 
            "smart" in name and 
            "compatible" not in name and 
            "-v1" not in name and 
            "-v2" not in name and 
            "-v3" not in name and 
            "go12" not in name and 
            name.endswith(target_ext)):
            download_url = asset['browser_download_url']
            break
            
    if not download_url:
        raise Exception(f"❌ 未找到适合当前系统({sys_os}-{sys_arch})的 smart 核心文件！")

    temp_file = f"mihomo_temp{target_ext}"
    print(f"📦 正在下载: {download_url}")
    
    for attempt in range(max_retries):
        try:
            urllib.request.urlretrieve(download_url, temp_file)
            break
        except urllib.error.URLError as e:
            print(f"⚠️ 下载文件失败 ({attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise Exception("❌ 内核文件下载持续失败！")
            time.sleep(3)
    
    print("🔧 正在解压内核...")
    if is_windows:
        import zipfile
        with zipfile.ZipFile(temp_file, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith('.exe'):
                    zip_ref.extract(file_info, path=".")
                    if file_info.filename != core_name:
                        if os.path.exists(core_name):
                            os.remove(core_name)
                        os.rename(file_info.filename, core_name)
                    break
    else:
        with gzip.open(temp_file, 'rb') as f_in:
            with open(core_name, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.chmod(core_name, 0o755)
            
    os.remove(temp_file)
    print("✅ Smart 内核准备就绪！")
    return os.path.abspath(core_name)

def build_profile(module_name, strategy_type, core_path):
    print(f"\n=============================================")
    print(f"🔧 正在构建 {module_name} 模块 ({strategy_type} 策略)...")
    
    base = load_yaml("base.yaml")
    providers = load_yaml("providers.yaml")
    groups = load_yaml("groups.yaml")
    rules = load_yaml("rules.yaml")
    
    combined = merge_dicts(base, providers)
    combined = merge_dicts(combined, groups)
    combined = merge_dicts(combined, rules)
    
    diff = load_yaml(f"diffs/{module_name}.diff.yaml")
    final_config = merge_dicts(combined, diff)
    
    # 策略注入
    for group in final_config.get('proxy-groups', []):
        if 'use' in group and not group['name'].endswith('-All'):
            if strategy_type == 'smart':
                group['type'] = 'smart'
                group['uselightgbm'] = True
                group['collectdata'] = False
                group['prefer-asn'] = True
                group['interval'] = 120
                group.pop('tolerance', None)
            elif strategy_type == 'urltest':
                group['type'] = 'url-test'
                group['tolerance'] = 50
                group['interval'] = 300
                group.pop('uselightgbm', None)
                group.pop('collectdata', None)
                group.pop('prefer-asn', None)

    # 剔除辅助锚点
    keys_to_remove = [k for k in final_config.keys() if k.startswith('x-')]
    for k in keys_to_remove:
        del final_config[k]
        
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_filename = f"{module_name}-{strategy_type}.yaml"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(final_config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    # 优化：集成由 Alpha 内核执行的强校验
    print(f"🔍 正在使用内核校验 {output_filename}...")
    try:
        subprocess.run([core_path, "-t", "-f", output_path], check=True, capture_output=True, text=True)
        print(f"✅ {output_filename} 语法与逻辑验证通过！")
    except subprocess.CalledProcessError as e:
        print(f"❌ {output_filename} 校验失败！\n内核报错信息：\n{e.stderr}")
        raise

if __name__ == "__main__":
    # 提前准备一次内核，复用给所有文件校验
    core_path = get_mihomo_core()
    
    build_profile("box", "smart", core_path)
    build_profile("box", "urltest", core_path)
    build_profile("surfing", "smart", core_path)
    build_profile("surfing", "urltest", core_path)
    print("\n🎉 所有配置均已构建并校验完毕！")
