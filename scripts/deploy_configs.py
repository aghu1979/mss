import os
import re
import urllib.request
import gzip
import shutil
import subprocess
import platform
import sys
import json

def clean_yaml_text(text):
    # 暴力清洗：移除文件开头所有潜伏的 BOM 和零宽幽灵字符
    text = re.sub(r'^[\ufeff\u200b\u200d\u200c\xef\xbb\xbf]+', '', text)
    return text.strip()

def get_mihomo_core():
    """动态获取并准备当前平台最新的 Mihomo Alpha 内核"""
    core_name = "mihomo.exe" if platform.system() == "Windows" else "./mihomo"
    if os.path.exists(core_name):
        return os.path.abspath(core_name)

    print("\n⬇️ 未检测到 Mihomo 内核，正在从 GitHub Prerelease-Alpha 抓取...")
    arch_map = {"x86_64": "amd64", "AMD64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    sys_arch = arch_map.get(platform.machine(), "amd64")
    
    is_windows = platform.system() == "Windows"
    sys_os = "windows" if is_windows else "linux"
    
    # 强制要求匹配后缀名，避免误下 .deb 或 .rpm
    target_ext = ".zip" if is_windows else ".gz"
    
    api_url = "https://api.github.com/repos/vernesong/mihomo/releases/tags/Prerelease-Alpha"
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    import json
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        
    download_url = None
    for asset in data.get('assets', []):
        name = asset['name']
        # 精准匹配：系统、架构，排除兼容包，且后缀必须是 .gz 或 .zip
        if sys_os in name and sys_arch in name and "compatible" not in name and name.endswith(target_ext):
            download_url = asset['browser_download_url']
            break
            
    if not download_url:
        raise Exception(f"❌ 未找到适合当前系统({sys_os}-{sys_arch})的 {target_ext} 格式内核文件！")

    temp_file = f"mihomo_temp{target_ext}"
    print(f"📦 正在下载: {download_url}")
    urllib.request.urlretrieve(download_url, temp_file)
    
    print("🔧 正在解压内核...")
    if is_windows:
        import zipfile
        with zipfile.ZipFile(temp_file, 'r') as zip_ref:
            # 找到压缩包里的 .exe 文件并提取
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith('.exe'):
                    zip_ref.extract(file_info, path=".")
                    # 重命名以确保一致性
                    if file_info.filename != core_name:
                        if os.path.exists(core_name):
                            os.remove(core_name)
                        os.rename(file_info.filename, core_name)
                    break
    else:
        with gzip.open(temp_file, 'rb') as f_in:
            with open(core_name, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.chmod(core_name, 0o755) # 赋予执行权限
            
    os.remove(temp_file)
    print("✅ 内核准备就绪！")
    return os.path.abspath(core_name)

def validate_configs_batch(core_path, config_paths, work_dir):
    """
    批量验证配置文件，检查 YAML 语法、策略组引用、Rule-Providers 连接性
    """
    print("\n" + "="*55)
    print("🚀 开始批量深度验证配置 (包含策略组与远端规则检查)...")
    print("="*55)

    failed_reports = {}
    passed_count = 0

    for config_path in config_paths:
        filename = os.path.basename(config_path)
        print(f"⏳ 正在测试 [{filename}] ...", end=" ", flush=True)
        
        # 核心：指定 -d 为配置生成的目录，这样内核会在该目录下模拟运行，自动下载或读取 geo / rules 数据
        result = subprocess.run(
            [core_path, "-d", work_dir, "-t", "-f", os.path.basename(config_path)], 
            capture_output=True, 
            text=True,
            cwd=work_dir 
        )
        
        if result.returncode == 0:
            print("✅ 验证通过")
            passed_count += 1
        else:
            print("❌ 验证失败")
            # 捕获并清洗报错日志
            error_msg = result.stdout.strip() + "\n" + result.stderr.strip()
            failed_reports[filename] = error_msg

    # === 生成友好的控制台测试报告 ===
    print("\n" + "="*55)
    print(f"📊 验证报告: 共测试 {len(config_paths)} 个文件，通过 {passed_count} 个，失败 {len(failed_reports)} 个")
    print("="*55)

    if failed_reports:
        print("\n🚨 致命错误阻断：规则或策略组存在异常！\n")
        for path, error in failed_reports.items():
            print(f"🛑 【{path}】")
            print("-" * 50)
            for line in error.split('\n'):
                # 过滤掉一些多余的内核启动 INFO 级废话，聚焦 ERROR 和 FATAL
                if "level=error" in line or "level=fatal" in line or "error" in line.lower():
                    print(f"   | {line.strip()}")
            print("-" * 50 + "\n")
        
        print("❌ 批量验证未通过，部署流水线已终止。")
        sys.exit(1) # 返回退出码 1，告诉 GitHub Actions 失败，不要提交代码
    else:
        print("🎉 完美！所有配置文件及策略组均通过内核严格校验，准备发布！\n")

def main():
    TEMPLATE_DIR = 'template'
    OUTPUT_DIR = 'release/configs'
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    def read_yaml(filename):
        filepath = os.path.join(TEMPLATE_DIR, filename)
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return clean_yaml_text(f.read())

    print("🧩 开始组装 Mihomo 配置文件...")
    anchors = read_yaml('anchors.yaml')
    rules = read_yaml('rule-providers&rules.yaml')
    base_config = anchors + "\n\n" + rules

    box_diff = read_yaml('box.diff.yaml')
    surfing_diff = read_yaml('surfing.diff.yaml')

    box_path = os.path.join(OUTPUT_DIR, 'box.yaml')
    surfing_path = os.path.join(OUTPUT_DIR, 'surfing.yaml')

    with open(box_path, 'w', encoding='utf-8') as f:
        f.write(box_diff + "\n\n" + base_config)
    
    with open(surfing_path, 'w', encoding='utf-8') as f:
        f.write(surfing_diff + "\n\n" + base_config)
        
    print(f"✅ 成功生成配置到 {OUTPUT_DIR}/ 目录")

    # --- 启动自动化防错检查 ---
    try:
        core_path = get_mihomo_core()
        # 传递 OUTPUT_DIR 的绝对路径，让内核在这个目录下模拟沙盒运行验证
        work_dir = os.path.abspath(OUTPUT_DIR)
        validate_configs_batch(core_path, [box_path, surfing_path], work_dir)
    except Exception as e:
        print(f"\n⚠️ 验证器组件异常退出: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
