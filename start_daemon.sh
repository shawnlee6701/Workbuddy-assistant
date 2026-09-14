#!/bin/bash
# 一键在后台启动 Workbuddy 桌面状态机守护进程 (完全脱离会话常驻)

DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$DIR/.workbuddy-ai/daemon.pid"
LOG_FILE="$DIR/.workbuddy-ai/daemon.log"
LABEL="com.workbuddy.desktop-hud-v2"
USER_ID="$(id -u)"

mkdir -p "$DIR/.workbuddy-ai"

# 已安装 LaunchAgent 时，交给 launchd 管理，避免启动两个 Bridge。
if launchctl print "gui/$USER_ID/$LABEL" >/dev/null 2>&1; then
    launchctl kickstart -k "gui/$USER_ID/$LABEL"
    echo "✅ Workbuddy V2.0 LaunchAgent 已重启"
    exit 0
fi

# 1. 如果已有记录的 PID，仅停止属于本项目的守护进程。
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(sed -n '1p' "$PID_FILE")
    OLD_COMMAND=$(ps -p "$OLD_PID" -o command= 2>/dev/null || true)
    if [[ "$OLD_COMMAND" == *"$DIR/host_bridge/daemon.py"* ]]; then
        kill -9 "$OLD_PID" 2>/dev/null
    fi
    rm -f "$PID_FILE"
fi

# 2. 使用 Python start_new_session 真正脱离终端常驻。
python3 -c "import subprocess, sys, os
log_f = open('$LOG_FILE', 'a')
p = subprocess.Popen([sys.executable, '-u', '$DIR/host_bridge/daemon.py'], start_new_session=True, stdout=log_f, stderr=subprocess.STDOUT)
open('$PID_FILE', 'w').write(str(p.pid))
"

echo "✅ Workbuddy 桌面状态机后台守护进程已启动 (PID: $(cat "$PID_FILE"))"
echo "👉 状态日志: $LOG_FILE"
