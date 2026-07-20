import os
import re
import base64
import asyncio
import time
import urllib.request
import urllib.parse
import random
import yaml
import maxminddb
import datetime
import sys
import subprocess
import requests
import json

# ==================== 🛠️ 全局与策略配置 ====================
WORK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBS_DIR = os.path.join(WORK_DIR, 'subs')
BLACKLIST_FILE = os.path.join(SUBS_DIR, 'blacklist.txt')

ALLOWED_PROTOCOLS = r'^(vless|vmess|trojan|hysteria2|hy2|tuic)://'
DIRTY_WORDS = re.compile(
    r'佣金|套餐|官网|官方|网址|售后|免翻|过期|剩余|到期|流量|更新|点外|重置|免流|使用|教程|优惠|超实惠|群|址|TG|AFF|Days|Date', 
    re.IGNORECASE
)

TARGET_COUNTRIES = ['HK', 'TW', 'JP', 'SG', 'US', 'KR', 'TH', 'VN', 'MY', 'PH', 'IN', 'GB', 'DE', 'RU', 'TR']
COUNTRY_DICT = {
    'HK': r'hk|hongkong|香港|深港|港', 'TW': r'tw|taiwan|台湾|台灣|台北|新北|台',
    'JP': r'jp|japan|日本|东京|大阪|埼玉|川崎', 'SG': r'sg|singapore|新加坡|狮城',
    'US': r'us|america|美国|美國|洛杉矶|波特兰|硅谷|圣开塞', 'KR': r'kr|korea|韩国|韓國|首尔|春川',
    'TH': r'th|thailand|泰国|泰國|曼谷', 'VN': r'vn|vietnam|越南|胡志明|河内',
    'MY': r'my|malaysia|马来西亚|馬來西亞|吉隆坡', 'PH': r'ph|philippines|菲律宾|菲律賓|马尼拉',
    'IN': r'in|india|印度|孟买', 'GB': r'gb|uk|britain|英国|英國|伦敦',
    'DE': r'de|germany|德国|德國|法兰克福',
    'RU': r'ru|russia|俄罗斯|俄国|莫斯科|圣彼得堡|伯力',
    'TR': r'tr|turkey|turkiye|土耳其|伊斯坦布尔'
}

TCP_TIMEOUT = 1.5
MAX_CONCURRENT = 200

# 🌟 策略解耦: 针对不同池子实施不同级别的宽容度
POOLS = {
    'SubPre': {'input': 'SubPreOrg.txt', 'limit': 99999, 'region_limit': 99999, 'filter_dirty': False, 'drop_dead': False, 'country_lock': True},
    'SubCF': {'input': 'SubCFOrg.txt', 'limit': 99999, 'region_limit': 99999, 'filter_dirty': False, 'drop_dead': True, 'country_lock': False},
    'SubFree': {'input': 'SubFreeOrg.txt', 'limit': 1000, 'region_limit': 50, 'filter_dirty': True, 'drop_dead': True, 'country_lock': True}
}

#     """每周一清空过期黑名单"""
def reset_blacklist_if_monday():
    """每周一清空过期黑名单"""
    if datetime.datetime.now().weekday() == 0:
        if os.path.exists(BLACKLIST_FILE):
            with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if len(lines) > 1000:
                with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
                    f.writelines(lines[-1000:])
                print_log("周一已自动重置黑名单，保留最后 1000 条活跃拦截", "🔄")
                
# 全局变量用于跨流程存储面板数据
GLOBAL_REGIONS = []

def print_log(msg, icon="💡"):
    print(f"[{time.strftime('%H:%M:%S')}] {icon} {msg}")
    sys.stdout.flush()

def load_blacklist():
    if not os.path.exists(BLACKLIST_FILE): return set()
    with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f if line.strip())

def save_blacklist(bl_set):
    bl_list = list(bl_set)[-50000:]
    with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f: f.write('\n'.join(bl_list))

def build_standard_url_from_clash(p):
    """正向解析：将 Clash 字典转为标准 URI (融合了 gRPC 与 servername 兼容)"""
    try:
        ptype = str(p.get('type', '')).lower()
        if ptype not in ['vless', 'vmess', 'trojan', 'hysteria2', 'hy2', 'tuic']: return None
        server = p.get('server', '')
        port = p.get('port', '')
        credential = p.get('uuid') or p.get('password') or p.get('secret', '')
        base_url = f"{ptype}://{credential}@{server}:{port}" if credential else f"{ptype}://{server}:{port}"
        
        params = {}
        if p.get('tls') or p.get('security') == 'tls':
            params['security'] = 'tls'
            if p.get('sni'): params['sni'] = p.get('sni')
            elif p.get('servername'): params['sni'] = p.get('servername')
            if p.get('skip-cert-verify'): params['allowInsecure'] = '1'
            
        network = p.get('network', 'tcp').lower()
        if network in ['ws', 'websocket']:
            params['type'] = 'ws'
            ws_opts = p.get('ws-opts', {}) or p.get('ws-parameters', {})
            if ws_opts.get('path'): params['path'] = ws_opts.get('path')
            headers = ws_opts.get('headers', {})
            if headers and headers.get('Host'): params['host'] = headers.get('Host')
        elif network == 'grpc':
            params['type'] = 'grpc'
            grpc_opts = p.get('grpc-opts', {})
            if grpc_opts.get('grpc-service-name'): params['serviceName'] = grpc_opts.get('grpc-service-name')
            
        res_url = f"{base_url}?{urllib.parse.urlencode(params)}" if params else base_url
        name = p.get('name', '')
        if name: res_url += f"#{urllib.parse.quote(name)}"
        return res_url
    except: return None

def extract_nodes_from_text(text):
    extracted = []
    text_str = text.strip()
    if not text_str: return extracted

    if "proxies:" in text_str:
        try:
            data = yaml.safe_load(text_str)
            if data and 'proxies' in data:
                for p in data['proxies']:
                    std_link = build_standard_url_from_clash(p)
                    if std_link: extracted.append(std_link)
                return extracted
        except: pass

    try:
        padded = text_str + '=' * (-len(text_str) % 4)
        decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
        if any(proto in decoded.lower() for proto in ['vless://', 'vmess://', 'trojan://']):
            text_str = decoded
    except: pass

    for line in text_str.splitlines():
        line = line.strip()
        if re.match(ALLOWED_PROTOCOLS, line, re.IGNORECASE):
            extracted.append(line)
    return extracted

def uri_to_proxy_dict(uri, new_name):
    """反向序列化：将标准 URI 转回 Clash 字典 (同步支持 gRPC 还原)"""
    try:
        core = uri.split('#')[0]
        scheme, rest = core.split('://', 1)
        scheme = scheme.lower()
        p = {"name": new_name, "type": scheme}
        
        if scheme == 'vmess':
            padded = rest + '=' * (-len(rest) % 4)
            d = json.loads(base64.b64decode(padded).decode('utf-8'))
            p.update({
                "server": d.get("add", ""), "port": int(d.get("port", 443)),
                "uuid": d.get("id", ""), "alterId": int(d.get("aid", 0)),
                "cipher": d.get("scy", "auto"), "network": d.get("net", "tcp")
            })
            if d.get("tls") == "tls": p["tls"] = True
            if d.get("sni"): p["sni"] = d.get("sni")
            if p["network"] == "ws":
                p["ws-opts"] = {"path": d.get("path", "")}
                if d.get("host"): p["ws-opts"]["headers"] = {"Host": d.get("host")}
            elif p["network"] == "grpc":
                p["grpc-opts"] = {}
                if d.get("path"): p["grpc-opts"]["grpc-service-name"] = d.get("path")
            return p
            
        auth_split = rest.split('@', 1)
        auth, host_port_params = auth_split if len(auth_split) == 2 else ("", rest)
        hp_split = host_port_params.split('?', 1)
        host_port, params_str = hp_split if len(hp_split) == 2 else (host_port_params, "")
        host, port = host_port.split(':', 1)
        
        p["server"] = host; p["port"] = int(port)
        if scheme == 'vless': p["uuid"] = auth
        elif scheme == 'trojan': p["password"] = auth
        elif scheme in ['hy2', 'hysteria2']: p["password"] = auth; p["type"] = "hysteria2"
        elif scheme == 'tuic': 
            if ':' in auth: p["uuid"], p["password"] = auth.split(':', 1)
            else: p["uuid"] = auth
            
        if params_str:
            params = dict(urllib.parse.parse_qsl(params_str))
            if params.get("security") == "tls": p["tls"] = True
            if params.get("sni"): p["sni"] = params.get("sni")
            if params.get("allowInsecure") == "1": p["skip-cert-verify"] = True
            
            if params.get("type") == "ws": 
                p["network"] = "ws"
                p["ws-opts"] = {}
                if params.get("path"): p["ws-opts"]["path"] = params.get("path")
                if params.get("host"): p["ws-opts"]["headers"] = {"Host": params.get("host")}
            elif params.get("type") == "grpc":
                p["network"] = "grpc"
                p["grpc-opts"] = {}
                if params.get("serviceName"): p["grpc-opts"]["grpc-service-name"] = params.get("serviceName")
                
        return p
    except: return None

def fetch_url_content(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mihomo-Cleaner/1.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print_log(f"抓取失败 [{url}]: {e}", "⚠️")
        return ""

def parse_nodes_from_file(filepath):
    nodes = []
    if not os.path.exists(filepath): return nodes
    with open(filepath, 'r', encoding='utf-8') as f: content = f.read().strip()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        url_match = re.search(r'(https?://[^\s]+)', line)
        if url_match:
            print_log(f"正在抓取远程订阅: {url_match.group(1)}", "⬇️")
            sub_content = fetch_url_content(url_match.group(1))
            nodes.extend(extract_nodes_from_text(sub_content))
        else: nodes.extend(extract_nodes_from_text(line))
    return nodes

def extract_fingerprint(uri):
    try:
        core = uri.split('#')[0]
        match = re.search(r'^(?P<proto>[a-z2]+)://(?:(?P<auth>[^@]+)@)?(?P<host>[^:/]+)(?::(?P<port>\d+))?', core, re.IGNORECASE)
        if match: return core, match.group('host'), int(match.group('port')) if match.group('port') else 443
    except: pass
    return None, None, None

def get_country_from_name(name):
    name_lower = urllib.parse.unquote(name).lower()
    for code, pattern in COUNTRY_DICT.items():
        if re.search(pattern, name_lower): return code
    return None

def lookup_geo_asn(host):
    country, is_cf = 'UNKNOWN', False
    try:
        with maxminddb.open_database(os.path.join(WORK_DIR, 'GeoLite2-ASN.mmdb')) as asn_db:
            res = asn_db.get(host)
            if res and res.get('autonomous_system_number') == 13335: is_cf = True
        if not is_cf:
            with maxminddb.open_database(os.path.join(WORK_DIR, 'GeoLite2-Country.mmdb')) as country_db:
                res = country_db.get(host)
                if res and 'country' in res: country = res['country'].get('iso_code', 'UNKNOWN').upper()
    except: pass
    return country, is_cf

# ==================== 🛠️ 核心：Mihomo 真机引擎 ====================

class MihomoTester:
    def __init__(self, proxy_dicts, work_dir):
        self.proxies = proxy_dicts; self.work_dir = work_dir
        self.api_base = "http://127.0.0.1:9090"; self.proxy_port = 7890; self.process = None

    def start(self):
        if not self.proxies: return
        os.makedirs(f"{self.work_dir}/.temp_mihomo", exist_ok=True)
        config = {"port": self.proxy_port, "external-controller": "127.0.0.1:9090", "proxies": self.proxies, "proxy-groups": [{"name": "API-TEST", "type": "select", "proxies": [p['name'] for p in self.proxies]}]}
        with open(f"{self.work_dir}/.temp_mihomo/config.yaml", 'w', encoding='utf-8') as f: yaml.dump(config, f, allow_unicode=True)
        self.process = subprocess.Popen(["./mihomo", "-d", f"{self.work_dir}/.temp_mihomo", "-f", f"{self.work_dir}/.temp_mihomo/config.yaml"], cwd=self.work_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)

    def run_tests(self):
        results = {}
        for p in self.proxies:
            name = p['name']
            try:
                requests.put(f"{self.api_base}/proxies/API-TEST", json={"name": name}, timeout=2)
                start = time.time()
                res = requests.get("https://1.1.1.1/cdn-cgi/trace", proxies={"http": f"http://127.0.0.1:{self.proxy_port}", "https": f"http://127.0.0.1:{self.proxy_port}"}, timeout=3.5)
                loc = "UNKNOWN"
                for line in res.text.splitlines():
                    if line.startswith("loc="): loc = line.split("=")[1].strip(); break
                results[name] = {"alive": True, "latency": int((time.time() - start) * 1000), "loc": loc}
                print_log(f"真机突破: {name} -> 落地:{loc}", "🟢")
            except: results[name] = {"alive": False}
        return results

    def stop(self):
        if self.process: self.process.terminate(); self.process.wait()

async def tcp_ping(host, port, sem):
    async with sem:
        try:
            start_time = time.time()
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=TCP_TIMEOUT)
            writer.close()
            await writer.wait_closed()
            return True, int((time.time() - start_time) * 1000)
        except: return False, 9999

async def tcp_ping_batch(nodes):
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = []
    for node in nodes:
        async def _check(n):
            alive, lat = await tcp_ping(n['host'], n['port'], sem)
            n['alive'], n['latency'] = alive, lat
            return n
        tasks.append(asyncio.create_task(_check(node)))
    return await asyncio.gather(*tasks)

def get_base_group_name(pool, is_cf, country):
    """获取区域节点细分的归属组别名"""
    c = country if country and country != "UNKNOWN" else "保留原名组" if pool == "SubCF" else "UNKNOWN"
    if pool == "SubPre": return f"Pre-{c}"
    elif pool == "SubCF": return f"CF-{c}"
    elif pool == "SubFree": return f"Free-CF-{c}" if is_cf else f"Free-{c}"
    return "Unknown"

def generate_readme(all_stats):
    tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')

    md = f"# 🚀 节点多态清洗与双轨探活看板\n\n> **🕒 最新更新时间:** `{now}` (UTC+8)\n\n"
    
    for pool_name, stats in all_stats.items():
        md += f"## 📊 {pool_name} 淘汰漏斗\n"
        md += "| 阶段 | 数量对比 | 描述 |\n| :--- | :--- | :--- |\n"
        md += f"| 📦 **抓取解包** | `{stats['total_raw']}` ➔ `{stats['clean']}` | 剔除脏词与去重 |\n"
        md += f"| 🌍 **国别锁定** | `{stats['clean']}` ➔ `{stats['target']}` | {('锁定 15 国目标' if POOLS[pool_name]['country_lock'] else '放行全域国家')} |\n"
        md += f"| 💀 **探活清洗** | `{stats['target']}` ➔ `{stats['alive']}` | {('剔除 '+str(stats['target'] - stats['alive'])+' 个失效节点' if POOLS[pool_name]['drop_dead'] else '特权节点免剔除')} |\n"
        md += f"| 🎯 **成品输出** | **`{stats['final']}`** 节点可用 | `TXT` / `YAML` 双发 |\n\n"

    md += "## 🌍 区域节点细分\n"
    md += "| 订阅池 | 区域组别 | 初始数量 | 最终可用 |\n| :--- | :--- | :--- | :--- |\n"
    
    GLOBAL_REGIONS.sort(key=lambda x: (x['level'], x['group_name']))
    for r in GLOBAL_REGIONS:
        md += f"| {r['icon']} | `{r['group_name']}` | {r['initial']} | {r['final']} |\n"

    with open(os.path.join(WORK_DIR, 'README.md'), 'w', encoding='utf-8') as f: f.write(md)

# ==================== 🛠️ 主逻辑 ====================
def main():
    print_log("=== 节点清洗流水线启动 ===", "🏁")
    reset_blacklist_if_monday()
    blacklist = load_blacklist()
    print_log(f"已加载历史黑名单库，当前拦截总数: {len(blacklist)}", "🛡️")
    
    all_stats = {}

    for pool_name, cfg in POOLS.items():
        print_log(f"\n[{pool_name}] 开始流水线...", "🔥")
        in_file = os.path.join(SUBS_DIR, cfg['input'])
        raw_nodes = parse_nodes_from_file(in_file)
        if not raw_nodes: continue

        # 1. 去重与降噪 (增加详细日志)
        unique_fps, clean_nodes = set(), []
        dirty_cnt, bl_cnt = 0, 0
        for uri in raw_nodes:
            if cfg['filter_dirty'] and DIRTY_WORDS.search(uri): 
                dirty_cnt += 1; continue
            fingerprint, host, port = extract_fingerprint(uri)
            if not fingerprint: continue
            if host in blacklist: 
                bl_cnt += 1; continue
            if fingerprint not in unique_fps:
                unique_fps.add(fingerprint)
                clean_nodes.append({'uri': fingerprint, 'name': uri.split('#')[1] if '#' in uri else "", 'host': host, 'port': port, 'original': uri})

        print_log(f"🧹 清洗统计: 剔除脏词 {dirty_cnt} 个，黑名单阻断 {bl_cnt} 个", "🛡️")

        # 2. 国别与基建界定
        cf_nodes, non_cf_nodes = [], []
        group_initial_counters = {}
        for n in clean_nodes:
            country = get_country_from_name(n['name'])
            is_cf = False
            if not country: country, is_cf = lookup_geo_asn(n['host'])
            else: _, is_cf = lookup_geo_asn(n['host'])
            
            n.update({'country': country, 'is_cf': is_cf})
            
            if not cfg.get('country_lock', True) or country in TARGET_COUNTRIES or (is_cf and pool_name == 'SubFree'):
                if is_cf: cf_nodes.append(n)
                else: non_cf_nodes.append(n)
                
                g_name = get_base_group_name(pool_name, is_cf, country)
                group_initial_counters[g_name] = group_initial_counters.get(g_name, 0) + 1

        print_log(f"🔍 分类完毕: CF任播 {len(cf_nodes)} 个, 非CF直连 {len(non_cf_nodes)} 个", "🧭")

        # 3. 探活轨道 A: 非 CF 节点 TCP 测速
        alive_non_cf = []
        if non_cf_nodes:
            results = asyncio.run(tcp_ping_batch(non_cf_nodes))
            for r in results:
                if r['alive'] or not cfg['drop_dead']: alive_non_cf.append(r)
                if not r['alive'] and cfg['drop_dead']: blacklist.add(r['host'])

        # 4. 探活轨道 B: CF 节点 七层内核测速
        alive_cf = []
        if cf_nodes:
            cf_sample = random.sample(cf_nodes, min(600, len(cf_nodes)))
            test_dicts = []
            for n in cf_sample:
                d = uri_to_proxy_dict(n['original'], f"TEST-{n['host']}")
                if d: test_dicts.append((n, d))
                
            tester = MihomoTester([td for n, td in test_dicts], WORK_DIR)
            tester.start()
            cf_results = tester.run_tests()
            tester.stop()
            
            for n, proxy_dict in test_dicts:
                res = cf_results.get(proxy_dict['name'], {})
                if res.get('alive') or not cfg['drop_dead']:
                    n['latency'] = res.get('latency', 9999)
                    if res.get('loc', 'UNKNOWN') != "UNKNOWN": n['country'] = res['loc']
                    alive_cf.append(n)
                if not res.get('alive') and cfg['drop_dead']: blacklist.add(n['host'])

        # 5. 组装、格式化与区域看板统计
        final_list = []
        region_counts = {}
        all_alive = alive_non_cf + alive_cf
        all_alive.sort(key=lambda x: x['latency'])

        out_txt, out_yaml_proxies = [], []
        country_idx = {}
        group_final_counters = {}

        for n in all_alive:
            c = n['country'] or "UNKNOWN"
            g_name = get_base_group_name(pool_name, n['is_cf'], c)
            region_counts.setdefault(g_name, 0)
            
            if region_counts[g_name] < cfg['region_limit']:
                region_counts[g_name] += 1
                final_list.append(n)
            
        for n in final_list:
            c = n['country'] if n['country'] else "UNKNOWN"
            g_name = get_base_group_name(pool_name, n['is_cf'], c)
            
            group_final_counters[g_name] = group_final_counters.get(g_name, 0) + 1
            
            country_idx[g_name] = country_idx.get(g_name, 0) + 1
            final_name = f"Sub{g_name}-{country_idx[g_name]:02d}"
            
            out_txt.append(f"{n['uri']}#{final_name}")
            proxy_dict = uri_to_proxy_dict(n['original'], final_name)
            if proxy_dict: out_yaml_proxies.append(proxy_dict)

        icon_map = {'SubPre': (1, "💎 专线/付费"), 'SubCF': (2, "☁️ CF自建"), 'SubFree': (3, "🎁 免费池")}
        for g_name, initial_val in group_initial_counters.items():
            if g_name.endswith('UNKNOWN') and pool_name != 'SubCF': continue 
            GLOBAL_REGIONS.append({
                'level': icon_map[pool_name][0],
                'icon': icon_map[pool_name][1],
                'group_name': g_name,
                'initial': initial_val,
                'final': group_final_counters.get(g_name, 0)
            })

        # 6. 生成物理文件
        with open(os.path.join(SUBS_DIR, f"{pool_name}.txt"), 'w', encoding='utf-8') as f:
            f.write('\n'.join(out_txt))
        with open(os.path.join(SUBS_DIR, f"{pool_name}.yaml"), 'w', encoding='utf-8') as f:
            yaml.dump({"proxies": out_yaml_proxies}, f, allow_unicode=True, sort_keys=False)

        all_stats[pool_name] = {
            'total_raw': len(raw_nodes), 'clean': len(clean_nodes),
            'target': len(cf_nodes) + len(non_cf_nodes), 'alive': len(all_alive), 'final': len(final_list)
        }
        print_log(f"[{pool_name}] 产出完成! TXT/YAML 已生成。", "✅")

    save_blacklist(blacklist)
    generate_readme(all_stats)
    print_log("=== 所有流水线任务执行完毕 ===", "🎉")

if __name__ == "__main__": main()
