# -*- coding: utf-8 -*-
import sys
import unittest
from unittest.mock import MagicMock

# Mock qgis modules for standalone pytest
if "qgis" not in sys.modules:
    mock_qgis = MagicMock()
    mock_pyqt = MagicMock()
    mock_core = MagicMock()
    mock_core.pyqtSignal = lambda *args, **kwargs: MagicMock()
    mock_core.QThread = object
    mock_pyqt.QtCore = mock_core
    mock_qgis.PyQt = mock_pyqt
    sys.modules["qgis"] = mock_qgis
    sys.modules["qgis.PyQt"] = mock_pyqt
    sys.modules["qgis.PyQt.QtCore"] = mock_core
    sys.modules["qgis.core"] = MagicMock()
if "processing" not in sys.modules:
    sys.modules["processing"] = MagicMock()

from qgis_agent_plugin.core.harness_thread import HarnessThread

def test_ndwi_index_task_metro_detection():
    """Verify that NDWI query auto-detects and generates standard 3-station workflow."""
    thread = HarnessThread("dummy_dir")
    thread.user_input = "计算@shijiao_2019101 这个区域的ndwi"
    
    received_events = []
    sig = thread.operation_progress_signal
    if isinstance(sig, MagicMock):
        sig.emit = MagicMock(side_effect=lambda e: received_events.append(e))
    else:
        sig.connect(lambda e: received_events.append(e))

    thread._detect_and_init_long_task_stations()
    
    assert len(received_events) >= 1
    event = received_events[0]
    assert "NDWI" in event["title"]
    stations = event["stations"]
    assert len(stations) == 3
    assert stations[0]["title"] == "1. 影像波段准备"
    assert stations[1]["title"] == "2. NDWI栅格计算"
    assert stations[2]["title"] == "3. 成果入库渲染"
    assert stations[0]["status"] == "completed"
    assert stations[1]["status"] == "running"

def test_milestone_business_title_mapping():
    """Verify that raw tool names are properly mapped to clean Chinese titles."""
    thread = HarnessThread("dummy_dir")
    t1 = thread._get_milestone_business_title("run_processing_algorithm", {"alg_id": "gdal:rastercalculator"}, ok=True)
    assert t1 == "遥感指数栅格计算"

    t2 = thread._get_milestone_business_title("run_processing_algorithm", {"alg_id": "native:fillsinkswangliu"}, ok=False)
    assert t2 == "水文填洼与流向计算 遇阻"

    t3 = thread._get_milestone_business_title("save_project_and_verify", {}, ok=True)
    assert t3 == "工程保存与成果校验"
