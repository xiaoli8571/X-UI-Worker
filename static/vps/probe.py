#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# X-UI 探针 Agent：只采集并上报系统状态（CPU/内存/磁盘/网络/负载/进程等），
# 不构建 sing-box 代理。上报协议与完整版 agent 的 /api/report 兼容。
import urllib.request
import urllib.parse
import json
import os
import time
import subprocess
import re
import platform
import sys

if sys.stdout.encoding != 'UTF-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

CONF_FILE = "/opt/xui/config.json"

try:
    with open(CONF_FILE, 'r') as f:
        env = json.load(f)
except Exception:
    print("Failed to read config file.")
    exit(1)

API_URL = env["api_url"]
REPORT_URL = env["report_url"]
VPS_IP = env["ip"]
TOKEN = env["token"]

HEADERS = {'Content-Type': 'application/json', 'Authorization': TOKEN, 'User-Agent': 'X-UI-Probe/1.0'}

def _require_https_url(value, name):
    parsed = urllib.parse.urlsplit(value or "")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise RuntimeError(f"{name} must be HTTPS without credentials or fragment")
    return value.rstrip("/")

API_URL = _require_https_url(API_URL, "api_url")
REPORT_URL = _require_https_url(REPORT_URL, "report_url")

prev_cpu_total = prev_cpu_idle = 0
prev_rx = prev_tx = 0
loop_counter = 0

cached_os = cached_arch = cached_cpu_info = cached_virt = None

def run_text(command, timeout=5):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception:
        return ""

def get_static_sysinfo():
    global cached_os, cached_arch, cached_cpu_info, cached_virt
    if not cached_os:
        try:
            with open('/etc/os-release') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME='):
                        cached_os = line.split('=')[1].strip().strip('"')
                        break
        except: cached_os = run_text('uname -srm') or "Unknown OS"
    if not cached_arch: cached_arch = run_text('uname -m') or platform.machine() or "unknown"
    if not cached_cpu_info:
        try:
            with open('/proc/cpuinfo') as f:
                for line in f:
                    if 'model name' in line:
                        cached_cpu_info = line.split(':')[1].strip()
                        break
        except: cached_cpu_info = "Unknown CPU"
    if not cached_virt:
        virt = run_text('systemd-detect-virt 2>/dev/null')
        if not virt or virt == 'none':
            try:
                with open('/proc/1/environ', 'r', errors='ignore') as f: init_env = f.read()
                with open('/proc/cpuinfo', 'r', errors='ignore') as f: cpu_info = f.read().lower()
                if 'lxc' in init_env: virt = 'lxc'
                elif 'docker' in init_env: virt = 'docker'
                elif os.path.exists('/proc/user_beancounters'): virt = 'openvz'
                elif 'kvm' in cpu_info: virt = 'kvm'
                elif 'qemu' in cpu_info: virt = 'qemu'
                else: virt = "KVM/Physical"
            except Exception:
                virt = "Unknown"
        cached_virt = virt.upper()
    return cached_os, cached_arch, cached_cpu_info, cached_virt

def get_http_ping(url):
    try:
        out = subprocess.check_output(f'curl -o /dev/null -s -m 2 -w "%{{time_total}}" "http://{url}"', shell=True).decode().strip()
        return str(int(float(out) * 1000))
    except: return "0"

def get_net_dev_bytes():
    try:
        route = subprocess.run(
            ["ip", "-o", "route", "show", "default"],
            capture_output=True, text=True, timeout=3, check=True
        ).stdout
        match = re.search(r'\bdev\s+(\S+)', route)
        if not match:
            return 0, 0
        interface = match.group(1)
        with open(f'/sys/class/net/{interface}/statistics/rx_bytes') as f:
            rx = int(f.read().strip())
        with open(f'/sys/class/net/{interface}/statistics/tx_bytes') as f:
            tx = int(f.read().strip())
        return rx, tx
    except: pass
    return 0, 0

def get_system_status():
    global prev_cpu_total, prev_cpu_idle, prev_rx, prev_tx, loop_counter
    stats = {"cpu": 0, "mem": 0, "disk": 0, "uptime": "Unknown", "load": "0.00", "net_in_speed": 0, "net_out_speed": 0}

    try:
        with open('/proc/stat', 'r') as f:
            for line in f:
                if line.startswith('cpu '):
                    p = [float(x) for x in line.split()[1:]]
                    idle, total = p[3] + p[4], sum(p)
                    if prev_cpu_total > 0 and (total - prev_cpu_total) > 0:
                        stats["cpu"] = int(100.0 * (1.0 - (idle - prev_cpu_idle) / (total - prev_cpu_total)))
                    prev_cpu_total, prev_cpu_idle = total, idle
                    break
    except Exception: pass

    try:
        with open('/proc/meminfo', 'r') as f: mem = f.read()
        t = re.search(r'MemTotal:\s+(\d+)', mem); a = re.search(r'MemAvailable:\s+(\d+)', mem)
        u = re.search(r'SwapTotal:\s+(\d+)', mem); v = re.search(r'SwapFree:\s+(\d+)', mem)
        total_ram = int(t.group(1)) // 1024 if t else 0
        avail_ram = int(a.group(1)) // 1024 if a else 0
        used_ram = total_ram - avail_ram
        if total_ram > 0: stats["mem"] = int((used_ram / total_ram) * 100)

        stats["ram_total"] = str(total_ram)
        stats["ram_used"] = str(used_ram)
        stats["swap_total"] = str(int(u.group(1)) // 1024) if u else "0"
        stats["swap_used"] = str((int(u.group(1)) - int(v.group(1))) // 1024) if u and v else "0"
    except Exception: pass

    try:
        df_output = subprocess.run(["df", "-m", "/"], capture_output=True, text=True, timeout=3, check=True).stdout
        df = df_output.split('\n')[1].split()
        stats["disk_total"] = df[1]
        stats["disk_used"] = df[2]
        stats["disk"] = int(df[4].replace('%', ''))
    except: pass

    try:
        with open('/proc/loadavg') as f: stats["load"] = " ".join(f.read().split()[:3])
        with open('/proc/uptime') as f:
            up_sec = float(f.read().split()[0])
            d, h, m = int(up_sec//86400), int((up_sec%86400)//3600), int((up_sec%3600)//60)
            stats["uptime"] = f"{d} days, {h:02d}:{m:02d}" if d > 0 else f"{h:02d}:{m:02d}"

        stats["boot_time"] = run_text("uptime -s 2>/dev/null || stat -c %y / 2>/dev/null | cut -d'.' -f1", timeout=3)
        process_count = run_text("ps -e | wc -l", timeout=3)
        stats["processes"] = str(max(0, int(process_count or '1') - 1))
        stats["tcp_conn"] = run_text("ss -ant 2>/dev/null | grep -v 'State' | wc -l", timeout=3) or "0"
        stats["udp_conn"] = run_text("ss -anu 2>/dev/null | grep -v 'State' | wc -l", timeout=3) or "0"
    except: pass

    rx_now, tx_now = get_net_dev_bytes()
    stats["net_rx"] = str(rx_now); stats["net_tx"] = str(tx_now)
    now = time.monotonic()
    previous_sample_at = getattr(get_system_status, "previous_sample_at", 0.0)
    elapsed = now - previous_sample_at if previous_sample_at else 0.0
    if elapsed > 0:
        stats["net_in_speed"] = max(0, rx_now - prev_rx) / elapsed
        stats["net_out_speed"] = max(0, tx_now - prev_tx) / elapsed
    get_system_status.previous_sample_at = now
    prev_rx, prev_tx = rx_now, tx_now

    if loop_counter % 4 == 0:
        idx = (loop_counter // 4) % 3
        if idx == 0: ct, cu, cm = "bj-ct-dualstack.ip.zstaticcdn.com", "bj-cu-dualstack.ip.zstaticcdn.com", "bj-cm-dualstack.ip.zstaticcdn.com"
        elif idx == 1: ct, cu, cm = "sh-ct-dualstack.ip.zstaticcdn.com", "sh-cu-dualstack.ip.zstaticcdn.com", "sh-cm-dualstack.ip.zstaticcdn.com"
        else: ct, cu, cm = "gd-ct-dualstack.ip.zstaticcdn.com", "gd-cu-dualstack.ip.zstaticcdn.com", "gd-cm-dualstack.ip.zstaticcdn.com"
        stats["ping_ct"] = get_http_ping(ct)
        stats["ping_cu"] = get_http_ping(cu)
        stats["ping_cm"] = get_http_ping(cm)
        stats["ping_bd"] = get_http_ping("lf3-ips.zstaticcdn.com")
    else:
        stats["ping_ct"] = getattr(get_system_status, "last_ping_ct", "0")
        stats["ping_cu"] = getattr(get_system_status, "last_ping_cu", "0")
        stats["ping_cm"] = getattr(get_system_status, "last_ping_cm", "0")
        stats["ping_bd"] = getattr(get_system_status, "last_ping_bd", "0")
    get_system_status.last_ping_ct = stats["ping_ct"]
    get_system_status.last_ping_cu = stats["ping_cu"]
    get_system_status.last_ping_cm = stats["ping_cm"]
    get_system_status.last_ping_bd = stats["ping_bd"]

    os_info, arch, cpu_info, virt = get_static_sysinfo()
    stats.update({"os": os_info, "arch": arch, "cpu_info": cpu_info, "virt": virt})

    loop_counter += 1
    return stats

def report_status():
    status = get_system_status()
    status["ip"] = VPS_IP
    status["report_id"] = f"{VPS_IP}:{time.time_ns()}"
    status["node_traffic"] = []
    status["argo_urls"] = []
    req = urllib.request.Request(REPORT_URL, data=json.dumps(status).encode(), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode('utf-8'))

def main():
    print(f"[probe] X-UI Probe Agent started for {VPS_IP}", flush=True)
    interval = 60
    while True:
        started = time.monotonic()
        try:
            resp = report_status()
            if resp and "interval" in resp:
                interval = min(max(15, int(resp["interval"])), 300)
        except Exception as error:
            print(f"[probe] report failed: {error}", flush=True)
            interval = 60
        elapsed = time.monotonic() - started
        time.sleep(max(5, interval - elapsed))

if __name__ == "__main__":
    main()
