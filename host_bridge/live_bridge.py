#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workbuddy 桌面状态机 - 高频实时中继服务 (Live Bridge Pro)
特性：
1. 秒级高频心跳推流（时间与运行耗时每秒自动跳动更新，屏幕秒级响应）
2. 毫秒级感知 `.workbuddy-ai/live_status.json` 变动并立即推送到硬件屏幕
3. 支持 HTTP REST API (端口 5200)，支持一键远程推送状态
4. 捕获开发板硬件按键反向控制事件
"""

import os
import sys
import time
import json
import glob
import select
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

STATUS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.workbuddy-ai/live_status.json"))
HTTP_PORT = 5200

# 全局状态
current_status = {
    "state": "RUNNING",
    "thread": "Workbuddy · 实时监控",
    "time": datetime.now().strftime("%H:%M:%S"),
    "alert_title": "桌面状态机已连接",
    "alert_desc": "实时数据总线已就绪，正在监听工作流...",
    "step": "1/1",
    "tools": "1 次",
    "duration": "00:00",
    "tokens": "1.2k",
    "timeline": [
        {"text": "ESP32-S3 硬件屏幕点亮", "dur": "完成", "done": True, "active": False},
        {"text": "建立 USB 串口高频数据总线", "dur": "进行中", "done": False, "active": True}
    ]
}

last_mtime = 0
ser_device = None
ser_lock = threading.Lock()
task_start_time = time.time()

def get_serial_ports():
    ports = []
    if sys.platform.startswith('darwin'):
        ports = (glob.glob('/dev/tty.usbmodem*') + 
                 glob.glob('/dev/tty.usbserial*') + 
                 glob.glob('/dev/tty.wchusbserial*'))
    elif sys.platform.startswith('linux'):
        ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
    elif sys.platform.startswith('win'):
        ports = [f'COM{i+1}' for i in range(256)]
    return ports

def load_status_file():
    global current_status, last_mtime, task_start_time
    if not os.path.exists(STATUS_FILE):
        return False
    try:
        mtime = os.path.getmtime(STATUS_FILE)
        if mtime != last_mtime:
            last_mtime = mtime
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("state") == "RUNNING" and current_status.get("state") != "RUNNING":
                    task_start_time = time.time()
                current_status.update(data)
                return True
    except Exception:
        pass
    return False

def push_to_serial(force_log=False):
    global ser_device, current_status
    if ser_device is None or not ser_device.is_open:
        return False
    try:
        with ser_lock:
            payload = json.dumps(current_status, ensure_ascii=False) + "\n"
            ser_device.write(payload.encode("utf-8"))
            ser_device.flush()
        if force_log:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ 推送更新 -> {current_status.get('state')}: {current_status.get('alert_title')}")
        return True
    except Exception:
        ser_device = None
        return False

# ==================== HTTP 服务 ====================
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class StatusHttpHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(current_status, ensure_ascii=False).encode("utf-8"))

    def do_POST(self):
        global current_status
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode("utf-8"))
            current_status.update(data)
            push_to_serial(force_log=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"success"}')
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(str(e).encode('utf-8'))

def http_server_worker():
    try:
        server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), StatusHttpHandler)
        server.serve_forever()
    except Exception as e:
        print(f"[-] HTTP Server 启动提示: {e}")

# ==================== 串口通信 ====================
try:
    import serial
except ImportError:
    serial = None

def serial_connect_and_listen():
    global ser_device
    if not serial:
        print("[-] 未检测到 pyserial 库，仅启用 HTTP 模式")
        return

    while True:
        if ser_device is None or not ser_device.is_open:
            ports = get_serial_ports()
            if ports:
                try:
                    s = serial.Serial(ports[0], 115200, timeout=0.1)
                    ser_device = s
                    print(f"[+] 成功连接硬件串口: {ports[0]} (115200 bps)")
                    time.sleep(0.5)
                    push_to_serial(force_log=True)
                except Exception:
                    ser_device = None
            time.sleep(1.0)
            continue

        # 监听硬件回显与按键
        try:
            line = ser_device.readline().decode('utf-8', errors='ignore').strip()
            if line:
                if "KEY_PRESS" in line:
                    try:
                        event = json.loads(line)
                        print(f"\n[🎮 硬件按键] -> 触发: {event.get('action')} (Key: {event.get('key')})")
                    except Exception:
                        pass
                else:
                    # 打印开发板的回显与诊断信息
                    print(f"  [开发板回显] {line}")
        except Exception:
            ser_device = None

        time.sleep(0.02)

def main():
    print("=" * 60)
    print("🚀 Workbuddy 桌面状态机 · 高频实时中继已启动")
    print(f"📡 本地 HTTP API: http://127.0.0.1:{HTTP_PORT}/status")
    print("=" * 60)

    # 1. 启动 HTTP API
    t_http = threading.Thread(target=http_server_worker, daemon=True)
    t_http.start()

    # 2. 启动串口通信线程
    t_ser = threading.Thread(target=serial_connect_and_listen, daemon=True)
    t_ser.start()

    load_status_file()
    last_push_sec = 0

    try:
        while True:
            now = datetime.now()
            file_changed = load_status_file()
            
            current_status["time"] = now.strftime("%H:%M:%S")
            if current_status.get("state") == "RUNNING":
                elapsed = int(time.time() - task_start_time)
                mins = elapsed // 60
                secs = elapsed % 60
                current_status["duration"] = f"{mins:02d}:{secs:02d}"

            cur_sec = now.second
            if file_changed or (cur_sec != last_push_sec):
                last_push_sec = cur_sec
                push_to_serial(force_log=file_changed)

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n中继服务已退出。")

if __name__ == '__main__':
    main()
