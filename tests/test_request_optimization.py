import os
import importlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from qgis_agent_plugin.core.local_continuation import should_finalize_locally
from qgis_agent_plugin.core.cache_metrics import build_structure_fingerprints
from qgis_agent_plugin.core.request_profile import (
    canonicalize_tool_schemas,
    detect_task_domains,
    expand_tool_names,
    frozen_tool_names,
)
from qgis_agent_plugin.core.step_runner import StepExecutionController
from qgis_agent_plugin.core.task_state import TaskPlan, TaskStep
from qgis_agent_plugin.core.tool_result import ToolResult
from qgis_agent_plugin.tools.qgis_tools.workflow_tools import run_osm_acquisition_workflow


class RequestProfileTests(unittest.TestCase):
    def test_ambiguous_school_acquisition_keeps_osm_tools_available(self):
        available = {
            "activate_domain_tools",
            "ask_human",
            "run_osm_acquisition_workflow",
            "download_osm_features",
        }
        names = frozen_tool_names("能获取海淀区这些学校吗？", available)
        self.assertIn("activate_domain_tools", names)
        self.assertIn("run_osm_acquisition_workflow", names)
        self.assertIn("download_osm_features", names)

    def test_domain_expansion_is_additive_and_deterministic(self):
        available = {
            "activate_domain_tools",
            "ask_human",
            "summarize_layers",
            "run_osm_acquisition_workflow",
            "download_osm_boundary",
            "download_osm_features",
        }
        initial = frozen_tool_names("帮我获取这些对象", available)
        expanded = expand_tool_names(initial, {"osm"}, available)
        repeated = expand_tool_names(expanded, {"osm"}, available)
        self.assertTrue(set(initial).issubset(expanded))
        self.assertIn("run_osm_acquisition_workflow", expanded)
        self.assertEqual(expanded, repeated)
        self.assertEqual(sorted(expanded), expanded)

    def test_osm_tool_pack_is_sorted_and_contains_high_level_workflow(self):
        available = {
            "ask_human",
            "summarize_layers",
            "validate_project_outputs",
            "save_project_and_verify",
            "search_project_layers",
            "describe_project_layer",
            "run_osm_acquisition_workflow",
            "download_osm_boundary",
            "download_osm_features",
            "clip_vector_layers_to_boundary",
            "submit_plan_for_approval",
        }
        names = frozen_tool_names("获取 OSM 边界、道路、建筑、POI 和水系", available, work_mode="PLAN")
        self.assertEqual(sorted(names), names)
        self.assertIn("run_osm_acquisition_workflow", names)
        self.assertIn("submit_plan_for_approval", names)
        self.assertIn("download_osm_features", names)

    def test_tool_results_cannot_change_detected_task_domains(self):
        task = "使用 GEE 下载 Sentinel-2 后进行波段计算和制图"
        first = detect_task_domains(task)
        second = detect_task_domains(task)
        self.assertEqual(first, second)
        self.assertIn("gee", first)
        self.assertIn("processing", first)
        self.assertIn("mapping", first)

    def test_tool_schema_canonicalization_is_deterministic(self):
        first = [{"function": {"name": "b", "parameters": {"z": 1, "a": 2}}, "type": "function"},
                 {"type": "function", "function": {"name": "a"}}]
        second = [{"function": {"name": "a"}, "type": "function"},
                  {"type": "function", "function": {"parameters": {"a": 2, "z": 1}, "name": "b"}}]
        self.assertEqual(canonicalize_tool_schemas(first), canonicalize_tool_schemas(second))
        self.assertEqual("a", canonicalize_tool_schemas(first)[0]["function"]["name"])

    def test_cache_sensitive_prefix_hashes_stay_fixed_as_results_append(self):
        context = "QGIS snapshot"
        tools = canonicalize_tool_schemas([
            {"type": "function", "function": {"name": "summarize_layers"}}
        ])
        initial = [
            {"role": "system", "content": "stable prompt"},
            {"role": "system", "content": context},
            {"role": "user", "content": "list layers"},
        ]
        grown = initial + [
            {"role": "assistant", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "structured result"},
        ]
        first = build_structure_fingerprints(initial, tools, context)
        second = build_structure_fingerprints(grown, tools, context)
        self.assertEqual(first, second)

    def test_controlled_tool_expansion_changes_only_tool_fingerprint(self):
        messages = [{"role": "system", "content": "stable prompt"}]
        initial_tools = canonicalize_tool_schemas([
            {"type": "function", "function": {"name": "activate_domain_tools"}},
        ])
        expanded_tools = canonicalize_tool_schemas(initial_tools + [
            {"type": "function", "function": {"name": "run_osm_acquisition_workflow"}},
        ])
        initial = build_structure_fingerprints(messages, initial_tools)
        expanded = build_structure_fingerprints(messages, expanded_tools)
        self.assertEqual(initial["stable_system_sha256"], expanded["stable_system_sha256"])
        self.assertNotEqual(initial["tool_schema_sha256"], expanded["tool_schema_sha256"])


class LocalContinuationTests(unittest.TestCase):
    def test_single_complete_osm_workflow_finishes_without_model(self):
        payload = {"ok": True, "data": {"workflow_complete": True}}
        self.assertTrue(should_finalize_locally(
            "run_osm_acquisition_workflow", payload, {"osm"}, response_result_count=1
        ))

    def test_followup_analysis_requires_new_decision(self):
        payload = {"ok": True, "data": {"workflow_complete": True}}
        self.assertFalse(should_finalize_locally(
            "run_osm_acquisition_workflow", payload, {"osm", "processing"}, response_result_count=1
        ))

    def test_complete_plan_finishes_after_local_verifier(self):
        payload = {"ok": True, "data": {}}
        self.assertTrue(should_finalize_locally(
            "run_processing_algorithm", payload, {"processing"}, plan_complete=True
        ))

    def test_simple_layer_summary_does_not_need_transition_round(self):
        payload = {"ok": True, "data": {"layer_count": 2, "layers": []}}
        self.assertTrue(should_finalize_locally(
            "summarize_layers", payload, set(), response_result_count=1
        ))

    def test_verifier_advances_two_planned_calls_in_one_response(self):
        plan = TaskPlan("two local steps", steps=[
            TaskStep("s1", "first"),
            TaskStep("s2", "second"),
        ])
        controller = StepExecutionController(plan=plan)
        controller.start_response()
        first_gate = controller.begin_tool_call("call-1", "run_processing_algorithm", {})
        self.assertTrue(first_gate.allowed)
        first_result = controller.complete_tool_call(
            "call-1", "run_processing_algorithm", {}, ToolResult.success("first done").to_json()
        )
        self.assertTrue(first_result.ok)
        second_gate = controller.begin_tool_call("call-2", "run_processing_algorithm", {})
        self.assertTrue(second_gate.allowed)
        second_result = controller.complete_tool_call(
            "call-2", "run_processing_algorithm", {}, ToolResult.success("second done").to_json()
        )
        self.assertTrue(second_result.ok)
        self.assertTrue(plan.all_passed())


class FakeLayer:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class FakeProject:
    _instance = None

    def __init__(self, home):
        self.home = home
        self.layers = {}

    @classmethod
    def instance(cls):
        return cls._instance

    def homePath(self):
        return self.home

    def mapLayer(self, _layer_id):
        return None

    def mapLayersByName(self, name):
        return [self.layers[name]] if name in self.layers else []


class OsmWorkflowSimulationTests(unittest.TestCase):
    def test_full_osm_bundle_runs_sequentially_and_verifies_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = FakeProject(temp_dir)
            FakeProject._instance = project
            fake_qgis = types.ModuleType("qgis")
            fake_core = types.ModuleType("qgis.core")
            fake_core.QgsProject = FakeProject
            fake_core.QgsMapLayerType = object
            fake_core.QgsVectorLayer = object
            fake_core.QgsRasterLayer = object
            fake_core.QgsExpression = object
            fake_core.Qgis = object
            fake_qgis.core = fake_core
            fake_processing = types.ModuleType("processing")
            calls = []
            progress = []

            def fake_execute(_iface, action, arguments, progress_callback=None, cancel_callback=None):
                calls.append((action, dict(arguments)))
                if progress_callback:
                    progress_callback({
                        "determinate": True,
                        "percent": 50,
                        "detail": action,
                        "stage": "download",
                    })
                output_file = arguments["output_file"]
                layer_name = arguments.get("layer_name") or "layer"
                with open(output_file, "wb") as handle:
                    handle.write(b"valid simulated vector output")
                project.layers[layer_name] = FakeLayer(layer_name)
                return ToolResult.success(
                    f"{action} complete",
                    data={"output_file": output_file, "layer_name": layer_name, "feature_count": 3},
                    artifacts=[{"path": output_file, "type": "vector"}],
                ).to_dict()

            with patch.dict(sys.modules, {
                "qgis": fake_qgis,
                "qgis.core": fake_core,
                "processing": fake_processing,
            }):
                tools_module = importlib.import_module("qgis_agent_plugin.tools.tools")
                with patch.object(tools_module, "execute_atomic_tool", side_effect=fake_execute):
                    result = run_osm_acquisition_workflow(
                        None,
                        place_name="Test District",
                        output_dir=temp_dir,
                        output_prefix="test",
                        overwrite=True,
                        progress_callback=progress.append,
                    )

            self.assertTrue(result["ok"])
            self.assertTrue(result["data"]["workflow_complete"])
            self.assertEqual(6, len(calls))
            self.assertEqual("download_osm_boundary", calls[0][0])
            self.assertEqual(
                ["roads", "buildings", "poi", "waterways", "water"],
                [call[1].get("preset") for call in calls[1:]],
            )
            self.assertEqual(6, len(result["data"]["expected_files"]))
            self.assertTrue(all(item["ok"] for item in result["data"]["verification"]))
            self.assertGreater(len(progress), 6)


if __name__ == "__main__":
    unittest.main()
