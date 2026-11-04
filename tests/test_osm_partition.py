import sys
import types
import unittest


def _install_qgis_import_stubs():
    qgis_module = sys.modules.setdefault("qgis", types.ModuleType("qgis"))
    core_module = sys.modules.setdefault("qgis.core", types.ModuleType("qgis.core"))
    utils_module = sys.modules.setdefault("qgis.utils", types.ModuleType("qgis.utils"))
    for name in ("QgsVectorLayer", "QgsProject", "Qgis"):
        if not hasattr(core_module, name):
            setattr(core_module, name, type(name, (), {}))
    if not hasattr(utils_module, "iface"):
        utils_module.iface = object()
    qgis_module.core = core_module
    qgis_module.utils = utils_module


_install_qgis_import_stubs()

from qgis_agent_plugin.bridges.osm_bridge import (  # noqa: E402
    build_bbox_query,
    classify_overpass_error,
    normalize_overpass_ql,
    split_bbox,
)


class OsmPartitionTests(unittest.TestCase):
    def test_split_bbox_respects_area_limit(self):
        chunks = split_bbox((100.0, 20.0, 101.0, 21.0), max_area=0.25)
        self.assertGreaterEqual(len(chunks), 4)
        self.assertTrue(all((x2 - x1) * (y2 - y1) <= 0.25 + 1e-12 for x1, y1, x2, y2 in chunks))

    def test_split_bbox_rejects_non_positive_area(self):
        with self.assertRaises(ValueError):
            split_bbox((100.0, 20.0, 101.0, 21.0), max_area=0)

    def test_bbox_query_uses_overpass_coordinate_order(self):
        query = build_bbox_query(['way["building"]'], (100.0, 20.0, 101.0, 21.0), "multipolygons")
        self.assertIn("(20.0,100.0,21.0,101.0)", query)
        self.assertIn("[out:xml]", query)

    def test_normalizer_removes_duplicate_headers(self):
        query = normalize_overpass_ql("[out:json][timeout:10];\nnode[\"amenity\"](1,2,3,4);\nout body;", 180)
        self.assertEqual(1, query.count("[out:"))
        self.assertEqual(1, query.count("[timeout:"))

    def test_overpass_error_classification(self):
        self.assertEqual("overpass_rate_limited", classify_overpass_error("HTTP 429 Too Many Requests"))
        self.assertEqual("overpass_timeout", classify_overpass_error("gateway timeout"))
        self.assertEqual("overpass_parse_error", classify_overpass_error("parse error"))


if __name__ == "__main__":
    unittest.main()
