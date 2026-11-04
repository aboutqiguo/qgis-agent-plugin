import unittest

from qgis_agent_plugin.core.gee_routing import (
    EE_DIRECT_MAX_BYTES,
    EE_DIRECT_MAX_DIMENSION,
    estimate_direct_download_route,
)


class GeeRoutingTests(unittest.TestCase):
    def test_small_export_uses_earth_engine_direct_route(self):
        result = estimate_direct_download_route(
            area_m2=1_000_000,
            width_m=1_000,
            height_m=1_000,
            band_count=4,
            scale=10,
        )
        self.assertTrue(result["eligible"])
        self.assertEqual("ee_direct", result["route"])

    def test_large_payload_uses_batch_export(self):
        result = estimate_direct_download_route(
            area_m2=400_000_000,
            width_m=20_000,
            height_m=20_000,
            band_count=10,
            scale=10,
        )
        self.assertFalse(result["eligible"])
        self.assertEqual("batch_export", result["route"])
        self.assertGreaterEqual(result["estimated_bytes"], EE_DIRECT_MAX_BYTES)

    def test_grid_dimension_limit_is_independent_of_drive(self):
        result = estimate_direct_download_route(
            area_m2=1,
            width_m=(EE_DIRECT_MAX_DIMENSION + 1) * 10,
            height_m=10,
            band_count=1,
            scale=10,
        )
        self.assertFalse(result["eligible"])
        self.assertGreater(result["width_px"], EE_DIRECT_MAX_DIMENSION)


if __name__ == "__main__":
    unittest.main()
