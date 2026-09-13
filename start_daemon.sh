#!/bin/bash
# 一键在后台启动 Workbuddy 桌面状态机守护进程 (完全脱离会话常驻)

DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$DIR/.workbuddy-ai/daemon.pid"
LOG_FILE="$DIR/.workbuddy-ai/daemon.log"

mkdir -p "$DIR/.workbuddy-ai"

# 1. 如果已有记录的 PID，先杀掉
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        kill -9 "$OLD_PID" 2>/dev/null
    fi
    rm -f "$PID_FILE"
fi

# 2. 强力释放串口占用，防止多个旧进程冲突争抢
for port in /dev/cu.usbmodem* /dev/tty.usbmodem*; do
    if [ -e "$port" ]; then
        PIDS=$(lsof -t "$port" 2>/dev/null)
        if [ -n "$PIDS" ]; then
            kill -9 $PIDS 2>/dev/null
        fi
    fi
done

# 3. 使用 Python start_new_session 真正脱离终端常驻
python3 -c "import subprocess, sys, os
log_f = open('$LOG_FILE', 'a')
p = subprocess.Popen([sys.executable, '-u', '$DIR/host_bridge/daemon.py'], start_new_session=True, stdout=log_f, stderr=subprocess.STDOUT)
open('$PID_FILE', 'w').write(str(p.pid))
"

echo "✅ Workbuddy 桌面状态机后台守护进程已启动 (PID: $(cat "$PID_FILE"))"
echo "👉 状态日志: $LOG_FILE"
