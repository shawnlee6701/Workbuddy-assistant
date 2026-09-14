# V2.0 代码级可实现性最终勘误

只修订 `WIFI_SCHEME_V2_0.md` 与 `PROJECT_RECORD.md`。不要写实现代码、不要编译、不要烧录。

1. **删除不存在的 WebSocket API**：`links2004/WebSockets 2.4.1` 的 `WebSocketsClient` 没有 `setPayloadSize()`。不要写 `webSocket.setPayloadSize(4096)`。改成：库在 ESP32 上由 `WEBSOCKETS_MAX_DATA_SIZE` 提供更大的接收上限；本项目在 `WStype_TEXT`/分片重组完成的回调入口先检查 `length <= 4096`，超限立即拒绝且不进入 JSON 解析。Host 必须禁止超过 4096 字节的业务帧。Phase 2 用实际依赖版本编译验证。
2. **统一帧类型**：全文不要同时出现 `SNAPSHOT` 与 `FULL_SNAPSHOT`。统一使用 `SNAPSHOT`；AUTH 成功后的第一帧必须是权威 `SNAPSHOT`。仅在已经通过双向鉴权的新连接中，首个 `SNAPSHOT` 才能建立/切换 `stream_id` 并设置 `last_received_seq`；同一连接后续不得任意切换 stream。
3. **补服务端身份证明**：现有 HMAC 只证明设备持有密钥。主机校验设备签名后，返回 `AUTH_OK`，其中包含 `server_signature = HMAC_SHA256(pairing_secret, "AUTH_OK|" + nonce + "|" + device_id + "|" + server_id + "|" + protocol_version)`。设备必须恒定时间校验该签名后才接受 `SNAPSHOT`。Nonce 随连接销毁。文档称为“双向挑战应答鉴权”。
4. **配网 AP 凭据闭环**：5~10 秒进入的 AP 必须为 WPA2，密码由设备每次进入配网时随机生成至少 12 位，并只显示在实体屏幕；3 分钟自动关闭。不得使用固定默认密码、不得开放热点、不得把密码写入日志。
5. **状态名不矛盾**：保持网络 FSM 为 7 状态。`UNPAIRED` 改为正交的 `pairing_status=UNPAIRED` 标志；网络显示仍进入 `WIFI_NO_CREDENTIALS`/配对引导，不把 UNPAIRED 算成第 8 个 FSM 状态。
6. **排版与版本说明**：所有时间范围用 `1.5–5s`、`5–10s`，不要用 `~` 造成 Markdown 删除线；明确文档版本 `V2.0-R4`，wire `protocol_version` 仍为 `2.0.0`，两者职责不同。

结论不变：P0 `GO for implementation`（未实施、未验收）；P1 `NO-GO`。
