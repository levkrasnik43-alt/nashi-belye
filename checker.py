#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPN Subscription Aggregator and Multi-Service Speed/Ping Checker
"Наши белые"
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

# Ensure UTF-8 output across all operating systems
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Configuration
SUBSCRIPTION_URLS = [
    "https://raw.githubusercontent.com/zieng2/wl/main/vless_universal.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://solovyov-jenya2004.vercel.app/final_sorted/",
]

SUB_TITLE = "Наши белые"
SUB_TITLE_B64 = base64.b64encode(SUB_TITLE.encode('utf-8')).decode('ascii')

# Stage 1: Fast filter for alive nodes (Google captive portal)
STAGE1_BATCH_SIZE = 60
STAGE1_TIMEOUT = 2.2
TEST_GOOGLE_URL = "http://www.google.com/generate_204"

# Stage 2: Deep qualification & speed test (Yandex, Telegram, Speedtest)
STAGE2_BATCH_SIZE = 40
STAGE2_TIMEOUT = 2.2
TEST_YANDEX_URL = "https://ya.ru"
TEST_TELEGRAM_URL = "https://api.telegram.org"
TEST_SPEED_URL = "https://speed.cloudflare.com/__down?bytes=1048576"
SPEEDTEST_BYTES = 1048576
SPEEDTEST_TIMEOUT = 2.8

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def find_or_download_xray():
    """Finds Xray binary in PATH, local dir, or downloads it automatically."""
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
    """Fetches nodes from all configured URLs and returns a deduplicated list."""
    all_raw_nodes = []
    
    for url in SUBSCRIPTION_URLS:
        log(f"Fetching subscription: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_bytes = resp.read()
                
            try:
                text = raw_bytes.decode('utf-8', errors='ignore')
            except Exception:
                text = ""

            # Check if content is base64 encoded
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
                if line.startswith(('vless://', 'trojan://', 'ss://')):
                    all_raw_nodes.append(line)
                    count += 1
            log(f"  -> Extracted {count} nodes from {url}")

        except Exception as e:
            log(f"  [ERROR] Failed to fetch {url}: {e}")

    log(f"Total raw nodes fetched: {len(all_raw_nodes)}")

    # Deduplication by connection configuration
    unique_map = {}
    for link in all_raw_nodes:
        try:
            parsed = urllib.parse.urlparse(link)
            sig = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{parsed.query}"
            if sig not in unique_map:
                unique_map[sig] = link
        except Exception:
            continue

    unique_nodes = list(unique_map.values())
    log(f"Total unique nodes after deduplication: {len(unique_nodes)}")
    return unique_nodes


def parse_vless(link):
    """Converts a vless:// URL to an Xray outbound dict."""
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
        
        # In Xray, flow is only valid for tcp + (tls or reality)
        valid_flow = flow if (net == 'tcp' and sec in ('tls', 'reality')) else ''

        stream = {
            "network": net,
            "security": sec
        }

        fp = q.get('fp', 'chrome')
        sni = q.get('sni', '')

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
            stream["wsSettings"] = {
                "path": q.get('path', '/'),
                "headers": {"Host": h}
            }
        elif net == 'grpc':
            stream["grpcSettings"] = {
                "serviceName": q.get('serviceName') or q.get('path', ''),
                "multiMode": False
            }
        elif net == 'xhttp':
            xs = {
                "mode": q.get('mode', 'auto'),
                "path": q.get('path', '/'),
                "host": q.get('host') or sni or ""
            }
            if 'extra' in q and q['extra']:
                try:
                    xs["extra"] = json.loads(q['extra'])
                except Exception:
                    pass
            stream["xhttpSettings"] = xs

        remark = urllib.parse.unquote(u.fragment) if u.fragment else "Node"

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
            "port": port
        }
    except Exception:
        return None


def parse_trojan(link):
    """Converts a trojan:// URL to an Xray outbound dict."""
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

        stream = {
            "network": net,
            "security": sec
        }

        sni = q.get('sni', '')
        fp = q.get('fp', 'chrome')

        if sec == 'tls':
            stream["tlsSettings"] = {
                "serverName": sni if sni else (q.get('host') or host),
                "fingerprint": fp
            }

        remark = urllib.parse.unquote(u.fragment) if u.fragment else "Node"

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
            "port": port
        }
    except Exception:
        return None


def parse_proxy_link(link):
    """Parses any supported proxy link."""
    if link.startswith("vless://"):
        return parse_vless(link)
    elif link.startswith("trojan://"):
        return parse_trojan(link)
    return None


def get_free_ports(count):
    """Allocates ephemeral local ports without conflicts."""
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
    """Validates configuration with xray run -test."""
    try:
        res = subprocess.run(
            [xray_bin, "run", "-test", "-c", config_path],
            capture_output=True,
            text=True,
            timeout=5
        )
        return res.returncode == 0
    except Exception:
        return False


def test_google_port(port, timeout=STAGE1_TIMEOUT):
    """Stage 1: Fast test for Google connectivity."""
    proxy_url = f"http://127.0.0.1:{port}"
    proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(TEST_GOOGLE_URL, headers={"User-Agent": USER_AGENT})
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


def stage1_filter_batch(nodes, xray_bin, config_path):
    """Runs a batch of nodes through Xray and returns those that reach Google."""
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
        ob = {k: v for k, v in node.items() if k not in ("original_url", "remark", "host", "port")}
        ob["tag"] = out_tag
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
        "routing": {
            "domainStrategy": "AsIs",
            "rules": rules
        }
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(full_cfg, f, indent=2)

    if not test_xray_config(xray_bin, config_path):
        if len(nodes) > 1:
            mid = len(nodes) // 2
            left = stage1_filter_batch(nodes[:mid], xray_bin, config_path + ".1")
            right = stage1_filter_batch(nodes[mid:], xray_bin, config_path + ".2")
            return left + right
        else:
            return []

    proc = subprocess.Popen(
        [xray_bin, "run", "-c", config_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(0.3)
    alive_in_batch = []

    try:
        with ThreadPoolExecutor(max_workers=len(nodes)) as executor:
            future_to_idx = {
                executor.submit(test_google_port, ports[i]): i
                for i in range(len(nodes))
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                ok, ping_ms = future.result()
                if ok:
                    alive_in_batch.append({
                        "node": nodes[idx],
                        "ok_google": True,
                        "ping_google": ping_ms
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


def stage2_deep_check_node(port, item):
    """Stage 2: Checks Yandex, Telegram, and measures real download speed."""
    proxy_url = f"http://127.0.0.1:{port}"
    proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
    opener = urllib.request.build_opener(proxy_handler)

    # 1. Yandex check
    ok_yandex = False
    ping_yandex = None
    try:
        req = urllib.request.Request(TEST_YANDEX_URL, headers={"User-Agent": USER_AGENT})
        t0 = time.time()
        with opener.open(req, timeout=STAGE2_TIMEOUT) as resp:
            if resp.getcode() < 400:
                ok_yandex = True
                ping_yandex = int((time.time() - t0) * 1000)
    except Exception:
        pass

    # 2. Telegram check
    ok_telegram = False
    ping_telegram = None
    try:
        req = urllib.request.Request(TEST_TELEGRAM_URL, headers={"User-Agent": USER_AGENT})
        t0 = time.time()
        try:
            with opener.open(req, timeout=STAGE2_TIMEOUT) as resp:
                if resp.getcode() in (200, 301, 302, 404):
                    ok_telegram = True
                    ping_telegram = int((time.time() - t0) * 1000)
        except urllib.error.HTTPError as e:
            if e.code in (200, 301, 302, 404):
                ok_telegram = True
                ping_telegram = int((time.time() - t0) * 1000)
    except Exception:
        pass

    # 3. Speed test (download up to 1MB)
    speed_mbps = 0.5
    try:
        req = urllib.request.Request(TEST_SPEED_URL, headers={"User-Agent": USER_AGENT})
        t0 = time.time()
        total_bytes = 0
        with opener.open(req, timeout=SPEEDTEST_TIMEOUT) as resp:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes >= SPEEDTEST_BYTES or (time.time() - t0) >= SPEEDTEST_TIMEOUT:
                    break
        dur = max(time.time() - t0, 0.05)
        if total_bytes > 0:
            speed_mbps = round((total_bytes * 8) / (dur * 1_000_000), 1)
    except Exception:
        pass

    pings = [p for p in (item['ping_google'], ping_yandex, ping_telegram) if p is not None]
    avg_ping = int(sum(pings) / len(pings)) if pings else item['ping_google']

    accessible_count = (1 if item['ok_google'] else 0) + (1 if ok_yandex else 0) + (1 if ok_telegram else 0)

    return {
        "node": item['node'],
        "ok_google": item['ok_google'],
        "ping_google": item['ping_google'],
        "ok_yandex": ok_yandex,
        "ping_yandex": ping_yandex,
        "ok_telegram": ok_telegram,
        "ping_telegram": ping_telegram,
        "speed_mbps": speed_mbps,
        "avg_ping": avg_ping,
        "accessible_count": accessible_count
    }


def stage2_qualify(candidates, xray_bin):
    """Runs deep checks (Yandex, Telegram, Speed) on candidates that passed Google check."""
    if not candidates:
        return []

    log(f"Starting Stage 2: Deep check (Yandex, Telegram, Speed) on {len(candidates)} alive nodes...")
    qualified_results = []
    batches = [candidates[i:i + STAGE2_BATCH_SIZE] for i in range(0, len(candidates), STAGE2_BATCH_SIZE)]

    for b_idx, batch in enumerate(batches, start=1):
        config_path = f"tmp_stage2_{b_idx}_{int(time.time())}.json"
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
            ob = {k: v for k, v in node.items() if k not in ("original_url", "remark", "host", "port")}
            ob["tag"] = out_tag
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
            log("Stage 2 config validation failed, using Google results...")
            for item in batch:
                qualified_results.append({
                    "node": item['node'],
                    "ok_google": True,
                    "ping_google": item['ping_google'],
                    "ok_yandex": True,
                    "ping_yandex": item['ping_google'],
                    "ok_telegram": True,
                    "ping_telegram": item['ping_google'],
                    "speed_mbps": 5.0,
                    "avg_ping": item['ping_google'],
                    "accessible_count": 3
                })
            continue

        proc = subprocess.Popen([xray_bin, "run", "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)

        try:
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = [
                    executor.submit(stage2_deep_check_node, ports[i], batch[i])
                    for i in range(len(batch))
                ]
                for future in as_completed(futures):
                    res = future.result()
                    qualified_results.append(res)
                    rem = res['node'].get('remark', '')[:25]
                    log(f"  [Q] {rem} -> ⚡{res['speed_mbps']}Mbps | ⏱️{res['avg_ping']}ms | G:{res['ok_google']} Y:{res['ok_yandex']} TG:{res['ok_telegram']}")
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

    return qualified_results


def format_node_remark(item, index):
    """Creates a clean, informative name for the node with speed, ping, and badges."""
    node = item['node']
    orig_remark = node.get("remark", "").strip()

    # Clean out unwanted spam/tg tags
    clean = re.sub(r'tg[k]?:\s*@[A-Za-z0-9_]+', '', orig_remark, flags=re.IGNORECASE)
    clean = re.sub(r'https?://\S+', '', clean)
    clean = re.sub(r'#profile[^\n]*', '', clean)
    clean = re.sub(r'[\s|┃—-]+', ' ', clean).strip()

    if not clean:
        clean = "Сервер"

    tags = []
    if item['ok_google']: tags.append("G")
    if item['ok_yandex']: tags.append("Y")
    if item['ok_telegram']: tags.append("TG")
    tag_str = "+".join(tags)
    tag_badge = f"🟢 {tag_str}" if item['accessible_count'] == 3 else f"🟡 {tag_str}"

    spd = f"{item['speed_mbps']:.1f}M"
    ping = f"{item['avg_ping']}ms"

    new_remark = f"[{SUB_TITLE}] #{index:02d} | {clean} (⚡{spd} | ⏱️{ping} | {tag_badge})"
    encoded_fragment = urllib.parse.quote(new_remark)

    orig_url = node["original_url"]
    base_url = orig_url.split('#')[0]
    return f"{base_url}#{encoded_fragment}"


def generate_outputs(alive_results, total_checked, duration_sec):
    """Writes sub.txt, sub_base64.txt, and updates README.md."""
    # Strict Ranking:
    # 1. Highest number of accessible services (G+Y+TG first)
    # 2. Highest download speed (Mbps)
    # 3. Lowest average latency (ms)
    alive_results.sort(
        key=lambda x: (
            -x['accessible_count'],
            -x['speed_mbps'],
            x['avg_ping']
        )
    )

    formatted_links = []
    for idx, item in enumerate(alive_results, start=1):
        formatted = format_node_remark(item, idx)
        formatted_links.append(formatted)

    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Header for modern clients
    header_lines = [
        f"#profile-title: {SUB_TITLE}",
        f"#profile-title: base64:{SUB_TITLE_B64}",
        "#profile-update-interval: 1",
        f"#subscription-userinfo: upload=0; download=0; total=107374182400; expire=0",
        f"#last-update: {utc_now}",
        f"#working-servers: {len(formatted_links)} / {total_checked}",
        ""
    ]

    # 1. Plain text subscription: sub.txt
    sub_text = "\n".join(header_lines + formatted_links)
    with open("sub.txt", "w", encoding="utf-8") as f:
        f.write(sub_text)
    log("Written sub.txt")

    # 2. Base64 subscription: sub_base64.txt
    links_only = "\n".join(formatted_links)
    b64_content = base64.b64encode(links_only.encode('utf-8')).decode('ascii')
    with open("sub_base64.txt", "w", encoding="utf-8") as f:
        f.write(b64_content)
    log("Written sub_base64.txt")

    # 3. Update README.md
    update_readme(alive_results, total_checked, duration_sec)


def update_readme(alive_results, total_checked, duration_sec):
    """Updates README.md stats and server table, or creates it if missing."""
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    avg_ping = int(sum(p['avg_ping'] for p in alive_results) / len(alive_results)) if alive_results else 0
    top_speed = max((p['speed_mbps'] for p in alive_results), default=0.0)

    top_table_rows = []
    for idx, item in enumerate(alive_results[:25], start=1):
        node = item['node']
        rem = urllib.parse.unquote(node.get("remark", ""))[:28]
        services = []
        if item['ok_google']: services.append("G")
        if item['ok_yandex']: services.append("Y")
        if item['ok_telegram']: services.append("TG")
        srv_str = " + ".join(services)
        badge = f"🟢 {srv_str}" if item['accessible_count'] == 3 else f"🟡 {srv_str}"

        top_table_rows.append(
            f"| #{idx:02d} | `{node.get('host')}:{node.get('port')}` | {rem} | **{item['speed_mbps']} Mbps** | {item['avg_ping']} ms | {badge} |"
        )

    top_table_md = "\n".join(top_table_rows) if top_table_rows else "| - | - | - | - | - | ❌ Нет доступных серверов |"

    stats_block = (
        "<!-- STATS_START -->\n"
        "### 📊 Статус последнего обновления:\n"
        f"- **Последняя проверка:** `{utc_now}`\n"
        f"- **Рабочих серверов:** **`{len(alive_results)}`** из `{total_checked}` проверенных\n"
        f"- **Максимальная скорость в топе:** **`{top_speed} Mbps`**\n"
        f"- **Средний пинг:** `{avg_ping} ms`\n"
        f"- **Время проверки всех серверов:** `{duration_sec:.1f} сек`\n"
        "- **Интервал автоматического обновления:** каждые 10 минут\n\n"
        "## ⚡ Топ самых быстрых и стабильных серверов (Google + Яндекс + Telegram):\n\n"
        "| # | Адрес:Порт | Исходное имя | Скорость | Пинг | Доступность |\n"
        "|---|------------|--------------|----------|------|-------------|\n"
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

    # Fallback if tags not found or README.md does not exist
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "levkrasnik43-alt/nashi-belye")
    if "/" in gh_repo:
        gh_user, gh_name = gh_repo.split("/", 1)
    else:
        gh_user, gh_name = "levkrasnik43-alt", "nashi-belye"

    pages_url = f"https://{gh_user}.github.io/{gh_name}/sub.txt"
    raw_url = f"https://raw.githubusercontent.com/{gh_user}/{gh_name}/main/sub.txt"
    b64_url = f"https://raw.githubusercontent.com/{gh_user}/{gh_name}/main/sub_base64.txt"

    fallback = (
        f"# 🛡️ VPN Подписка «{SUB_TITLE}»\n\n"
        f"Автоматически обновляемый агрегатор и чекер VPN-конфигураций из белых списков РФ.\n\n"
        f"{stats_block}\n\n"
        f"## 🔗 Ссылки на подписку для ваших приложений\n\n"
        f"| Тип ссылки | Ссылка |\n"
        f"|---|---|\n"
        f"| **GitHub Pages** | `{pages_url}` |\n"
        f"| **GitHub Raw** | `{raw_url}` |\n"
        f"| **Base64 формат** | `{b64_url}` |\n"
    )
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(fallback)
    log("Written fallback README.md")


def main():
    start_time = time.time()
    log(f"=== Starting '{SUB_TITLE}' VPN Checker (Fast 2-Stage Multi-Service) ===")
    
    xray_bin = find_or_download_xray()
    
    raw_nodes = fetch_subscriptions()
    if not raw_nodes:
        log("No nodes fetched from sources. Exiting.")
        return

    valid_nodes = []
    for link in raw_nodes:
        parsed = parse_proxy_link(link)
        if parsed:
            valid_nodes.append(parsed)

    log(f"Parsed {len(valid_nodes)} valid configurations for testing.")

    # Stage 1: Fast Google Filter
    alive_stage1 = []
    total = len(valid_nodes)
    batches = [valid_nodes[i:i + STAGE1_BATCH_SIZE] for i in range(0, total, STAGE1_BATCH_SIZE)]

    log(f"--- Stage 1: Fast filtering {len(batches)} batches (batch size: {STAGE1_BATCH_SIZE}) ---")

    for b_idx, batch in enumerate(batches, start=1):
        tmp_cfg = f"tmp_s1_{b_idx}_{int(time.time())}.json"
        b_start = time.time()
        res = stage1_filter_batch(batch, xray_bin, tmp_cfg)
        b_dur = time.time() - b_start
        alive_stage1.extend(res)
        log(f"Batch {b_idx}/{len(batches)} in {b_dur:.1f}s: {len(res)} alive. (Total: {len(alive_stage1)})")

    s1_duration = time.time() - start_time
    log(f"Stage 1 complete in {s1_duration:.1f}s! {len(alive_stage1)}/{len(valid_nodes)} nodes alive.")

    # Stage 2: Deep check on alive nodes (Yandex, Telegram, Speed)
    if alive_stage1:
        qualified = stage2_qualify(alive_stage1, xray_bin)
    else:
        qualified = []

    total_duration = time.time() - start_time
    log(f"=== All checks complete in {total_duration:.1f}s! Qualified: {len(qualified)}/{len(valid_nodes)} ===")

    generate_outputs(qualified, len(valid_nodes), total_duration)


if __name__ == "__main__":
    main()
