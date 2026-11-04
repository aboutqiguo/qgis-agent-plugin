import os
import importlib
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from qgis_agent_plugin.core.mode_state import (
    build_gee_retry_message,
    is_gee_retry_confirmation,
)
from qgis_agent_plugin.core.path_access import grant_write_access, revoke_write_access
from qgis_agent_plugin.core.validators import (
    redirect_external_outputs_to_project,
    validate_path_within_allowed_roots,
)
from qgis_agent_plugin.tools.qgis_tools.external_data import _stream_copy


class ExternalPathGrantTests(unittest.TestCase):
    def test_explicit_one_task_grant_allows_only_the_selected_parent(self):
        target = r"C:\qgis-agent-external-test\result.gpkg"
        before = validate_path_within_allowed_roots(target, "output_file")
        self.assertFalse(before.ok)

        root = grant_write_access(target)
        try:
            self.assertTrue(validate_path_within_allowed_roots(target, "output_file").ok)
            self.assertFalse(validate_path_within_allowed_roots(
                r"C:\another-qgis-agent-test\result.gpkg", "output_file"
            ).ok)
        finally:
            revoke_write_access([root])

    def test_external_output_can_be_redirected_into_saved_project(self):
        with tempfile.TemporaryDirectory() as project_home:
            args = {"project_path": r"C:\qgis-agent-external-test\analysis.qgz"}
            changes = redirect_external_outputs_to_project(
                "save_project_and_verify", args, project_home
            )
            self.assertEqual(1, len(changes))
            self.assertTrue(args["project_path"].startswith(project_home))
            self.assertTrue(args["project_path"].endswith("analysis.qgz"))


class ExternalCopyTests(unittest.TestCase):
    def test_stream_copy_handles_regular_files_without_platform_copy_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "source.bin")
            target = os.path.join(temp_dir, "nested", "target.bin")
            payload = b"qgis-agent" * 1024
            with open(source, "wb") as handle:
                handle.write(payload)
            _stream_copy(source, target, chunk_size=37)
            with open(target, "rb") as handle:
                self.assertEqual(payload, handle.read())


class ProjectDataRemovalTests(unittest.TestCase):
    class _FakeLayer:
        def __init__(self, layer_id, name, source):
            self._id = layer_id
            self._name = name
            self._source = source

        def id(self):
            return self._id

        def name(self):
            return self._name

        def source(self):
            return self._source

    class _FakeProject:
        _instance = None

        def __init__(self, layers):
            self.layers = {layer.id(): layer for layer in layers}

        @classmethod
        def instance(cls):
            return cls._instance

        def mapLayers(self):
            return dict(self.layers)

        def removeMapLayer(self, layer_id):
            self.layers.pop(layer_id)

        def fileName(self):
            return ""

    def _tools_with_fake_qgis(self):
        qgis_module = types.ModuleType("qgis")
        core_module = types.ModuleType("qgis.core")
        core_module.QgsProject = self._FakeProject
        core_module.QgsApplication = type("QgsApplication", (), {"processEvents": staticmethod(lambda: None)})
        core_module.QgsMapLayerType = object
        core_module.QgsVectorLayer = object
        core_module.QgsRasterLayer = object
        core_module.QgsExpression = object
        core_module.Qgis = object
        qgis_module.core = core_module
        return patch.dict(sys.modules, {
            "qgis": qgis_module,
            "qgis.core": core_module,
            "processing": types.ModuleType("processing"),
        })

    def test_removes_all_layers_and_their_local_source_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "roads.geojson")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write('{"type":"FeatureCollection","features":[]}')
            self._FakeProject._instance = self._FakeProject([
                self._FakeLayer("roads-id", "roads", source),
                self._FakeLayer("memory-id", "temporary", "memory:temporary"),
            ])
            with self._tools_with_fake_qgis():
                tools_module = importlib.import_module("qgis_agent_plugin.tools.tools")
                result = tools_module._remove_qgis_layers_and_data({
                    "scope": "all_layers",
                    "delete_source_files": True,
                    "save_project": False,
                })

            self.assertTrue(result["ok"])
            self.assertFalse(os.path.exists(source))
            self.assertEqual(0, len(self._FakeProject._instance.mapLayers()))
            self.assertEqual(1, len(result["data"]["removed_files"]))

    def test_named_removal_preserves_a_source_still_used_by_another_layer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "shared.gpkg")
            with open(source, "wb") as handle:
                handle.write(b"simulated gpkg")
            self._FakeProject._instance = self._FakeProject([
                self._FakeLayer("one", "selected", source + "|layername=one"),
                self._FakeLayer("two", "retained", source + "|layername=two"),
            ])
            with self._tools_with_fake_qgis():
                tools_module = importlib.import_module("qgis_agent_plugin.tools.tools")
                result = tools_module._remove_qgis_layers_and_data({
                    "scope": "named_layers",
                    "layer_names": ["selected"],
                    "delete_source_files": True,
                    "save_project": False,
                })

            self.assertTrue(result["ok"])
            self.assertTrue(os.path.exists(source))
            self.assertEqual(1, len(self._FakeProject._instance.mapLayers()))
            self.assertEqual("retained", next(iter(self._FakeProject._instance.mapLayers().values())).name())
            self.assertIn("source is also used", result["data"]["skipped_sources"][0]["reason"])


class GeeRecoveryTests(unittest.TestCase):
    def test_short_configuration_acknowledgement_reuses_confirmed_parameters(self):
        context = {
            "kind": "gee_retry",
            "tool_name": "run_gee_sentinel2_download_workflow",
            "arguments": {"bands": ["B2", "B3", "B4"], "scale": 10},
            "failure_message": "Earth Engine API was disabled.",
        }
        self.assertTrue(is_gee_retry_confirmation("通过了", context))
        message = build_gee_retry_message("通过了", context)
        self.assertIn("run_gee_sentinel2_download_workflow", message)
        self.assertIn('"scale": 10', message)
        self.assertFalse(is_gee_retry_confirmation("请重新下载完整的另一份数据", context))

    def test_explicit_project_is_preflighted_and_disabled_api_is_actionable(self):
        initialized_projects = []

        class FakeNumber:
            def __init__(self, error=None):
                self.error = error

            def getInfo(self):
                if self.error:
                    raise self.error
                return 1

        ee_module = types.ModuleType("ee")
        ee_module.Initialize = lambda *, project: initialized_projects.append(project)
        ee_module.Number = lambda _value: FakeNumber()

        qgis_module = types.ModuleType("qgis")
        pyqt_module = types.ModuleType("qgis.PyQt")
        widgets_module = types.ModuleType("qgis.PyQt.QtWidgets")
        widgets_module.QInputDialog = object
        widgets_module.QLineEdit = object
        widgets_module.QMessageBox = type("MessageBox", (), {"Cancel": 0, "Ok": 1})
        core_module = types.ModuleType("qgis.core")
        core_module.QgsProject = object
        core_module.QgsRasterLayer = object
        core_module.QgsTask = type("QgsTask", (), {"CanCancel": 1, "Terminated": 2})
        core_module.Qgis = type("Qgis", (), {"MessageLevel": type("Level", (), {"Warning": 1, "Critical": 2, "Success": 3})})
        utils_module = types.ModuleType("qgis.utils")
        utils_module.iface = object()
        qgis_module.PyQt = pyqt_module
        qgis_module.core = core_module
        pyqt_module.QtWidgets = widgets_module

        module_name = "qgis_agent_plugin.bridges._gee_bridge_simulation"
        bridge_path = Path(__file__).resolve().parents[1] / "qgis_agent_plugin" / "bridges" / "gee_bridge.py"
        modules = {
            "ee": ee_module,
            "qgis": qgis_module,
            "qgis.PyQt": pyqt_module,
            "qgis.PyQt.QtWidgets": widgets_module,
            "qgis.core": core_module,
            "qgis.utils": utils_module,
        }
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location(module_name, bridge_path)
            bridge = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = bridge
            try:
                spec.loader.exec_module(bridge)
                self.assertTrue(bridge.GEEAuth._initialize_and_verify("selected-project"))
                self.assertEqual(["selected-project"], initialized_projects)

                ee_module.Number = lambda _value: FakeNumber(
                    Exception("Google Earth Engine API has not been used in project disabled-project before or it is disabled.")
                )
                with self.assertRaises(bridge.GEEProjectConfigurationError) as error:
                    bridge.GEEAuth._initialize_and_verify("selected-project")
                self.assertIn("console.cloud.google.com", str(error.exception))
                self.assertIn("disabled-project", str(error.exception))
            finally:
                sys.modules.pop(module_name, None)


if __name__ == "__main__":
    unittest.main()
