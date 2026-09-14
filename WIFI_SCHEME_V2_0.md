# Workbuddy 桌面状态机 V2.0 Wi-Fi 方案终审修订版（USB 配置，Wi-Fi 运行）

> **方案文档版本**：V2.0-R5 (Implementation Tracking)  
> **协议线版本 (Wire Protocol)**：2.0.0  
> **版本关系**：V1.1 是当前已实现的 USB 有线方案；V2.0 是本 Wi-Fi 升级方案。  
> **产品形态基准**：**配置阶段需要 USB 连接电脑；日常运行通过 Wi-Fi 无线工作**（状态源电脑在同一局域网运行 Host Daemon）。  
> **状态（2026-09-13）**：P0 下行推流的 Phase 0–2 已实施，Host/固件已测试、编译和烧录；Phase 3 等待用户本机输入 Wi-Fi 密码与纯无线实物验收。P1 实体审批仍为 `NO-GO`。  
> **R5 核心修订**：彻底取消板端 SoftAP / Web 配网与 WebServer / DNSServer 依赖；所有网络与配对配置收敛至本机 Dashboard (127.0.0.1:5200) 经 USB-CDC 传输；引入 pending/active 原子生效与回滚机制；BOOT 按键收敛为 3 区间；三级发现链第 3 级改为 USB 写入 Manual Host IP。

---

## 一、 产品边界与服务安全模型

### 1. 单一明确的产品边界
- **配置阶段（有线连接）**：首次设备配对、扫描并选择 2.4GHz Wi-Fi、输入/修改 Wi-Fi 密码、配置静态/手动 Host IP、解除配对及故障恢复，**一律将开发板通过 USB-CDC 连接电脑，在电脑本地 Dashboard (`http://127.0.0.1:5200`) 完成**。
- **日常运行阶段（完全无线）**：配置成功后，开发板**彻底拔除 USB 数据线，仅需接入独立 5V 电源（充电头/充电宝）**即可立在桌面任意位置，通过 2.4GHz Wi-Fi 接收同局域网内 Workbuddy 电脑端下推的状态与指标。
- **彻底废除 SoftAP**：固件**不开启任何无线热点（SoftAP）、不运行 WebServer 与 DNSServer**。无凭据或网络失效时，屏幕直接显示“请连接 USB 配置 Wi-Fi”，杜绝无线被动暴露与弱密码风险。

### 2. 服务端口与安全边界
- **本机 Dashboard 接口**：`daemon.py` 的 HTTP 路由（`/api/bridge`、`/api/dashboard`、`/api/status`、`/` 及 USB 配置接口）**严格仅绑定 `127.0.0.1`**。
- **局域网暴露端口**：仅 UDP 发现应答（Port 5202）与 WebSocket 推流（Port 5201）绑定 `0.0.0.0`。
- **网络信任域说明**：通信基于受控局域网明文 `ws://`，在家庭与私有受控网络中安全可用；不受信任的公共网络列为不支持。

---

## 二、 系统架构与并发线程模型

### 1. 架构拓扑图

```
+-----------------------------------------------------------------------------------------------+
| 💻 电脑端 (Workbuddy Host Daemon v2.0.0)                                                       |
|                                                                                               |
|  [ Workbuddy 核心感知引擎 ] (只读轮询 ~/.workbuddy-ai/workbuddy.db 与 traces)                   |
|                 │                                                                             |
|                 ▼                                                                             |
|  [ 统一状态分发层 StateDispatcher ] (单例不可变 StateSnapshot + threading.RLock + stream_id)   |
|        ├── 线程 1: UDP 局域网广播应答器 (Port 5202, 响应配对 OFFER, 发布公开信息与 Nonce)      |
|        ├── 线程 2: WebSocket asyncio 广播服务器 (Port 5201, 双向鉴权下推 + 按键接收队列)       |
|        ├── 线程 3: HTTP 本地服务 (Port 5200, 仅绑定 127.0.0.1 供设备/网络配置与仪表盘)        |
|        └── 线程 4: USB-CDC 串口通道 (配对密钥下发 + Wi-Fi 扫描配置协议 + 插入时双发推流)        |
+-----------------------------------------------┬-----------------------------------------------+
                                                │  WiFi 2.4GHz (WebSocket JSON)
                                                ▼
+-----------------------------------------------------------------------------------------------+
| 📟 桌面状态机硬件 (ESP32-S3 实战派, Firmware v2.0.0)                                           |
|                                                                                               |
|  [ 网络状态机 (Network FSM 7 状态 + 正交 pairing_status) ]                                    |
|     ├── WiFi 连接管理 (NVS 存储 / 指数退避+Jitter / USB pending-active 原子配置 / 引导屏)      |
|     ├── 三级发现链 (1. UDP 探针 -> 2. Last-Known Host IP -> 3. USB 写入 Manual Host IP)         |
|     └── WebSocket 客户端 (双向 HMAC 鉴权 -> stream_id 重置 -> seq 过滤 -> 4096B 守卫 -> 心跳)  |
|                 │                                                                             |
|                 ▼ (通过线程安全环形缓冲区投递有效 Payload)                                      |
|  [ 主业务与渲染引擎 ]                                                                         |
|     ├── LovyanGFX + ST7789 双缓冲驱动 (顶栏 4 格 RSSI 信号/IP/状态指示)                       |
|     └── BOOT 按键判定 (Key-Up：<1.5s 审批; 1.5–10s 提示连 USB; ≥10s NVS 清除重置)             |
+-----------------------------------------------------------------------------------------------+
```

---

## 三、 USB 配置工作流与原子生效机制

针对网络凭据与设备配对，采用全闭环的 USB-CDC 安全交互协议：

```
[用户本地浏览器 Dashboard]           [电脑 Host Daemon]                 [ESP32-S3 (USB-CDC 物理连接)]
       │                                     │                                     │
       │── 1. 点击「扫描 2.4G Wi-Fi」 ───────>│── 发送 WIFI_SCAN_REQUEST ─────────>│
       │                                     │<── 返回 WIFI_SCAN_RESULT ───────────│ (返回 SSID/RSSI/Auth)
       │<── 2. 展示 Wi-Fi 下拉列表 ──────────│                                     │ (不包含任何密码)
       │                                     │                                     │
       │── 3. 选择 SSID 并输入密码 ──────────>│                                     │
       │   (前端遮罩，不存本地缓存)          │── 发送 WIFI_CONFIG_SET ────────────>│ (包含 SSID/Password)
       │                                     │   (内存阅后即焚)                    │
       │                                     │                                     │── 1. 写入 pending 槽
       │                                     │                                     │── 2. 尝试连网与鉴权
       │                                     │                                     │
       │                                     │<── 返回 WIFI_CONFIG_OK ─────────────│── 3. 成功：提升为 active
       │                                     │   (或返回 WIFI_CONFIG_ERROR)        │   (失败：回退旧 active)
       │<── 4. Dashboard 提示配置成功 ───────│                                     │
```

### 1. 详细配置步骤与防护规范
1. **USB 扫描探测**：Dashboard 下发 `WIFI_SCAN_REQUEST`，开发板执行 2.4GHz 扫描并回传 `WIFI_SCAN_RESULT`（仅含 `ssid`, `rssi`, `auth_mode`），**不记录、不回传任何密码**。
2. **密码输入与内存安全**：Dashboard 密码输入框默认 `type="password"` 遮罩，禁止存入浏览器 LocalStorage；Host 经 USB 发送 `WIFI_CONFIG_SET` 后立即清空内存，**Host/串口全链路日志严格对密码字段脱敏（`***`）**。
3. **Pending / Active 双槽原子生效**：
   - 设备收到配置后先写入 `pending` NVS 槽，并尝试连接目标 Wi-Fi 与主机进行握手鉴权。
   - **连接成功**：设备回传 `WIFI_CONFIG_OK`，将 `pending` 原子提升为 `active`，清除 `pending`。
   - **连接失败（密码错误/SSID 不存在/5GHz 频段不支持/Host 不可达）**：设备回传 `WIFI_CONFIG_ERROR`（携带详细错误码），**丢弃 `pending` 并完整保留原有 `active` 配置**，彻底防止因输错密码导致设备在无线下永久失联。
4. **无凭据引导**：若 NVS 中无凭据，屏幕常驻提示：`"请连接 USB 配置 Wi-Fi"`。

### 2. USB 配置协议帧定义 (CDC Frames)

- **扫描请求 (Host -> Device)**：
  ```json
  {"type": "WIFI_SCAN_REQUEST", "seq": 1}
  ```
- **扫描结果 (Device -> Host)**：
  ```json
  {
    "type": "WIFI_SCAN_RESULT",
    "networks": [
      {"ssid": "Home-WiFi-2.4G", "rssi": -58, "auth": "WPA2_PSK"},
      {"ssid": "Work-Office-2.4G", "rssi": -72, "auth": "WPA2_PSK"}
    ]
  }
  ```
- **写入配置 (Host -> Device，脱敏传输)**：
  ```json
  {
    "type": "WIFI_CONFIG_SET",
    "ssid": "Home-WiFi-2.4G",
    "password": "my_secure_wifi_password",
    "manual_host_ip": "192.168.1.108"
  }
  ```
- **确认回执 (Device -> Host)**：
  ```json
  {"type": "WIFI_CONFIG_OK", "ip": "192.168.1.155", "rssi": -56}
  ```
- **错误回执 (Device -> Host)**：
  ```json
  {"type": "WIFI_CONFIG_ERROR", "code": "AUTH_FAIL", "message": "Password incorrect"}
  ```

---

## 四、 首次设备配对与双向挑战应答鉴权

1. **USB-CDC 密钥安全写入**：
   - 首次配对在 USB 连接时进行，用户在 Dashboard 点击「开启配对」。
   - 主机生成 ≥128-bit 强随机 `pairing_secret` 经 USB 下发给设备 NVS（namespace: `hud_v2_0`）。
   - 设备回传 `device_id` 与密钥指纹（SHA256 前 8 字节），**严禁回传密钥原文**；主机将密钥存入 macOS Keychain。
2. **双向挑战应答鉴权握手 (Wireless Connection)**：
   - 设备发 UDP DISCOVER -> 主机回 UDP OFFER（带 30s 一次性 nonce，不带 Token/http_port）。
   - 设备发 WS AUTH：`device_signature = HMAC_SHA256(pairing_secret, nonce + "|" + device_id + "|" + server_id + "|" + protocol_version)`。
   - 主机恒定时间校验后回传 WS AUTH_OK：`server_signature = HMAC_SHA256(pairing_secret, "AUTH_OK|" + nonce + "|" + device_id + "|" + server_id + "|" + protocol_version)`。
   - 设备在本地恒定时间校验 `server_signature` 后方可进入 `ONLINE` 状态并接收 `SNAPSHOT`。

---

## 五、 协议契约、4096B 守卫与重启解死锁

1. **统一数据帧头规范 (Base Frame Envelope)**：
   ```json
   {
     "protocol_version": "2.0.0",
     "type": "SNAPSHOT",
     "stream_id": "strm_1757750400_x9a2",
     "device_id": "esp32s3_hud_01",
     "server_id": "srv_shawn_mbp_a8c2",
     "session_id": "sess_89f310ab",
     "seq": 1042,
     "sent_at_ms": 1757750400120,
     "payload": {
       "state": "RUNNING",
       "thread": "Thread #04 · vibe-coding",
       "time": "16:00:01",
       "alert_title": "正在重构状态机核心总线",
       "alert_desc": "Task: 执行代码修改与单元测试",
       "step": "2/5",
       "tools": "8 次",
       "duration": "01:20",
       "session_tokens": "14.2k",
       "today_tokens": "128.5k",
       "model": "gemini-3.7-flash-high",
       "timeline": [ ... ]
     }
   }
   ```
2. **全链路 4096 UTF-8 字节守卫**：
   - **Host 发送端**：单帧严格 ≤ 4096 字节。
   - **串口接收**：`main.cpp` 中 `serialBuffer` 上限扩容至 4096 字节。
   - **WebSocket 回调**：在 `WStype_TEXT` 回调入口执行首行拦截：`if (length > 4096) { return; }`，超限直接丢弃。
   - **字段上限**：`alert_title` ≤ 64 字节，`alert_desc` ≤ 128 字节，`timeline` ≤ 5 项。
3. **`stream_id` 与重启解死锁**：
   - 主机重启生成新 `stream_id`；
   - 板端在通过鉴权后的首个权威 `SNAPSHOT` 帧中更新 `last_stream_id = stream_id` 并重置 `last_received_seq = seq`。同一连接内后续仅接收 `seq > last_received_seq` 的帧。

---

## 六、 三级发现链与网络状态机

### 1. 收敛后的三级 Host 发现链
1. **一级（UDP 局域网广播）**：向 `255.255.255.255:5202` 发送探针，匹配已配对 `server_id`。
2. **二级（Last-Known Host IP）**：若 5 秒未收到广播响应，尝试向 NVS 记忆的上次主机 IP 单播直连。
3. **三级（USB 配置的手动 Host IP）**：由电脑 Dashboard 经 USB 写入的 `manual_host_ip` 单播直连。

### 2. 网络状态机模型 (Network FSM - 7 状态)

```
                       ┌────────────────────────┐
                       │  WIFI_NO_CREDENTIALS   │ (提示"请连接 USB 配置 Wi-Fi")
                       └───────────┬────────────┘
                                   │ (USB 写入 Wi-Fi 凭据)
                                   ▼
┌─────────────────┐    ┌────────────────────────┐    ┌────────────────────────┐
│     OFFLINE     │◄───┤    WIFI_CONNECTING     ├───>│    HOST_DISCOVERING    │
│ (附带 .reason)   │    └────────────────────────┘    └───────────┬────────────┘
└────────┬────────┘                ▲                              │ (收到有效 OFFER)
         │                         │ (WiFi 掉线)                   ▼
         │ (指数退避+Jitter)         │                        ┌────────────────────────┐
         └─────────────────────────┴───────────────────────  │   WS_AUTHENTICATING    │
                                                              └───────────┬────────────┘
                                                                          │ (双向 AUTH 成功)
                                                                          ▼
┌─────────────────┐                                           ┌────────────────────────┐
│ DEGRADED_SERIAL │ (有线插入时双向通信)                         │      ONLINE (WiFi)     │
└─────────────────┘                                           └────────────────────────┘
```

- **重连退避**：按 `1s -> 2s -> 4s -> 8s -> 16s -> 最大 30s` 指数退避，叠加 `±500ms` 随机 Jitter，**绝对不开启任何 SoftAP**。

### 3. BOOT 按键 3 阶段解耦 (Key-Up 判定)

```
0s ----------------- 1.5s ---------------------------------- 10.0s -----------> (按压时间)
│   [阶段 1: 短按]     │          [阶段 2: 提示区间]             │  [阶段 3: 硬重置]
│   < 1.5s            │          1.5–10.0s                      │  ≥ 10.0s
│   仅在 NEED_APPROVAL│          松开静默返回；                 │  屏幕倒计时 3s 后
│   时发送审批请求    │          按住超 1.5s 提示"连接 USB 配置"│  清除 Wi-Fi 与配对 NVS
```

---

## 七、 依赖精确锁定与工程闭环

### 1. 电脑端依赖 (`host_bridge/requirements.txt`)
```text
pyserial==3.5
websockets==15.0.1
```

### 2. 固件依赖 (`firmware/platformio.ini`)
```ini
lib_deps = 
    lovyan03/LovyanGFX @ ^1.1.16
    bblanchon/ArduinoJson @ 7.0.4
    links2004/WebSockets @ 2.4.1
```
*(仅使用 ESP32-Arduino 原生 `WiFi` 与 `Preferences` 库；**彻底移除 `WebServer` 与 `DNSServer` 依赖**。)*

---

## 八、 实施阶段与可测量验收指标 (Phase 0–3)

### 1. 实施阶段分工与 Gate
- **Phase 0（现状核对与 API 探查）**：只读验证现有状态源、串口协议与路由；探查 Approve 机制（严禁接入 UI 自动化）。Gate 0：记录完整。
- **Phase 1（Host P0 实现）**：实现 StateDispatcher、UDP 5202、WS 5201、USB 配置及配对协议、Keychain 存储与 127.0.0.1 Dashboard 页面。Gate 1：单测与集成测试 100% PASS。
- **Phase 2（Firmware P0 实现）**：实现 NVS namespace、USB 配置解析器、pending-active 原子切换、UDP 发现、双向 HMAC 握手、7 状态 FSM、按键 3 阶段与 4096B 守卫。Gate 2：编译通过且模拟协议注入 100% PASS。
- **Phase 3（纯无线真机全场景综合验收）**：拔掉 USB 数据线、独立 5V 供电，执行 N≥10 轮压测。Gate 3：全部 P95 指标达标，产出实物照片与日志证据。
- **Phase 4（P1 实体按键审批）**：仅在 Phase 0 验证受支持的稳定接口后另行评估；否则维持挂起。

### 1.1 当前执行状态（2026-09-13）

| Phase | 状态 | 当前证据 |
| :--- | :---: | :--- |
| Phase 0 | ✅ 完成 | V1.1 回滚 Tag `v1.1.0` 已创建；现有状态源、USB 协议与 Approve 边界已核对。 |
| Phase 1 | ✅ 完成 | Host UDP/WS/USB/Keychain/Dashboard 已实现；V2 单测 11/11、集成/压力测试 36/36 通过。 |
| Phase 2 | ✅ 完成 | ESP32-S3 固件编译成功、已烧录并完成真机 USB 配对与 2.4GHz 扫描；扫描链路修复后真机 12/12 轮均命中目标 SSID，新增串口 JSON 解析错误为 0。 |
| Phase 3 | ⏳ 待用户操作 | 需在已打开的本机 Dashboard 输入 Wi-Fi 密码，再拔除 USB、独立 5V 供电完成无线连接、屏幕像素与 N≥10 压测验收。 |
| Phase 4 | ⛔ NO-GO | 未发现受官方支持的 Workbuddy Approve 稳定接口，不使用 UI 自动化替代。 |

### 2. 真实验收指标与用例 (Phase 3 Gate, N ≥ 10)

| 验收项目 | 验收标准 / 硬门槛 | 容忍度 |
| :--- | :--- | :---: |
| **USB 配置正确生效** | Dashboard 选择 2.4G Wi-Fi 输对密码，原子生效并回传 `WIFI_CONFIG_OK` | 100% 成功 |
| **错误密码保护机制** | 输入错误密码回传 `WIFI_CONFIG_ERROR`，保留原 active 配置不失联 | 100% 防护 |
| **5GHz 频段拒绝提示** | 扫描或配置 5GHz-only 网络时给出明确“仅支持 2.4GHz”错误提示 | 100% 提示 |
| **日志脱敏核验** | Host 与固件串口日志中 Wi-Fi 密码与 Token 100% 脱敏（`***`） | 0 泄露 |
| **冷启动至 ONLINE (无线)** | 拔除 USB 独立 5V 供电冷启动，**P95 ≤ 15 秒**（P50 ≤ 8 秒） | 0 失败 |
| **Mac 唤醒 / 重启后恢复** | Mac 唤醒或 daemon 重启，**P95 ≤ 15 秒**（P50 ≤ 6 秒） | 0 失败 |
| **稳态状态突变推流** | 状态机切换到屏幕渲染，**P95 ≤ 100 ms**（P50 ≤ 40 ms） | 0 失败 |
| **路由器断开与恢复** | 路由器断电持续退避重试（不暴露 AP），通电后自动重连 | 100% 恢复 |
| **双通道乱序防覆盖** | USB 与 WiFi 并发乱序注入，旧 seq 帧 100% 被过滤 | 100% 过滤 |
| **交付证据要求** | 必须提供完整运行日志 + **拔除 USB 数据线、独立 5V 供电真机工作实物照片** | 必备 |

---

## 九、 回滚预案与配置隔离 (Rollback Plan)

1. **基线保护与宏开关**：V1.1 稳定基线 Tag `v1.1.0` 已创建和验证；V2.0 执行分支当前以 `ENABLE_WIFI_HUD=1` 编译，回滚时可切回 V1.1 Tag 或关闭该宏。
2. **NVS 配置隔离**：所有 V2.0 配置独占 namespace `"hud_v2_0"`，回滚时完全不影响 V1.1 启动；重置时仅清理该 namespace。

---

## 十、 方案终审 Go / No-Go 判定结论

| 评估维度 | 核心核查内容 | R5 判定 |
| :--- | :--- | :---: |
| **产品边界清晰** | 是否明确配置必须连 USB，日常运行彻底无线，且完全废除 SoftAP？ | ✅ 符合 |
| **USB 配置原子性** | 是否具备 pending-active 双槽机制，输错密码不覆盖可用配置？ | ✅ 符合 |
| **依赖完全闭合** | 是否彻底移除 WebServer 与 DNSServer，仅保留必要原生库？ | ✅ 符合 |
| **按键逻辑收敛** | 是否收敛为 3 区间（<1.5s, 1.5–10s, ≥10s），彻底删除 5–10s AP 行为？ | ✅ 符合 |
| **双向挑战鉴权** | 是否采用 HMAC-SHA256 双向挑战应答，30s Nonce 一次性销毁？ | ✅ 符合 |
| **4096B 入口守卫** | 是否在 WStype_TEXT 首行执行 `length > 4096` 拦截？ | ✅ 符合 |
| **验收指标完备** | 是否包含错误密码不失联、日志脱敏、独立 5V 供电 7 大真机压测？ | ✅ 符合 |

### 🚀 终审结论：
- **P0 阶段（WiFi 状态下行显示与 USB 配置）**：**Phase 0–2 已完成；Phase 3 待验收**。代码、编译、烧录、USB 配对和扫描已完成；只有在本机输入真实 Wi-Fi 密码、拔除 USB 并完成实物验收后，才能宣布 P0 全面 GO。
- **P1 阶段（实体按键真实审批）**：**`NO-GO`**（保持挂起，等待 Phase 0 找到并验证受官方支持的 Workbuddy 本地 Approve 稳定接口）。
