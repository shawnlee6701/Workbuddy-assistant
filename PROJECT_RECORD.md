# Workbuddy 桌面状态机开发档案与工作记录

更新时间：2026-09-13

---

## 一、 项目背景与目标
为 Workbuddy 打造一款物理桌面级状态监控器（HUD 提示器），利用 **立创·实战派 ESP32-S3 开发板**，通过 USB 串口或 Wi-Fi 实时展示当前 Workbuddy Agent 的执行进度、任务时间线、核心指标数据，并在需要人类介入（提问/审批/报错）时提供高亮视觉聚焦与实体按键反向操作。

### 版本命名

- **V1.1（现有方案）**：当前已经实现的 USB-CDC 有线状态推流、实体 HUD 与本机 Dashboard。
- **V2.0（Wi-Fi 方案）**：配置阶段仍通过 USB 连接电脑，配置成功后的日常状态推流改用 Wi-Fi。Phase 0–2 已实施、编译、烧录和通过主机/串口测试；Phase 3 等待用户本机输入 Wi-Fi 密码及拔除 USB 后的实物验收。

---

## 二、 硬件配置与引脚映射规范（立创·实战派 ESP32-S3）

- **主控芯片**：ESP32-S3-WROOM-1-N16R8（16MB Flash, 8MB Octal PSRAM）
- **显示屏**：2.0 寸 IPS 液晶屏，驱动芯片 ST7789，分辨率 320 × 240（横屏）
- **IO 扩展芯片**：PCA9557（I2C 地址 0x19 / 0x18）
  - `IO0`：`LCD_CS` 液晶屏片选（低电平选通使能）
  - `IO1`：`PA_EN` 音频功放使能（高电平开启）
  - `IO2`：`DVP_PWDN` 摄像头掉电控制（高电平关闭）
- **屏幕 SPI 引脚**：
  - `SCLK`：`GPIO 41`
  - `MOSI`：`GPIO 40`
  - `DC`：`GPIO 39`
  - `Backlight (BL)`：`GPIO 42`（低电平点亮）
- **I2C 引脚**：`SDA: GPIO 1`, `SCL: GPIO 2`
- **用户按键**：`BOOT: GPIO 0`（低电平按下，用于硬件一键 Approve）

---

## 三、 系统架构与模块分工

```
[ Workbuddy PC 端 ]
       │
       ▼ (串口推流 JSON 帧 @ 115200 bps)
[ host_bridge/bridge.py ]  <---- 自动端口扫描、仿真流转、按键回传捕获
       │
       ▼ USB Type-C (CH340K / USB-CDC)
[ 立创 ESP32-S3 开发板 (firmware/) ]
  ├── bsp_board: I2C 探测 + PCA9557 片选常开 + GPIO42 背光控制
  ├── display_hud: LovyanGFX + 8MB PSRAM 320x240 全屏双缓冲
  └── main: ArduinoJson 协议解析 + 状态分发 + 按键事件回传
```

---

## 四、 状态机协议定义 (JSON 帧格式)

```json
{
  "state": "RUNNING", // 状态枚举: IDLE | RUNNING | NEED_ANSWER | NEED_APPROVAL | COMPLETED | ERROR
  "thread": "Thread #04 · vibe-coding",
  "time": "18:35:00",
  "alert_title": "正在重构状态机核心总线",
  "alert_desc": "Task: 执行代码修改与单元测试",
  "step": "2/5",
  "tools": "8 次",
  "duration": "01:20",
  "tokens": "12.3k",
  "model": "gemini-3.7-flash-high", // 可选；取不到时不显示
  "timeline": [
    {"text": "分析项目代码架构", "dur": "0.6s", "done": true, "active": false},
    {"text": "编写状态监听模块", "dur": "1.2s", "done": true, "active": false},
    {"text": "重构状态机核心总线", "dur": "进行中", "done": false, "active": true}
  ]
}
```

---

## 五、 当前工作进展与调试记录

### 2026-09-12 显示修复实测补充

- 用户已目视确认底层 `esp_lcd` 纯色色带正常显示，硬件屏幕、背光、SPI 与 ST7789 可用。
- 原 LovyanGFX 物理输出层已绕过：LovyanGFX 保留为 PSRAM 离屏画布，最终画面交给已验证的 `esp_lcd` 驱动输出。
- HUD 固件已重新烧录并成功解析 `RUNNING / HUD ONLINE` 测试帧。
- `live_bridge.py` 已改为只读查询 `~/.workbuddy-ai/workbuddy.db` 的真实 session 状态，并以后台模式推送至 USB 串口。
- 实测桥接 API 返回 `RUNNING / Workbuddy Live`，后台进程已连接 `/dev/tty.usbmodem1301`。
- 2026-09-12：屏幕界面已中文化（状态、引导页、指标标签、任务进度和提示语），中文固件已编译并烧录成功，实时桥接已恢复。
- 2026-09-12：根据用户提供的实物参考图重做 HUD：纯黑背景、顶部品牌/时间/在线点、大号中文状态、青绿强调线、单行同步信息及底部当前任务。新固件已烧录。
- 2026-09-12：修复 HUD 任务未实时更新问题。将 `daemon.py` 升级为系统级自动感知中继（Auto-Sensor Live Engine），直接对接 Workbuddy 系统数据库与 Traces，无需手动写文件即可自动同步当前会话名称、运行状态、工具调用动态与时长，板端实时回执确认正常。
- 2026-09-13：HUB 新增任务完成 Token 凭据。守护进程按当前 `sessionId` 精确匹配最新 Workbuddy Trace，仅提取总 Token、输入、输出、缓存命中与模型调用数，不读取 Prompt 或模型输出；完成后在 Bridge HUB 显示可核对的本轮用量。
- 2026-09-13：HUB 实时概览新增「今日 Token」卡片，统计当地日期内全部带 `sessionId` 的 Agent Trace，同时返回会话数、Trace 数、输入、输出、缓存命中与模型调用数。
- 2026-09-13：修复开发版 HUB 通过 `file://` 直接打开时长期停在「连接中」的问题。`bridge_dashboard.html` 会根据页面协议选择 API：开发版连接 `http://127.0.0.1:5200/api/bridge`，HTTP 正式入口保持同源 `/api/bridge`。
- 2026-09-13：修复实体开发板 HUD 未显示 Token 的问题。固件原先只解析 `tokens` 但未绘制；现在指标栏在有真实用量时优先显示绿色 `TOKEN <count>`，无用量时保留原「同步」状态，串口回执同步输出 token 值便于核验。
- 2026-09-13：状态协议新增可选 `model` 字段。守护进程从当前 Workbuddy 会话读取并清理模型名称，实体 HUD 顶栏和 Bridge Monitor 仅在字段有值时显示当前模型。
- 2026-09-14：正式发布 **V2.0**（Git Tag `v2.0.0`）。Wi-Fi 自动连接与秒级断电重连闭环完成：真机实测断电重启 2 秒内自动接入 2.4GHz Wi-Fi 并完成 WebSocket 握手，持续稳定推流；全套 19 项单元测试与 36 项接口压力测试 100% 通过。
- 2026-09-14：实测发现 Mac 重启后 V2.0 配对数据未丢失，实际故障为 Bridge 守护进程没有登录自启。新增 `com.workbuddy.desktop-hud-v2` LaunchAgent 及安装脚本，将最小运行副本与 Host 身份迁移到 `~/Library/Application Support/Workbuddy Desktop HUD` 以绕开 `Documents` 的 macOS TCC 后台访问限制；同时收紧启停脚本的 PID 归属检查，避免误杀无关进程。
- 2026-09-14：进一步复现 Mac 端恢复后的鉴权风暴：`arduinoWebSockets` 把 `setReconnectInterval(0)` 解释为零延迟重连，固件因此在 Host 重启后不断复用已消费 nonce。修改为 WebSocket 断开后禁用库级自动重连，清空 nonce 并回到 UDP discovery 取得新 OFFER；Host 端鉴权失败日志同时增加 5 秒限流。
- 2026-09-14：第一次烧录后又暴露 DHCP 变更边界：Mac 由 `192.168.8.13` 变为 `192.168.8.180`，开发板在启动前 5 秒错过广播后，会永久只试旧 `last_host`/手动 Host IP。发现调度改为持续循环“广播→上次 Host→广播→手动 Host”，旧 IP 仅做加速提示，不再阻断新 Host 发现。
- 2026-09-13：将当前已实现的 USB 有线方案正式命名为 **V1.1**；将规划中的 Wi-Fi 无线通信方案正式命名为 **V2.0**。
- 2026-09-13：制定并固化 **V2.0 Wi-Fi 无线通信落地方案**（详见 `WIFI_SCHEME_V2_0.md`），确立局域网 UDP 探针广播自发现（5202 端口）+ WebSocket 实时推流与反向按键长连接（5201 端口）+ USB 配置 / NVS 凭据记忆 + USB 串口兼容体系。
- 2026-09-13：根据 `V2_0_REVIEW_ROUND5.md` 用户确认的产品边界修订意见，完成方案终修订，形成 **V2.0-R5 终审版**（见 `WIFI_SCHEME_V2_0.md`）：
  - **产品形态定版**：**配置阶段需要 USB 连接电脑；日常运行彻底无线**（插 5V 独立电源，同 LAN 下接收电脑 Host Daemon 推流）；
  - **彻底废除 SoftAP**：删除 WPA2 AP、随机 AP 密码、`192.168.4.1`、`WebServer`、`DNSServer` 依赖与 5–10 秒 AP 行为，无凭据时屏幕直接提示“请连接 USB 配置 Wi-Fi”；
  - **USB-CDC 配置与原子生效**：定义 `WIFI_SCAN_REQUEST/RESULT`、`WIFI_CONFIG_SET/OK/ERROR` 协议，采用 `pending` -> `active` 原子生效机制，输错密码回退旧配置不失联，全链路密码严格脱敏；
  - **按键与发现收敛**：BOOT 键收敛为 3 区间（<1.5s 审批，1.5–10s 提示连 USB，≥10s 倒计时清除 NVS 重置）；三级发现链第 3 级改为 USB 写入 Manual Host IP；
  - **终审开工判定**：P0 阶段（WiFi 状态下行显示与 USB 配置工作流）判定为 **`GO for implementation`**；P1 阶段（实体按键真实审批）维持 **`NO-GO`**。
- 2026-09-13：开始并完成 **V2.0 Phase 0–2 实施**：
  - 创建并验证 V1.1 回滚基线 Tag `v1.1.0`；
  - Host 实现 UDP 5202 发现、WebSocket 5201 鉴权推流、USB 请求回执、Keychain 配对密钥、Dashboard 配网 API 与递归脱敏；
  - Firmware 实现 `hud_v2_0` NVS、pending/active 原子配置、Wi-Fi FSM、UDP/WebSocket/HMAC、stream/seq 防旧帧、4096B 守卫、网络 HUD 与 BOOT 三阶段重置；
  - 固件已编译并烧录到真机，完成 USB 安全配对和 2.4GHz 扫描，已过滤隐藏 SSID；
  - V2 协议单测 11/11、主机集成/压力测试 36/36 通过；串口状态帧增加字段白名单、UTF-8 限长和 400ms 合并发送，复验新增日志中 JSON 解析错误为 0；
  - 修复扫描期间固件阻塞导致 HUD 帧填满串口缓存、单轮扫描间歇漏检网络的问题：Host 在独占 USB 命令期间暂停状态帧并仅补发最新帧；固件改为非阻塞被动扫描、两轮合并去重、明确设置 SG 国家码；Dashboard 增加手动 SSID 兜底。烧录后真机 12/12 轮均扫到目标网络（RSSI -52～-58 dBm），新增传输错误 0，全量回归 36/36 通过；
  - 未将编译、烧录或串口回执当作屏幕像素验收。Phase 3 必须在用户本机输入 Wi-Fi 密码后，拔除 USB、独立 5V 供电并由用户目视确认。
- SPI 模式由 0 调整为官方例程使用的 2；IO 扩展先写输出默认值再设置输出方向。
- 增加 LCD 初始化、画布分配失败检查和中文字体；启动显示红绿蓝测试色。
- 固件重新编译、烧录成功，烧录器完成 Hash 校验。
- 串口实际回执：`[HUD] Screen rendered -> State: IDLE, Title: 屏幕连接测试`。
- 当前 `bridge.py` 仍为模拟演示；真实状态使用 `live_bridge.py`。
- 为烧录已停止旧演示进程，当前保留静态连接测试画面。
- 下方早期记录中的烧录成功不应视为屏幕点亮验收。

1. **固件编译与烧录**：
   - 采用 PlatformIO + Arduino 框架，成功配置 16MB Flash 与 PSRAM 编译选项。
   - 依赖项：`LovyanGFX`（高速渲染）+ `ArduinoJson`。
   - 首次烧录已 100% 成功。
2. **电脑端推流**：
   - 安装并验证了 `pyserial`，编写了 `host_bridge/bridge.py`。
   - 成功在 `/dev/tty.usbmodem1301` 与开发板建立连接并推送多状态数据帧。
3. **屏幕点亮与显示优化**：
   - 针对实战派板子的硬件特性，强化了 `GPIO 42` 背光低电平拉低逻辑。
   - 在 `bsp_board.cpp` 中加入了 I2C 自动寻址与 PCA9557 强制将 `LCD_CS (IO0)` 置低。
   - 固件与推流脚本均已持久化保存至工作区目录。
