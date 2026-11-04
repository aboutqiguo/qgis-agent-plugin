import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from qgis_agent_plugin.core.cache_metrics import (
    append_record,
    build_metrics_record,
    build_structure_fingerprints,
    extract_usage,
    load_records,
    summarize_records,
)
from qgis_agent_plugin.core.artifacts import AgentRunArtifacts


class FakeUsage:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        if exclude_none:
            return {key: value for key, value in self.values.items() if value is not None}
        return dict(self.values)


class FakeResponse:
    def __init__(self, usage, response_id="req-test"):
        self.usage = usage
        self.id = response_id


class CacheMetricsTests(unittest.TestCase):
    def test_extracts_deepseek_cache_usage(self):
        response = FakeResponse(FakeUsage(
            prompt_tokens=1_000,
            completion_tokens=100,
            total_tokens=1_100,
            prompt_cache_hit_tokens=800,
            prompt_cache_miss_tokens=200,
        ))
        usage = extract_usage(response)
        self.assertEqual(800, usage["prompt_cache_hit_tokens"])
        self.assertEqual(200, usage["prompt_cache_miss_tokens"])
        self.assertTrue(usage["cache_fields_reported"])
        self.assertEqual([], usage["warnings"])

    def test_missing_cache_fields_remain_unknown(self):
        usage = extract_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 2}})
        self.assertIsNone(usage["prompt_cache_hit_tokens"])
        self.assertIsNone(usage["prompt_cache_miss_tokens"])
        self.assertFalse(usage["cache_fields_reported"])

    def test_cached_tokens_detail_is_supported(self):
        usage = extract_usage({
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 75},
            }
        })
        self.assertEqual(75, usage["prompt_cache_hit_tokens"])
        self.assertEqual(25, usage["prompt_cache_miss_tokens"])

    def test_fingerprints_are_canonical(self):
        messages = [{"role": "system", "content": "stable"}]
        first = [{"type": "function", "function": {"name": "x", "description": "d"}}]
        second = [{"function": {"description": "d", "name": "x"}, "type": "function"}]
        self.assertEqual(
            build_structure_fingerprints(messages, first),
            build_structure_fingerprints(messages, second),
        )

    def test_record_contains_hashes_but_not_prompt_or_tool_text(self):
        response = FakeResponse(FakeUsage(
            prompt_tokens=1_000_000,
            completion_tokens=100_000,
            total_tokens=1_100_000,
            prompt_cache_hit_tokens=800_000,
            prompt_cache_miss_tokens=200_000,
        ))
        record = build_metrics_record(
            response,
            "deepseek-v4-flash",
            [{"role": "system", "content": "SECRET_PROMPT"}],
            [{"type": "function", "function": {"name": "secret_tool", "description": "SECRET_TOOL"}}],
            run_id="SECRET_RUN_NAME",
        )
        serialized = json.dumps(record, ensure_ascii=False)
        self.assertNotIn("SECRET_PROMPT", serialized)
        self.assertNotIn("SECRET_TOOL", serialized)
        self.assertNotIn("SECRET_RUN_NAME", serialized)
        self.assertAlmostEqual(0.416, record["cost_estimate"]["estimated_actual"])
        self.assertAlmostEqual(0.784, record["cost_estimate"]["estimated_savings"])

    def test_summary_uses_cache_known_requests_only(self):
        known = build_metrics_record(
            FakeResponse(FakeUsage(
                prompt_tokens=100,
                completion_tokens=10,
                total_tokens=110,
                prompt_cache_hit_tokens=80,
                prompt_cache_miss_tokens=20,
            )),
            "deepseek-v4-flash",
            [],
            [],
        )
        unknown = build_metrics_record(
            FakeResponse(FakeUsage(prompt_tokens=100, completion_tokens=10, total_tokens=110)),
            "other-model",
            [],
            [],
        )
        summary = summarize_records([known, unknown])
        self.assertEqual(2, summary["request_count"])
        self.assertEqual(1, summary["cache_known_requests"])
        self.assertEqual(0.5, summary["cache_coverage"])
        self.assertEqual(0.8, summary["cache_hit_rate"])

    def test_append_prunes_records_outside_retention(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "cache_usage.jsonl")
            old = {"time": (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()}
            current = {"time": datetime.now(timezone.utc).isoformat()}
            append_record(old, path=path, retention_days=30, max_bytes=1024 * 1024)
            append_record(current, path=path, retention_days=30, max_bytes=1024 * 1024)
            records = load_records(path=path)
            self.assertEqual(1, len(records))
            self.assertEqual(current["time"], records[0]["time"])

    def test_run_artifact_summary_includes_cache_metrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts = AgentRunArtifacts(temp_dir, "cache test")
            record = build_metrics_record(
                FakeResponse(FakeUsage(
                    prompt_tokens=100,
                    completion_tokens=10,
                    total_tokens=110,
                    prompt_cache_hit_tokens=80,
                    prompt_cache_miss_tokens=20,
                )),
                "deepseek-v4-flash",
                [],
                [],
            )
            artifacts.append_jsonl("token_usage.jsonl", record)
            summary = artifacts._build_token_usage_summary()
            self.assertEqual(1, summary["cache_known_requests"])
            self.assertEqual(0.8, summary["cache_hit_rate"])
            self.assertGreater(summary["estimated_savings_cny"], 0)


if __name__ == "__main__":
    unittest.main()
