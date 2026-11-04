import json
import unittest

from qgis_agent_plugin.core.message_protocol import (
    build_cancelled_tool_results,
    reconcile_tool_messages,
    validate_tool_message_sequence,
)


class MessageProtocolTests(unittest.TestCase):
    def setUp(self):
        self.cancelled = json.dumps({"ok": False, "error_type": "cancelled_error"})

    def test_missing_multi_tool_result_is_repaired(self):
        messages = [
            {"role": "user", "content": "run"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_a", "function": {"name": "tool_a", "arguments": "{}"}},
                    {"id": "call_b", "function": {"name": "tool_b", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "name": "tool_a", "content": "ok"},
        ]

        repaired, repairs = reconcile_tool_messages(messages, self.cancelled)

        self.assertEqual([], validate_tool_message_sequence(repaired))
        self.assertEqual(["call_a", "call_b"], [item["tool_call_id"] for item in repaired[-2:]])
        self.assertTrue(any(item["action"] == "insert_cancelled_tool_result" for item in repairs))

    def test_orphan_duplicate_and_unknown_results_are_removed(self):
        messages = [
            {"role": "tool", "tool_call_id": "orphan", "content": "bad"},
            {
                "role": "assistant",
                "tool_calls": [{"id": "call_a", "function": {"name": "tool_a", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "first"},
            {"role": "tool", "tool_call_id": "call_a", "content": "duplicate"},
            {"role": "tool", "tool_call_id": "unknown", "content": "unknown"},
            {"role": "assistant", "content": "done"},
        ]

        repaired, repairs = reconcile_tool_messages(messages, self.cancelled)

        self.assertEqual([], validate_tool_message_sequence(repaired))
        results = [item for item in repaired if item.get("role") == "tool"]
        self.assertEqual(1, len(results))
        self.assertEqual("first", results[0]["content"])
        self.assertGreaterEqual(len(repairs), 3)

    def test_valid_sequence_is_unchanged(self):
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "x", "function": {"name": "a"}}]},
            {"role": "tool", "tool_call_id": "x", "name": "a", "content": "ok"},
        ]
        repaired, repairs = reconcile_tool_messages(messages, self.cancelled)
        self.assertEqual(messages, repaired)
        self.assertEqual([], repairs)

    def test_pending_multi_tool_calls_receive_cancellation_results(self):
        tool_calls = [
            {"id": "call_b", "function": {"name": "download_b", "arguments": "{}"}},
            {"id": "call_c", "function": {"name": "download_c", "arguments": "{}"}},
        ]
        results = build_cancelled_tool_results(tool_calls, self.cancelled)
        self.assertEqual(["call_b", "call_c"], [item["tool_call_id"] for item in results])
        self.assertTrue(all(item["role"] == "tool" for item in results))


if __name__ == "__main__":
    unittest.main()
