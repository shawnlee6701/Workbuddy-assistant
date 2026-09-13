#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workbuddy 桌面状态机 - 命令行一键推送工具
使用方法：
  python3 host_bridge/send_status.py --state RUNNING --title "正在写代码" --desc "正在生成组件"
  python3 host_bridge/send_status.py --state NEED_ANSWER --title "需要确认方案" --desc "选择 A 还是 B"
  python3 host_bridge/send_status.py --state NEED_APPROVAL --title "执行敏感命令" --desc "git push --force"
  python3 host_bridge/send_status.py --state COMPLETED --title "任务已全部完成"
  python3 host_bridge/send_status.py --state IDLE --title "工作台待命中"
"""

import os
import sys
import json
import argparse
import urllib.request
from datetime import datetime

HTTP_URL = "http://127.0.0.1:5200"
STATUS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.workbuddy-ai/live_status.json"))

def main():
    parser = argparse.ArgumentParser(description="一键推送状态到桌面状态机")
    parser.add_argument("--state", choices=["RUNNING", "NEED_ANSWER", "NEED_APPROVAL", "COMPLETED", "ERROR", "IDLE"], default="RUNNING", help="状态标识")
    parser.add_argument("--title", type=str, default="正在执行任务", help="聚焦卡片标题")
    parser.add_argument("--desc", type=str, default="Task 详细描述与进度", help="聚焦卡片描述")
    parser.add_argument("--thread", type=str, default="Workbuddy · 实时线程", help="线程名称")
    parser.add_argument("--step", type=str, default="1/1", help="当前步骤 (如 2/5)")
    parser.add_argument("--tools", type=str, default="1 次", help="工具调用数")
    parser.add_argument("--tokens", type=str, default="1.2k", help="Token 消耗")
    parser.add_argument("--model", type=str, default="", help="当前模型名称（空值不展示）")

    args = parser.parse_args()

    payload = {
        "state": args.state,
        "thread": args.thread,
        "time": datetime.now().strftime("%H:%M:%S"),
        "alert_title": args.title,
        "alert_desc": args.desc,
        "step": args.step,
        "tools": args.tools,
        "duration": "00:00",
        "tokens": args.tokens,
        "timeline": [
            {"text": args.title, "dur": "进行中" if args.state == "RUNNING" else "就绪", "done": args.state == "COMPLETED", "active": args.state == "RUNNING"}
        ]
    }
    if args.model.strip():
        payload["model"] = args.model.strip()

    # 1. 优先通过 HTTP API 注入
    sent_http = False
    try:
        req = urllib.request.Request(
            HTTP_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                sent_http = True
    except Exception:
        sent_http = False

    # 2. 同步写入本地文件
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    if sent_http:
        print(f"✅ 成功推送状态 (HTTP+文件): [{args.state}] {args.title}")
    else:
        print(f"✅ 成功推送状态 (文件): [{args.state}] {args.title}")

if __name__ == '__main__':
    main()
