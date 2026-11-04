import sys
import tempfile
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

from qgis_agent_plugin.core.tool_registry import (  # noqa: E402
    BATCHABLE_TOOLS,
    build_all_tool_openai_schemas,
    get_tool_spec,
    validate_registry_health,
)
from qgis_agent_plugin.core.validators import validate_tool_call  # noqa: E402


class RegistryValidationTests(unittest.TestCase):
    def test_registry_health_and_schema_names(self):
        health = validate_registry_health()
        schemas = build_all_tool_openai_schemas()
        names = [item["function"]["name"] for item in schemas]
        self.assertTrue(health["ok"], health["issues"])
        self.assertEqual(health["tool_count"], len(schemas))
        self.assertEqual(len(names), len(set(names)))

    def test_domain_activation_control_is_registered_and_validated(self):
        spec = get_tool_spec("activate_domain_tools")
        self.assertEqual("low", spec.risk_level)
        self.assertFalse(spec.requires_qgis_main_thread)
        self.assertTrue(spec.read_only)
        self.assertTrue(validate_tool_call(
            "activate_domain_tools",
            {"domains": ["osm"], "reason": "The user clarified that the source is OSM."},
        ).ok)
        self.assertFalse(validate_tool_call(
            "activate_domain_tools",
            {"domains": ["unknown"], "reason": "invalid"},
        ).ok)

    def test_high_risk_tools_are_not_batchable(self):
        for name in (
            "execute_pyqgis_script",
            "install_python_package",
            "save_skill",
            "save_or_update_dynamic_skill",
        ):
            self.assertEqual("high", get_tool_spec(name).risk_level)
            self.assertNotIn(name, BATCHABLE_TOOLS)

    def test_main_thread_code_rejects_blocking_fallbacks_before_approval(self):
        self.assertTrue(validate_tool_call(
            "execute_pyqgis_script",
            {"code": "value = sum(range(10))", "is_destructive": False},
        ).ok)
        self.assertFalse(validate_tool_call(
            "execute_pyqgis_script",
            {"code": "while True:\n    pass", "is_destructive": False},
        ).ok)
        self.assertFalse(validate_tool_call(
            "execute_pyqgis_script",
            {"code": "import processing\nprocessing.run('native:buffer', {})", "is_destructive": False},
        ).ok)

    def test_external_layer_loader_is_registered_as_project_mutation(self):
        schema_names = [item["function"]["name"] for item in build_all_tool_openai_schemas()]
        spec = get_tool_spec("load_external_layer")
        self.assertIn("load_external_layer", schema_names)
        self.assertEqual("medium", spec.risk_level)
        self.assertTrue(spec.mutates_project)
        self.assertTrue(validate_tool_call(
            "load_external_layer", {"source_path": r"C:\data\outside.gpkg"}
        ).ok)

    def test_destructive_layer_and_data_removal_is_registered_and_validated(self):
        spec = get_tool_spec("remove_qgis_layers_and_data")
        self.assertEqual("high", spec.risk_level)
        self.assertTrue(spec.mutates_project)
        self.assertTrue(validate_tool_call(
            "remove_qgis_layers_and_data",
            {"scope": "all_layers", "delete_source_files": True},
        ).ok)
        self.assertFalse(validate_tool_call(
            "remove_qgis_layers_and_data",
            {"scope": "named_layers", "layer_names": [], "delete_source_files": False},
        ).ok)

    def test_batch_validation_rejects_unknown_and_invalid_children(self):
        unknown = validate_tool_call(
            "run_qgis_workflow_batch",
            {"steps": [{"action": "execute_pyqgis_script", "arguments": {"code": "print(1)"}}]},
        )
        invalid_child = validate_tool_call(
            "run_qgis_workflow_batch",
            {"steps": [{"action": "inspect_raster_file", "arguments": {}}]},
        )
        self.assertFalse(unknown.ok)
        self.assertFalse(invalid_child.ok)

    def test_package_install_allowlist_and_syntax(self):
        self.assertTrue(validate_tool_call("install_python_package", {"package_name": "pandas==2.2.0"}).ok)
        self.assertFalse(validate_tool_call("install_python_package", {"package_name": "unknown-package"}).ok)
        self.assertFalse(validate_tool_call("install_python_package", {"package_name": "pandas; whoami"}).ok)

    def test_gee_confirmation_and_parameter_validation(self):
        with tempfile.TemporaryDirectory() as output_dir:
            base = {
                "boundary_layer_name": "roi",
                "collection_id": "COPERNICUS/S2_SR_HARMONIZED",
                "start_date": "2024-01-01",
                "end_date": "2024-02-01",
                "bands": ["B2", "B3", "B4"],
                "cloud_pct": 20,
                "scale": 10,
                "processing_method": "median",
                "output_name": "s2_test",
                "output_dir": output_dir,
                "crs": "EPSG:4326",
                "load_layer": False,
                "user_confirmed_parameters": True,
            }
            self.assertTrue(validate_tool_call("run_gee_sentinel2_download_workflow", base).ok)
            missing_confirmation = dict(base, user_confirmed_parameters=False)
            bad_dates = dict(base, start_date="2024-03-01", end_date="2024-02-01")
            bad_crs = dict(base, crs="not-a-crs")
            bad_valid_percent = dict(base, min_valid_percent=101)
            self.assertFalse(validate_tool_call("run_gee_sentinel2_download_workflow", missing_confirmation).ok)
            self.assertFalse(validate_tool_call("run_gee_sentinel2_download_workflow", bad_dates).ok)
            self.assertFalse(validate_tool_call("run_gee_sentinel2_download_workflow", bad_crs).ok)
            self.assertFalse(validate_tool_call("run_gee_sentinel2_download_workflow", bad_valid_percent).ok)

    def test_osm_chunk_area_validation(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report = validate_tool_call("download_osm_features", {
                "bbox": "100,20,101,21",
                "preset": "buildings",
                "output_file": f"{output_dir}/buildings.gpkg",
                "layer_name": "buildings",
                "max_chunk_area": 0,
            })
            self.assertFalse(report.ok)


if __name__ == "__main__":
    unittest.main()
