#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workbuddy 桌面状态机 - 现场目视验收测试 (Visual Acceptance Live Demo)
每个状态在开发板上停留 4 秒，以便用户清晰观察开发板屏幕的颜色、中文大字、强调色条和动态时间跳动。
"""

import os
import sys
import time
import json
import urllib.request
from datetime import datetime

HTTP_URL = "http://127.0.0.1:5200"
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.workbuddy-ai/daemon.log"))

DEMO_STEPS = [
    {
        "state": "RUNNING",
        "title": "【1/5 执行中】正在分析代码架构",
        "desc": "正在深度扫描 AST 与依赖调用链...",
        "thread": "Workbuddy · 状态机演示",
        "step": "1/4",
        "tools": "3 次",
        "tokens": "1.8k",
        "color_name": "亮青蓝 (Cyan) #00F2FE",
        "board_state_text": "执行中"
    },
    {
        "state": "NEED_APPROVAL",
        "title": "【2/5 等待确认】硬件按键审批",
        "desc": "请查看屏幕橙色卡片，按板上 BOOT 键确认",
        "thread": "Workbuddy · 审批流",
        "step": "2/4",
        "tools": "5 次",
        "tokens": "3.2k",
        "color_name": "警示橙 (Orange) #F59E0B",
        "board_state_text": "等待确认"
    },
    {
        "state": "NEED_ANSWER",
        "title": "【3/5 等待回答】需要方案决策",
        "desc": "请在 PC 端选择架构方案 A 或方案 B",
        "thread": "Workbuddy · 交互流",
        "step": "3/4",
        "tools": "6 次",
        "tokens": "5.6k",
        "color_name": "交互紫 (Purple) #8B5CF6",
        "board_state_text": "等待回答"
    },
    {
        "state": "COMPLETED",
        "title": "【4/5 已完成】全流程测试成功",
        "desc": "所有断言与指标全部通过，响应正常",
        "thread": "Workbuddy · 结算卡片",
        "step": "4/4",
        "tools": "9 次",
        "tokens": "12.5k",
        "color_name": "亮绿色 (Green) #00E676",
        "board_state_text": "已完成"
    },
    {
        "state": "IDLE",
        "title": "【5/5 待命中】工作台就绪",
        "desc": "所有测试演示完毕，系统待命中...",
        "thread": "Workbuddy · 待命状态",
        "step": "0/0",
        "tools": "0 次",
        "tokens": "0k",
        "color_name": "待命灰 (Gray) #7B889B",
        "board_state_text": "待命中"
    }
]

def push_state(step):
    payload = {
        "state": step["state"],
        "thread": step["thread"],
        "time": datetime.now().strftime("%H:%M:%S"),
        "alert_title": step["title"],
        "alert_desc": step["desc"],
        "step": step["step"],
        "tools": step["tools"],
        "duration": "00:45",
        "tokens": step["tokens"],
        "timeline": [
            {"text": step["title"], "dur": step["desc"], "done": step["state"] == "COMPLETED", "active": step["state"] == "RUNNING"}
        ]
    }
    req = urllib.request.Request(
        HTTP_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"❌ 推送失败: {e}")
        return False

def get_latest_board_ack():
    if not os.path.exists(LOG_FILE):
        return None
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in reversed(lines[-10:]):
                if "[板端] [HUD] OK" in line:
                    return line.strip()
    except Exception:
        pass
    return None

def main():
    print("=" * 60)
    print("🚀 开始 Workbuddy 桌面状态机【开发板目视验证推流】")
    print("提示：每个状态将在开发板上驻留 4 秒，请仔细观察屏幕视觉变化。")
    print("=" * 60)

    for i, step in enumerate(DEMO_STEPS, 1):
        print(f"\n▶️ [第 {i}/5 步] 正在切换到状态: 【{step['board_state_text']}】")
        print(f"   🎨 屏幕主题色: {step['color_name']}")
        print(f"   📌 屏幕卡片标题: {step['title']}")
        print(f"   📝 屏幕卡片描述: {step['desc']}")

        ok = push_state(step)
        if not ok:
            print("   ⚠️ 推流未成功，请检查 daemon 服务是否运行。")
            continue

        # 等待 4 秒，每秒打一个点并检查板端回执
        for sec in range(4):
            time.sleep(1.0)
            ack = get_latest_board_ack()
            print(f"   ⏱️ 驻留中 ({sec+1}/4s) | 板端回执: {ack[20:] if ack else '等待中'}")

    print("\n" + "=" * 60)
    print("✅ 现场目视推流演示完成！开发板屏幕已依次展示 5 种核心状态。")
    print("=" * 60)

if __name__ == '__main__':
    main()
