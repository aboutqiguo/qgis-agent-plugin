import os
import tempfile
import unittest

from qgis_agent_plugin.core.planner import build_task_plan_from_markdown, build_task_plan_from_payload
from qgis_agent_plugin.core.tool_result import ToolResult
from qgis_agent_plugin.core.verifier import verify_step


class PlannerContractTests(unittest.TestCase):
    def test_typed_plan_does_not_trust_model_status(self):
        plan = build_task_plan_from_payload({
            "objective": "download",
            "steps": [{
                "step_id": "download",
                "title": "create result.tif",
                "status": "passed",
                "expected_outputs": [{"type": "raster_file", "path": "result.tif"}],
            }],
        })
        self.assertEqual("pending", plan.steps[0].status)
        self.assertEqual("raster_file", plan.steps[0].expected_outputs[0]["type"])

    def test_markdown_plan_infers_file_contract(self):
        plan = build_task_plan_from_markdown("# Test\n- [ ] 生成 `roads.gpkg`")
        self.assertIn("roads.gpkg", plan.steps[0].expected_files)
        self.assertEqual("file", plan.steps[0].expected_outputs[0]["type"])

    def test_verifier_rejects_missing_expected_file(self):
        with tempfile.TemporaryDirectory() as folder:
            plan = build_task_plan_from_markdown("- [ ] create missing.gpkg")
            result = verify_step(
                plan.steps[0],
                "run_processing_algorithm",
                ToolResult.success("algorithm returned").to_json(),
                project_home=folder,
            )
            self.assertFalse(result.ok)
            self.assertTrue(any(check.get("name") == "expected_file_exists" for check in result.checks))

    def test_verifier_accepts_existing_generic_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "result.gpkg")
            with open(path, "wb") as handle:
                handle.write(b"not-empty")
            plan = build_task_plan_from_markdown("- [ ] create result.gpkg")
            result = verify_step(
                plan.steps[0],
                "run_processing_algorithm",
                ToolResult.success("algorithm returned").to_json(),
                project_home=folder,
            )
            self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
