#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$DIR/.workbuddy-ai/daemon.pid"
LABEL="com.workbuddy.desktop-hud-v2"
USER_ID="$(id -u)"

if launchctl print "gui/$USER_ID/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "gui/$USER_ID/$LABEL"
    echo "🛑 已停止当前登录会话中的 Workbuddy V2.0 LaunchAgent"
fi

if [ -f "$PID_FILE" ]; then
    PID=$(sed -n '1p' "$PID_FILE")
    COMMAND=$(ps -p "$PID" -o command= 2>/dev/null || true)
    if [[ "$COMMAND" == *"$DIR/host_bridge/daemon.py"* ]]; then
        kill "$PID" 2>/dev/null
        echo "🛑 已停止 Workbuddy 桌面状态机后台守护进程 (PID: $PID)"
    else
        echo "ℹ️ 进程已不在运行"
    fi
    rm -f "$PID_FILE"
else
    echo "ℹ️ 未发现运行中的守护进程"
fi
