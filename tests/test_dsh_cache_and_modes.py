import os
import sys
import types
import unittest


def _install_qgis_import_stubs():
    qgis_module = sys.modules.setdefault("qgis", types.ModuleType("qgis"))
    core_module = sys.modules.setdefault("qgis.core", types.ModuleType("qgis.core"))
    for name in (
        "QgsProject",
        "QgsMapLayerType",
        "QgsVectorLayer",
        "QgsRasterLayer",
        "QgsExpression",
        "Qgis",
    ):
        if not hasattr(core_module, name):
            setattr(core_module, name, type(name, (), {}))
    qgis_module.core = core_module
    sys.modules.setdefault("processing", types.ModuleType("processing"))


_install_qgis_import_stubs()

from qgis_agent_plugin.core.mode_state import (
    MODE_READ_ONLY,
    MODE_WORKSPACE_WRITE,
    MODE_FULL_ACCESS,
    normalize_mode,
    MODE_DISPLAY_CONFIG,
)
from qgis_agent_plugin.core.approval_policy import ToolApprovalPolicy


class DshModeAndCacheTests(unittest.TestCase):
    def test_mode_normalization_and_display(self):
        self.assertEqual(normalize_mode("read_only"), MODE_READ_ONLY)
        self.assertEqual(normalize_mode("PLAN"), MODE_READ_ONLY)
        self.assertEqual(normalize_mode("WORKSPACE"), MODE_WORKSPACE_WRITE)
        self.assertEqual(normalize_mode("WORK"), MODE_FULL_ACCESS)
        self.assertEqual(normalize_mode("FULL_ACCESS"), MODE_FULL_ACCESS)

        self.assertIn("仅可查看", MODE_DISPLAY_CONFIG[MODE_READ_ONLY]["text"])
        self.assertIn("工作区内修改", MODE_DISPLAY_CONFIG[MODE_WORKSPACE_WRITE]["text"])
        self.assertIn("完全权限", MODE_DISPLAY_CONFIG[MODE_FULL_ACCESS]["text"])

    def test_read_only_mode_blocks_writes(self):
        policy = ToolApprovalPolicy()
        
        # Read-only query tools are permitted
        read_decision = policy.evaluate(
            "read_file",
            {"file_path": "USER.md"},
            context={"mode": MODE_READ_ONLY},
        )
        self.assertFalse(read_decision.requires_approval)

        # Mutating tools require approval in read-only mode
        write_decision = policy.evaluate(
            "write_file",
            {"file_path": "output.geojson", "content": "{}"},
            context={"mode": MODE_READ_ONLY},
        )
        self.assertTrue(write_decision.requires_approval)

    def test_workspace_mode_allows_in_project_and_blocks_escapes(self):
        import tempfile

        ws_dir = tempfile.mkdtemp()
        policy = ToolApprovalPolicy()

        # In-workspace file write is approved autonomously
        in_ws_file = os.path.join(ws_dir, "result.geojson")
        ws_decision = policy.evaluate(
            "write_file",
            {"file_path": in_ws_file, "content": "{}"},
            context={"mode": MODE_WORKSPACE_WRITE, "project_home": ws_dir},
        )
        self.assertFalse(ws_decision.requires_approval)

        # Safe PyQGIS script within workspace is approved
        safe_script_decision = policy.evaluate(
            "execute_pyqgis_script",
            {"code": "print('hello from workspace')"},
            context={"mode": MODE_WORKSPACE_WRITE, "project_home": ws_dir},
        )
        self.assertFalse(safe_script_decision.requires_approval)

        # PyQGIS script with dangerous subprocess is intercepted for approval
        escape_script_decision = policy.evaluate(
            "execute_pyqgis_script",
            {"code": "import subprocess; subprocess.run(['cmd'])"},
            context={"mode": MODE_WORKSPACE_WRITE, "project_home": ws_dir},
        )
        self.assertTrue(escape_script_decision.requires_approval)

    def test_full_access_mode_grants_all_operations(self):
        policy = ToolApprovalPolicy()
        decision = policy.evaluate(
            "execute_pyqgis_script",
            {"code": "print('autonomous execution')"},
            context={"mode": MODE_FULL_ACCESS},
        )
        self.assertFalse(decision.requires_approval)

    def test_tool_deterministic_sorting_for_prompt_cache(self):
        unsorted_tools = [
            {"function": {"name": "zoom_to_layer"}},
            {"function": {"name": "apply_graduated_renderer"}},
            {"function": {"name": "buffer_layer"}},
            {"function": {"name": "add_vector_layer"}},
        ]
        sorted_tools = sorted(unsorted_tools, key=lambda t: t.get("function", {}).get("name", ""))
        tool_names = [t["function"]["name"] for t in sorted_tools]
        self.assertEqual(
            tool_names,
            ["add_vector_layer", "apply_graduated_renderer", "buffer_layer", "zoom_to_layer"],
        )

    def test_project_scoped_cache_isolation(self):
        import tempfile
        from qgis_agent_plugin.core.cache_metrics import (
            build_metrics_record,
            append_record,
            get_summary,
        )

        project_a = tempfile.mkdtemp(prefix="project_a_")
        project_b = tempfile.mkdtemp(prefix="project_b_")

        dummy_response = {
            "id": "resp-test-01",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "total_tokens": 1100,
                "prompt_cache_hit_tokens": 900,
                "prompt_cache_miss_tokens": 100,
            },
        }

        # Project A record
        rec_a = build_metrics_record(
            response=dummy_response,
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            project_home=project_a,
        )
        append_record(rec_a)

        # Summary for Project A should see the tokens
        summary_a = get_summary(project_home=project_a)
        self.assertEqual(summary_a["request_count"], 1)
        self.assertEqual(summary_a["prompt_cache_hit_tokens"], 900)
        self.assertEqual(summary_a["prompt_cache_miss_tokens"], 100)
        self.assertAlmostEqual(summary_a["cache_hit_rate"], 0.9, places=2)

        # Summary for Project B (new project) should be 0 (from scratch!)
        summary_b = get_summary(project_home=project_b)
        self.assertEqual(summary_b["request_count"], 0)
        self.assertEqual(summary_b["total_tokens"], 0)
        self.assertIsNone(summary_b["cache_hit_rate"])


if __name__ == "__main__":
    unittest.main()
