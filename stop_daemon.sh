#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$DIR/.workbuddy-ai/daemon.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        kill "$PID" 2>/dev/null
        echo "🛑 已停止 Workbuddy 桌面状态机后台守护进程 (PID: $PID)"
    else
        echo "ℹ️ 进程已不在运行"
    fi
    rm -f "$PID_FILE"
else
    echo "ℹ️ 未发现运行中的守护进程"
fi
