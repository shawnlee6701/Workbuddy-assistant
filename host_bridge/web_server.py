#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workbuddy 桌面状态机 - Web HUD 实时可视化看板与 API 服务
"""

import os
import sys
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

STATUS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.workbuddy-ai/live_status.json"))
HTTP_PORT = 5200

def get_current_status():
    default_data = {
        "state": "RUNNING",
        "thread": "Workbuddy · 桌面状态机",
        "time": "20:00:00",
        "alert_title": "正在接入 Workbuddy 真实数据源",
        "alert_desc": "Task: 构建本地 live_status 状态总线与串口/Web 双向推流",
        "step": "1/3",
        "tools": "4 次",
        "duration": "00:45",
        "tokens": "8.2k",
        "timeline": [
            {"text": "设计真实数据同步总线协议", "dur": "0.4s", "done": True, "active": False},
            {"text": "实现 Web / 串口 实时中继器", "dur": "进行中", "done": False, "active": True},
            {"text": "联调开发板屏幕与终端真实渲染", "dur": "", "done": False, "active": False}
        ]
    }
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_data

def save_status(data):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

WEB_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Workbuddy Desktop HUD · 实时监控看板</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #090a0f;
      color: #f0f2f5;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      padding: 20px;
    }
    .hud-enclosure {
      background: #181b20;
      border: 3px solid #2d3135;
      border-radius: 24px;
      padding: 24px;
      width: 100%;
      max-width: 620px;
      box-shadow: 0 12px 36px rgba(0,0,0,0.5);
    }
    .hud-case-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      font-family: monospace;
      font-size: 12px;
      color: #888780;
    }
    .hud-led {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #378ADD;
      box-shadow: 0 0 8px #378ADD;
      display: inline-block;
      margin-right: 8px;
    }
    .screen-bezel {
      background: #0f1115;
      border: 1px solid #262930;
      border-radius: 14px;
      padding: 18px;
    }
    .top-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid #262930;
      padding-bottom: 12px;
      margin-bottom: 14px;
    }
    .state-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 13px;
      background: #185FA5;
      color: #fff;
    }
    .time-thread {
      text-align: right;
    }
    .time-text {
      font-family: monospace;
      color: #9FE1CB;
      font-size: 14px;
      font-weight: bold;
    }
    .thread-text {
      color: #888780;
      font-size: 12px;
    }
    .alert-card {
      background: rgba(55,138,221,0.15);
      border: 1px solid #378ADD;
      border-radius: 8px;
      padding: 12px 14px;
      margin-bottom: 14px;
    }
    .alert-title {
      font-weight: bold;
      color: #85B7EB;
      font-size: 14px;
      margin-bottom: 4px;
    }
    .alert-desc {
      color: #B4B2A9;
      font-size: 12px;
    }
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric-cell {
      background: #181b20;
      border: 1px solid #262930;
      border-radius: 6px;
      padding: 8px 10px;
    }
    .metric-label {
      font-size: 11px;
      color: #888780;
      text-transform: uppercase;
    }
    .metric-value {
      font-size: 16px;
      font-family: monospace;
      font-weight: bold;
      color: #fff;
      margin-top: 4px;
    }
    .timeline-box {
      background: #181b20;
      border: 1px solid #262930;
      border-radius: 8px;
      padding: 12px 14px;
    }
    .timeline-header {
      font-size: 11px;
      color: #888780;
      margin-bottom: 10px;
      font-weight: bold;
    }
    .timeline-item {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 13px;
      margin-bottom: 8px;
    }
    .timeline-dot {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      font-weight: bold;
    }
    .dot-done { background: #27500A; color: #97C459; }
    .dot-active { background: #185FA5; color: #fff; }
    .dot-pending { background: #262930; color: #888780; }
    .action-controls {
      margin-top: 20px;
      display: flex;
      gap: 10px;
      justify-content: center;
    }
    .btn {
      padding: 8px 16px;
      border-radius: 6px;
      border: 1px solid #378ADD;
      background: #185FA5;
      color: white;
      cursor: pointer;
      font-size: 13px;
    }
    .btn-approve { background: #BA7517; border-color: #EF9F27; }
  </style>
</head>
<body>
  <div class="hud-enclosure">
    <div class="hud-case-header">
      <div><span class="hud-led" id="led"></span>WORKBUDDY · LIVE DESKTOP HUD</div>
      <div>320x240 IPS · LIVE STREAM</div>
    </div>
    
    <div class="screen-bezel">
      <div class="top-bar">
        <div class="state-badge" id="state-badge">● RUNNING</div>
        <div class="time-thread">
          <div class="time-text" id="time-text">--:--:--</div>
          <div class="thread-text" id="thread-text">Workbuddy Main</div>
        </div>
      </div>

      <div class="alert-card" id="alert-card">
        <div class="alert-title" id="alert-title">正在处理任务...</div>
        <div class="alert-desc" id="alert-desc">Task: 状态监听与同步</div>
      </div>

      <div class="metrics-grid">
        <div class="metric-cell">
          <div class="metric-label">Step</div>
          <div class="metric-value" id="val-step">0/0</div>
        </div>
        <div class="metric-cell">
          <div class="metric-label">Tools</div>
          <div class="metric-value" id="val-tools">0</div>
        </div>
        <div class="metric-cell">
          <div class="metric-label">Time</div>
          <div class="metric-value" id="val-time">00:00</div>
        </div>
        <div class="metric-cell">
          <div class="metric-label">Tokens</div>
          <div class="metric-value" id="val-tokens">0k</div>
        </div>
      </div>

      <div class="timeline-box">
        <div class="timeline-header">TASK TIMELINE (实时任务时间线)</div>
        <div id="timeline-list"></div>
      </div>
    </div>

    <div class="action-controls">
      <button class="btn btn-approve" onclick="triggerApprove()">🎮 模拟硬件 Approve 按键</button>
      <button class="btn" onclick="fetchStatus()">🔄 立即刷新</button>
    </div>
  </div>

  <script>
    const STATE_COLORS = {
      'RUNNING': { bg: '#185FA5', led: '#378ADD', alertBg: 'rgba(55,138,221,0.15)', alertBorder: '#378ADD', alertTitle: '#85B7EB' },
      'NEED_ANSWER': { bg: '#534AB7', led: '#7F77DD', alertBg: 'rgba(127,119,221,0.2)', alertBorder: '#7F77DD', alertTitle: '#AFA9EC' },
      'NEED_APPROVAL': { bg: '#BA7517', led: '#EF9F27', alertBg: 'rgba(239,159,39,0.2)', alertBorder: '#EF9F27', alertTitle: '#FAC775' },
      'COMPLETED': { bg: '#3B6D11', led: '#639922', alertBg: 'rgba(99,153,34,0.18)', alertBorder: '#639922', alertTitle: '#97C459' },
      'ERROR': { bg: '#A32D2D', led: '#E24B4A', alertBg: 'rgba(226,75,74,0.2)', alertBorder: '#E24B4A', alertTitle: '#F09595' },
      'IDLE': { bg: '#5F5E5A', led: '#888780', alertBg: 'rgba(136,135,128,0.15)', alertBorder: '#888780', alertTitle: '#D3D1C7' }
    };

    async function fetchStatus() {
      try {
        const res = await fetch('/status');
        const data = await res.json();
        render(data);
      } catch (e) {
        console.error(e);
      }
    }

    function render(data) {
      const state = data.state || 'IDLE';
      const c = STATE_COLORS[state] || STATE_COLORS['IDLE'];

      const badge = document.getElementById('state-badge');
      badge.textContent = state;
      badge.style.background = c.bg;

      const led = document.getElementById('led');
      led.style.background = c.led;
      led.style.boxShadow = '0 0 8px ' + c.led;

      document.getElementById('time-text').textContent = data.time || '--:--:--';
      document.getElementById('thread-text').textContent = data.thread || 'Workbuddy Main';

      const card = document.getElementById('alert-card');
      card.style.background = c.alertBg;
      card.style.borderColor = c.alertBorder;

      const title = document.getElementById('alert-title');
      title.textContent = data.alert_title || '';
      title.style.color = c.alertTitle;

      document.getElementById('alert-desc').textContent = data.alert_desc || '';

      document.getElementById('val-step').textContent = data.step || '0/0';
      document.getElementById('val-tools').textContent = data.tools || '0';
      document.getElementById('val-time').textContent = data.duration || '00:00';
      document.getElementById('val-tokens').textContent = data.tokens || '0k';

      const tlBox = document.getElementById('timeline-list');
      tlBox.innerHTML = '';
      if (!data.timeline || data.timeline.length === 0) {
        tlBox.innerHTML = '<div style="color:#5F5E5A;font-size:12px;">◌ 工作台空闲就绪...</div>';
      } else {
        data.timeline.forEach(item => {
          const div = document.createElement('div');
          div.className = 'timeline-item';
          let dotCls = 'dot-pending';
          let dotTxt = '○';
          if (item.done) { dotCls = 'dot-done'; dotTxt = '✓'; }
          else if (item.active) { dotCls = 'dot-active'; dotTxt = '▶'; }

          div.innerHTML = `
            <div class="timeline-dot ${dotCls}">${dotTxt}</div>
            <div style="flex:1; color:${item.active ? '#fff' : '#B4B2A9'}">${item.text}</div>
            <div style="font-family:monospace; font-size:11px; color:#888780;">${item.dur || ''}</div>
          `;
          tlBox.appendChild(div);
        });
      }
    }

    async function triggerApprove() {
      alert("🎮 收到硬件 Approve 指令并已同步！");
    }

    setInterval(fetchStatus, 500);
    fetchStatus();
  </script>
</body>
</html>
"""

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class SimpleHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = get_current_status()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        elif self.path == "/" or self.path.startswith("/index"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(WEB_HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def main():
    server = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), SimpleHandler)
    print(f"HUD Web Server running on http://127.0.0.1:{HTTP_PORT}")
    server.serve_forever()

if __name__ == '__main__':
    main()
