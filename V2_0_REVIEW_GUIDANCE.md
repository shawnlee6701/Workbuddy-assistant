# Workbuddy 桌面状态机 V2.0 方案复审意见

复审结论：核心方向可保留，但 `WIFI_SCHEME_V2_0.md` 当前版本不能直接开工。请先只修订方案，不写代码、不烧录开发板。

请将原方案原地升级为“V2.0 开工前方案”，并在 `PROJECT_RECORD.md` 追加一条“方案经复审后补强，尚未实施”的记录。

## 必须修正

1. 明确现状边界
   - 当前 `daemon.py` 的 HTTP 仅监听 `127.0.0.1`。
   - 串口收到 BOOT/APPROVE 目前只写日志，并没有真实执行 Workbuddy 审批。
   - “WiFi 状态下行显示”列为 P0；“实体按键反向审批”列为 P1。
   - 在找到并验证受支持的 Workbuddy 本地审批接口前，不得宣称 Approve 已打通，也不得用 UI 自动点击冒充稳定接口。

2. 统一数据源与并发模型
   - daemon 内只维护一份不可变状态快照，由同一个 publish/fan-out 层分发到 Serial、WebSocket 和本地文件。
   - 使用锁或线程安全队列，避免现有 HTTP 线程、串口循环、WebSocket asyncio 并发改写全局状态。
   - HTTP Dashboard 继续只绑定 `127.0.0.1`；只有 UDP 5202 和 WebSocket 5201 绑定局域网接口。

3. 调整推流频率与承诺
   - 状态变化立即推送；时间与存活心跳 1 Hz 即可，不要固定 10 Hz 全量 JSON。
   - “小于 30 ms”只能写成局域网实测指标和验收目标，不能作无条件承诺。

4. 补齐协议契约
   - 所有帧至少包含：`protocol_version`、`type`、`device_id/server_id`、`session_id`、`seq`、`sent_at_ms`、`payload`。
   - 连接流程必须包含：`DISCOVER/OFFER -> WS CONNECT -> AUTH/HELLO -> FULL_SNAPSHOT -> ACK/PING/PONG`。
   - 板端按 `seq` 去重并拒绝旧帧，解决 USB 与 WiFi 同时到达时的乱序覆盖。
   - 规定最大帧尺寸、字段长度、timeline 上限、未知字段兼容和畸形帧处理。

5. 补齐安全边界
   - 公开仓库禁止把 SSID/Password 写入受版本控制的 `wifi_config.h`。
   - 默认使用 NVS 配网；若保留开发便捷模式，只允许被 `.gitignore` 排除的 `wifi_secrets.local.h`，并提供不含真实凭据的 example。
   - 配网 AP 不得常开或默认无密码；仅“无凭据首次启动”或物理长按触发，并限时关闭。
   - 凭据和配对令牌禁止写日志。
   - WebSocket 在接受状态或按键事件前，必须按已配对 `device_id` 加随机令牌鉴权。
   - 文档必须说明局域网明文链路的剩余风险。

6. 解决 BOOT 键职责冲突
   - 不得在按下瞬间发送 APPROVE。
   - 按“松开时判定时长”设计：短按仅在当前画面为 `NEED_APPROVAL` 且携带匹配的 `session_id + approval_id/challenge` 时发送；长按 5 秒进入配网并完全抑制本次短按。
   - 主机返回 `APPROVED/REJECTED/STALE` ACK，板端给出可见反馈；同一 `approval_id` 必须幂等。

7. 补发现、多主机与网络限制
   - OFFER 必须带 `server_id`、`protocol_version`、`host_name`。
   - 优先已配对 `server_id`，禁止无条件接受第一个响应。
   - 明确企业/访客 WiFi 的 AP isolation、macOS 防火墙、定向广播限制和开机自启动要求。
   - 提供 last-known host、mDNS 或手动 IP 的明确降级路径；不要保留“UDP 或 mDNS”这种未决表达。

8. 补状态机与重连
   - 至少区分：`WIFI_NO_CREDENTIALS`、`WIFI_CONNECTING`、`HOST_DISCOVERING`、`WS_AUTHENTICATING`、`ONLINE`、`DEGRADED_SERIAL`、`OFFLINE`。
   - 使用指数退避加 jitter；主机恢复后自动接收 `FULL_SNAPSHOT`。
   - 已有凭据但路由器临时不可用时，不得在 10 秒后自动暴露配网 AP。

9. 补工程清单
   - 明确 Python WebSocket 依赖及锁定版本、`requirements.txt` 更新、WiFi 管理模块、协议模块、配置存储模块和测试文件。
   - 当前 ArduinoJson 已是 7.0.4，不要重复写成待新增项。
   - “WiFiManager 第三方库”和“自研 WebServer/DNSServer”必须明确二选一，不得混写。

10. 重排里程碑与验收
   - 阶段 0：先验证真实 Workbuddy Approve 接口可行性。
   - 阶段 1：主机端发现、鉴权、WebSocket 下行。
   - 阶段 2：板端联网、发现、状态显示。
   - 阶段 3：真机 WiFi-only 验收。
   - 阶段 4：仅在审批接口可行后实施反向审批。
   - 真机验收必须包含：Mac 端 USB 数据线实际拔掉；开发板只由充电头或充电宝供电；屏幕可见状态变化；重启自动重连；主机休眠与恢复；路由器断开与恢复；错误令牌被拒绝；畸形或超大帧不崩溃；双通道乱序时旧 `seq` 不覆盖新状态。
   - 用日志和实物照片记录证据。构建成功或日志“已发送”不能代替实体屏幕验收。

11. 补回滚
   - 保留 v1.1.0 可重新烧录。
   - 增加 WiFi 功能开关。
   - 失败时能回退到纯串口，不破坏现有 HUD。

## 必须保留的核心方向

- UDP 自发现
- WebSocket 长连接
- NVS 凭据保存
- USB 串口兼容

## 交付要求

- 把以上内容改写为可以直接执行的 V2.0 方案。
- 文档结尾必须有明确的 Go/No-Go Checklist。
- 完成后只汇报修改了哪些文件，以及当前是否达到“可以开工”。
- 不要开始实现代码。
