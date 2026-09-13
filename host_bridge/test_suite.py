#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workbuddy 桌面状态机 - 综合自动化测试套件
全面覆盖：HTTP API 契约、状态流转多轮仿真、高频压力与延迟、异常容错、板端硬件回执与数据库感知校验。
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
import concurrent.futures
from datetime import datetime

BASE_URL = "http://127.0.0.1:5200"
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATUS_FILE = os.path.join(WORKSPACE_DIR, ".workbuddy-ai/live_status.json")
LOG_FILE = os.path.join(WORKSPACE_DIR, ".workbuddy-ai/daemon.log")

class TestRunner:
    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0

    def record(self, category, name, success, detail="", latency_ms=0.0):
        status_str = "PASS" if success else "FAIL"
        if success:
            self.passed += 1
        else:
            self.failed += 1
        self.results.append({
            "category": category,
            "name": name,
            "status": status_str,
            "latency_ms": round(latency_ms, 2),
            "detail": detail
        })
        icon = "✅" if success else "❌"
        print(f"[{icon} {status_str}] [{category}] {name} ({latency_ms:.2f}ms) - {detail}")

    def http_request(self, path, method="GET", data=None, headers=None, timeout=3.0):
        url = f"{BASE_URL}{path}"
        req_headers = headers or {}
        body = None
        if data is not None:
            if isinstance(data, (dict, list)):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                req_headers["Content-Type"] = "application/json"
            elif isinstance(data, str):
                body = data.encode("utf-8")
            elif isinstance(data, bytes):
                body = data

        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        t0 = time.perf_counter()
        resp_obj = {"status": None, "headers": {}, "body": b"", "latency_ms": 0.0, "error": None}
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_obj["status"] = resp.status
                resp_obj["headers"] = dict(resp.headers)
                resp_obj["body"] = resp.read()
        except urllib.error.HTTPError as e:
            resp_obj["status"] = e.code
            resp_obj["headers"] = dict(e.headers)
            resp_obj["body"] = e.read()
            resp_obj["error"] = str(e)
        except Exception as e:
            resp_obj["error"] = str(e)
        resp_obj["latency_ms"] = (time.perf_counter() - t0) * 1000
        return resp_obj

    # 1. 基础接口与契约测试
    def test_basic_endpoints(self):
        print("\n" + "="*50)
        print(">>> 1. 基础接口与契约测试 (Endpoint & Schema Checks)")
        print("="*50)

        # GET /api/status
        r = self.http_request("/api/status")
        if r["status"] == 200:
            try:
                data = json.loads(r["body"].decode("utf-8"))
                has_keys = all(k in data for k in ["state", "thread", "time", "alert_title"])
                self.record("API契约", "GET /api/status (核心字段完整性)", has_keys, f"state={data.get('state')}", r["latency_ms"])
            except Exception as e:
                self.record("API契约", "GET /api/status", False, f"JSON解析失败: {e}", r["latency_ms"])
        else:
            self.record("API契约", "GET /api/status", False, f"HTTP {r['status']}", r["latency_ms"])

        # GET /api/dashboard
        r = self.http_request("/api/dashboard")
        if r["status"] == 200:
            try:
                data = json.loads(r["body"].decode("utf-8"))
                has_bridge = "bridge" in data and "live" in data
                self.record("API契约", "GET /api/dashboard (仪表盘数据聚合)", has_bridge, f"keys={list(data.keys())}", r["latency_ms"])
            except Exception as e:
                self.record("API契约", "GET /api/dashboard", False, f"JSON解析失败: {e}", r["latency_ms"])
        else:
            self.record("API契约", "GET /api/dashboard", False, f"HTTP {r['status']}", r["latency_ms"])

        # GET /bridge (HTML 页面)
        r = self.http_request("/bridge")
        is_html = r["status"] == 200 and b"<!doctype html>" in r["body"].lower()
        self.record("静态资源", "GET /bridge (仪表盘界面)", is_html, f"size={len(r['body'])} bytes", r["latency_ms"])

        # GET /monitor (HTML 页面)
        r = self.http_request("/monitor")
        is_monitor = r["status"] == 200 and len(r["body"]) > 500
        self.record("静态资源", "GET /monitor (实时HUD界面)", is_monitor, f"size={len(r['body'])} bytes", r["latency_ms"])

        # OPTIONS 跨域预检
        r = self.http_request("/api/status", method="OPTIONS")
        cors_ok = r["status"] == 200 and r["headers"].get("Access-Control-Allow-Origin") == "*"
        self.record("安全与跨域", "OPTIONS CORS 预检", cors_ok, f"Allow-Origin={r['headers'].get('Access-Control-Allow-Origin')}", r["latency_ms"])

        # GET 404 路由
        r = self.http_request("/non_existing_path")
        self.record("错误处理", "GET 404 路由容错", r["status"] == 404, f"HTTP {r['status']}", r["latency_ms"])

    # 2. 多轮状态机流转仿真测试
    def test_multi_cycle_state_machine(self, rounds=3):
        print("\n" + "="*50)
        print(f">>> 2. 多轮状态流转仿真测试 (执行 {rounds} 轮完整周期)")
        print("="*50)

        test_states = [
            {"state": "RUNNING", "title": "【自动化测试】执行代码分析", "desc": "正在扫描抽象语法树与依赖图谱...", "step": "1/4", "tools": "3 次"},
            {"state": "NEED_APPROVAL", "title": "【自动化测试】请求敏感操作审批", "desc": "即将执行: git push --force origin main", "step": "2/4", "tools": "5 次"},
            {"state": "NEED_ANSWER", "title": "【自动化测试】等待方案决策", "desc": "方案A: 本地缓存优先 / 方案B: 实时接口拉取", "step": "3/4", "tools": "6 次"},
            {"state": "COMPLETED", "title": "【自动化测试】全流程测试成功", "desc": "所有单元测试通过，用时 0.4s", "step": "4/4", "tools": "8 次"},
            {"state": "IDLE", "title": "【自动化测试】恢复待命中", "desc": "系统待命中，等待新指令...", "step": "0/0", "tools": "0 次"}
        ]

        for cycle_idx in range(1, rounds + 1):
            print(f"\n--- 正在执行第 {cycle_idx}/{rounds} 轮状态推流测试 ---")
            for item in test_states:
                payload = {
                    "state": item["state"],
                    "thread": f"AutoTest · Round #{cycle_idx}",
                    "alert_title": item["title"],
                    "alert_desc": item["desc"],
                    "step": item["step"],
                    "tools": item["tools"],
                    "time": datetime.now().strftime("%H:%M:%S")
                }
                # POST 推送
                post_r = self.http_request("/", method="POST", data=payload)
                post_ok = post_r["status"] == 200
                
                # 立即验证 GET 是否反映了最新状态
                get_r = self.http_request("/api/status")
                get_state = ""
                if get_r["status"] == 200:
                    try:
                        cur_data = json.loads(get_r["body"].decode("utf-8"))
                        get_state = cur_data.get("state")
                    except Exception:
                        pass
                
                match = (get_state == item["state"])
                self.record(
                    f"状态流转-R{cycle_idx}",
                    f"推流 [{item['state']}] -> 验证回显",
                    post_ok and match,
                    f"期望={item['state']}, 实际={get_state}, 推送延时={post_r['latency_ms']:.1f}ms",
                    post_r["latency_ms"] + get_r["latency_ms"]
                )
                time.sleep(0.1)

    # 3. 高频突发并发压力测试
    def test_burst_concurrency(self, total_requests=50, max_workers=10):
        print("\n" + "="*50)
        print(f">>> 3. 高频突发压力测试 ({total_requests} 次并发请求, 线程池={max_workers})")
        print("="*50)

        latencies = []
        errors = 0

        def send_single(i):
            return self.http_request("/api/status")

        t_start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(send_single, i) for i in range(total_requests)]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res["status"] == 200:
                    latencies.append(res["latency_ms"])
                else:
                    errors += 1

        total_time = (time.perf_counter() - t_start) * 1000
        latencies.sort()
        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        p50 = latencies[int(len(latencies) * 0.5)] if latencies else 0
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
        p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0
        qps = (total_requests / (total_time / 1000)) if total_time > 0 else 0

        # 本地单进程多线程服务器，P95 < 200ms 且 0 错误视为非常优秀
        success = (errors == 0) and (p95 < 200.0)
        detail_msg = f"QPS: {qps:.1f} | 平均: {avg_lat:.2f}ms | P50: {p50:.2f}ms | P95: {p95:.2f}ms | P99: {p99:.2f}ms | 异常数: {errors}"
        self.record("并发压力", f"{total_requests}次并发读取 (/api/status)", success, detail_msg, avg_lat)

    # 4. 异常载荷注入测试
    def test_fault_injection(self):
        print("\n" + "="*50)
        print(">>> 4. 异常载荷注入与鲁棒性测试 (Fault Injection)")
        print("="*50)

        # 畸形 JSON
        r = self.http_request("/", method="POST", data="{invalid_json: 123", headers={"Content-Type": "application/json"})
        self.record("异常注入", "畸形 JSON 提交", r["status"] == 400, f"返回状态码: {r['status']}", r["latency_ms"])

        # 缺少 state 字段
        r = self.http_request("/", method="POST", data={"some_key": "val"}, headers={"Content-Type": "application/json"})
        self.record("异常注入", "缺失 state 核心字段", r["status"] == 400, f"返回状态码: {r['status']}", r["latency_ms"])

        # 空 Payload
        r = self.http_request("/", method="POST", data="", headers={"Content-Type": "application/json"})
        self.record("异常注入", "空 Payload 提交", r["status"] == 400, f"返回状态码: {r['status']}", r["latency_ms"])

    # 5. 硬件串口与日志回执验证
    def test_hardware_and_log(self):
        print("\n" + "="*50)
        print(">>> 5. 硬件串口连接与板端回执验证")
        print("="*50)

        # 检查日志文件
        log_exists = os.path.exists(LOG_FILE)
        recent_ok = False
        last_log_line = ""
        if log_exists:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if lines:
                    last_log_line = lines[-1].strip()
                    for line in reversed(lines[-20:]):
                        if "[板端] [HUD] OK" in line or "成功连接开发板" in line:
                            recent_ok = True
                            break

        self.record("硬件与串口", "板端实时回执校验 (Serial Feedback)", recent_ok, f"最新日志: {last_log_line[:60]}...", 0.0)

    def print_summary(self):
        print("\n" + "="*50)
        print(f"自动化测试完成! 总计: {len(self.results)} | 通过: {self.passed} | 失败: {self.failed}")
        print("="*50)
        return self.failed == 0

if __name__ == '__main__':
    runner = TestRunner()
    runner.test_basic_endpoints()
    runner.test_multi_cycle_state_machine(rounds=5)
    runner.test_burst_concurrency(total_requests=50, max_workers=10)
    runner.test_fault_injection()
    runner.test_hardware_and_log()
    success = runner.print_summary()
    sys.exit(0 if success else 1)
