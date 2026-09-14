#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.workbuddy.desktop-hud-v2"
USER_ID="$(id -u)"
SOURCE_PLIST="$DIR/macos/$LABEL.plist"
TARGET_PLIST="/Users/shawn/Library/LaunchAgents/$LABEL.plist"
PYTHON_BIN="/Applications/Xcode.app/Contents/Developer/usr/bin/python3"
RUNTIME_DIR="/Users/shawn/Library/Application Support/Workbuddy Desktop HUD"
RUNTIME_STATE="$RUNTIME_DIR/.workbuddy-ai"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "❌ 未找到 V2.0 当前使用的 Python: $PYTHON_BIN"
    exit 1
fi

"$PYTHON_BIN" -c 'import serial, websockets' || {
    echo "❌ Python 缺少 pyserial 或 websockets 依赖"
    exit 1
}

mkdir -p "$DIR/.workbuddy-ai" "/Users/shawn/Library/LaunchAgents" "$RUNTIME_DIR/host_bridge" "$RUNTIME_STATE"

# Stop an older launchd job before replacing its definition.
launchctl bootout "gui/$USER_ID/$LABEL" >/dev/null 2>&1 || true

# Stop only a manually-started Workbuddy daemon recorded by this project.
if [ -f "$DIR/.workbuddy-ai/daemon.pid" ]; then
    OLD_PID="$(sed -n '1p' "$DIR/.workbuddy-ai/daemon.pid")"
    OLD_COMMAND="$(ps -p "$OLD_PID" -o command= 2>/dev/null || true)"
    if [[ "$OLD_COMMAND" == *"$DIR/host_bridge/daemon.py"* ]]; then
        kill "$OLD_PID" 2>/dev/null || true
    fi
fi

# LaunchAgents do not receive macOS permission to execute source code directly
# from Documents. Deploy a minimal runtime copy to Application Support instead.
cp "$DIR/host_bridge/daemon.py" "$RUNTIME_DIR/host_bridge/daemon.py"
cp "$DIR/host_bridge/v2_transport.py" "$RUNTIME_DIR/host_bridge/v2_transport.py"
cp "$DIR/bridge_dashboard.html" "$RUNTIME_DIR/bridge_dashboard.html"
cp "$DIR/web_hud.html" "$RUNTIME_DIR/web_hud.html"

# Migrate identity/registry only on first install. Subsequent upgrades preserve
# the deployed Host identity and do not touch any Keychain secret.
for STATE_FILE in v2_host.json v2_paired_devices.json; do
    if [ ! -f "$RUNTIME_STATE/$STATE_FILE" ] && [ -f "$DIR/.workbuddy-ai/$STATE_FILE" ]; then
        cp "$DIR/.workbuddy-ai/$STATE_FILE" "$RUNTIME_STATE/$STATE_FILE"
    fi
done

cp "$SOURCE_PLIST" "$TARGET_PLIST"
plutil -lint "$TARGET_PLIST" >/dev/null
launchctl bootstrap "gui/$USER_ID" "$TARGET_PLIST"

echo "✅ Workbuddy V2.0 已安装为 macOS 登录自启服务"
echo "👉 LaunchAgent: $TARGET_PLIST"
echo "👉 Runtime: $RUNTIME_DIR"
