import json
import os
import tempfile
import unittest
from unittest import mock

from host_bridge import daemon


class TraceUsageTests(unittest.TestCase):
    def setUp(self):
        daemon.trace_usage_cache = {
            "session_id": None,
            "checked_at": 0.0,
            "usage": None,
        }

    def test_parse_trace_usage_returns_exact_breakdown(self):
        payload = {
            "trace": {
                "traceId": "trace_current",
                "endedAt": "2026-09-13T02:28:13Z",
                "totalTokens": 2568544,
                "modelInfo": {
                    "totalInputTokens": 2562951,
                    "totalOutputTokens": 5593,
                    "totalCachedTokens": 2364552,
                    "callCount": 46,
                },
            }
        }

        usage = daemon.parse_trace_usage(payload)

        self.assertEqual(usage["total"], 2568544)
        self.assertEqual(usage["input"], 2562951)
        self.assertEqual(usage["output"], 5593)
        self.assertEqual(usage["cached"], 2364552)
        self.assertEqual(usage["calls"], 46)
        self.assertEqual(usage["trace_id"], "trace_current")

    def test_parse_trace_usage_falls_back_to_input_plus_output(self):
        usage = daemon.parse_trace_usage({
            "trace": {
                "modelInfo": {
                    "totalInputTokens": "1200",
                    "totalOutputTokens": 45,
                }
            }
        })

        self.assertEqual(usage["total"], 1245)
        self.assertEqual(usage["total_label"], "1.2k")

    def test_session_lookup_ignores_newer_trace_from_another_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_dir = os.path.join(temp_dir, "worker")
            os.makedirs(trace_dir)
            matching_path = os.path.join(trace_dir, "matching.json")
            other_path = os.path.join(trace_dir, "other.json")

            with open(matching_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "trace": {
                        "sessionId": "session-target",
                        "endedAt": "2026-09-13T02:28:13Z",
                        "totalTokens": 9876,
                    }
                }, handle)
            with open(other_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "trace": {
                        "sessionId": "session-other",
                        "endedAt": "2026-09-13T02:29:13Z",
                        "totalTokens": 999999,
                    }
                }, handle)
            os.utime(other_path, (2, 2))
            os.utime(matching_path, (1, 1))

            with mock.patch.object(daemon, "SYSTEM_TRACES", temp_dir):
                usage = daemon.get_session_trace_usage("session-target", refresh_after=0)

        self.assertEqual(usage["total"], 9876)

    def test_today_summary_aggregates_session_traces_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_dir = os.path.join(temp_dir, "worker")
            os.makedirs(trace_dir)
            payloads = [
                {
                    "trace": {
                        "sessionId": "session-a",
                        "totalTokens": 120,
                        "modelInfo": {
                            "totalInputTokens": 100,
                            "totalOutputTokens": 20,
                            "totalCachedTokens": 50,
                            "callCount": 2,
                        },
                    },
                    "spans": [],
                },
                {
                    "trace": {
                        "sessionId": "session-b",
                        "totalTokens": 230,
                        "modelInfo": {
                            "totalInputTokens": 200,
                            "totalOutputTokens": 30,
                            "totalCachedTokens": 80,
                            "callCount": 3,
                        },
                    },
                    "spans": [],
                },
                {
                    "trace": {
                        "totalTokens": 999999,
                        "modelInfo": {"totalInputTokens": 999999},
                    },
                    "spans": [],
                },
            ]
            for index, payload in enumerate(payloads):
                path = os.path.join(trace_dir, f"trace-{index}.json")
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)

            with mock.patch.object(daemon, "SYSTEM_TRACES", temp_dir):
                summary = daemon.get_trace_summary()

        self.assertEqual(summary["token_usage"]["total"], 350)
        self.assertEqual(summary["token_usage"]["input"], 300)
        self.assertEqual(summary["token_usage"]["output"], 50)
        self.assertEqual(summary["token_usage"]["cached"], 130)
        self.assertEqual(summary["token_usage"]["calls"], 5)
        self.assertEqual(summary["token_usage"]["sessions"], 2)
        self.assertEqual(summary["token_usage"]["traces"], 2)


if __name__ == "__main__":
    unittest.main()
