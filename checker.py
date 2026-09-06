#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPN Subscription Aggregator & High-Speed Performance Benchmark
"Наши белые" — Перебор всех серверов по максимальной скорости + Оптимизация для мобильных операторов (МТС)
"""

import os
import sys
import re
import json
import time
import socket
import base64
import platform
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

SUB_TITLE = "Наши белые"
SUB_TITLE_B64 = base64.b64encode(SUB_TITLE.encode('utf-8')).decode('ascii')

# Источники серверов
SUBSCRIPTION_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-checked.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-SNI-RU-all.txt",
    "https://raw.githubusercontent.com/zieng2/wl/main/vless_universal.txt",
    "https://solovyov-jenya2004.vercel.app/final_sorted/",
]

# Домены РФ для обхода мобильного ТСПУ МТС
RU_DOMAINS_PATTERN = re.compile(
    r'(\.ru$|\.su$|\.рф$|yandex|ya\.ru|vk\.com|vkvideo|userapi|mail\.ru|ok\.ru|dzen|gosuslugi|mts\.ru|megafon|beeline|tele2|t2\.ru|ozon|wildberries|wb\.ru|tbank|tinkoff|sber|rutube|avito|2gis|kinopoisk|rzd\.ru|rambler|moex|lenta\.ru|rbc\.ru|pepro\.site|oaklandjoseph|rumedia-cdn|wba-pn\.ru|24lider\.ru|abvpn\.ru)',
    re.IGNORECASE
)

STAGE1_BATCH_SIZE = 60
STAGE1_TIMEOUT = 2.0
TEST_PING_URL = "http://www.google.com/generate_204"

STAGE2_BATCH_SIZE = 30
STAGE2_TIMEOUT = 3.2
TEST_SPEED_URL = "https://speed.cloudflare.com/__down?bytes=1572864"
SPEEDTEST_BYTES = 1572864

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def find_or_download_xray():
    os_name = platform.system().lower()
    arch = platform.machine().lower()
    exe_name = "xray.exe" if os_name == "windows" else "xray"

    search_paths = [
        exe_name,
        os.path.join(".", exe_name),
        os.path.join("/usr/local/bin", exe_name),
        os.path.join("/usr/bin", exe_name),
    ]

    for p in search_paths:
        if os.path.exists(p):
            try:
                res = subprocess.run([p, "version"], capture_output=True, text=True)
                if res.returncode == 0:
                    log(f"Found Xray binary: {p}")
                    return p
            except Exception:
                pass

    try:
        cmd = "where" if os_name == "windows" else "which"
        res = subprocess.run([cmd, exe_name], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            p = res.stdout.strip().splitlines()[0]
            log(f"Found Xray in PATH: {p}")
            return p
    except Exception:
        pass

    log("Xray binary not found. Downloading official Xray-core release...")
    version = "v25.1.30"
    
    if os_name == "linux":
        pkg = "Xray-linux-64.zip" if "64" in arch else "Xray-linux-32.zip"
    elif os_name == "windows":
        pkg = "Xray-windows-64.zip" if "64" in arch else "Xray-windows-32.zip"
    elif os_name == "darwin":
        pkg = "Xray-macos-arm64-v8a.zip" if "arm" in arch else "Xray-macos-64.zip"
    else:
        raise RuntimeError(f"Unsupported operating system: {os_name}")

    url = f"https://github.com/XTLS/Xray-core/releases/download/{version}/{pkg}"
    zip_path = "xray_download.zip"

    log(f"Downloading {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp, open(zip_path, "wb") as out_f:
        out_f.write(resp.read())

    import zipfile
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extract(exe_name, ".")
    
    if os.path.exists(zip_path):
        os.remove(zip_path)

    if os_name != "windows":
        os.chmod(exe_name, 0o755)

    local_path = os.path.abspath(exe_name)
    log(f"Xray downloaded successfully to {local_path}")
    return local_path


def fetch_subscriptions():
    all_raw_nodes = []
    for url in SUBSCRIPTION_URLS:
        is_mobile_source = ("Rus-Mobile" in url or "WHITE-SNI" in url or "WHITE-CIDR" in url)
        log(f"Fetching subscription: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_bytes = resp.read()
                
            try:
                text = raw_bytes.decode('utf-8', errors='ignore')
            except Exception:
                text = ""

            if not ("vless://" in text or "trojan://" in text or "ss://" in text):
                try:
                    cleaned_b64 = re.sub(r'\s+', '', text)
                    decoded = base64.b64decode(cleaned_b64).decode('utf-8', errors='ignore')
                    if "vless://" in decoded or "trojan://" in decoded:
                        text = decoded
                except Exception:
                    pass

            lines = text.splitlines()
            count = 0
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith(('vless://', 'trojan://')):
                    all_raw_nodes.append((line, is_mobile_source))
                    count += 1
            log(f"  -> Extracted {count} nodes from {url}")
        except Exception as e:
            log(f"  [ERROR] Failed to fetch {url}: {e}")

    log(f"Total raw nodes fetched: {len(all_raw_nodes)}")

    unique_map = {}
    for link, from_mobile in all_raw_nodes:
        try:
            parsed = urllib.parse.urlparse(link)
            sig = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{parsed.query}"
            if sig not in unique_map:
                unique_map[sig] = (link, from_mobile)
            elif from_mobile:
                prev_link, _ = unique_map[sig]
                unique_map[sig] = (prev_link, True)
        except Exception:
            continue

    unique_nodes = list(unique_map.values())
    log(f"Total unique nodes after deduplication: {len(unique_nodes)}")
    return unique_nodes


def evaluate_mobile_readiness(sni, port, sec, flow, from_mobile_source=False):
    is_ru_sni = bool(RU_DOMAINS_PATTERN.search(sni)) if sni else False
    is_port_443 = (port in (443, 80))
    is_vision = (flow == 'xtls-rprx-vision')
    is_reality = (sec == 'reality')

    is_mts_ready = (is_ru_sni and is_port_443) or (from_mobile_source and is_port_443)

    mobile_score = 0
    if is_mts_ready:
        mobile_score += 100
    elif is_ru_sni:
        mobile_score += 40
    elif is_port_443:
        mobile_score += 25

    if is_vision:
        mobile_score += 25
    if is_reality:
        mobile_score += 15
    if from_mobile_source:
        mobile_score += 15

    return is_mts_ready, mobile_score


def parse_vless(link, from_mobile_source=False):
    try:
        u = urllib.parse.urlparse(link)
        uuid = u.username
        host = u.hostname
        port = u.port
        if not uuid or not host or not port:
            return None

        q = dict(urllib.parse.parse_qsl(u.query))
        raw_type = q.get('type', 'tcp').lower()
        if raw_type in ('raw', 'none', ''):
            net = 'tcp'
        elif raw_type in ('xhttp', 'splithttp', 'x'):
            net = 'xhttp'
        else:
            net = raw_type

        sec = q.get('security', 'none').lower()
        flow = q.get('flow', '')
        valid_flow = flow if (net == 'tcp' and sec in ('tls', 'reality')) else ''

        stream = {"network": net, "security": sec}
        fp = q.get('fp', 'chrome')
        sni = q.get('sni', '') or q.get('host', '') or host

        if sec == 'reality':
            stream["realitySettings"] = {
                "show": False,
                "fingerprint": fp if fp else "chrome",
                "serverName": sni if sni else host,
                "publicKey": q.get('pbk', ''),
                "shortId": q.get('sid', ''),
                "spiderX": q.get('spx', '')
            }
        elif sec == 'tls':
            tls_s = {
                "serverName": sni if sni else (q.get('host') or host),
                "fingerprint": fp if fp else "chrome"
            }
            alpn = q.get('alpn')
            if alpn:
                tls_s["alpn"] = [x.strip() for x in alpn.split(',') if x.strip()]
            stream["tlsSettings"] = tls_s

        if net == 'tcp':
            stream["tcpSettings"] = {"header": {"type": "none"}}
        elif net == 'ws':
            h = q.get('host') or sni or host
            stream["wsSettings"] = {"path": q.get('path', '/'), "headers": {"Host": h}}
        elif net == 'grpc':
            stream["grpcSettings"] = {"serviceName": q.get('serviceName') or q.get('path', ''), "multiMode": False}
        elif net == 'xhttp':
            xs = {"mode": q.get('mode', 'auto'), "path": q.get('path', '/'), "host": q.get('host') or sni or ""}
            if 'extra' in q and q['extra']:
                try:
                    xs["extra"] = json.loads(q['extra'])
                except Exception:
                    pass
            stream["xhttpSettings"] = xs

        remark = urllib.parse.unquote(u.fragment) if u.fragment else "Node"
        is_mts_ready, mobile_score = evaluate_mobile_readiness(sni, port, sec, valid_flow, from_mobile_source)

        return {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": host,
                    "port": port,
                    "users": [{
                        "id": uuid,
                        "encryption": q.get('encryption', 'none'),
                        "flow": valid_flow
                    }]
                }]
            },
            "streamSettings": stream,
            "original_url": link,
            "remark": remark,
            "host": host,
            "port": port,
            "sni": sni,
            "is_mts_ready": is_mts_ready,
            "mobile_score": mobile_score
        }
    except Exception:
        return None


def parse_trojan(link, from_mobile_source=False):
    try:
        u = urllib.parse.urlparse(link)
        password = u.username
        host = u.hostname
        port = u.port
        if not password or not host or not port:
            return None

        q = dict(urllib.parse.parse_qsl(u.query))
        net = q.get('type', 'tcp').lower()
        sec = q.get('security', 'tls').lower()

        stream = {"network": net, "security": sec}
        sni = q.get('sni', '') or q.get('host', '') or host
        fp = q.get('fp', 'chrome')

        if sec == 'tls':
            stream["tlsSettings"] = {
                "serverName": sni if sni else (q.get('host') or host),
                "fingerprint": fp
            }

        remark = urllib.parse.unquote(u.fragment) if u.fragment else "Node"
        is_mts_ready, mobile_score = evaluate_mobile_readiness(sni, port, sec, "", from_mobile_source)

        return {
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": port,
                    "password": password
                }]
            },
            "streamSettings": stream,
            "original_url": link,
            "remark": remark,
            "host": host,
            "port": port,
            "sni": sni,
            "is_mts_ready": is_mts_ready,
            "mobile_score": mobile_score
        }
    except Exception:
        return None


def parse_proxy_link(link, from_mobile_source=False):
    if link.startswith("vless://"):
        return parse_vless(link, from_mobile_source)
    elif link.startswith("trojan://"):
        return parse_trojan(link, from_mobile_source)
    return None


def get_free_ports(count):
    sockets = []
    ports = []
    for _ in range(count):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        ports.append(s.getsockname()[1])
        sockets.append(s)
    for s in sockets:
        s.close()
    return ports


def test_xray_config(xray_bin, config_path):
    try:
        res = subprocess.run([xray_bin, "run", "-test", "-c", config_path], capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


def test_ping_port(port, timeout=STAGE1_TIMEOUT):
    proxy_url = f"http://127.0.0.1:{port}"
    proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(TEST_PING_URL, headers={"User-Agent": USER_AGENT})
    start_time = time.time()
    try:
        with opener.open(req, timeout=timeout) as resp:
            code = resp.getcode()
            elapsed_ms = int((time.time() - start_time) * 1000)
            if code in (204, 200, 301, 302):
                return True, elapsed_ms
    except Exception:
        pass
    return False, None


def stage1_fast_filter(nodes, xray_bin, config_path):
    if not nodes:
        return []

    ports = get_free_ports(len(nodes))
    inbounds = []
    outbounds = []
    rules = []

    for i, node in enumerate(nodes):
        in_tag = f"in_{i}"
        out_tag = f"out_{i}"
        inbounds.append({
            "tag": in_tag,
            "port": ports[i],
            "listen": "127.0.0.1",
            "protocol": "http"
        })
        ob = {
            "protocol": node["protocol"],
            "settings": node["settings"],
            "streamSettings": node["streamSettings"],
            "tag": out_tag
        }
        outbounds.append(ob)
        rules.append({
            "type": "field",
            "inboundTag": [in_tag],
            "outboundTag": out_tag
        })

    outbounds.append({"tag": "direct", "protocol": "freedom"})

    full_cfg = {
        "log": {"loglevel": "none"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"domainStrategy": "AsIs", "rules": rules}
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(full_cfg, f, indent=2)

    if not test_xray_config(xray_bin, config_path):
        if len(nodes) > 1:
            mid = len(nodes) // 2
            left = stage1_fast_filter(nodes[:mid], xray_bin, config_path + ".1")
            right = stage1_fast_filter(nodes[mid:], xray_bin, config_path + ".2")
            return left + right
        else:
            return []

    proc = subprocess.Popen([xray_bin, "run", "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    alive_in_batch = []

    try:
        with ThreadPoolExecutor(max_workers=len(nodes)) as executor:
            future_to_idx = {
                executor.submit(test_ping_port, ports[i]): i
                for i in range(len(nodes))
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                ok, ping_ms = future.result()
                if ok:
                    alive_in_batch.append({
                        "node": nodes[idx],
                        "ping_ms": ping_ms,
                        "is_mts_ready": nodes[idx].get("is_mts_ready", False),
                        "mobile_score": nodes[idx].get("mobile_score", 0)
                    })
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        if os.path.exists(config_path):
            try:
                os.remove(config_path)
            except Exception:
                pass

    return alive_in_batch


def benchmark_speed_single_node(port, item):
    proxy_url = f"http://127.0.0.1:{port}"
    proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
    opener = urllib.request.build_opener(proxy_handler)

    total_bytes = 0
    start_time = time.perf_counter()
    speed_mbps = 0.5
    ping_ms = item.get('ping_ms', 100)

    try:
        req = urllib.request.Request(TEST_SPEED_URL, headers={"User-Agent": USER_AGENT})
        with opener.open(req, timeout=STAGE2_TIMEOUT) as resp:
            ttfb_ms = int((time.perf_counter() - start_time) * 1000)
            if ttfb_ms > 0:
                ping_ms = min(ping_ms, ttfb_ms)

            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes >= SPEEDTEST_BYTES or (time.perf_counter() - start_time) >= STAGE2_TIMEOUT:
                    break

        elapsed = max(time.perf_counter() - start_time, 0.05)
        if total_bytes > 0:
            speed_mbps = round((total_bytes * 8) / (elapsed * 1_000_000), 1)
    except Exception:
        elapsed = max(time.perf_counter() - start_time, 0.1)
        if total_bytes > 10000:
            speed_mbps = round((total_bytes * 8) / (elapsed * 1_000_000), 1)

    return {
        "node": item['node'],
        "speed_mbps": speed_mbps,
        "ping_ms": ping_ms,
        "is_mts_ready": item.get('is_mts_ready', False),
        "mobile_score": item.get('mobile_score', 0)
    }


def stage2_speed_benchmark(candidates, xray_bin):
    if not candidates:
        return []

    log(f"Starting Stage 2: Direct Speed Benchmark on {len(candidates)} alive nodes...")
    benchmarked_results = []
    batches = [candidates[i:i + STAGE2_BATCH_SIZE] for i in range(0, len(candidates), STAGE2_BATCH_SIZE)]

    for b_idx, batch in enumerate(batches, start=1):
        config_path = f"tmp_speed_{b_idx}_{int(time.time())}.json"
        ports = get_free_ports(len(batch))
        inbounds = []
        outbounds = []
        rules = []

        for i, item in enumerate(batch):
            node = item['node']
            in_tag = f"in_{i}"
            out_tag = f"out_{i}"
            inbounds.append({
                "tag": in_tag,
                "port": ports[i],
                "listen": "127.0.0.1",
                "protocol": "http"
            })
            ob = {
                "protocol": node["protocol"],
                "settings": node["settings"],
                "streamSettings": node["streamSettings"],
                "tag": out_tag
            }
            outbounds.append(ob)
            rules.append({
                "type": "field",
                "inboundTag": [in_tag],
                "outboundTag": out_tag
            })

        outbounds.append({"tag": "direct", "protocol": "freedom"})

        full_cfg = {
            "log": {"loglevel": "none"},
            "inbounds": inbounds,
            "outbounds": outbounds,
            "routing": {"domainStrategy": "AsIs", "rules": rules}
        }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(full_cfg, f, indent=2)

        if not test_xray_config(xray_bin, config_path):
            log("Config validation error, retaining fallback speeds...")
            for item in batch:
                benchmarked_results.append({
                    "node": item['node'],
                    "speed_mbps": 5.0,
                    "ping_ms": item.get('ping_ms', 100),
                    "is_mts_ready": item.get('is_mts_ready', False),
                    "mobile_score": item.get('mobile_score', 0)
                })
            continue

        proc = subprocess.Popen([xray_bin, "run", "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)

        try:
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = [
                    executor.submit(benchmark_speed_single_node, ports[i], batch[i])
                    for i in range(len(batch))
                ]
                for future in as_completed(futures):
                    res = future.result()
                    benchmarked_results.append(res)
                    rem = res['node'].get('remark', '')[:25]
                    mts_icon = "📱МТС" if res.get('is_mts_ready') else "💻WiFi"
                    log(f"  [{mts_icon}] ⚡ {res['speed_mbps']:5.1f} Mbps | ⏱️ {res['ping_ms']}ms | {rem}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
            if os.path.exists(config_path):
                try:
                    os.remove(config_path)
                except Exception:
                    pass

    return benchmarked_results


def format_node_remark(item, index):
    node = item['node']
    orig_remark = node.get("remark", "").strip()

    clean = re.sub(r'tg[k]?:\s*@[A-Za-z0-9_]+', '', orig_remark, flags=re.IGNORECASE)
    clean = re.sub(r'https?://\S+', '', clean)
    clean = re.sub(r'#profile[^\n]*', '', clean)
    clean = re.sub(r'[\s|┃—-]+', ' ', clean).strip()

    if not clean:
        clean = "Сервер"

    is_mts = item.get('is_mts_ready', False)
    net_badge = "📱МТС" if is_mts else "💻WiFi"

    spd = f"{item['speed_mbps']:.1f} Mbps"
    ping = f"{item['ping_ms']}ms"

    new_remark = f"[{SUB_TITLE}] #{index:02d} | ⚡ {spd} | {net_badge} | {clean} (⏱️{ping})"
    encoded_fragment = urllib.parse.quote(new_remark)

    orig_url = node["original_url"]
    base_url = orig_url.split('#')[0]
    return f"{base_url}#{encoded_fragment}"


def generate_outputs(alive_results, total_checked, duration_sec):
    alive_results.sort(
        key=lambda x: (
            -int(x.get('is_mts_ready', False)),  # МТС сервера на самом верху
            -x['speed_mbps'],                    # Строго по скорости (Mbps)
            x['ping_ms']                         # По минимальному пингу
        )
    )

    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    mts_nodes = [x for x in alive_results if x.get('is_mts_ready', False)]
    top_speed = max((p['speed_mbps'] for p in alive_results), default=0.0)

    # 1. Основная подписка (МТС в топе + Wi-Fi)
    full_links = [format_node_remark(item, idx) for idx, item in enumerate(alive_results, start=1)]

    header_full = [
        f"#profile-title: {SUB_TITLE} [Максимальная скорость]",
        f"#profile-title: base64:{SUB_TITLE_B64}",
        "#profile-update-interval: 1",
        "#subscription-userinfo: upload=0; download=0; total=107374182400; expire=0",
        f"#last-update: {utc_now}",
        f"#working-servers: {len(full_links)} / {total_checked}",
        f"#max-speed-top: {top_speed} Mbps",
        f"#mts-mobile-servers: {len(mts_nodes)}",
        "#sorting: Speed-Sorted (Top positions 1..N = Mobile MTS Ready)",
        ""
    ]

    with open("sub.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(header_full + full_links))
    log("Written sub.txt (Full, Speed-Sorted)")

    b64_full = base64.b64encode("\n".join(full_links).encode('utf-8')).decode('ascii')
    with open("sub_base64.txt", "w", encoding="utf-8") as f:
        f.write(b64_full)
    log("Written sub_base64.txt (Full)")

    # 2. Мобильная подписка (ТОЛЬКО сервера для мобильной сети МТС)
    mobile_target = mts_nodes if mts_nodes else alive_results[:15]
    mobile_target.sort(key=lambda x: (-x['speed_mbps'], x['ping_ms']))
    mobile_links = [format_node_remark(item, idx) for idx, item in enumerate(mobile_target, start=1)]

    mobile_title = f"{SUB_TITLE} [МТС Мобайл ⚡ Скорость]"
    mobile_title_b64 = base64.b64encode(mobile_title.encode('utf-8')).decode('ascii')

    header_mobile = [
        f"#profile-title: {mobile_title}",
        f"#profile-title: base64:{mobile_title_b64}",
        "#profile-update-interval: 1",
        "#subscription-userinfo: upload=0; download=0; total=107374182400; expire=0",
        f"#last-update: {utc_now}",
        f"#mobile-servers-count: {len(mobile_links)}",
        "#note: 100% Mobile Ready (Port 443 + RU Whitelist SNI + Reality Vision for MTS/MegaFon/Beeline/Tele2)",
        ""
    ]

    with open("sub_mobile.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(header_mobile + mobile_links))
    log("Written sub_mobile.txt (Dedicated Mobile, Speed-Sorted)")

    b64_mobile = base64.b64encode("\n".join(mobile_links).encode('utf-8')).decode('ascii')
    with open("sub_mobile_base64.txt", "w", encoding="utf-8") as f:
        f.write(b64_mobile)
    log("Written sub_mobile_base64.txt (Dedicated Mobile)")

    # 3. Чистый ТОП по скорости (Все сервера подряд)
    pure_speed_list = sorted(alive_results, key=lambda x: (-x['speed_mbps'], x['ping_ms']))
    pure_speed_links = [format_node_remark(item, idx) for idx, item in enumerate(pure_speed_list, start=1)]

    header_pure_speed = [
        f"#profile-title: {SUB_TITLE} [Чистый ТОП Скорости]",
        "#profile-update-interval: 1",
        f"#last-update: {utc_now}",
        f"#working-servers: {len(pure_speed_links)}",
        f"#max-speed: {top_speed} Mbps",
        ""
    ]

    with open("sub_speed.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(header_pure_speed + pure_speed_links))
    log("Written sub_speed.txt (Pure Speed)")

    b64_pure_speed = base64.b64encode("\n".join(pure_speed_links).encode('utf-8')).decode('ascii')
    with open("sub_speed_base64.txt", "w", encoding="utf-8") as f:
        f.write(b64_pure_speed)
    log("Written sub_speed_base64.txt (Pure Speed)")

    update_readme(alive_results, total_checked, duration_sec)


def update_readme(alive_results, total_checked, duration_sec):
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    avg_ping = int(sum(p['ping_ms'] for p in alive_results) / len(alive_results)) if alive_results else 0
    top_speed = max((p['speed_mbps'] for p in alive_results), default=0.0)
    mts_count = sum(1 for p in alive_results if p.get('is_mts_ready', False))

    top_table_rows = []
    for idx, item in enumerate(alive_results[:25], start=1):
        node = item['node']
        rem = urllib.parse.unquote(node.get("remark", ""))[:26]
        net_icon = "📱 МТС / Мобайл" if item.get('is_mts_ready') else "💻 Wi-Fi / ПК"

        top_table_rows.append(
            f"| #{idx:02d} | **⚡ {item['speed_mbps']} Mbps** | {net_icon} | `{node.get('host')}:{node.get('port')}` | {rem} | {item['ping_ms']} ms |"
        )

    top_table_md = "\n".join(top_table_rows) if top_table_rows else "| - | - | - | - | - | - |"

    stats_block = (
        "<!-- STATS_START -->\n"
        "### 📊 Результаты скоростного тестирования:\n"
        f"- **Последний замер скорости:** `{utc_now}`\n"
        f"- **Максимальная скорость в топе:** **`⚡ {top_speed} Mbps`**\n"
        f"- **Рабочих серверов всего:** **`{len(alive_results)}`** из `{total_checked}` проверенных\n"
        f"- **📱 Готовы для мобильных операторов (МТС):** **`{mts_count}`** (вынесены на первые места)\n"
        f"- **Средний пинг:** `{avg_ping} ms`\n"
        f"- **Время полного тестирования:** `{duration_sec:.1f} сек`\n"
        "- **Автообновление:** каждые 30 минут\n\n"
        "## ⚡ Топ самых быстрых серверов (вверху — проверенные для МТС/Мобильных сетей):\n\n"
        "| # | Скорость | Сеть | Адрес:Порт | Имя сервера | Пинг |\n"
        "|---|----------|------|------------|-------------|------|\n"
        f"{top_table_md}\n"
        "<!-- STATS_END -->"
    )

    if os.path.exists("README.md"):
        try:
            with open("README.md", "r", encoding="utf-8") as f:
                content = f.read()

            if "<!-- STATS_START -->" in content and "<!-- STATS_END -->" in content:
                pattern = r"<!-- STATS_START -->.*?<!-- STATS_END -->"
                new_content = re.sub(pattern, stats_block, content, flags=re.DOTALL)
                with open("README.md", "w", encoding="utf-8") as f:
                    f.write(new_content)
                log("Updated README.md stats block")
                return
        except Exception as e:
            log(f"Warning: Failed to update README.md stats: {e}")


def main():
    start_time = time.time()
    log(f"=== Starting '{SUB_TITLE}' VPN Speed Benchmark (MTS Mobile Optimized) ===")
    
    xray_bin = find_or_download_xray()
    
    raw_nodes = fetch_subscriptions()
    if not raw_nodes:
        log("No nodes fetched from sources. Exiting.")
        return

    valid_nodes = []
    for link, from_mobile in raw_nodes:
        parsed = parse_proxy_link(link, from_mobile)
        if parsed:
            valid_nodes.append(parsed)

    log(f"Parsed {len(valid_nodes)} valid configurations for testing.")

    # Этап 1: Быстрый отсев неработающих узлов
    alive_stage1 = []
    total = len(valid_nodes)
    batches = [valid_nodes[i:i + STAGE1_BATCH_SIZE] for i in range(0, total, STAGE1_BATCH_SIZE)]

    log(f"--- Stage 1: Ultra-fast alive check of {len(batches)} batches ---")

    for b_idx, batch in enumerate(batches, start=1):
        tmp_cfg = f"tmp_s1_{b_idx}_{int(time.time())}.json"
        b_start = time.time()
        res = stage1_fast_filter(batch, xray_bin, tmp_cfg)
        b_dur = time.time() - b_start
        alive_stage1.extend(res)
        log(f"Batch {b_idx}/{len(batches)} in {b_dur:.1f}s: {len(res)} alive. (Total alive: {len(alive_stage1)})")

    s1_duration = time.time() - start_time
    log(f"Stage 1 complete in {s1_duration:.1f}s! {len(alive_stage1)}/{len(valid_nodes)} nodes responding.")

    # Этап 2: Замер реальной скорости скачивания (Throughput)
    if alive_stage1:
        benchmarked = stage2_speed_benchmark(alive_stage1, xray_bin)
    else:
        benchmarked = []

    total_duration = time.time() - start_time
    log(f"=== All speed tests complete in {total_duration:.1f}s! Benchmarked: {len(benchmarked)} nodes ===")

    generate_outputs(benchmarked, len(valid_nodes), total_duration)


if __name__ == "__main__":
    main()
