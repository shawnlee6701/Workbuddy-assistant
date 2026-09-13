#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workbuddy 桌面状态机 - Terminal 终端全真 HUD 模拟器
特性：
1. 纯终端 ANSI 高反差渲染，1:1 仿真 320x240 屏幕排版与色彩
2. 支持全自动状态机流转演练
3. 键盘交互：
   - 按 'a' 模拟硬件 BOOT 实体按键 (Approve 审批)
   - 按 1~6 手动切换不同状态 (RUNNING, NEED_ANSWER, NEED_APPROVAL, COMPLETED, ERROR, IDLE)
   - 按 'q' 退出
"""

import os
import sys
import time
import select
import tty
import termios
from datetime import datetime

# ANSI 颜色定义
C_RESET   = "\033[0m"
C_BOLD    = "\033[1m"
C_DIM     = "\033[2m"

# 状态主题配色 (ANSI 256/RGB)
BG_SCREEN = "\033[48;5;234m"   # 深色背景
FG_WHITE  = "\033[38;5;255m"
FG_MUTED  = "\033[38;5;246m"
FG_DIM    = "\033[38;5;240m"
FG_BORDER = "\033[38;5;238m"
FG_CYAN   = "\033[38;5;122m"

STATE_STYLES = {
    "RUNNING": {
        "badge_bg": "\033[48;5;26m",
        "badge_fg": "\033[38;5;255m",
        "icon": "●",
        "card_fg": "\033[38;5;75m",
        "card_border": "\033[38;5;33m"
    },
    "NEED_ANSWER": {
        "badge_bg": "\033[48;5;97m",
        "badge_fg": "\033[38;5;255m",
        "icon": "?",
        "card_fg": "\033[38;5;183m",
        "card_border": "\033[38;5;141m"
    },
    "NEED_APPROVAL": {
        "badge_bg": "\033[48;5;172m",
        "badge_fg": "\033[38;5;255m",
        "icon": "⚠",
        "card_fg": "\033[38;5;221m",
        "card_border": "\033[38;5;214m"
    },
    "COMPLETED": {
        "badge_bg": "\033[48;5;28m",
        "badge_fg": "\033[38;5;255m",
        "icon": "✓",
        "card_fg": "\033[38;5;114m",
        "card_border": "\033[38;5;76m"
    },
    "ERROR": {
        "badge_bg": "\033[48;5;160m",
        "badge_fg": "\033[38;5;255m",
        "icon": "✕",
        "card_fg": "\033[38;5;203m",
        "card_border": "\033[38;5;196m"
    },
    "IDLE": {
        "badge_bg": "\033[48;5;240m",
        "badge_fg": "\033[38;5;250m",
        "icon": "◌",
        "card_fg": "\033[38;5;250m",
        "card_border": "\033[38;5;244m"
    }
}

STAGES = [
    {
        "state": "RUNNING",
        "thread": "Workbuddy · vibe-coding",
        "alert_title": "正在重构状态机核心总线",
        "alert_desc": "Task: 执行代码修改与单元测试验证",
        "step": "2/5",
        "tools": "8 次",
        "duration": "01:20",
        "tokens": "12.3k",
        "timeline": [
            {"text": "分析项目代码架构", "dur": "0.6s", "done": True, "active": False},
            {"text": "编写 WebSocket 状态监听", "dur": "1.2s", "done": True, "active": False},
            {"text": "重构状态机核心总线", "dur": "进行中", "done": False, "active": True}
        ]
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
        ]
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
        ]
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
        ]
    },
    {
        "state": "ERROR",
        "thread": "Workbuddy · vibe-coding",
        "alert_title": "任务异常中断 (模拟)",
        "alert_desc": "错误: 端口连接超时，请检查硬件链路",
        "step": "3/5",
        "tools": "12 次",
        "duration": "02:15",
        "tokens": "16.8k",
        "timeline": [
            {"text": "重构状态机核心总线", "dur": "1.8s", "done": True, "active": False},
            {"text": "异常中断并暂停", "dur": "失败", "done": False, "active": True},
            {"text": "待重试恢复", "dur": "", "done": False, "active": False}
        ]
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
        "timeline": []
    }
]

def render_hud(data, last_action_msg=""):
    state = data.get("state", "IDLE")
    style = STATE_STYLES.get(state, STATE_STYLES["IDLE"])
    now_str = datetime.now().strftime("%H:%M:%S")

    w = 66  # 宽度
    lines = []
    
    # 清屏并定位到左上角
    lines.append("\033[H")
    
    # 顶部外壳装饰
    lines.append(f"{C_BOLD}{FG_MUTED}╭─ 📟 WORKBUDDY DESKTOP HUD · TERMINAL SIMULATOR ─ 320x240 IPS ─╮{C_RESET}")
    
    # 1. 顶栏：Badge + 线程名 + 时间
    badge = f"{style['badge_bg']}{style['badge_fg']} {style['icon']} {state} {C_RESET}"
    thread_name = f"{FG_MUTED}{data.get('thread', 'Workbuddy Main')}{C_RESET}"
    time_badge = f"{FG_CYAN}{now_str}{C_RESET}"
    
    # 拼接顶栏
    top_line = f"│ {badge}  {thread_name}".ljust(68) + f"{time_badge} │"
    lines.append(top_line)
    lines.append(f"├{'─' * w}┤")
    
    # 2. 状态聚焦卡片
    alert_t = data.get("alert_title", "")
    alert_d = data.get("alert_desc", "")
    card_border = style['card_border']
    card_fg = style['card_fg']
    
    lines.append(f"│  {card_border}┌─ 状态聚焦 (FOCUS ALERT) {'─' * 38}┐{C_RESET}  │")
    lines.append(f"│  {card_border}│{C_RESET}  {C_BOLD}{card_fg}{alert_t:<58}{C_RESET}{card_border}│{C_RESET}  │")
    lines.append(f"│  {card_border}│{C_RESET}  {FG_MUTED}{alert_d:<58}{C_RESET}{card_border}│{C_RESET}  │")
    if state == "NEED_APPROVAL":
        action_tip = f"{C_BOLD}\033[48;5;172m\033[38;5;255m [按 'a' 键或板载 BOOT 键 Approve] {C_RESET}"
        lines.append(f"│  {card_border}│{C_RESET}  {action_tip:<74}{card_border}│{C_RESET}  │")
    lines.append(f"│  {card_border}└{'─' * 60}┘{C_RESET}  │")
    
    # 3. 指标网格 4 列 (STEP, TOOLS, TIME, TOKENS)
    s_step = data.get('step', '0/0')
    s_tool = data.get('tools', '0 次')
    s_dur  = data.get('duration', '00:00')
    s_tok  = data.get('tokens', '0k')
    
    lines.append(f"│  {FG_BORDER}┌────────────┬────────────┬────────────┬────────────┐{C_RESET}  │")
    lines.append(f"│  {FG_BORDER}│{C_RESET} {FG_DIM}STEP{C_RESET}       {FG_BORDER}│{C_RESET} {FG_DIM}TOOLS{C_RESET}      {FG_BORDER}│{C_RESET} {FG_DIM}TIME{C_RESET}       {FG_BORDER}│{C_RESET} {FG_DIM}TOKENS{C_RESET}     {FG_BORDER}│{C_RESET}  │")
    lines.append(f"│  {FG_BORDER}│{C_RESET} {FG_WHITE}{s_step:<10}{C_RESET} {FG_BORDER}│{C_RESET} {FG_WHITE}{s_tool:<10}{C_RESET} {FG_BORDER}│{C_RESET} {FG_WHITE}{s_dur:<10}{C_RESET} {FG_BORDER}│{C_RESET} {FG_WHITE}{s_tok:<10}{C_RESET} {FG_BORDER}│{C_RESET}  │")
    lines.append(f"│  {FG_BORDER}└────────────┴────────────┴────────────┴────────────┘{C_RESET}  │")
    
    # 4. 时间线
    lines.append(f"│  {FG_DIM}── 任务时间线 (TIMELINE) ───────────────────────────────{C_RESET}  │")
    tl = data.get("timeline", [])
    if not tl:
        lines.append(f"│     {FG_DIM}◌ 工作台空闲就绪，无活跃子任务...{C_RESET}".ljust(72) + "│")
        lines.append(f"│{' ' * w}│")
        lines.append(f"│{' ' * w}│")
    else:
        for i in range(3):
            if i < len(tl):
                item = tl[i]
                if item.get("done"):
                    dot = f"\033[38;5;114m✓{C_RESET}"
                    txt = f"{FG_MUTED}{item['text']}{C_RESET}"
                elif item.get("active"):
                    dot = f"\033[38;5;75m▶{C_RESET}"
                    txt = f"{C_BOLD}{FG_WHITE}{item['text']}{C_RESET}"
                else:
                    dot = f"{FG_DIM}○{C_RESET}"
                    txt = f"{FG_DIM}{item['text']}{C_RESET}"
                dur = f"{FG_DIM}{item.get('dur', '')}{C_RESET}"
                line_str = f"│     {dot} {txt}".ljust(64) + f"{dur}  │"
                lines.append(line_str)
            else:
                lines.append(f"│{' ' * w}│")
                
    # 底部快捷键提示
    lines.append(f"├{'─' * w}┤")
    lines.append(f"│ {FG_DIM}快捷键: [1~6]切换状态 | [a]模拟按键Approve | [Space]暂停 | [q]退出{C_RESET} │")
    lines.append(f"╰{'─' * w}╯")
    
    if last_action_msg:
        lines.append(f"\n{C_BOLD}\033[38;5;220m⚡ 硬件事件捕获: {last_action_msg}{C_RESET}\n")
    else:
        lines.append("\n" + " "*60 + "\n")

    sys.stdout.write("\n".join(lines))
    sys.stdout.flush()

def main():
    # 终端清屏
    os.system("clear" if os.name != "nt" else "cls")
    
    # 切换为原始终端模式以捕获单字符按键
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())
    
    stage_idx = 0
    auto_play = True
    last_switch_time = time.time()
    last_action_msg = ""
    action_msg_expire = 0
    
    try:
        while True:
            cur_data = STAGES[stage_idx]
            
            # 检查是否有按键输入 (非阻塞)
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch = sys.stdin.read(1)
                if ch == 'q' or ch == '\x03':  # q 或 Ctrl+C
                    break
                elif ch in ['1', '2', '3', '4', '5', '6']:
                    stage_idx = int(ch) - 1
                    auto_play = False
                    last_action_msg = f"已手动切换至: {STAGES[stage_idx]['state']}"
                    action_msg_expire = time.time() + 2
                elif ch == 'a':
                    last_action_msg = "🎮 BOOT 实体按键触发 -> APPROVE 审批通过！"
                    action_msg_expire = time.time() + 3
                elif ch == ' ':
                    auto_play = not auto_play
                    last_action_msg = "自动流转已" + ("继续" if auto_play else "暂停")
                    action_msg_expire = time.time() + 2

            # 自动流转
            if auto_play and (time.time() - last_switch_time > 4.0):
                stage_idx = (stage_idx + 1) % len(STAGES)
                last_switch_time = time.time()

            # 清理过期的提示
            if time.time() > action_msg_expire:
                last_action_msg = ""

            render_hud(cur_data, last_action_msg)
            time.sleep(0.1)

    finally:
        # 恢复终端
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        print("\n\n已退出 HUD 终端仿真器。\n")

if __name__ == '__main__':
    main()
