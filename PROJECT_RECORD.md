# Workbuddy 桌面状态机开发档案与工作记录

更新时间：2026-09-12 19:22

---

## 一、 项目背景与目标
为 Workbuddy 打造一款物理桌面级状态监控器（HUD 提示器），利用 **立创·实战派 ESP32-S3 开发板**，通过 USB 串口或 Wi-Fi 实时展示当前 Workbuddy Agent 的执行进度、任务时间线、核心指标数据，并在需要人类介入（提问/审批/报错）时提供高亮视觉聚焦与实体按键反向操作。

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
