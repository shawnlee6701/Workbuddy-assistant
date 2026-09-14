# V2.0 配置边界修订：USB 配置，Wi-Fi 运行

用户确认：Wi-Fi 连接、SSID/密码输入等配置动作仍然需要把开发板连接电脑完成。请只修订 `WIFI_SCHEME_V2_0.md` 与 `PROJECT_RECORD.md`，不要写实现代码、不要编译、不要烧录。

## 产品边界定版

V2.0 采用以下单一路线：

- **配置阶段需要 USB 连接电脑**：首次设备配对、选择 Wi-Fi、输入/修改 Wi-Fi 密码、修改手动 Host IP、解除配对和故障恢复，都通过 `http://127.0.0.1:5200` 本机 Dashboard 操作，并经 USB-CDC 传给开发板。
- **日常运行不需要 USB 数据连接**：配置成功后，开发板可以只接独立 5V 电源，通过 2.4GHz Wi-Fi 接收状态；但作为状态源的 Mac/电脑必须在同一局域网运行 Workbuddy Host Daemon。
- **彻底取消开发板 SoftAP/Web 配网**：删除 WPA2 AP、随机 AP 密码、`192.168.4.1`、`WebServer`、`DNSServer`、5–10 秒进入 AP 等设计。不要保留双路线。

## USB 配置工作流

1. 用户通过 USB-CDC 连接开发板，打开本机 Dashboard 的“设备与网络设置”。
2. Dashboard 请求开发板扫描 2.4GHz SSID；开发板通过 USB 返回 SSID、RSSI、加密类型，不返回或记录任何密码。
3. 用户在电脑 Dashboard 选择 SSID、输入密码；输入框默认遮罩且不写浏览器持久存储、不进入日志。
4. Host 通过 USB 一次性发送 `WIFI_CONFIG_SET`。设备先写入 `pending` 配置槽并尝试连接，不立即覆盖当前可用配置。
5. 连接成功且能完成已配对 Host 的双向鉴权后，设备回传 `WIFI_CONFIG_OK`，再将 `pending` 原子提升为 `active`；Host 立即清除内存中的密码。
6. 连接失败则回传明确错误（SSID 不存在、密码错误、只支持 2.4GHz、Host 不可达等），删除 `pending`，保留旧的 `active` 配置，避免输错密码导致设备失联。
7. 无凭据或配置失效时，屏幕显示“请连接 USB 配置 Wi-Fi”，不得自行开放热点。

## 协议与按键同步修订

- 新增 USB 配置帧：`WIFI_SCAN_REQUEST`、`WIFI_SCAN_RESULT`、`WIFI_CONFIG_SET`、`WIFI_CONFIG_OK`、`WIFI_CONFIG_ERROR`；敏感字段仅允许出现在 Host -> Device 的 USB 配置帧，日志必须按字段脱敏。
- 三级 Host 发现链改为：UDP 广播 -> Last-Known Host IP -> 由电脑 Dashboard 经 USB 写入 Manual Host IP。删除“板端 Web 配网页填写 IP”。
- BOOT 只保留三个区间：`<1.5s` 短按（P1 仍为 NO-GO）；`1.5–10s` 无动作并提示“连接 USB 配置”；`>=10s` 屏幕倒计时确认后清除 V2.0 Wi-Fi/配对 NVS。取消 5–10 秒 AP 行为。
- 固件依赖只保留实际需要的 `WiFi`、`Preferences`、`WebSockets` 等；删除 `WebServer`、`DNSServer`。

## 验收补充

- 配置验收必须覆盖：正确密码成功、错误密码不覆盖旧配置、5GHz-only SSID 给出明确提示、密码不出现在 Host/串口日志、拔 USB 后独立 5V 自动恢复无线运行。
- 文档标题升级为 `V2.0-R5`；结论保持 P0 `GO for implementation`（尚未实施/验收），P1 `NO-GO`。
