import json
import os
import tempfile
import unittest

from qgis_agent_plugin.core.checkpoints import CheckpointManager, TaskCheckpoint
from qgis_agent_plugin.core.local_continuation import is_consultative_query, should_finalize_locally
from qgis_agent_plugin.ui.markdown_renderer import render_markdown_to_html
from qgis_agent_plugin.ui.metro_progress import render_metro_line_html


class CheckpointsAndContinuationTests(unittest.TestCase):
    def test_consultative_queries_never_finalizes_locally(self):
        """Consultative and open-ended queries must NEVER shortcut locally, so LLM can synthesize answers."""
        payload = {"ok": True, "message": "Found 2 layer(s).", "data": {"layer_count": 2}}
        self.assertTrue(is_consultative_query("基于这份数据，你能帮我完成哪些工作呢？"))
        self.assertFalse(
            should_finalize_locally(
                "summarize_layers",
                payload,
                set(),
                response_result_count=1,
                user_text="基于这份数据，你能帮我完成哪些工作呢？",
            )
        )
        self.assertFalse(
            should_finalize_locally(
                "summarize_layers",
                payload,
                {"selection"},
                response_result_count=1,
                user_text="基于dem计算潜在河流，请告诉我步骤方案",
            )
        )

    def test_simple_terminal_query_finalizes_if_not_consultative(self):
        """When user request is a pure simple query with empty domains or selection domain, shortcut is allowed."""
        payload = {"ok": True, "message": "Found 2 layer(s).", "data": {"layer_count": 2}}
        self.assertTrue(
            should_finalize_locally(
                "summarize_layers",
                payload,
                set(),
                response_result_count=1,
                user_text="",
            )
        )

    def test_plan_complete_allows_finalization(self):
        """When plan is fully complete, finalization is permitted."""
        payload = {"ok": True, "message": "All steps done"}
        self.assertTrue(should_finalize_locally("summarize_layers", payload, ["selection"], plan_complete=True))

    def test_workflow_complete_allows_finalization(self):
        """When high-level workflow reports workflow_complete, finalization is allowed."""
        payload = {"ok": True, "data": {"workflow_complete": True}}
        self.assertTrue(should_finalize_locally("run_gee_dem_download_workflow", payload, ["gee"]))
        self.assertFalse(should_finalize_locally("run_gee_dem_download_workflow", payload, ["gee", "osm"]))

    def test_checkpoint_record_and_persist(self):
        with tempfile.TemporaryDirectory() as project_dir:
            run_dir = os.path.join(project_dir, ".qgis_agent_runs", "run_001")
            os.makedirs(run_dir, exist_ok=True)

            mgr = CheckpointManager(project_home=project_dir, run_dir=run_dir, run_id="run_001")
            cp1 = mgr.record_checkpoint(
                step_number=1,
                title="DEM填洼预处理",
                tool_name="run_processing_algorithm",
                inputs={"dem": "beijing_dem.tif"},
                outputs={"layers": ["beijing_dem_filled"], "files": ["beijing_dem_filled.tif"]},
                status="completed",
                notes="已完成填洼",
            )

            self.assertEqual(cp1.step_number, 1)
            self.assertEqual(cp1.status, "completed")
            self.assertTrue(os.path.exists(os.path.join(run_dir, "checkpoints.json")))

            # Test reload from file
            mgr2 = CheckpointManager(project_home=project_dir, run_dir=run_dir, run_id="run_001")
            self.assertEqual(len(mgr2.checkpoints), 1)
            last = mgr2.get_last_checkpoint()
            self.assertIsNotNone(last)
            self.assertEqual(last.title, "DEM填洼预处理")
            self.assertEqual(last.outputs["layers"], ["beijing_dem_filled"])

            # Test mark interrupted
            paused_cp = mgr2.mark_interrupted(title="用户暂停", reason="点击停止")
            self.assertEqual(paused_cp.status, "paused")
            card = mgr2.format_checkpoint_card(paused_cp)
            self.assertIn("⏸️", card)
            self.assertIn("执行节点已保存", card)

    def test_markdown_renderer_tables_and_code(self):
        bt = chr(96)
        raw_md = (
            "当前工程内共 **3 个图层**:\n\n"
            "| # | 图层名 | 类型 | 数据源 |\n"
            "|---|--------|------|--------|\n"
            "| 1 | beijing_boundary | 矢量 | " + bt + "data/beijing.geojson" + bt + " |\n"
            "| 2 | beijing_dem | 栅格 | " + bt + "data/dem.tif" + bt + " |\n"
        )
        html_out = render_markdown_to_html(raw_md)
        self.assertIn("<table", html_out)
        self.assertIn("<thead>", html_out)
        self.assertIn("<b>3 个图层</b>", html_out)
        self.assertIn("<code", html_out)

    def test_metro_stepper_rendering(self):
        stations = [
            {"title": "填洼预处理", "status": "completed"},
            {"title": "流向累积量", "status": "running"},
            {"title": "河网提取", "status": "pending"},
        ]
        html_out = render_metro_line_html(stations)
        self.assertIn("🚇 任务执行线路图", html_out)
        self.assertIn("✔", html_out)
        self.assertIn("🚆", html_out)
        self.assertIn("○", html_out)


if __name__ == "__main__":
    unittest.main()
