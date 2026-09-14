# V2.0 终审补丁（仅修闭环，不扩大范围）

请只修改 `WIFI_SCHEME_V2_0.md` 与 `PROJECT_RECORD.md`，不要实现代码、不要编译、不要烧录。

## 1. P0 首次配对密钥交换必须闭环

当前方案说主机生成 `pairing_secret`，但没有定义如何把它安全交给开发板。不能把长期密钥直接通过明文 `ws://` 或 UDP 下发。

V2.0 P0 采用现有 USB 连接完成首次配对：

- 首次配对要求开发板通过 USB-CDC 连接本机；Dashboard 的两分钟配对窗口只作为本机用户确认入口。
- 主机生成至少 128-bit 随机 `pairing_secret`，通过 USB-CDC 一次性写入设备 NVS；设备回传只包含 `device_id` 与密钥指纹，不回传密钥原文。
- 主机将同一密钥存入 macOS Keychain，并记录 `device_id`、`server_id`、指纹与配对时间。
- 配对完成后才允许 WiFi `DISCOVER/OFFER/AUTH`。UDP 与 `ws://` 永远不传长期密钥。
- 增加“解除配对/重新配对”：Dashboard 本机操作删除 Keychain 记录，设备长按 BOOT 至少 10 秒清除 WiFi 与配对 NVS；两端任一缺失都进入 `UNPAIRED`/无凭据引导，不自动降级为无鉴权连接。
- 如果未来需要完全无线首次配对，另立版本评估 PAKE/TLS，不纳入 V2.0。

相应调整 BOOT 按键区间，避免与 5 秒配网冲突：短按 `<1.5s`；`1.5s~5s` 无动作提示；`5s~10s` 进入限时 WPA2 配网；`>=10s` 显示倒计时并清除 WiFi+配对信息。所有动作在 Key-Up 或倒计时确认后一次触发，不能在 Key-Down 时误报短按。

## 2. 补真实的实施与回滚章节

正文新增明确的阶段清单与每阶段 Gate：

1. Phase 0：只读验证现有 daemon 状态源、串口协议、实际路由；P1 Approve API 只探查、不接入 UI 自动化。Gate：证据记录完整。
2. Phase 1 Host P0：实现 StateDispatcher、UDP、WS、USB 配对、Keychain、依赖与本机 Dashboard 控制。Gate：主机单元/集成测试通过，5200 仍只绑定 loopback。
3. Phase 2 Firmware P0：实现 NVS、发现、HMAC、stream_id/seq、网络 FSM、按键 Key-Up、4096 字节边界。Gate：编译与协议注入测试通过。
4. Phase 3 真机验收：按表格 N>=10、拔 USB 数据线独立 5V、实物屏幕与日志共同验收。Gate：全部 P95/恢复/安全项通过。
5. Phase 4 P1：仅在受支持 Approve API 被验证后另行 GO；否则维持 NO-GO。

新增回滚步骤，不能只在终审表声称存在：

- 开工前创建当前可用基线 tag（若 `v1.1.0` 已存在，先核验它确实指向当前稳定基线，不得移动既有 tag）。
- WiFi 功能由 `ENABLE_WIFI_HUD` 默认关闭的编译开关隔离；关闭时保留 V1.1 USB 路径。
- Host 新服务失败：停用 5201/5202，仅保留 5200 与 USB 推流；Firmware 失败：刷回已验证基线构建产物/commit。
- 写清配置迁移策略：V2.0 新增 NVS namespace/version；回滚不得破坏 V1.1 启动，必要时只清理 V2.0 namespace。

## 3. 修正结论措辞

完成以上补丁后仍保持：

- P0：`GO for implementation`，不是“已经完成”或“已经验收”。
- P1：`NO-GO`。
- 文档版本可更新为 `V2.0-R3`。
