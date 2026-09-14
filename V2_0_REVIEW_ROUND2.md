# Workbuddy V2.0 方案二审修正

二审结论：第一轮已补齐大框架，但仍有实现级矛盾，不能写“全部符合”。请继续只修订方案，不写代码、不烧录。

## 1. 修正现有事实

- 当前 `daemon.py` 只有 `/api/bridge`、`/api/dashboard`、`/api/status` 和 `/`，不要写不存在的 `/api/snapshot`、`/api/traces/today`。
- `OFFER` 不要携带或宣称携带 Token；它只能提供可公开的服务信息和一次性 nonce。
- HTTP 5200 既然只绑定 `127.0.0.1`，就不应在给板端的 OFFER 中发布 `http_port`。

## 2. 把鉴权写成可实现且不可直接重放的流程

- 不得发送 `pre_shared_secret` 或固定 `sha256(secret)`。
- AUTH 使用 `HMAC-SHA256(pairing_secret, nonce | device_id | server_id | protocol_version)`；只发送 HMAC 摘要。
- nonce 必须一次性、30 秒过期，服务端使用恒定时间比较并拒绝重复 nonce。
- 明确首次配对生命周期：主机本地 Dashboard 开启 2 分钟配对窗口并生成一次性配对码；设备在物理配网模式提交配对码；主机生成至少 128-bit 随机 `pairing_secret`，主机存 macOS Keychain，设备存 NVS。日志不得出现配对码、secret 或 HMAC 原文。
- 明确 `ws://` 仍不能防止同广播域被动嗅探状态内容；不受信任网络列为不支持，不能写“安全可用”。

## 3. 修正 seq 在服务重启后的死锁

- 增加随机 `stream_id/server_boot_id`。主机 daemon 每次启动生成新值。
- `seq` 只在同一 `stream_id` 内单调递增。
- 板端在已鉴权的 `FULL_SNAPSHOT` 带新 `stream_id` 时重置 `last_received_seq`；否则主机重启后从 0 开始会被板端永久当成旧帧。
- USB 与 WiFi 必须由同一个 dispatcher 发送完全一致的 `stream_id + seq`。

## 4. 修正协议与缓冲限制

- 4096 的单位写成 UTF-8 字节，不是“字符”。字段上限也明确按 UTF-8 字节或 Unicode code point 计算，二选一并全链路一致。
- 当前串口缓冲上限是 2048；若协议上限为 4096，工程清单必须明确同步修改串口缓冲、WebSocket 分片重组与内存预算，不能只改文档数字。
- `sent_at_ms` 由主机提供 Unix epoch；设备未校时前的上行事件使用 `device_uptime_ms`，不得把伪 epoch 当安全判断依据。

## 5. 收敛发现机制和依赖

- V2.0 P0 采用明确的三级顺序：UDP 广播 -> Last-Known Host IP -> 配网页面手动 IP。
- 本版移除 mDNS，避免引入但未列出的 host `zeroconf` 与 firmware `ESPmDNS` 依赖；后续版本再评估。
- 补充 macOS 防火墙放行 UDP 5202 / TCP 5201 的实测步骤，以及 daemon 登录自启动后的端口存活检查。
- Python 依赖既然写“精确锁定”，就使用 `pyserial==3.5`，不要写 `>=`。

## 6. 修正状态机和按键空档

- 文档称 7 个状态，但图中实际有 8 个。统一为 7 个：`WIFI_NO_CREDENTIALS`、`WIFI_CONNECTING`、`HOST_DISCOVERING`、`WS_AUTHENTICATING`、`ONLINE`、`DEGRADED_SERIAL`、`OFFLINE`；断开原因放在 `OFFLINE.reason`，移除独立 `WS_DISCONNECTED`。
- 明确 `1.5s <= 按下时长 < 5s` 为无动作区间，松开后不审批、不配网，并提示“继续长按进入配网”或静默返回。

## 7. 修正互相矛盾的验收时间

- 现有最大 30 秒指数退避与“冷启动 3 秒、Mac 唤醒 2 秒”冲突。
- 改为可测量且现实的门槛：受控家庭 LAN 下，冷启动至 ONLINE `P95 <= 15s`；Mac 唤醒或 daemon 重启后恢复 `P95 <= 15s`；已连接时状态变更到屏幕渲染 `P95 <= 100ms`，同时记录中位数，`<30ms` 只保留为优化目标。
- 每项至少测 10 次，记录样本、P50、P95、失败次数。不要写“0 延迟”“瞬间”“无缝”这类不可验证词。

## 8. 修正 Go / No-Go 结论

- 不得把“文档里写了设计”标成实现已经符合。
- 最终结论必须拆开：
  - `P0 WiFi 下行显示：GO（方案可开工，尚未实施/未验收）`。
  - `P1 实体按键真实审批：NO-GO（等待阶段 0 找到并验证受支持的 Workbuddy Approve 接口）`。
- Checklist 增加“事实核对”“鉴权不可重放”“stream_id 重启恢复”“依赖闭合”“性能指标无矛盾”五项。
- `PROJECT_RECORD.md` 同步更正为上述分拆结论，不得继续写“方案完全满足、整体可开工”。

完成后仅汇报方案与项目记录的修改结果，不实施代码。
