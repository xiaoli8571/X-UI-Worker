#!/bin/sh
# =============================================================
# X-UI 探针接入脚本 —— 宿主机只安装探针 Agent（仅采集上报系统状态），不装代理
# 参考 cf-vps-monitor 的轻量探针思路：独立进程采集 CPU/内存/磁盘/网络，HTTP 上报面板
# 用法: curl -fsSL -H "Authorization: <token>" "<api>/api/agent_update?ip=<ip>&component=probe-installer" | sh -s -- --api "<api>" --ip "<ip>" --token "<token>"
# =============================================================
set -e

API_URL=""
IP=""
TOKEN=""

while [ $# -gt 0 ]; do
    case "$1" in
        --api) API_URL="$2"; shift 2 ;;
        --ip) IP="$2"; shift 2 ;;
        --token) TOKEN="$2"; shift 2 ;;
        *) shift ;;
    esac
done

[ -n "$API_URL" ] || { echo "缺少 --api"; exit 1; }
[ -n "$IP" ] || { echo "缺少 --ip"; exit 1; }
[ -n "$TOKEN" ] || { echo "缺少 --token"; exit 1; }

echo "[probe] 安装探针（只上报状态，不装代理）..."

# 需要 python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[probe] 安装 python3..."
    if command -v apt-get >/dev/null 2>&1; then apt-get update -qq && apt-get install -y -qq python3 curl
    elif command -v apk >/dev/null 2>&1; then apk add --no-cache python3 curl
    else echo "不支持的包管理器，请手动安装 python3"; exit 1; fi
fi

mkdir -p /opt/xui

# ============ 清理旧完整版 agent 环境（sing-box 代理 + 旧服务 + 旧文件） ============
echo "[probe] 清理旧代理环境（sing-box / 旧 agent / 旧配置）..."
# 注意：以下清理命令在 systemd / openrc / 容器等不同环境下可能不存在或无匹配进程，
# 全部容错（|| true），避免 set -e 导致脚本静默中断。
timeout 15 systemctl stop sing-box 2>/dev/null || true; timeout 5 systemctl disable sing-box 2>/dev/null || true
timeout 15 rc-service sing-box stop 2>/dev/null || true
systemctl kill -s KILL sing-box 2>/dev/null || true
rm -rf /etc/sing-box
rm -f /etc/systemd/system/sing-box.service /etc/init.d/sing-box
# 停止旧 agent 服务（探针与完整版 agent 互斥，只保留一个）
timeout 15 systemctl stop xui-agent 2>/dev/null || true; timeout 5 systemctl disable xui-agent 2>/dev/null || true
timeout 15 rc-service xui-agent stop 2>/dev/null || true
# 杀掉完整版 agent 的残留组件进程（lite_manager / proxy / realtime，可能用旧 IP 继续上报）
pkill -f lite_manager.py 2>/dev/null || true; pkill -f proxy_server.py 2>/dev/null || true; pkill -f realtime_client.py 2>/dev/null || true
sleep 1; pkill -9 -f lite_manager.py 2>/dev/null || true; pkill -9 -f proxy_server.py 2>/dev/null || true; pkill -9 -f realtime_client.py 2>/dev/null || true
rm -rf /opt/proxy_lite
# 清除更新标记与旧代理组件/证书（config.json 会被覆盖重写）
rm -f /opt/xui/.update-pending
rm -f /opt/xui/*.pem /opt/xui/*.key /opt/xui/warp.json /opt/xui/egress-state.json \
      /opt/xui/traffic-state.json /opt/xui/realtime_client.py /opt/xui/lite_manager.py \
      /opt/xui/proxy_server.py /opt/xui/agent.py /opt/xui/run-agent.sh 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true
echo "[probe] ✅ 旧环境已清理"

# 下载独立探针 agent（只采集上报，不构建 sing-box）
echo "[probe] 下载 probe.py..."
if ! curl -fsSL -H "Authorization: $TOKEN" "$API_URL/api/agent_update?ip=$IP&component=probe-agent" -o /opt/xui/probe.py; then
    echo "[probe] ❌ 下载 probe.py 失败（网络/鉴权问题），请检查 API 地址与 Token 后重试。"
    exit 1
fi
chmod +x /opt/xui/probe.py
echo "[probe] ✅ probe.py 下载完成 ($(wc -c < /opt/xui/probe.py) bytes)"

# 探针配置（仅采集上报，无代理构建）
python3 - "$API_URL" "$IP" "$TOKEN" <<'PY'
import json, sys, os
api, ip, token = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = {"api_url": api + "/api/config", "report_url": api + "/api/report", "ip": ip, "token": token}
path = "/opt/xui/config.json"
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cfg, f)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print("[probe] 探针配置已写入 /opt/xui/config.json")
PY

# systemd 服务
cat > /etc/systemd/system/xui-probe.service <<EOF
[Unit]
Description=X-UI Probe Agent (status-only)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/xui
ExecStart=$(command -v python3) /opt/xui/probe.py
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable xui-probe >/dev/null 2>&1 || true
systemctl restart xui-probe

sleep 2
if systemctl is-active xui-probe >/dev/null 2>&1 || rc-service xui-probe status >/dev/null 2>&1; then
    echo ""
    echo "[probe] =================================================="
    echo "[probe] ✅ 探针安装成功！"
    echo "[probe]    节点: $IP"
    echo "[probe]    状态: 已启动 xui-probe（独立探针 Agent，只采集上报）"
    echo "[probe]    面板: $API_URL 探针大盘将显示该机器"
    echo "[probe]    日志: journalctl -u xui-probe -f"
    echo "[probe] =================================================="
else
    echo ""
    echo "[probe] =================================================="
    echo "[probe] ❌ 探针服务启动失败！"
    echo "[probe]    查看日志: journalctl -u xui-probe -n 30"
    echo "[probe]    或手动运行: python3 /opt/xui/probe.py"
    echo "[probe] =================================================="
    exit 1
fi
