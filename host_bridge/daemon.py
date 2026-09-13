#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workbuddy 桌面状态机 - 全自动智能感知中继守护服务 (Workbuddy Live Auto-Daemon)

功能特性：
1. 【双模融合】：
   - 自动感知模式：实时监听 ~/.workbuddy-ai/workbuddy.db 与系统会话状态，自动捕捉当前任务标题、状态（执行中/已完成/空闲）与工具调用。
   - 显式覆盖模式：通过 HTTP POST (端口 5200) 精细化临时控制。
2. 【高频时钟心跳与 Web 直推】：
   - 每秒跳动时间与运行时长，毫秒级响应状态突变。
   - 单向将最新数据写入 .workbuddy-ai/live_status.json 与本地 HTTP API (端口 5200)，供网页 HUD 实时拉取。
3. 【串口高可靠性连接】：
   - 自动识别 macOS (/dev/cu.usbmodem*), Linux, Windows 串口。
   - 非阻塞读写，自动断线重连，捕获板端硬件按键。
"""

import os
import sys
import time
import json
import glob
import sqlite3
import logging
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATUS_FILE = os.path.join(WORKSPACE_DIR, ".workbuddy-ai/live_status.json")
LOG_FILE = os.path.join(WORKSPACE_DIR, ".workbuddy-ai/daemon.log")
SYSTEM_DB = os.path.expanduser("~/.workbuddy-ai/workbuddy.db")
SYSTEM_TRACES = os.path.expanduser("~/.workbuddy-ai/traces")
DASHBOARD_FILE = os.path.join(WORKSPACE_DIR, "bridge_dashboard.html")
MONITOR_FILE = os.path.join(WORKSPACE_DIR, "web_hud.html")
HTTP_PORT = 5200
PROCESS_STARTED_AT = time.time()

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

class FlushHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

root_logger = logging.getLogger()
for h in list(root_logger.handlers):
    root_logger.removeHandler(h)
fh = FlushHandler(LOG_FILE, encoding='utf-8')
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
root_logger.addHandler(fh)
root_logger.setLevel(logging.INFO)

try:
    import serial
except ImportError:
    logging.error("未安装 pyserial")
    serial = None

current_status = {
    "state": "IDLE",
    "thread": "Workbuddy Main",
    "time": datetime.now().strftime("%H:%M:%S"),
    "alert_title": "工作台待命中",
    "alert_desc": "等待任务指令...",
    "step": "0/0",
    "tools": "0 次",
    "duration": "00:00",
    "tokens": "0k",
    "timeline": []
}

manual_override_until = 0
active_session_id = None
task_start_time = time.time()
ser = None
dashboard_cache = {"expires_at": 0, "value": None}
trace_usage_cache = {
    "session_id": None,
    "checked_at": 0.0,
    "usage": None,
}


def compact_number(value):
    """将大数字压缩为适合仪表盘阅读的短格式。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}m"
    if number >= 1_000:
        return f"{number / 1_000:.1f}k"
    return str(int(number))


def local_iso(timestamp):
    """兼容数据库中的毫秒/秒时间戳，返回本地 ISO 时间。"""
    try:
        value = float(timestamp)
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def clean_model_name(model):
    if not model:
        return None
    value = str(model).strip()
    for prefix in ("custom-local:", "openai:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value or None


def _nonnegative_int(value):
    """将 Trace 用量字段安全归一化为非负整数。"""
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def parse_trace_usage(payload):
    """从 Workbuddy Trace 中提取任务本轮 Token 凭据，不读取 Prompt 或模型输出。"""
    if not isinstance(payload, dict):
        return None

    trace = payload.get("trace")
    if not isinstance(trace, dict):
        return None

    model_info = trace.get("modelInfo")
    if not isinstance(model_info, dict):
        model_info = {}

    input_tokens = _nonnegative_int(model_info.get("totalInputTokens"))
    output_tokens = _nonnegative_int(model_info.get("totalOutputTokens"))
    cached_tokens = _nonnegative_int(model_info.get("totalCachedTokens"))
    total_tokens = _nonnegative_int(trace.get("totalTokens"))
    if total_tokens == 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    if total_tokens == 0:
        return None

    usage = {
        "total": total_tokens,
        "total_label": compact_number(total_tokens),
        "input": input_tokens,
        "input_label": compact_number(input_tokens),
        "output": output_tokens,
        "output_label": compact_number(output_tokens),
        "cached": cached_tokens,
        "cached_label": compact_number(cached_tokens),
        "calls": _nonnegative_int(model_info.get("callCount")),
        "trace_id": trace.get("traceId") or None,
        "ended_at": trace.get("endedAt") or None,
    }
    return {key: value for key, value in usage.items() if value not in (None, "")}


def get_session_trace_usage(session_id, refresh_after=1.0):
    """按 sessionId 精确匹配最新任务 Trace，避免串入其他会话的 Token。"""
    global trace_usage_cache
    if not session_id:
        return None

    now = time.time()
    if trace_usage_cache.get("session_id") == session_id:
        cached_usage = trace_usage_cache.get("usage")
        # 已经完成的 Trace 是不可变凭据，命中后无需反复扫描。
        if cached_usage and cached_usage.get("ended_at"):
            return cached_usage
        if now - trace_usage_cache.get("checked_at", 0) < refresh_after:
            return cached_usage

    try:
        paths = glob.glob(os.path.join(SYSTEM_TRACES, "*", "*.json"))
        paths.sort(key=os.path.getmtime, reverse=True)
    except OSError:
        paths = []

    usage = None
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as trace_file:
                payload = json.load(trace_file)
            trace = payload.get("trace") if isinstance(payload, dict) else None
            if not isinstance(trace, dict) or trace.get("sessionId") != session_id:
                continue
            usage = parse_trace_usage(payload)
            if usage:
                break
        except (OSError, ValueError, AttributeError):
            continue

    trace_usage_cache = {
        "session_id": session_id,
        "checked_at": now,
        "usage": usage,
    }
    return usage


def get_trace_summary():
    """只提取调用计数；不读取或返回 Prompt、参数与模型输出。"""
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    tool_counts = {}
    tool_total = 0
    generation_total = 0
    error_total = 0
    token_total = 0
    input_total = 0
    output_total = 0
    cached_total = 0
    model_call_total = 0
    token_trace_count = 0
    token_session_ids = set()

    try:
        paths = glob.glob(os.path.join(SYSTEM_TRACES, "*", "*.json"))
        paths = [path for path in paths if os.path.getmtime(path) >= midnight]
    except OSError:
        return {}

    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as trace_file:
                payload = json.load(trace_file)
            spans = payload.get("spans", [])
            for span in spans:
                span_type = span.get("type")
                if span_type == "function":
                    name = str(span.get("name") or "其他工具").strip()
                    tool_counts[name] = tool_counts.get(name, 0) + 1
                    tool_total += 1
                elif span_type == "generation":
                    generation_total += 1
                if span.get("error") or str(span.get("status", "")).lower() in {"error", "failed"}:
                    error_total += 1

            # 只统计绑定了真实会话的 Agent Trace；排除标题生成等系统 Trace。
            trace = payload.get("trace") if isinstance(payload, dict) else None
            session_id = trace.get("sessionId") if isinstance(trace, dict) else None
            usage = parse_trace_usage(payload) if session_id else None
            if usage:
                token_total += usage["total"]
                input_total += usage["input"]
                output_total += usage["output"]
                cached_total += usage["cached"]
                model_call_total += usage["calls"]
                token_trace_count += 1
                token_session_ids.add(session_id)
        except (OSError, ValueError, AttributeError):
            continue

    result = {}
    if tool_total:
        result["tool_calls"] = tool_total
        result["tools"] = [
            {"name": name, "count": count}
            for name, count in sorted(tool_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
            if count > 0
        ]
    if generation_total:
        result["generations"] = generation_total
    if error_total:
        result["errors"] = error_total
    if token_total:
        result["token_usage"] = {
            "total": token_total,
            "total_label": compact_number(token_total),
            "input": input_total,
            "input_label": compact_number(input_total),
            "output": output_total,
            "output_label": compact_number(output_total),
            "cached": cached_total,
            "cached_label": compact_number(cached_total),
            "calls": model_call_total,
            "traces": token_trace_count,
            "sessions": len(token_session_ids),
        }
    return result


def get_dashboard_data(force=False):
    """聚合 Workbuddy 可验证的数据；无记录的字段不进入响应。"""
    now = time.time()
    if not force and dashboard_cache["value"] is not None and now < dashboard_cache["expires_at"]:
        return dashboard_cache["value"]

    result = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "bridge": {
            "uptime_seconds": int(now - PROCESS_STARTED_AT),
            "serial_port": getattr(ser, "port", None) if ser is not None and getattr(ser, "is_open", False) else None,
        },
        "live": dict(current_status),
    }
    result["bridge"] = {key: value for key, value in result["bridge"].items() if value not in (None, "")}

    trace_summary = get_trace_summary()
    today = {}
    if trace_summary.get("tool_calls"):
        today["tool_calls"] = trace_summary["tool_calls"]
    if trace_summary.get("generations"):
        today["generations"] = trace_summary["generations"]
    if trace_summary.get("errors"):
        today["trace_errors"] = trace_summary["errors"]
    if trace_summary.get("tools"):
        result["tools"] = trace_summary["tools"]
    if trace_summary.get("token_usage"):
        result["today_token_usage"] = trace_summary["token_usage"]
        today["tokens"] = trace_summary["token_usage"]["total"]

    if os.path.exists(SYSTEM_DB):
        try:
            con = sqlite3.connect(f"file:{SYSTEM_DB}?mode=ro", uri=True, timeout=1)
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            # 今日指标：按今日活跃时间统计
            rows = cur.execute(
                """SELECT lower(status) AS status, COUNT(*) AS count
                   FROM sessions
                   WHERE deleted_at IS NULL
                     AND date(COALESCE(last_activity_at, updated_at, created_at) / 1000, 'unixepoch', 'localtime') = date('now', 'localtime')
                   GROUP BY lower(status)"""
            ).fetchall()
            status_counts = {row["status"]: row["count"] for row in rows if row["count"] > 0}
            session_total = sum(status_counts.values())
            if session_total:
                today["sessions"] = session_total
            for key in ("working", "completed", "terminated", "failed"):
                if status_counts.get(key):
                    today[key] = status_counts[key]

            # 最近会话不包含 user_id、完整 cwd、插件配置或 Prompt。
            rows = cur.execute(
                """SELECT title, custom_title, status, model, created_at, updated_at
                   FROM sessions
                   WHERE deleted_at IS NULL
                   ORDER BY COALESCE(last_activity_at, updated_at) DESC
                   LIMIT 8"""
            ).fetchall()
            recent_sessions = []
            for row in rows:
                title = (row["custom_title"] or row["title"] or "").strip()
                if not title:
                    continue
                item = {
                    "title": title,
                    "status": str(row["status"] or "").lower(),
                    "model": clean_model_name(row["model"]),
                    "updated_at": local_iso(row["updated_at"]),
                }
                recent_sessions.append({key: value for key, value in item.items() if value not in (None, "")})
            if recent_sessions:
                result["recent_sessions"] = recent_sessions

            rows = cur.execute(
                """SELECT model, COUNT(*) AS count
                   FROM sessions
                   WHERE deleted_at IS NULL AND model IS NOT NULL AND trim(model) <> ''
                   GROUP BY model ORDER BY count DESC LIMIT 6"""
            ).fetchall()
            models = [
                {"name": clean_model_name(row["model"]), "count": row["count"]}
                for row in rows if row["count"] > 0 and clean_model_name(row["model"])
            ]
            if models:
                result["models"] = models

            rows = cur.execute(
                """SELECT date(COALESCE(last_activity_at, updated_at, created_at) / 1000, 'unixepoch', 'localtime') AS day, COUNT(*) AS count
                   FROM sessions
                   WHERE deleted_at IS NULL
                   GROUP BY day ORDER BY day DESC LIMIT 7"""
            ).fetchall()
            activity = [{"day": row["day"], "count": row["count"]} for row in reversed(rows) if row["day"] and row["count"] > 0]
            if activity:
                result["activity"] = activity

            row = cur.execute(
                """SELECT su.used, su.size, su.updated_at, s.title
                   FROM session_usage su JOIN sessions s ON s.id = su.session_id
                   WHERE su.size > 0 AND su.used > 0 AND s.deleted_at IS NULL
                   ORDER BY su.updated_at DESC LIMIT 1"""
            ).fetchone()
            if row:
                result["context_usage"] = {
                    "used": row["used"],
                    "used_label": compact_number(row["used"]),
                    "size": row["size"],
                    "size_label": compact_number(row["size"]),
                    "percent": round(min(100, row["used"] / row["size"] * 100), 1),
                    "session": row["title"] or None,
                    "updated_at": local_iso(row["updated_at"]),
                }
                result["context_usage"] = {
                    key: value for key, value in result["context_usage"].items() if value not in (None, "")
                }

            rows = cur.execute(
                """SELECT path, last_opened_at FROM workspaces
                   WHERE path IS NOT NULL AND trim(path) <> ''
                   ORDER BY last_opened_at DESC LIMIT 6"""
            ).fetchall()
            workspaces = []
            for row in rows:
                name = os.path.basename(str(row["path"]).rstrip(os.sep))
                if name:
                    workspaces.append({"name": name, "last_opened_at": local_iso(row["last_opened_at"])})
            if workspaces:
                result["workspaces"] = workspaces

            rows = cur.execute(
                """SELECT name, status, next_run_at, last_run_at
                   FROM automations
                   WHERE deleted_at IS NULL
                   ORDER BY updated_at DESC LIMIT 6"""
            ).fetchall()
            automations = []
            for row in rows:
                if not row["name"]:
                    continue
                item = {
                    "name": row["name"],
                    "status": str(row["status"] or "").lower(),
                    "next_run_at": local_iso(row["next_run_at"]),
                    "last_run_at": local_iso(row["last_run_at"]),
                }
                automations.append({key: value for key, value in item.items() if value not in (None, "")})
            if automations:
                result["automations"] = automations
            con.close()
        except (sqlite3.Error, OSError) as exc:
            logging.debug(f"Bridge Dashboard 数据库读取跳过: {exc}")

    if today:
        result["today"] = today
    dashboard_cache["value"] = result
    dashboard_cache["expires_at"] = now + 5
    return result

# ==================== HTTP 服务 (供网页 HUD 跨域秒级直取 & 显式状态推送) ====================
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class StatusHttpHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/bridge":
            return self.serve_file(DASHBOARD_FILE, "text/html; charset=utf-8")
        if path == "/monitor":
            return self.serve_file(MONITOR_FILE, "text/html; charset=utf-8")
        if path in {"/api/bridge", "/api/dashboard"}:
            return self.send_json(get_dashboard_data())
        if path in {"/", "/api/status"}:
            return self.send_json(current_status)
        self.send_error(404)

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_file(self, path, content_type):
        try:
            with open(path, "rb") as file_handle:
                payload = file_handle.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        global current_status, manual_override_until, task_start_time
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode("utf-8"))
            if isinstance(data, dict) and "state" in data:
                now = time.time()
                manual_override_until = now + 15.0  # 显式覆盖 15 秒
                if data.get("state") == "RUNNING" and current_status.get("state") != "RUNNING":
                    task_start_time = now
                current_status.update(data)
                logging.info(f"⚡ [HTTP显式推送] [{data.get('state')}] {data.get('alert_title')}")
                dashboard_cache["expires_at"] = 0
                
                # 显式推送立即推送到串口，实现零延迟即时刷屏
                if ser is not None and getattr(ser, "is_open", False):
                    try:
                        immediate_payload = json.dumps(current_status, ensure_ascii=False) + "\n"
                        ser.write(immediate_payload.encode("utf-8"))
                        ser.flush()
                    except Exception as se:
                        logging.warning(f"显式推送串口写入异常: {se}")
                
                return self.send_json({"status": "ok"})
        except Exception as e:
            logging.error(f"HTTP POST 处理失败: {e}")
        self.send_response(400)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

def start_http_server():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), StatusHttpHandler)
        server.serve_forever()
    except Exception as e:
        logging.warning(f"HTTP Server 异常: {e}")

def find_serial():
    ports = []
    if sys.platform.startswith('darwin'):
        ports = (glob.glob('/dev/cu.usbmodem*') + 
                 glob.glob('/dev/cu.usbserial*') + 
                 glob.glob('/dev/cu.wchusbserial*') +
                 glob.glob('/dev/tty.usbmodem*') +
                 glob.glob('/dev/tty.usbserial*'))
    elif sys.platform.startswith('linux'):
        ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
    elif sys.platform.startswith('win'):
        ports = [f'COM{i+1}' for i in range(256)]
    return ports[0] if ports else None

def get_system_live_status():
    """从 Workbuddy 系统数据库与 traces 提取真实会话状态"""
    if not os.path.exists(SYSTEM_DB):
        return None
    try:
        con = sqlite3.connect(f"file:{SYSTEM_DB}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT id, title, status, created_at, updated_at, model FROM sessions ORDER BY updated_at DESC LIMIT 1;")
        row = cur.fetchone()
        con.close()
        if not row:
            return None

        sess_id, title, status, created_at, updated_at, model = row
        title = title or "未命名任务"
        now_ms = int(time.time() * 1000)

        # 状态流转判定
        if status == "working":
            state = "RUNNING"
            desc = "正在执行 AI 工作流与工具调用..."
        elif status == "completed":
            # 如果是最近 10 秒内刚刚完成的，展示 COMPLETED 结算卡片；超过 10 秒自动转为 IDLE 待命
            if (now_ms - updated_at) < 10000:
                state = "COMPLETED"
                desc = "本轮任务已顺利完成"
            else:
                state = "IDLE"
                desc = "工作台就绪，等待新任务"
        else:
            state = "IDLE"
            desc = "工作台就绪，等待新任务"

        # 检查 trace 工具调用
        tool_count = 0
        latest_tool_desc = ""
        try:
            traces = sorted(glob.glob(os.path.join(SYSTEM_TRACES, "*/*.json")), key=os.path.getmtime, reverse=True)
            if traces:
                with open(traces[0], 'r', encoding='utf-8') as f:
                    t_data = json.load(f)
                    spans = t_data.get('spans', [])
                    funcs = [s for s in spans if s.get('type') == 'function']
                    tool_count = len(funcs)
                    if funcs:
                        last_fn = funcs[-1].get('name', '')
                        tool_map = {
                            "Bash": "终端命令执行中",
                            "Read": "读取分析代码文件",
                            "Write": "写入与生成文件",
                            "Edit": "精准重构代码段",
                            "Glob": "检索匹配项目文件",
                            "Grep": "全文正则扫描代码",
                            "Skill": "调度专用技能模块"
                        }
                        latest_tool_desc = tool_map.get(last_fn, f"调用工具: {last_fn}")
        except Exception:
            pass

        if latest_tool_desc and state == "RUNNING":
            desc = latest_tool_desc

        return {
            "session_id": sess_id,
            "session_status": str(status or "").lower(),
            "state": state,
            "title": title,
            "desc": desc,
            "tool_count": tool_count,
            "model": clean_model_name(model),
            "created_at": created_at,
            "updated_at": updated_at
        }
    except Exception as e:
        return None

def sync_status():
    global current_status, active_session_id, task_start_time, manual_override_until
    now = time.time()
    changed = False

    # 1. 如果处于 HTTP 显式控制窗口期内，保持显式状态
    if now < manual_override_until:
        return False

    # 2. 自动感知系统级会话状态 (查询 SQLite DB 与 Traces)
    sys_state = get_system_live_status()
    if sys_state:
        sess_id = sys_state["session_id"]
        if sess_id != active_session_id:
            active_session_id = sess_id
            task_start_time = now
            current_status["tokens"] = "0"
            current_status.pop("token_usage", None)
            changed = True

        new_state = sys_state["state"]
        new_title = sys_state["title"]
        new_desc = sys_state["desc"]
        new_model = sys_state.get("model")
        tool_count_str = f"{sys_state['tool_count']} 次"
        usage = None
        if sys_state.get("session_status") == "completed":
            usage = get_session_trace_usage(sess_id)
        
        # 提取本轮会话 Token 与今日总 Token
        today_summary = get_trace_summary()
        today_token_usage = today_summary.get("token_usage")
        session_usage = get_session_trace_usage(sess_id) if sess_id else None

        today_token_label = today_token_usage["total_label"] if today_token_usage else "0m"
        session_token_label = session_usage["total_label"] if session_usage else "0"

        previous_session_total = (current_status.get("session_token_usage") or {}).get("total")
        next_session_total = session_usage.get("total") if session_usage else None
        previous_today_total = (current_status.get("today_token_usage") or {}).get("total")
        next_today_total = today_token_usage.get("total") if today_token_usage else None

        if (current_status.get("state") != new_state or 
            current_status.get("alert_title") != new_title or 
            current_status.get("alert_desc") != new_desc or
            current_status.get("model") != new_model or
            previous_session_total != next_session_total or
            previous_today_total != next_today_total):
            changed = True
            logging.info(f"⚡ [自动感知] [{new_state}] {new_title} ({new_desc}) | 本轮:{session_token_label} 今日:{today_token_label}")

        current_status["state"] = new_state
        current_status["thread"] = "Workbuddy · 实时监控"
        current_status["alert_title"] = new_title
        current_status["alert_desc"] = new_desc
        current_status["step"] = "实时"
        current_status["tools"] = tool_count_str
        if new_model:
            current_status["model"] = new_model
        else:
            current_status.pop("model", None)

        # 固化双 Token 协议
        current_status["tokens"] = session_token_label
        current_status["session_tokens"] = session_token_label
        current_status["today_tokens"] = today_token_label

        if session_usage:
            current_status["session_token_usage"] = {
                key: value for key, value in session_usage.items()
                if key not in {"trace_id", "ended_at"}
            }
            current_status["token_usage"] = current_status["session_token_usage"]
        else:
            current_status.pop("session_token_usage", None)
            current_status.pop("token_usage", None)

        if today_token_usage:
            current_status["today_token_usage"] = today_token_usage
        else:
            current_status.pop("today_token_usage", None)
        current_status["timeline"] = [
            {"text": new_title, "dur": new_desc, "done": new_state == "COMPLETED", "active": new_state == "RUNNING"}
        ]

        if changed:
            dashboard_cache["expires_at"] = 0

    return changed

def main():
    global ser, current_status
    logging.info("🚀 Workbuddy 桌面全自动状态感知守护进程已启动")

    # 启动后台 HTTP API
    t_http = threading.Thread(target=start_http_server, daemon=True)
    t_http.start()

    sync_status()
    last_sec = -1

    while True:
        # 1. 维护串口连接
        if ser is None or not ser.is_open:
            port = find_serial()
            if port:
                try:
                    ser = serial.Serial()
                    ser.port = port
                    ser.baudrate = 115200
                    ser.timeout = 0.05
                    ser.write_timeout = 0.5
                    ser.setDTR(False)
                    ser.setRTS(False)
                    ser.open()
                    time.sleep(0.1)
                    ser.setDTR(True)
                    ser.setRTS(False)
                    logging.info(f"✅ 成功连接开发板 (DTR=1, RTS=0): {port}")
                    time.sleep(0.3)
                    # 刚连上立即推一次当前数据
                    payload = json.dumps(current_status, ensure_ascii=False) + "\n"
                    ser.write(payload.encode("utf-8"))
                    ser.flush()
                except Exception as e:
                    logging.warning(f"打开串口失败: {e}")
                    ser = None

        # 2. 非阻塞读取板端回传
        try:
            if ser and ser.in_waiting:
                raw = ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                for line in raw.splitlines():
                    line = line.strip()
                    if line:
                        logging.info(f"[板端] {line}")
        except Exception as e:
            logging.warning(f"串口读取异常: {e}")
            ser = None
            continue

        # 3. 检查系统状态与秒级心跳
        now_dt = datetime.now()
        status_changed = sync_status()

        current_status["time"] = now_dt.strftime("%H:%M:%S")
        if current_status.get("state") == "RUNNING":
            elapsed = int(time.time() - task_start_time)
            mins = elapsed // 60
            secs = elapsed % 60
            current_status["duration"] = f"{mins:02d}:{secs:02d}"
        else:
            current_status["duration"] = "00:00"

        # 触发推流条件：状态变更 OR 每秒跳动
        if status_changed or (now_dt.second != last_sec):
            last_sec = now_dt.second
            payload = json.dumps(current_status, ensure_ascii=False) + "\n"
            
            # 单向输出本地文件供静态网页直接读取
            try:
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    f.write(payload)
            except Exception:
                pass

            # 推送到硬件串口
            if ser is not None and getattr(ser, "is_open", False):
                try:
                    ser.write(payload.encode("utf-8"))
                    ser.flush()
                except Exception as e:
                    logging.warning(f"串口写入异常: {e}")
                    ser = None

        time.sleep(0.08)

if __name__ == '__main__':
    main()
