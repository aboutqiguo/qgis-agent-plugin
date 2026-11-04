# -*- coding: utf-8 -*-
"""Regression tests for optimizations derived from the 2026-11-03 21:16-21:41 agent_run.log."""

import os
import sys
import tempfile
import types
import unittest

import numpy as np


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

from qgis_agent_plugin.core.code_execution_guard import (
    autofix_gdal_temporary_datasets,
    execute_main_thread_code,
)
from qgis_agent_plugin.core.message_protocol import reconcile_tool_messages
from qgis_agent_plugin.core.raster_validation import (
    compute_raster_index,
    compute_raster_zonal_stats,
)
from qgis_agent_plugin.core.request_profile import (
    detect_task_domains,
    frozen_tool_names,
    strip_negated_phrases,
)
from qgis_agent_plugin.core.tool_registry import build_all_tool_openai_schemas
from qgis_agent_plugin.core.tool_result import ToolResult, classify_error
from qgis_agent_plugin.core.validators import validate_pyqgis_code, validate_tool_call


class _InMemoryGdalBand:
    def __init__(self, arr: np.ndarray, nodata=None, desc: str = ""):
        self._arr = arr
        self._nodata = nodata
        self._desc = desc
        self.DataType = 6 if arr.dtype == np.float32 else (2 if arr.dtype == np.uint16 else 1)

    def ReadAsArray(self):
        return self._arr.copy()

    def WriteArray(self, arr):
        self._arr = np.array(arr, copy=True)

    def GetNoDataValue(self):
        return self._nodata

    def SetNoDataValue(self, val):
        self._nodata = float(val)

    def GetDescription(self):
        return self._desc

    def SetDescription(self, desc):
        self._desc = str(desc)

    def GetStatistics(self, _approx, _force):
        valid = self._arr[np.isfinite(self._arr)]
        if self._nodata is not None:
            valid = valid[valid != self._nodata]
        if valid.size == 0:
            return [0.0, 0.0, 0.0, 0.0]
        return [float(valid.min()), float(valid.max()), float(valid.mean()), float(valid.std())]

    def GetMetadata(self):
        if self._nodata is None:
            return {"STATISTICS_VALID_PERCENT": "100.0"}
        valid = np.isfinite(self._arr) & (self._arr != self._nodata)
        pct = 100.0 * float(valid.sum()) / max(1, self._arr.size)
        return {"STATISTICS_VALID_PERCENT": str(pct)}

    def Checksum(self):
        return int(np.abs(self._arr).sum()) % 65536

    def FlushCache(self):
        pass


class _InMemoryGdalDataset:
    def __init__(self, path: str, width: int, height: int, bands):
        self.path = path
        self.RasterXSize = width
        self.RasterYSize = height
        self.RasterCount = len(bands)
        self._bands = bands
        self._gt = (816370.0, 10.0, 0.0, 2396050.0, 0.0, -10.0)
        self._proj = 'PROJCS["WGS 84 / UTM zone 48N",AUTHORITY["EPSG","32648"]]'

    def GetDriver(self):
        return types.SimpleNamespace(ShortName="GTiff")

    def GetGeoTransform(self, can_return_null=False):
        return self._gt

    def SetGeoTransform(self, gt):
        self._gt = tuple(gt)

    def GetProjection(self):
        return self._proj

    def SetProjection(self, proj):
        self._proj = str(proj)

    def GetRasterBand(self, idx: int):
        return self._bands[idx - 1]

    def FlushCache(self):
        if self.path:
            np.savez(
                self.path,
                gt=np.array(self._gt),
                proj=np.array(self._proj),
                nodata=np.array([b.GetNoDataValue() if b.GetNoDataValue() is not None else np.nan for b in self._bands]),
                desc=np.array([b.GetDescription() for b in self._bands]),
                **{f"b{i}": b._arr for i, b in enumerate(self._bands)},
            )
            # Ensure exact path exists on disk (np.savez appends .npz if not ending in .npz)
            if os.path.exists(self.path + ".npz"):
                os.replace(self.path + ".npz", self.path)


def _install_fake_osgeo_gdal():
    osgeo_mod = types.ModuleType("osgeo")
    gdal_mod = types.ModuleType("osgeo.gdal")
    gdal_mod.GA_ReadOnly = 0
    gdal_mod.GDT_Byte = 1
    gdal_mod.GDT_UInt16 = 2
    gdal_mod.GDT_Float32 = 6

    def UseExceptions():
        pass

    def GetDataTypeName(dt):
        return {1: "Byte", 2: "UInt16", 6: "Float32"}.get(dt, "Float32")

    def Open(path, _mode=0):
        if not os.path.exists(path):
            return None
        with np.load(path, allow_pickle=False) as data:
            keys = sorted([k for k in data.files if k.startswith("b")], key=lambda x: int(x[1:]))
            nodatas = data["nodata"]
            descs = data["desc"]
            bands = []
            for idx, k in enumerate(keys):
                nd = None if np.isnan(nodatas[idx]) else float(nodatas[idx])
                bands.append(_InMemoryGdalBand(data[k], nodata=nd, desc=str(descs[idx])))
            h, w = bands[0]._arr.shape
            ds = _InMemoryGdalDataset(path, w, h, bands)
            ds._gt = tuple(float(x) for x in data["gt"])
            ds._proj = str(data["proj"])
            return ds

    class _Driver:
        def Create(self, path, width, height, band_count, dtype, options=None):
            np_dtype = {1: np.uint8, 2: np.uint16, 6: np.float32}.get(dtype, np.float32)
            bands = [_InMemoryGdalBand(np.zeros((height, width), dtype=np_dtype)) for _ in range(band_count)]
            return _InMemoryGdalDataset(path, width, height, bands)

    def GetDriverByName(_name):
        return _Driver()

    gdal_mod.UseExceptions = UseExceptions
    gdal_mod.GetDataTypeName = GetDataTypeName
    gdal_mod.Open = Open
    gdal_mod.GetDriverByName = GetDriverByName
    osgeo_mod.gdal = gdal_mod
    return osgeo_mod, gdal_mod


class Log2141OptimizationTests(unittest.TestCase):
    def test_tool_result_failure_accepts_artifacts(self):
        """Fix for log line 1036: ToolResult.failure() got an unexpected keyword argument 'artifacts'."""
        res = ToolResult.failure(
            "OSM workflow stopped",
            error_type="operation_cancelled",
            data={"partial": True},
            artifacts=[{"type": "vector_layer", "path": "roads.gpkg"}],
        )
        self.assertFalse(res.ok)
        self.assertEqual(1, len(res.artifacts))
        self.assertEqual("roads.gpkg", res.artifacts[0]["path"])

    def test_classify_error_does_not_flag_pyqgis_docs_or_skills(self):
        """Fix for log line 1208: query_pyqgis_doc and read_skill falsely marked ok=False (file_path_error)."""
        doc_output = (
            "--- Native PyQGIS Docs for 'QgsRasterBandStats' ---\n"
            "Class QgsRasterBandStats:\n"
            "  minimumValue: float (returns invalid value if not computed)\n"
            "  maximumValue: float (read from raster file)\n"
        )
        self.assertIsNone(classify_error(doc_output))

        skill_output = (
            "<skill>\n"
            "name: qgis_gdal_quirks\n"
            "When a raster file is invalid or locked, release the layer first.\n"
            "</skill>"
        )
        self.assertIsNone(classify_error(skill_output))

    def test_autofix_gdal_temporary_datasets_keeps_dataset_alive(self):
        """Fix for log lines 107, 601, 1426: gdal.Open(p).GetRasterBand(1).ReadAsArray() SWIG crash."""
        code = (
            "arr = gdal.Open(msk_path).GetRasterBand(1).ReadAsArray()\n"
            "gt = gdal.Open(img_path).GetGeoTransform()\n"
        )
        fixed, count = autofix_gdal_temporary_datasets(code)
        self.assertEqual(2, count)
        self.assertIn("_qgis_agent_keep(gdal.Open(msk_path)).GetRasterBand(1).ReadAsArray()", fixed)
        self.assertIn("_qgis_agent_keep(gdal.Open(img_path)).GetGeoTransform()", fixed)

        alive = {"open": False}

        class DummyBand:
            def ReadAsArray(self):
                if not alive["open"]:
                    raise TypeError("in method 'Band_XSize_get', argument 1 of type 'GDALRasterBandShadow *'")
                return [1, 2, 3]

        class DummyDataset:
            def __init__(self):
                alive["open"] = True

            def GetRasterBand(self, _idx):
                return DummyBand()

            def __del__(self):
                alive["open"] = False

        class DummyGdal:
            @staticmethod
            def Open(_path):
                return DummyDataset()

        ns = {"gdal": DummyGdal, "msk_path": "dummy.tif"}
        execute_main_thread_code("arr = gdal.Open(msk_path).GetRasterBand(1).ReadAsArray()", ns)
        self.assertEqual([1, 2, 3], ns["arr"])

    def test_validators_catch_qgis_344_raster_band_stats_hallucinations(self):
        """Fix for log lines 450, 1115, 1152: prov.bandName(b), st.minimum, st.mean()."""
        r1 = validate_pyqgis_code("name = prov.bandName(1)")
        self.assertFalse(r1.ok)
        self.assertTrue(any("QgsRasterDataProvider does not have a bandName" in i.message for i in r1.issues))

        r2 = validate_pyqgis_code("st = prov.bandStatistics(1)\nmn = st.minimum\nmx = st.maximum")
        self.assertFalse(r2.ok)
        self.assertTrue(any("minimumValue" in i.suggestion for i in r2.issues))

        r3 = validate_pyqgis_code("st = prov.bandStatistics(1)\nm = st.mean()")
        self.assertFalse(r3.ok)
        self.assertTrue(any("float attribute" in i.message for i in r3.issues))

    def test_validators_catch_morning_log_rendering_and_gdal_dtype_pitfalls(self):
        """Fix for 2026-11-04 morning log lines 2129, 2295, 2662, 2848, 3019."""
        # 1. setClassificationMode(QgsColorRampShader.Discrete) or integer literal
        c1 = validate_pyqgis_code("fn.setClassificationMode(QgsColorRampShader.Discrete)")
        self.assertFalse(c1.ok)
        self.assertTrue(any("setColorRampType" in i.suggestion for i in c1.issues))

        c2 = validate_pyqgis_code("fn.setClassificationMode(1)")
        self.assertFalse(c2.ok)

        # 2. QgsVectorLayer.renderSettings()
        c3 = validate_pyqgis_code("zl.renderSettings().setOpacity(1.0)")
        self.assertFalse(c3.ok)
        self.assertTrue(any("renderSettings" in i.message for i in c3.issues))

        # 3. gdal_array.GDALTypeToNumpyType
        c4 = validate_pyqgis_code("npdt = gdal_array.GDALTypeToNumpyType(gdt)")
        self.assertFalse(c4.ok)
        self.assertTrue(any("GDALTypeCodeToNumericTypeCode" in i.suggestion for i in c4.issues))

        # 4. arr.astype(dtype) where dtype = gdal.GDT_Float32
        c5 = validate_pyqgis_code(
            "def write(arr, dtype):\n    b.WriteArray(arr.astype(dtype))\nwrite(a, gdal.GDT_Float32)"
        )
        self.assertFalse(c5.ok)
        self.assertTrue(any("integer enums" in i.message for i in c5.issues))

    def test_negated_osm_phrase_does_not_activate_osm_domain(self):
        """Fix for log line 1040: '跳过 osm数据，继续执行步骤 2' wrongly routed to domains=['osm']."""
        prompt = "跳过 osm数据，继续执行步骤 2（多光谱特征掩膜分析）"
        cleaned = strip_negated_phrases(prompt.lower())
        self.assertNotIn("osm", cleaned)
        domains = detect_task_domains(prompt)
        self.assertNotIn("osm", domains)
        self.assertIn("processing", domains)

    def test_local_raster_mask_stats_routes_to_processing_not_gee(self):
        """Fix for log line 10: local mask + multiband stats routed to 'processing' with new raster tools."""
        prompt = "基于 shijian_mask 分析 shijiao_2019101 各波段统计特征与 NDVI/NDWI"
        domains = detect_task_domains(prompt)
        self.assertIn("processing", domains)
        self.assertNotIn("gee", domains)
        available = {item["function"]["name"] for item in build_all_tool_openai_schemas()}
        frozen = frozen_tool_names(prompt, available)
        self.assertIn("compute_raster_zonal_stats", frozen)
        self.assertIn("compute_raster_index", frozen)

    def test_in_place_reconcile_tool_messages_preserves_list_reference(self):
        """Fix for repeated call_00_ET_QRmovBixLLhfl66Z6W5X9118 repair across turns."""
        global_messages = [
            {"role": "system", "content": "stable prompt"},
            {"role": "user", "content": "task 1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_interrupted_1",
                        "type": "function",
                        "function": {"name": "summarize_layers", "arguments": "{}"},
                    }
                ],
            },
        ]
        cancelled_json = ToolResult.failure("interrupted", error_type="operation_cancelled").to_json()
        repaired, repairs = reconcile_tool_messages(global_messages, cancelled_json)
        global_messages[:] = repaired
        self.assertEqual(1, len(repairs))
        repaired_again, repairs_again = reconcile_tool_messages(global_messages, cancelled_json)
        self.assertEqual(0, len(repairs_again))

    def test_compute_raster_zonal_stats_and_index_on_synthetic_uint16_tiff(self):
        """Verify compute_raster_zonal_stats and compute_raster_index prevent UInt16 underflow."""
        osgeo_mod, gdal_mod = _install_fake_osgeo_gdal()
        old_osgeo = sys.modules.get("osgeo")
        old_gdal = sys.modules.get("osgeo.gdal")
        sys.modules["osgeo"] = osgeo_mod
        sys.modules["osgeo.gdal"] = gdal_mod
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                img_path = os.path.join(tmpdir, "sentinel_test.tif")
                msk_path = os.path.join(tmpdir, "mask_test.tif")
                ndvi_path = os.path.join(tmpdir, "ndvi_out.tif")

                drv = gdal_mod.GetDriverByName("GTiff")
                ds = drv.Create(img_path, 10, 10, 4, gdal_mod.GDT_UInt16)

                mask_arr = np.zeros((10, 10), dtype=np.uint8)
                mask_arr[2:5, 2:5] = 1

                # In background (mask=0), Band 3 (Red=2000) > Band 4 (NIR=1000)
                # Naive UInt16 gdal_calc underflows (1000-2000 -> 64536 -> ratio=21.5)!
                b1 = np.full((10, 10), 500, dtype=np.uint16)
                b2 = np.where(mask_arr == 1, 1200, 800).astype(np.uint16)
                b3 = np.where(mask_arr == 1, 600, 2000).astype(np.uint16)
                b4 = np.where(mask_arr == 1, 3000, 1000).astype(np.uint16)
                for idx, arr in enumerate([b1, b2, b3, b4], start=1):
                    ds.GetRasterBand(idx).WriteArray(arr)
                ds.FlushCache()

                mds = drv.Create(msk_path, 10, 10, 1, gdal_mod.GDT_Byte)
                mds.GetRasterBand(1).WriteArray(mask_arr)
                mds.FlushCache()

                stats_res = compute_raster_zonal_stats(
                    source_layer_or_path=img_path,
                    mask_layer_or_path=msk_path,
                    mask_valid_value=1.0,
                )
                self.assertTrue(stats_res["ok"], stats_res)
                self.assertEqual(4, stats_res["data"]["band_count"])
                self.assertEqual(9, stats_res["data"]["target_pixels"])
                self.assertEqual(91, stats_res["data"]["background_pixels"])

                # Full-scene NDVI without mask filter (tests negative values stay >= -1.0)
                idx_full = compute_raster_index(
                    source_layer_or_path=img_path,
                    output_path=ndvi_path,
                    band_a=4,
                    band_b=3,
                    index_name="NDVI",
                    load_layer=False,
                )
                self.assertTrue(idx_full["ok"], idx_full)
                st = idx_full["data"]["statistics"]
                self.assertGreaterEqual(st["min"], -1.0)
                self.assertLessEqual(st["max"], 1.0)
                self.assertAlmostEqual(-0.3333, st["min"], places=3)
                self.assertAlmostEqual(0.6667, st["max"], places=3)
        finally:
            if old_osgeo is None:
                sys.modules.pop("osgeo", None)
            else:
                sys.modules["osgeo"] = old_osgeo
            if old_gdal is None:
                sys.modules.pop("osgeo.gdal", None)
            else:
                sys.modules["osgeo.gdal"] = old_gdal

    def test_metro_station_title_sanitization_prevents_long_sentence_overflow(self):
        """Fix for UI overlap bug: 70-char sentence in MetroStationWidget must be capped to <=10 chars."""
        from qgis_agent_plugin.ui.metro_progress import sanitize_station_title

        long_sentence = (
            "1. 与工程内已有 shijiao_2019101_named.tif 的首波段校验和一致（41550），"
            "其元数据给出 B2、B3、B4、B5、B6、B7、B8、B8A、B11、B12 的顺序；"
        )
        cleaned = sanitize_station_title(long_sentence, default_index=1)
        self.assertTrue(cleaned.startswith("1. "))
        body = cleaned.split(" ", 1)[1]
        self.assertLessEqual(len(body), 10)
        self.assertNotIn("41550", body)
        self.assertNotIn("B12", body)

        self.assertEqual("1. 图层数据清理", sanitize_station_title("remove_qgis_layers_and_data", 1))
        self.assertEqual("2. 外部图层加载", sanitize_station_title("load_external_layer", 2))

    def test_markdown_renderer_preserves_snake_case_and_pre_blocks(self):
        """Fix for UI underscore eating bug in thinking blocks and tool identifiers."""
        from qgis_agent_plugin.ui.markdown_renderer import render_markdown_to_html

        md = (
            "Use `execute_pyqgis_script` and `remove_qgis_layers_and_data`.\n"
            "Now ask_human about shijian_mask.png and shijiao_2019101.\n"
            '<div style="color:#666"><b>🧠 思考过程:</b><br/><pre>Now ask_human about shijian_mask.png and load_external_layer</pre></div>'
        )
        html_out = render_markdown_to_html(md)
        self.assertIn("execute_pyqgis_script", html_out)
        self.assertIn("remove_qgis_layers_and_data", html_out)
        self.assertIn("ask_human", html_out)
        self.assertIn("shijian_mask.png", html_out)
        self.assertIn("shijiao_2019101", html_out)
        self.assertIn("load_external_layer", html_out)
        self.assertNotIn("ask<i>human", html_out)


if __name__ == "__main__":
    unittest.main()
