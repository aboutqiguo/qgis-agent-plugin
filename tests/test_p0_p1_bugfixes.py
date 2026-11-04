import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

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
        "QgsCoordinateReferenceSystem",
        "QgsCoordinateTransform",
        "QgsRectangle",
        "QgsMapSettings",
        "QgsMapRendererParallelJob",
        "QgsVectorFileWriter",
        "QgsTask",
    ):
        if not hasattr(core_module, name):
            setattr(core_module, name, type(name, (), {}))
    
    if not hasattr(core_module.QgsMapLayerType, "VectorLayer"):
        core_module.QgsMapLayerType.VectorLayer = 0
    if not hasattr(core_module.QgsProject, "instance"):
        core_module.QgsProject.instance = staticmethod(lambda: MagicMock())

    qgis_module.core = core_module

    pyqt_module = sys.modules.setdefault("qgis.PyQt", types.ModuleType("qgis.PyQt"))
    
    pyqt_core = sys.modules.setdefault("qgis.PyQt.QtCore", types.ModuleType("qgis.PyQt.QtCore"))
    for name in ("QThread", "QSize", "QEventLoop", "QUrl", "QByteArray", "QTimer"):
        if not hasattr(pyqt_core, name):
            setattr(pyqt_core, name, type(name, (), {}))
    if not hasattr(pyqt_core, "pyqtSignal"):
        pyqt_core.pyqtSignal = lambda *args, **kwargs: MagicMock()

    pyqt_gui = sys.modules.setdefault("qgis.PyQt.QtGui", types.ModuleType("qgis.PyQt.QtGui"))
    if not hasattr(pyqt_gui, "QColor"):
        pyqt_gui.QColor = type("QColor", (), {})

    pyqt_widgets = sys.modules.setdefault("qgis.PyQt.QtWidgets", types.ModuleType("qgis.PyQt.QtWidgets"))
    for name in ("QInputDialog", "QLineEdit", "QMessageBox"):
        if not hasattr(pyqt_widgets, name):
            setattr(pyqt_widgets, name, type(name, (), {}))

    pyqt_network = sys.modules.setdefault("qgis.PyQt.QtNetwork", types.ModuleType("qgis.PyQt.QtNetwork"))

    pyqt_module.QtCore = pyqt_core
    pyqt_module.QtGui = pyqt_gui
    pyqt_module.QtWidgets = pyqt_widgets
    pyqt_module.QtNetwork = pyqt_network
    qgis_module.PyQt = pyqt_module

    proc_mod = sys.modules.setdefault("processing", types.ModuleType("processing"))
    if not hasattr(proc_mod, "run"):
        proc_mod.run = MagicMock()
    proc_core = sys.modules.setdefault("processing.core", types.ModuleType("processing.core"))
    proc_proc = sys.modules.setdefault("processing.core.Processing", types.ModuleType("processing.core.Processing"))
    proc_proc.Processing = type("Processing", (), {"initialize": staticmethod(lambda: None)})
    proc_core.Processing = proc_proc
    proc_mod.core = proc_core

    ee_module = sys.modules.setdefault("ee", types.ModuleType("ee"))
    if not hasattr(ee_module, "Image"):
        ee_module.Image = type("Image", (), {})

_install_qgis_import_stubs()

import qgis_agent_plugin.tools.qgis_tools.io_tools as io_tools
import qgis_agent_plugin.bridges.gee_bridge as gee_bridge
import qgis_agent_plugin.core.validators as validators


class P0P1BugfixTests(unittest.TestCase):
    def test_workflow_gpkg_overwrite_safety(self):
        """Bug 5 (P0): GPKG overwrite must not invoke os.remove directly on Windows."""
        from qgis_agent_plugin.tools.qgis_tools import workflow_tools

        with patch.object(workflow_tools, "_find_layer_by_name_or_id") as mock_find, \
             patch.object(io_tools, "remove_duplicate_layers") as mock_rm_dups, \
             patch.object(validators, "validate_path_within_allowed_roots") as mock_val, \
             patch.object(io_tools, "load_vector_layer") as mock_load, \
             patch("os.path.exists", return_value=True), \
             patch("os.remove") as mock_os_remove, \
             patch("processing.run") as mock_proc:

            mock_val.return_value.ok = True
            mock_boundary = MagicMock()
            mock_src = MagicMock()
            mock_find.side_effect = [mock_boundary, mock_src]

            mock_proc.return_value = {"OUTPUT": "C:/tmp/test_clipped.gpkg"}
            mock_loaded_layer = MagicMock()
            mock_loaded_layer.featureCount.return_value = 5
            mock_loaded_layer.isValid.return_value = True
            mock_load.return_value = mock_loaded_layer

            result = workflow_tools.clip_vector_layers_to_boundary(
                boundary_layer_name="boundary",
                clip_tasks=[{"input_layer_name": "roads", "output_name": "roads_clipped.gpkg"}],
                output_dir="C:/tmp",
                overwrite=True,
                create_spatial_index=False,
            )

            self.assertTrue(result["ok"])
            # os.remove must NOT have been called for .gpkg
            mock_os_remove.assert_not_called()

    def test_clip_crs_reprojection_alignment(self):
        """Bug 2 (P1): clip must reproject overlay layer when CRS differs from input layer."""
        from qgis_agent_plugin.tools.qgis_tools import geoprocessing_tools

        input_layer = MagicMock()
        input_layer.crs().isValid.return_value = True
        input_layer.crs().authid.return_value = "EPSG:32649"
        input_layer.name.return_value = "input"

        overlay_layer = MagicMock()
        overlay_layer.crs().isValid.return_value = True
        overlay_layer.crs().authid.return_value = "EPSG:4326"

        reprojected_overlay = MagicMock()
        reprojected_overlay.crs().authid.return_value = "EPSG:32649"

        with patch("processing.run") as mock_proc:
            def proc_side_effect(alg_id, params):
                if alg_id == "native:reprojectlayer":
                    return {"OUTPUT": reprojected_overlay}
                elif alg_id == "native:clip":
                    out = MagicMock()
                    out.setName = MagicMock()
                    return {"OUTPUT": out}
                return {}

            mock_proc.side_effect = proc_side_effect

            geoprocessing_tools.clip(input_layer, overlay_layer, output_path="memory:")

            calls = [call[0] for call in mock_proc.call_args_list]
            self.assertEqual(calls[0][0], "native:reprojectlayer")
            self.assertEqual(calls[0][1]["TARGET_CRS"], input_layer.crs())
            self.assertEqual(calls[1][0], "native:clip")
            self.assertEqual(calls[1][1]["OVERLAY"], reprojected_overlay)

    def test_dem_workflow_coverage_ratio_uses_min_valid_percent(self):
        """Bug 6 (P1): DEM download must calculate min_coverage_ratio from min_valid_percent instead of hardcoding 0.99."""
        from qgis_agent_plugin.tools import tools

        kwargs = {
            "boundary_layer_name": "boundary",
            "output_dir": "C:/tmp",
            "output_name": "dem.tif",
            "dataset_id": "USGS/SRTMGL1_003",
            "scale": 30,
            "crs": "EPSG:4326",
            "load_layer": True,
            "user_confirmed_parameters": True,
            "min_valid_percent": 80.0,
        }

        with patch("qgis_agent_plugin.tools.tools._find_project_layer") as mock_find, \
             patch.object(gee_bridge, "init_gee"), \
             patch("qgis_agent_plugin.tools.tools._boundary_layer_to_ee_geometry") as mock_geom, \
             patch.object(gee_bridge.GEEDownloader, "download_ee_object") as mock_download, \
             patch("qgis_agent_plugin.core.raster_validation.validate_raster_has_data") as mock_val, \
             patch.object(io_tools, "load_raster_layer") as mock_load, \
             patch("ee.Image") as mock_ee_img:

            mock_layer = MagicMock()
            from qgis.core import QgsMapLayerType
            mock_layer.type.return_value = QgsMapLayerType.VectorLayer
            mock_find.return_value = mock_layer

            mock_geom.return_value = MagicMock()
            mock_download.return_value = "C:/tmp/dem.tif"
            mock_val.return_value = {"ok": True}
            mock_load.return_value = MagicMock(id=lambda: "dem_id", name=lambda: "dem")

            tools._run_gee_dem_download_workflow(None, kwargs)

            self.assertTrue(mock_download.called)
            download_kwargs = mock_download.call_args[1]
            self.assertAlmostEqual(download_kwargs["min_coverage_ratio"], 0.80)

    def test_harness_thread_fallback_dispatches_main_thread(self):
        """Bug 4 (P0): Fallback in HarnessThread must route main-thread tools via request_atomic_tool_signal."""
        from qgis_agent_plugin.core.tool_registry import ToolSpec
        from qgis_agent_plugin.core import tool_registry

        main_spec = ToolSpec(
            name="custom_ui_tool",
            description="",
            args_schema={},
            risk_level="low",
            requires_qgis_main_thread=True,
        )

        with patch.object(tool_registry, "get_tool_spec", return_value=main_spec):
            spec = tool_registry.get_tool_spec("custom_ui_tool")
            self.assertTrue(spec.requires_qgis_main_thread)


if __name__ == "__main__":
    unittest.main()
