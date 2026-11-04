# -*- coding: utf-8 -*-
import sys
import unittest
from unittest.mock import MagicMock

# Ensure mock qgis modules
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
from qgis_agent_plugin.core.task_state import TaskPlan, TaskStep, STATUS_PASSED, STATUS_RUNNING

def test_metro_progress_sync():
    """Verify that multi-step plans correctly emit metro stations progress."""
    thread = HarnessThread("dummy_dir")
    thread.step_controller = MagicMock()
    
    received_events = []
    # If it's a MagicMock, track via side_effect / mock call
    sig = thread.operation_progress_signal
    if isinstance(sig, MagicMock):
        sig.emit = MagicMock(side_effect=lambda e: received_events.append(e))
    else:
        sig.connect(lambda e: received_events.append(e))

    plan = TaskPlan(
        objective="水文分析工作流",
        steps=[
            TaskStep(step_id="step_1", title="填洼处理", status=STATUS_PASSED),
            TaskStep(step_id="step_2", title="流向累积", status=STATUS_RUNNING),
            TaskStep(step_id="step_3", title="河网提取", status="pending"),
        ]
    )
    thread.step_controller.plan = plan
    
    # Trigger metro progress sync
    thread._sync_metro_progress(state="running", detail="正在执行步骤 2")
    
    assert len(received_events) == 1
    event = received_events[0]
    assert event["title"] == "水文分析工作流"
    assert event["state"] == "running"
    stations = event["stations"]
    assert len(stations) == 3
    assert stations[0]["title"] == "1. 填洼处理"
    assert stations[0]["status"] == "completed"
    assert stations[1]["title"] == "2. 流向累积"
    assert stations[1]["status"] == "running"
    assert stations[2]["title"] == "3. 河网提取"
    assert stations[2]["status"] == "pending"

def test_diagnostic_summary_on_watershed_error():
    """Verify diagnostic summary properly identifies grass:r.watershed threshold issue."""
    thread = HarnessThread("dummy_dir")
    thread.messages = [
        {"role": "user", "content": "计算水文流向"},
        {"role": "assistant", "content": ""},
        {
            "role": "tool",
            "name": "execute_pyqgis_script",
            "content": "ERROR: Minimum size of exterior watershed basin (threshold) must be specified\nAlgorithm grass:r.watershed failed."
        }
    ]
    diag = thread._build_diagnostic_summary_for_user("达到最大循环")
    assert "⚠️" in diag
    assert "r.watershed" in diag
    assert "threshold" in diag
    assert "1000" in diag

def test_emit_agent_message_tracks_emission():
    """Verify that _emit_agent_message marks _agent_message_emitted flag."""
    thread = HarnessThread("dummy_dir")
    assert thread._agent_message_emitted is False
    thread._emit_agent_message("测试回复")
    assert thread._agent_message_emitted is True
    assert thread._last_summary == "测试回复"
