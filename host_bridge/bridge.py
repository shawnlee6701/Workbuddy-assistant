#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workbuddy 桌面状态机 - PC端串口推流中继程序
"""

import sys
import os
import time
import json
import glob
import serial
import threading
from datetime import datetime

def find_serial_ports():
    """自动扫描可用的串口设备，优先匹配 ESP32-S3 设备"""
    ports = []
    if sys.platform.startswith('darwin'):
        # macOS 优先匹配 usbmodem 和 usbserial
        ports = (glob.glob('/dev/tty.usbmodem*') + 
                 glob.glob('/dev/tty.usbserial*') + 
                 glob.glob('/dev/tty.wchusbserial*'))
    elif sys.platform.startswith('linux'):
        ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
    elif sys.platform.startswith('win'):
        ports = [f'COM{i+1}' for i in range(256)]
    return ports

def listen_serial(ser):
    """监听来自开发板的实体按键和交互事件"""
    while ser.is_open:
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                try:
                    data = json.loads(line)
                    if data.get("event") == "KEY_PRESS":
                        print(f"\n[🎮 硬件实体按键触发] -> 动作: {data.get('action')} (按键: {data.get('key')})")
                except json.JSONDecodeError:
                    print(f"[DEVICE] {line}", flush=True)
        except Exception:
            break

def run_demo_simulation(ser):
    """全自动状态机流转演练"""
    print("\n" + "="*50)
    print("🚀 Workbuddy 桌面状态机推流已启动！")
    print("💡 状态流正持续推送到 ESP32-S3 屏幕...")
    print("👉 遇到 [NEED_APPROVAL] 状态时，可按下开发板上的 BOOT 键测试确认")
    print("👉 按 Ctrl+C 可退出推流")
    print("="*50 + "\n")
    
    stages = [
        {
            "state": "RUNNING",
            "thread": "Workbuddy · vibe-coding",
            "alert_title": "正在重构状态机核心总线",
            "alert_desc": "Task: 执行代码修改与单元测试",
            "step": "2/5",
            "tools": "8 次",
            "duration": "01:20",
            "tokens": "12.3k",
            "timeline": [
                {"text": "分析项目代码架构", "dur": "0.6s", "done": True, "active": False},
                {"text": "编写 WebSocket 状态监听", "dur": "1.2s", "done": True, "active": False},
                {"text": "重构状态机核心总线", "dur": "进行中", "done": False, "active": True}
            ],
            "hold": 4
        },
        {
            "state": "NEED_ANSWER",
            "thread": "Workbuddy · vibe-coding",
            "alert_title": "等待用户输入: 确认端口映射",
            "alert_desc": "提问: 是否要启用 921600 高速串口模式？",
            "step": "3/5",
            "tools": "12 次",
            "duration": "02:15",
            "tokens": "16.8k",
            "timeline": [
                {"text": "重构状态机核心总线", "dur": "1.8s", "done": True, "active": False},
                {"text": "确认端口映射与波特率", "dur": "等待输入", "done": False, "active": True},
                {"text": "固件打包与校验", "dur": "", "done": False, "active": False}
            ],
            "hold": 5
        },
        {
            "state": "NEED_APPROVAL",
            "thread": "Workbuddy · vibe-coding",
            "alert_title": "权限确认: 写入固件配置",
            "alert_desc": "请求写入: platformio.ini 硬件管脚配置",
            "step": "4/5",
            "tools": "15 次",
            "duration": "02:50",
            "tokens": "19.5k",
            "timeline": [
                {"text": "确认端口映射与波特率", "dur": "0.5s", "done": True, "active": False},
                {"text": "写入固件配置文件", "dur": "等待审批", "done": False, "active": True},
                {"text": "全量交付与运行测试", "dur": "", "done": False, "active": False}
            ],
            "hold": 5
        },
        {
            "state": "COMPLETED",
            "thread": "Workbuddy · vibe-coding",
            "alert_title": "任务线程全部顺利完成",
            "alert_desc": "已完成代码生成、依赖配置与状态机适配",
            "step": "5/5",
            "tools": "18 次",
            "duration": "03:12",
            "tokens": "22.1k",
            "timeline": [
                {"text": "写入固件配置文件", "dur": "0.3s", "done": True, "active": False},
                {"text": "全量交付与运行测试", "dur": "1.1s", "done": True, "active": False},
                {"text": "状态机准备就绪", "dur": "完成", "done": True, "active": False}
            ],
            "hold": 5
        },
        {
            "state": "IDLE",
            "thread": "Workbuddy Main",
            "alert_title": "工作台待命中",
            "alert_desc": "随时待命，等待下一个任务指令...",
            "step": "0/0",
            "tools": "0 次",
            "duration": "00:00",
            "tokens": "0k",
            "timeline": [],
            "hold": 4
        }
    ]

    while True:
        for stage in stages:
            stage_data = stage.copy()
            hold_sec = stage_data.pop("hold")
            stage_data["time"] = datetime.now().strftime("%H:%M:%S")
            
            payload = json.dumps(stage_data, ensure_ascii=False)
            ser.write((payload + "\n").encode("utf-8"))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 状态流 -> [{stage['state']:<13}] : {stage['alert_title']}")
            time.sleep(hold_sec)

def main():
    ports = find_serial_ports()
    if not ports:
        print("[-] 未发现可用的 USB 串口设备！")
        print("    请检查立创开发板是否已通过 Type-C 数据线连接至电脑。")
        return

    target_port = ports[0]
    print(f"[+] 自动扫描到串口: {target_port}")
    
    try:
        ser = serial.Serial(target_port, 115200, timeout=1)
        print(f"[+] 成功打开串口 {target_port} (波特率 115200)")
    except Exception as e:
        print(f"[-] 打开串口失败: {e}")
        return

    t = threading.Thread(target=listen_serial, args=(ser,), daemon=True)
    t.start()

    time.sleep(1.5)
    run_demo_simulation(ser)

if __name__ == '__main__':
    main()
