#!/usr/bin/env python3
"""Workbuddy Desktop HUD V2.0 transport and provisioning primitives."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import platform
import secrets
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional


PROTOCOL_VERSION = "2.0.0"
MAX_FRAME_BYTES = 4096
UDP_PORT = 5202
WS_PORT = 5201
KEYCHAIN_SERVICE = "com.workbuddy.desktop-hud.v2.pairing"
SENSITIVE_KEYS = {"password", "pairing_secret", "secret", "token"}
WIFI_ERROR_MESSAGES = {
    "WIFI_AP_NOT_FOUND": "未找到所选的 2.4GHz Wi-Fi；请重新扫描并选择完全一致的 SSID",
    "WIFI_AUTH_FAILED": "路由器拒绝认证；请核对 Wi-Fi 密码，并启用 WPA2 或 WPA2/WPA3 兼容模式",
    "WIFI_ASSOC_FAILED": "路由器拒绝设备接入；请检查 MAC 过滤、接入数量及 WPA 兼容设置",
    "WIFI_CONNECT_TIMEOUT": "连接 Wi-Fi 超时；请核对密码、2.4GHz SSID 与路由器兼容设置",
    "HOST_UNREACHABLE": "开发板已连上 Wi-Fi，但无法找到已配对的 Host；请确认电脑与开发板在同一局域网",
    "AUTH_TIMEOUT": "已找到 Host，但安全鉴权超时；请重新执行安全配对",
}
HUD_FIELDS = {
    "state", "thread", "time", "alert_title", "alert_desc", "step", "tools",
    "duration", "tokens", "session_tokens", "today_tokens", "model", "timeline",
}


class ProtocolError(ValueError):
    pass


class SerialUnavailable(RuntimeError):
    pass


class SerialRequestTimeout(TimeoutError):
    pass


def detect_lan_ipv4() -> str:
    """Return the IPv4 address selected by the host's current default route."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect selects a local route without sending application data.
        probe.connect(("192.0.2.1", 9))
        address = str(probe.getsockname()[0])
        return address if ipaddress.ip_address(address).version == 4 else ""
    except (OSError, ValueError):
        return ""
    finally:
        probe.close()


def canonical_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def frame_bytes(data: Dict[str, Any]) -> bytes:
    payload = (canonical_json(data) + "\n").encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError(f"frame exceeds {MAX_FRAME_BYTES} UTF-8 bytes")
    return payload


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("***" if key.lower() in SENSITIVE_KEYS else redact_sensitive(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def hmac_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def device_signature(secret: str, nonce: str, device_id: str, server_id: str) -> str:
    return hmac_hex(secret, f"{nonce}|{device_id}|{server_id}|{PROTOCOL_VERSION}")


def server_signature(secret: str, nonce: str, device_id: str, server_id: str) -> str:
    return hmac_hex(secret, f"AUTH_OK|{nonce}|{device_id}|{server_id}|{PROTOCOL_VERSION}")


def validate_wifi_config(data: Dict[str, Any]) -> Dict[str, str]:
    ssid = str(data.get("ssid") or "").strip()
    password = str(data.get("password") or "")
    manual_host_ip = str(data.get("manual_host_ip") or "").strip()
    if not ssid or len(ssid.encode("utf-8")) > 32:
        raise ProtocolError("SSID 必须为 1–32 UTF-8 字节")
    if len(password.encode("utf-8")) > 64:
        raise ProtocolError("Wi-Fi 密码不能超过 64 UTF-8 字节")
    if manual_host_ip:
        try:
            address = ipaddress.ip_address(manual_host_ip)
        except ValueError as exc:
            raise ProtocolError("Manual Host IP 格式无效") from exc
        if address.version != 4 or address.is_unspecified or address.is_multicast:
            raise ProtocolError("Manual Host IP 必须是可用的 IPv4 地址")
    return {"ssid": ssid, "password": password, "manual_host_ip": manual_host_ip}


def truncate_utf8(value: Any, limit: int) -> str:
    raw = str(value or "").encode("utf-8")[:limit]
    while raw:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raw = raw[:-1]
    return ""


def compact_hud_status(status: Dict[str, Any]) -> Dict[str, Any]:
    payload = {key: value for key, value in status.items() if key in HUD_FIELDS and key != "timeline"}
    payload["alert_title"] = truncate_utf8(payload.get("alert_title"), 64)
    payload["alert_desc"] = truncate_utf8(payload.get("alert_desc"), 128)
    timeline = []
    for source in (status.get("timeline") or [])[:5]:
        if not isinstance(source, dict):
            continue
        timeline.append({
            "text": truncate_utf8(source.get("text"), 64),
            "dur": truncate_utf8(source.get("dur"), 64),
            "done": bool(source.get("done")),
            "active": bool(source.get("active")),
        })
    payload["timeline"] = timeline
    return payload


class PairingStore:
    """Keep pairing secrets in macOS Keychain and only non-secret IDs on disk."""

    def __init__(self, state_dir: str):
        self.state_dir = state_dir
        self.registry_path = os.path.join(state_dir, "v2_paired_devices.json")
        os.makedirs(state_dir, exist_ok=True)
        self._secret_cache: Dict[str, str] = {}
        self._lock = threading.Lock()

    def _read_registry(self) -> Dict[str, Any]:
        try:
            with open(self.registry_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_registry(self, data: Dict[str, Any]) -> None:
        temp_path = self.registry_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.registry_path)

    def set(self, device_id: str, secret: str) -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("V2.0 pairing requires macOS Keychain")
        result = subprocess.run(
            ["security", "add-generic-password", "-a", device_id, "-s", KEYCHAIN_SERVICE, "-w", secret, "-U"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("无法写入 macOS Keychain")
        registry = self._read_registry()
        registry[device_id] = {"paired_at": int(time.time())}
        self._write_registry(registry)
        with self._lock:
            self._secret_cache[device_id] = secret

    def get(self, device_id: str) -> Optional[str]:
        if platform.system() != "Darwin":
            return None
        # Reject unknown LAN-supplied IDs before invoking Keychain.
        if device_id not in self._read_registry():
            return None
        with self._lock:
            cached = self._secret_cache.get(device_id)
        if cached:
            return cached
        result = subprocess.run(
            ["security", "find-generic-password", "-a", device_id, "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logging.warning("[V2配对] Keychain 读取失败 device=%s rc=%s", device_id, result.returncode)
            return None
        value = result.stdout.rstrip("\r\n") or None
        if value:
            with self._lock:
                self._secret_cache[device_id] = value
        return value

    def remove(self, device_id: str) -> None:
        if platform.system() == "Darwin":
            subprocess.run(
                ["security", "delete-generic-password", "-a", device_id, "-s", KEYCHAIN_SERVICE],
                capture_output=True,
                text=True,
                check=False,
            )
        registry = self._read_registry()
        registry.pop(device_id, None)
        self._write_registry(registry)
        with self._lock:
            self._secret_cache.pop(device_id, None)

    def list_devices(self) -> Iterable[str]:
        return sorted(self._read_registry())


class NonceStore:
    def __init__(self, lifetime_seconds: float = 30.0):
        self.lifetime_seconds = lifetime_seconds
        self._values: Dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def issue(self, device_id: str) -> str:
        nonce = secrets.token_hex(16)
        now = time.monotonic()
        with self._lock:
            self._values = {key: expires for key, expires in self._values.items() if expires > now}
            self._values[(device_id, nonce)] = now + self.lifetime_seconds
        return nonce

    def consume(self, device_id: str, nonce: str) -> bool:
        now = time.monotonic()
        with self._lock:
            expires = self._values.pop((device_id, nonce), None)
        return bool(expires and expires > now)


class UsbCommandBroker:
    """Serialize USB provisioning commands and match request/response frames."""

    def __init__(self):
        self._writer: Optional[Callable[[bytes], None]] = None
        self._port: Optional[str] = None
        self._condition = threading.Condition()
        self._responses: Dict[str, Dict[str, Any]] = {}
        self._request_lock = threading.Lock()
        self.last_device_status: Dict[str, Any] = {}

    @property
    def port(self) -> Optional[str]:
        return self._port

    def attach(self, port: str, writer: Callable[[bytes], None]) -> None:
        self._port = port
        self._writer = writer

    def detach(self) -> None:
        self._port = None
        self._writer = None

    def request(self, command: Dict[str, Any], expected_types: Iterable[str], timeout: float = 20.0) -> Dict[str, Any]:
        expected = set(expected_types)
        with self._request_lock:
            writer = self._writer
            if not writer or not self._port:
                raise SerialUnavailable("请先通过 USB 连接开发板")
            request_id = uuid.uuid4().hex
            command = dict(command)
            command["request_id"] = request_id
            writer(frame_bytes(command))
            deadline = time.monotonic() + timeout
            with self._condition:
                while True:
                    response = self._responses.pop(request_id, None)
                    if response is not None:
                        if response.get("type") not in expected:
                            raise ProtocolError(f"unexpected response: {response.get('type')}")
                        return response
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SerialRequestTimeout("等待开发板响应超时")
                    self._condition.wait(remaining)

    def feed_line(self, line: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(line)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("type") == "DEVICE_STATUS":
            self.last_device_status = redact_sensitive(data)
        request_id = data.get("request_id")
        if request_id:
            with self._condition:
                self._responses[str(request_id)] = data
                self._condition.notify_all()
        return data


class StateDispatcher:
    def __init__(
        self,
        serial_sender: Callable[[bytes], None],
        websocket_broadcaster: Callable[[Dict[str, Any]], None],
        server_id: str = "",
        serial_min_interval: float = 0.4,
    ):
        self.stream_id = f"strm_{int(time.time())}_{secrets.token_hex(4)}"
        self._seq = 0
        self._lock = threading.RLock()
        self._serial_sender = serial_sender
        self._websocket_broadcaster = websocket_broadcaster
        self._server_id = server_id
        self._serial_min_interval = max(0.0, serial_min_interval)
        self._serial_last_sent = 0.0
        self._serial_pending: Optional[bytes] = None
        self._serial_timer: Optional[threading.Timer] = None
        self._serial_suspend_count = 0

    def _send_serial(self, payload: bytes) -> None:
        try:
            self._serial_sender(payload)
        except (SerialUnavailable, OSError):
            pass

    def _flush_pending_serial(self) -> None:
        with self._lock:
            if self._serial_suspend_count:
                self._serial_timer = None
                return
            payload = self._serial_pending
            self._serial_pending = None
            self._serial_timer = None
            if payload is None:
                return
            self._serial_last_sent = time.monotonic()
        self._send_serial(payload)

    def _publish_serial(self, payload: bytes) -> None:
        """Coalesce bursts so the MCU can finish rendering before the next USB frame."""
        with self._lock:
            if self._serial_suspend_count:
                self._serial_pending = payload
                return
            elapsed = time.monotonic() - self._serial_last_sent
            if self._serial_min_interval == 0 or elapsed >= self._serial_min_interval:
                self._serial_last_sent = time.monotonic()
                send_now = True
            else:
                send_now = False
                self._serial_pending = payload
                if self._serial_timer is None:
                    delay = self._serial_min_interval - elapsed
                    self._serial_timer = threading.Timer(delay, self._flush_pending_serial)
                    self._serial_timer.daemon = True
                    self._serial_timer.start()
        if send_now:
            self._send_serial(payload)

    def suspend_serial(self) -> None:
        """Pause HUD frames while an exclusive USB provisioning command is active."""
        with self._lock:
            self._serial_suspend_count += 1
            if self._serial_timer is not None:
                self._serial_timer.cancel()
                self._serial_timer = None

    def resume_serial(self) -> None:
        """Resume USB HUD delivery and flush only the newest coalesced frame."""
        with self._lock:
            if self._serial_suspend_count == 0:
                return
            self._serial_suspend_count -= 1
            if self._serial_suspend_count or self._serial_pending is None or self._serial_timer is not None:
                return
            self._serial_timer = threading.Timer(0.2, self._flush_pending_serial)
            self._serial_timer.daemon = True
            self._serial_timer.start()

    def build_snapshot(self, status: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            frame = {
                "protocol_version": PROTOCOL_VERSION,
                "type": "SNAPSHOT",
                "stream_id": self.stream_id,
                "seq": self._seq,
                "sent_at_ms": int(time.time() * 1000),
                "payload": compact_hud_status(status),
            }
            if self._server_id:
                frame["server_id"] = self._server_id
            frame_bytes(frame)
            return frame

    def publish(self, status: Dict[str, Any]) -> Dict[str, Any]:
        frame = self.build_snapshot(status)
        self._publish_serial(frame_bytes(frame))
        self._websocket_broadcaster(frame)
        return frame


class DiscoveryServer:
    def __init__(self, server_id: str, pairing_store: PairingStore, nonce_store: NonceStore, port: int = UDP_PORT):
        self.server_id = server_id
        self.pairing_store = pairing_store
        self.nonce_store = nonce_store
        self.port = port
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="v2-udp-discovery", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.port))
        while True:
            raw, address = sock.recvfrom(MAX_FRAME_BYTES + 1)
            if len(raw) > MAX_FRAME_BYTES:
                continue
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if not isinstance(data, dict) or data.get("type") != "DISCOVER":
                continue
            if data.get("protocol_version") != PROTOCOL_VERSION:
                continue
            device_id = str(data.get("device_id") or "")
            if not device_id or not self.pairing_store.get(device_id):
                continue
            nonce = self.nonce_store.issue(device_id)
            offer = {
                "type": "OFFER",
                "protocol_version": PROTOCOL_VERSION,
                "device_id": device_id,
                "server_id": self.server_id,
                "nonce": nonce,
                "ws_port": WS_PORT,
            }
            sock.sendto(frame_bytes(offer).rstrip(b"\n"), address)


class WebSocketHub:
    def __init__(self, server_id: str, pairing_store: PairingStore, nonce_store: NonceStore, on_event=None, port: int = WS_PORT):
        self.server_id = server_id
        self.pairing_store = pairing_store
        self.nonce_store = nonce_store
        self.on_event = on_event
        self.port = port
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._clients = set()
        self._latest: Optional[Dict[str, Any]] = None
        self._last_auth_warning: Dict[str, float] = {}

    def _warn_auth(self, device_id: str, message: str) -> None:
        now = time.monotonic()
        if now - self._last_auth_warning.get(device_id, 0.0) < 5.0:
            return
        self._last_auth_warning[device_id] = now
        logging.warning("[V2鉴权] %s device=%s", message, device_id)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="v2-websocket", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        from websockets.asyncio.server import serve

        self._loop = asyncio.get_running_loop()
        async with serve(self._handle_client, "0.0.0.0", self.port, max_size=MAX_FRAME_BYTES, ping_interval=15, ping_timeout=10):
            await asyncio.Future()

    async def _handle_client(self, websocket) -> None:
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
                await websocket.close(code=1009, reason="frame too large")
                return
            auth = json.loads(raw)
            if not isinstance(auth, dict) or auth.get("type") != "AUTH":
                await websocket.close(code=1008, reason="AUTH required")
                return
            device_id = str(auth.get("device_id") or "")
            nonce = str(auth.get("nonce") or "")
            if auth.get("protocol_version") != PROTOCOL_VERSION or auth.get("server_id") != self.server_id:
                await websocket.close(code=1008, reason="protocol mismatch")
                return
            secret = self.pairing_store.get(device_id)
            expected = device_signature(secret or "", nonce, device_id, self.server_id)
            supplied = str(auth.get("signature") or "")
            if not secret:
                self._warn_auth(device_id, "缺少可用配对密钥")
                await websocket.close(code=1008, reason="authentication failed")
                return
            if not self.nonce_store.consume(device_id, nonce):
                self._warn_auth(device_id, "nonce 无效或已过期")
                await websocket.close(code=1008, reason="authentication failed")
                return
            if not hmac.compare_digest(expected, supplied):
                self._warn_auth(device_id, "签名不匹配")
                await websocket.close(code=1008, reason="authentication failed")
                return
            reply = {
                "type": "AUTH_OK",
                "protocol_version": PROTOCOL_VERSION,
                "device_id": device_id,
                "server_id": self.server_id,
                "nonce": nonce,
                "signature": server_signature(secret, nonce, device_id, self.server_id),
            }
            await websocket.send(canonical_json(reply))
            self._clients.add(websocket)
            if self._latest:
                await websocket.send(canonical_json(self._latest))
            async for message in websocket:
                if isinstance(message, bytes):
                    message = message.decode("utf-8")
                if len(message.encode("utf-8")) > MAX_FRAME_BYTES:
                    continue
                try:
                    event = json.loads(message)
                except ValueError:
                    continue
                if isinstance(event, dict) and self.on_event:
                    self.on_event(device_id, event)
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)

    def broadcast(self, frame: Dict[str, Any]) -> None:
        self._latest = frame
        loop = self._loop
        if not loop or loop.is_closed() or not loop.is_running():
            return
        coroutine = self._broadcast(frame)
        try:
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        except RuntimeError:
            coroutine.close()

    async def _broadcast(self, frame: Dict[str, Any]) -> None:
        if not self._clients:
            return
        payload = canonical_json(frame)
        stale = []
        for client in tuple(self._clients):
            try:
                await client.send(payload)
            except Exception:
                stale.append(client)
        for client in stale:
            self._clients.discard(client)

    @property
    def client_count(self) -> int:
        return len(self._clients)


@dataclass
class RuntimeStatus:
    protocol_version: str
    server_id: str
    serial_port: Optional[str]
    wireless_clients: int
    paired_devices: list[str]
    device: Dict[str, Any]
    host_ip: str


class V2Runtime:
    def __init__(self, state_dir: str, serial_sender: Callable[[bytes], None], on_event=None):
        os.makedirs(state_dir, exist_ok=True)
        self.state_dir = state_dir
        self.server_id = self._load_server_id()
        self.pairing_store = PairingStore(state_dir)
        self.nonce_store = NonceStore()
        self.usb = UsbCommandBroker()
        self.websocket = WebSocketHub(self.server_id, self.pairing_store, self.nonce_store, on_event=on_event)
        self.discovery = DiscoveryServer(self.server_id, self.pairing_store, self.nonce_store)
        self.dispatcher = StateDispatcher(serial_sender, self.websocket.broadcast, self.server_id)

    def _usb_request(self, command: Dict[str, Any], expected_types: Iterable[str], timeout: float) -> Dict[str, Any]:
        self.dispatcher.suspend_serial()
        try:
            return self.usb.request(command, expected_types, timeout)
        finally:
            self.dispatcher.resume_serial()

    def _load_server_id(self) -> str:
        path = os.path.join(self.state_dir, "v2_host.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle).get("server_id")
            if value:
                return str(value)
        except (OSError, ValueError, AttributeError):
            pass
        value = f"srv_{socket.gethostname().split('.')[0]}_{secrets.token_hex(4)}"
        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump({"server_id": value}, handle)
        os.replace(temp_path, path)
        return value

    def start(self) -> None:
        self.discovery.start()
        self.websocket.start()

    def pair(self, timeout: float = 8.0) -> Dict[str, Any]:
        secret = secrets.token_hex(32)
        response = self._usb_request(
            {"type": "PAIRING_SET", "protocol_version": PROTOCOL_VERSION, "server_id": self.server_id, "pairing_secret": secret},
            {"PAIRING_OK", "PAIRING_ERROR"},
            timeout=timeout,
        )
        if response.get("type") != "PAIRING_OK":
            raise ProtocolError(str(response.get("message") or "设备配对失败"))
        device_id = str(response.get("device_id") or "")
        if not device_id:
            raise ProtocolError("设备未返回 device_id")
        self.pairing_store.set(device_id, secret)
        return redact_sensitive(response)

    def scan_wifi(self, timeout: float = 20.0) -> Dict[str, Any]:
        return redact_sensitive(self._usb_request({"type": "WIFI_SCAN_REQUEST"}, {"WIFI_SCAN_RESULT", "WIFI_SCAN_ERROR"}, timeout))

    def configure_wifi(self, data: Dict[str, Any], timeout: float = 65.0) -> Dict[str, Any]:
        config = validate_wifi_config(data)
        command = {"type": "WIFI_CONFIG_SET", **config}
        response = self._usb_request(command, {"WIFI_CONFIG_OK", "WIFI_CONFIG_ERROR"}, timeout)
        if response.get("type") != "WIFI_CONFIG_OK":
            code = str(response.get("code") or "WIFI_CONFIG_FAILED")
            message = WIFI_ERROR_MESSAGES.get(code, str(response.get("message") or "Wi-Fi 配置失败"))
            raise ProtocolError(f"{code}: {message}")
        return redact_sensitive(response)

    def unpair(self, timeout: float = 8.0) -> Dict[str, Any]:
        response = self._usb_request({"type": "PAIRING_CLEAR"}, {"PAIRING_CLEARED", "PAIRING_ERROR"}, timeout)
        if response.get("type") != "PAIRING_CLEARED":
            raise ProtocolError(str(response.get("message") or "解除配对失败"))
        device_id = str(response.get("device_id") or "")
        if device_id:
            self.pairing_store.remove(device_id)
        return redact_sensitive(response)

    def status(self) -> Dict[str, Any]:
        status = RuntimeStatus(
            protocol_version=PROTOCOL_VERSION,
            server_id=self.server_id,
            serial_port=self.usb.port,
            wireless_clients=self.websocket.client_count,
            paired_devices=list(self.pairing_store.list_devices()),
            device=self.usb.last_device_status,
            host_ip=detect_lan_ipv4(),
        )
        return status.__dict__
