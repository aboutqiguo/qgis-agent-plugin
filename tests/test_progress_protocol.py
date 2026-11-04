import unittest

from qgis_agent_plugin.core.progress import (
    DATA_ACQUISITION_TOOLS,
    DataAcquisitionCancelled,
    ProgressEvent,
    emit_progress,
    raise_if_cancelled,
)


class ProgressProtocolTests(unittest.TestCase):
    def test_overall_percent_uses_stage_position(self):
        event = ProgressEvent(
            tool_name="download_osm_features",
            title="OSM",
            stage="Downloading chunks",
            stage_index=2,
            stage_count=4,
            stage_percent=50,
        ).to_dict()
        self.assertEqual(37.5, event["percent"])
        self.assertTrue(event["determinate"])

    def test_indeterminate_stage_does_not_invent_percent(self):
        event = ProgressEvent(
            tool_name="run_gee_sentinel2_download_workflow",
            title="GEE",
            stage="Cloud processing",
            stage_index=3,
            stage_count=6,
        ).to_dict()
        self.assertIsNone(event["percent"])
        self.assertFalse(event["determinate"])

    def test_completed_event_is_exactly_100_percent(self):
        event = ProgressEvent(
            tool_name="download_osm_boundary",
            title="OSM boundary",
            stage="Complete",
            stage_index=1,
            stage_count=4,
            state="completed",
        ).to_dict()
        self.assertEqual(100.0, event["percent"])

    def test_callback_failure_does_not_break_acquisition(self):
        event = emit_progress(
            lambda _event: (_ for _ in ()).throw(RuntimeError("UI closed")),
            tool_name="download_osm_data",
            title="OSM",
            stage="Request",
            stage_index=1,
            stage_count=2,
        )
        self.assertEqual("download_osm_data", event["tool_name"])

    def test_cancel_callback_raises_typed_exception(self):
        with self.assertRaises(DataAcquisitionCancelled):
            raise_if_cancelled(lambda: True)

    def test_registry_covers_all_download_tools(self):
        self.assertIn("download_osm_features", DATA_ACQUISITION_TOOLS)
        self.assertIn("run_gee_dem_download_workflow", DATA_ACQUISITION_TOOLS)


if __name__ == "__main__":
    unittest.main()
