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


def test_format_llm_exception_for_user_categories():
    """Verify that _format_llm_exception_for_user provides clear diagnostic markdown for all major errors."""
    thread = HarnessThread("dummy_dir")
    
    # 1. 402 Insufficient Balance
    class DummyAPIStatusError(Exception):
        def __init__(self, code, msg):
            super().__init__(f"Error code: {code} - {msg}")
            self.status_code = code

    exc_402 = DummyAPIStatusError(402, "Insufficient Balance")
    msg_402 = thread._format_llm_exception_for_user(exc_402)
    assert "402" in msg_402
    assert "余额不足" in msg_402
    assert "充值" in msg_402

    # 2. 401 Unauthorized
    exc_401 = DummyAPIStatusError(401, "Invalid API Key")
    msg_401 = thread._format_llm_exception_for_user(exc_401)
    assert "401" in msg_401
    assert "API Key" in msg_401

    # 3. 429 Rate Limit
    exc_429 = DummyAPIStatusError(429, "Rate limit reached")
    msg_429 = thread._format_llm_exception_for_user(exc_429)
    assert "429" in msg_429
    assert "频次超限" in msg_429

    # 4. 404 Not Found
    exc_404 = DummyAPIStatusError(404, "Model not found")
    msg_404 = thread._format_llm_exception_for_user(exc_404)
    assert "404" in msg_404
    assert "模型不存在" in msg_404

    # 5. 500 Server Error
    exc_500 = DummyAPIStatusError(500, "Internal Server Error")
    msg_500 = thread._format_llm_exception_for_user(exc_500)
    assert "服务端" in msg_500

    # 6. Connection error
    class DummyConnectionError(Exception):
        pass
    exc_conn = DummyConnectionError("Failed to establish a new connection: [WinError 10061]")
    msg_conn = thread._format_llm_exception_for_user(exc_conn)
    assert "网络连接" in msg_conn


def test_diagnostic_summary_turn_scoped_prevents_ghost_blame():
    """Verify that _build_diagnostic_summary_for_user does NOT blame tools from previous turns."""
    thread = HarnessThread("dummy_dir")
    # Previous turn messages
    thread.messages = [
        {"role": "user", "content": "导出地图"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "execute_pyqgis_script"}}]},
        {"role": "tool", "name": "execute_pyqgis_script", "content": "{\"status\": \"success\", \"output_path\": \"map.png\"}"},
        {"role": "assistant", "content": "地图已成功导出。"},
        # New turn starts here:
        {"role": "user", "content": "具体而言是哪一步错了呢？"}
    ]
    # Mark turn start index at the new turn
    thread._turn_messages_start_idx = 4
    
    diag = thread._build_diagnostic_summary_for_user("运行结束但未生成最终回复")
    assert "⚠️" in diag
    # Crucial assertion: Must NOT blame execute_pyqgis_script from turn 1!
    assert "execute_pyqgis_script" not in diag
    assert "受阻步骤/执行的工具" not in diag
    assert "运行结束但未生成最终回复" in diag


def test_llm_request_failure_emits_transparent_agent_message():
    """Verify that when LLM request fails (e.g. 402), a transparent AGENT card is emitted directly."""
    thread = HarnessThread("dummy_dir")
    thread.client = MagicMock()
    
    class Mock402Error(Exception):
        status_code = 402
        def __str__(self):
            return "Error code: 402 - Insufficient Balance"

    thread.client.chat.completions.create.side_effect = Mock402Error()

    emitted_messages = []
    thread.append_message_signal.emit = MagicMock(side_effect=lambda role, content: emitted_messages.append((role, content)))

    thread.user_input = "测试查询"
    thread.run()

    # Verify that an AGENT message was emitted
    agent_msgs = [content for role, content in emitted_messages if role == "AGENT"]
    assert len(agent_msgs) >= 1
    # Check that the 402 error was transparently reported to the user
    first_agent_msg = agent_msgs[0]
    assert "402" in first_agent_msg
    assert "余额不足" in first_agent_msg
    assert "充值" in first_agent_msg

    # Verify that the false "execute_pyqgis_script" card was NOT emitted
    assert "execute_pyqgis_script" not in first_agent_msg
    assert thread._run_status_override == "failed"
