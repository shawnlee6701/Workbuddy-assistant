#!/usr/bin/env python3

import json
import tempfile
import threading
import unittest

from v2_transport import (
    MAX_FRAME_BYTES,
    NonceStore,
    ProtocolError,
    SerialUnavailable,
    StateDispatcher,
    UsbCommandBroker,
    V2Runtime,
    device_signature,
    compact_hud_status,
    frame_bytes,
    redact_sensitive,
    server_signature,
    validate_wifi_config,
)


class V2ProtocolTests(unittest.TestCase):
    def test_redaction_is_recursive(self):
        value = {"ssid": "Office", "password": "secret", "nested": {"pairing_secret": "key"}}
        self.assertEqual(redact_sensitive(value)["ssid"], "Office")
        self.assertEqual(redact_sensitive(value)["password"], "***")
        self.assertEqual(redact_sensitive(value)["nested"]["pairing_secret"], "***")

    def test_frame_guard_counts_utf8_bytes(self):
        with self.assertRaises(ProtocolError):
            frame_bytes({"value": "中" * MAX_FRAME_BYTES})

    def test_signatures_have_distinct_directions(self):
        args = ("secret", "nonce", "device", "server")
        self.assertNotEqual(device_signature(*args), server_signature(*args))
        self.assertEqual(len(device_signature(*args)), 64)

    def test_nonce_is_single_use(self):
        store = NonceStore(lifetime_seconds=10)
        nonce = store.issue("device")
        self.assertTrue(store.consume("device", nonce))
        self.assertFalse(store.consume("device", nonce))

    def test_wifi_validation(self):
        self.assertEqual(
            validate_wifi_config({"ssid": "Home", "password": "abc", "manual_host_ip": "192.168.1.8"})["ssid"],
            "Home",
        )
        with self.assertRaises(ProtocolError):
            validate_wifi_config({"ssid": "", "password": ""})
        with self.assertRaises(ProtocolError):
            validate_wifi_config({"ssid": "Home", "password": "", "manual_host_ip": "not-an-ip"})

    def test_hud_payload_is_bounded_and_excludes_dashboard_details(self):
        payload = compact_hud_status({
            "state": "RUNNING",
            "alert_title": "中" * 100,
            "alert_desc": "文" * 100,
            "session_token_usage": {"total": 123},
            "timeline": [{"text": "步" * 100, "dur": "执行中", "done": False, "active": True}] * 8,
        })
        self.assertNotIn("session_token_usage", payload)
        self.assertLessEqual(len(payload["alert_title"].encode("utf-8")), 64)
        self.assertLessEqual(len(payload["alert_desc"].encode("utf-8")), 128)
        self.assertEqual(len(payload["timeline"]), 5)

    def test_dispatcher_uses_identical_frame_for_usb_and_wifi(self):
        serial_frames = []
        wireless_frames = []
        dispatcher = StateDispatcher(serial_frames.append, wireless_frames.append, serial_min_interval=0)
        frame = dispatcher.publish({"state": "RUNNING"})
        decoded = json.loads(serial_frames[0].decode("utf-8"))
        self.assertEqual(decoded, frame)
        self.assertEqual(wireless_frames[0], frame)
        self.assertEqual(frame["seq"], 1)
        self.assertEqual(dispatcher.publish({"state": "IDLE"})["seq"], 2)

    def test_dispatcher_coalesces_serial_bursts_but_not_wireless(self):
        serial_frames = []
        wireless_frames = []
        dispatcher = StateDispatcher(serial_frames.append, wireless_frames.append, serial_min_interval=0.05)
        dispatcher.publish({"state": "RUNNING"})
        dispatcher.publish({"state": "NEED_ANSWER"})
        dispatcher.publish({"state": "COMPLETED"})
        self.assertEqual(len(serial_frames), 1)
        self.assertEqual(len(wireless_frames), 3)
        threading.Event().wait(0.08)
        self.assertEqual(len(serial_frames), 2)
        self.assertEqual(json.loads(serial_frames[-1])["payload"]["state"], "COMPLETED")

    def test_dispatcher_suspends_usb_frames_and_flushes_only_latest(self):
        serial_frames = []
        wireless_frames = []
        dispatcher = StateDispatcher(serial_frames.append, wireless_frames.append, serial_min_interval=0)
        dispatcher.suspend_serial()
        dispatcher.publish({"state": "RUNNING"})
        dispatcher.publish({"state": "COMPLETED"})
        self.assertEqual(serial_frames, [])
        self.assertEqual(len(wireless_frames), 2)
        dispatcher.resume_serial()
        threading.Event().wait(0.25)
        self.assertEqual(len(serial_frames), 1)
        self.assertEqual(json.loads(serial_frames[0])["payload"]["state"], "COMPLETED")

    def test_usb_broker_matches_response_without_logging_secret(self):
        broker = UsbCommandBroker()

        def writer(payload):
            request = json.loads(payload.decode("utf-8"))
            response = {"type": "WIFI_CONFIG_OK", "request_id": request["request_id"], "ip": "192.168.1.9"}
            threading.Timer(0.01, lambda: broker.feed_line(json.dumps(response))).start()

        broker.attach("/dev/test", writer)
        result = broker.request(
            {"type": "WIFI_CONFIG_SET", "ssid": "Home", "password": "secret"},
            {"WIFI_CONFIG_OK"},
            timeout=1,
        )
        self.assertEqual(result["ip"], "192.168.1.9")

    def test_usb_broker_requires_connected_device(self):
        with self.assertRaises(SerialUnavailable):
            UsbCommandBroker().request({"type": "WIFI_SCAN_REQUEST"}, {"WIFI_SCAN_RESULT"}, timeout=0.01)

    def test_configure_wifi_rejects_device_error(self):
        with tempfile.TemporaryDirectory() as state_dir:
            runtime = V2Runtime(state_dir, lambda payload: None)
            runtime._usb_request = lambda command, expected, timeout: {
                "type": "WIFI_CONFIG_ERROR",
                "code": "WIFI_AUTH_FAILED",
                "message": "Router rejected credentials",
            }
            with self.assertRaisesRegex(ProtocolError, "WIFI_AUTH_FAILED"):
                runtime.configure_wifi({"ssid": "Home", "password": "secret"})


if __name__ == "__main__":
    unittest.main()
