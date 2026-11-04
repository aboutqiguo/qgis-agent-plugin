import json
import unittest

from qgis_agent_plugin.core.tool_result import ToolResult, parse_tool_result_payload


class ToolResultPayloadTests(unittest.TestCase):
    def test_json_success_payload_is_parsed(self):
        value = ToolResult.success("done", data={"count": 4}).to_json()
        payload = parse_tool_result_payload(value)
        self.assertTrue(payload["ok"])
        self.assertEqual(4, payload["data"]["count"])

    def test_dict_and_legacy_text_are_distinguished(self):
        payload = {"ok": False, "error_type": "operation_cancelled"}
        self.assertIs(payload, parse_tool_result_payload(payload))
        self.assertIsNone(parse_tool_result_payload("plain legacy output"))
        self.assertIsNone(parse_tool_result_payload(json.dumps([1, 2, 3])))


if __name__ == "__main__":
    unittest.main()
