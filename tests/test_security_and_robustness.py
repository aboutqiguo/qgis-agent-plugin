"""Systematic security, robustness, and modular architecture tests (Batch 2 & Batch 3)."""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "qgis_agent_plugin"


def _ensure_qgis_mocks() -> None:
    if "qgis" not in sys.modules:
        qgis_mod = MagicMock()
        sys.modules["qgis"] = qgis_mod
        sys.modules["qgis.core"] = qgis_mod.core
        sys.modules["qgis.gui"] = qgis_mod.gui
        sys.modules["qgis.utils"] = qgis_mod.utils
        sys.modules["qgis.PyQt"] = qgis_mod.PyQt
        sys.modules["qgis.PyQt.QtCore"] = qgis_mod.PyQt.QtCore
        sys.modules["qgis.PyQt.QtGui"] = qgis_mod.PyQt.QtGui
        sys.modules["qgis.PyQt.QtWidgets"] = qgis_mod.PyQt.QtWidgets
    if "processing" not in sys.modules:
        sys.modules["processing"] = MagicMock()


_ensure_qgis_mocks()

from qgis_agent_plugin.core.code_execution_guard import analyze_main_thread_code
from qgis_agent_plugin.core.user_tool_extensions import (
    create_or_update_user_tool,
    execute_user_tool,
)
from qgis_agent_plugin.core.validation_rules import (
    ALLOWED_INSTALL_PACKAGES,
    CODE_SECURITY_BLOCKING_RULES,
    PYQGIS_API_VALIDATION_RULES,
)
from qgis_agent_plugin.core.validators import validate_pyqgis_code, validate_tool_call


class BareExceptAndStructureTests(unittest.TestCase):
    def test_zero_bare_excepts_in_plugin_codebase(self):
        bare_locations = []
        for py_file in PLUGIN_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    rel = py_file.relative_to(ROOT)
                    bare_locations.append(f"{rel}:{node.lineno}")
        self.assertEqual([], bare_locations, f"Found bare except clauses: {bare_locations}")

    def test_zero_silent_broad_except_pass_and_bounded_broad_excepts(self):
        silent_broad_locations = []
        broad_count = 0
        for py_file in PLUGIN_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ExceptHandler)
                    and isinstance(node.type, ast.Name)
                    and node.type.id == "Exception"
                ):
                    broad_count += 1
                    if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        rel = py_file.relative_to(ROOT)
                        silent_broad_locations.append(f"{rel}:{node.lineno}")
        self.assertEqual(
            [],
            silent_broad_locations,
            f"Found silent 'except Exception: pass' blocks: {silent_broad_locations}",
        )
        self.assertLessEqual(broad_count, 100, f"Broad except Exception count regressed: {broad_count}")

    def test_modular_split_keeps_core_files_bounded(self):
        tools_lines = len((PLUGIN_DIR / "tools" / "tools.py").read_text(encoding="utf-8").splitlines())
        harness_lines = len((PLUGIN_DIR / "core" / "harness_thread.py").read_text(encoding="utf-8").splitlines())
        validators_lines = len((PLUGIN_DIR / "core" / "validators.py").read_text(encoding="utf-8").splitlines())
        self.assertLess(tools_lines, 1800)
        self.assertLess(harness_lines, 1800)
        self.assertLess(validators_lines, 1000)
        self.assertTrue((PLUGIN_DIR / "tools" / "schemas.py").exists())
        self.assertTrue((PLUGIN_DIR / "tools" / "osm_workflows.py").exists())
        self.assertTrue((PLUGIN_DIR / "tools" / "raster_and_project_ops.py").exists())
        self.assertTrue((PLUGIN_DIR / "tools" / "layer_and_processing_ops.py").exists())
        self.assertTrue((PLUGIN_DIR / "core" / "validation_rules.py").exists())
        self.assertTrue((PLUGIN_DIR / "core" / "harness_progress.py").exists())
        self.assertTrue((PLUGIN_DIR / "core" / "harness_memory_and_artifacts.py").exists())
        self.assertTrue((PLUGIN_DIR / "core" / "harness_execution_helpers.py").exists())


class LayerSnapshotAndSourceTests(unittest.TestCase):
    def _make_plugin_instance(self):
        import types
        if "qgis.PyQt.QtGui" not in sys.modules:
            sys.modules["qgis.PyQt.QtGui"] = types.ModuleType("qgis.PyQt.QtGui")
        qt_gui = sys.modules["qgis.PyQt.QtGui"]
        if not hasattr(qt_gui, "QIcon"):
            setattr(qt_gui, "QIcon", MagicMock())
        qt_widgets = sys.modules.get("qgis.PyQt.QtWidgets")
        if qt_widgets is not None and not hasattr(qt_widgets, "QAction"):
            setattr(qt_widgets, "QAction", MagicMock())
        qt_core = sys.modules.get("qgis.PyQt.QtCore")
        if qt_core is not None and not hasattr(qt_core, "Qt"):
            setattr(qt_core, "Qt", MagicMock())
        from qgis_agent_plugin.agent_plugin import QGISAIAgentPlugin

        plugin = QGISAIAgentPlugin.__new__(QGISAIAgentPlugin)
        plugin.iface = MagicMock()
        plugin.logger = MagicMock()
        plugin.plugin_dir = str(PLUGIN_DIR)
        plugin.dockwidget = MagicMock()
        plugin.harness_thread = MagicMock()
        return plugin

    def test_snapshot_failure_returns_none_and_skips_destructive_duplicate_cleanup(self):
        plugin = self._make_plugin_instance()
        with patch.object(plugin, "_snapshot_project_layers", return_value=None):
            removed = plugin._cleanup_new_duplicate_layers(None)
            self.assertEqual([], removed)
        delta = plugin._format_layer_delta(None, {"l1": {"id": "l1", "name": "A", "type": "vector", "source": "/a.shp"}})
        self.assertEqual("", delta)

    def test_canonical_layer_source_normalizes_paths_and_preserves_uris(self):
        plugin = self._make_plugin_instance()
        uri = "crs=EPSG:3857&type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        self.assertEqual(uri, plugin._canonical_layer_source(uri))
        norm = plugin._canonical_layer_source(r'"C:\Temp\folder\..\data.gpkg|layername=roads"')
        self.assertIn("data.gpkg|layername=roads", norm)
        self.assertNotIn("..", norm)

    def test_prune_temp_images_keeps_most_recent_files(self):
        plugin = self._make_plugin_instance()

        with tempfile.TemporaryDirectory() as tmp:
            created = []
            for idx in range(6):
                p = os.path.join(tmp, f"qgis_window_{idx:04d}.png")
                with open(p, "wb") as fh:
                    fh.write(b"png")
                os.utime(p, (1000 + idx, 1000 + idx))
                created.append(p)
            plugin._prune_temp_images(tmp, max_files=3)
            remaining = sorted(os.listdir(tmp))
            self.assertEqual(["qgis_window_0003.png", "qgis_window_0004.png", "qgis_window_0005.png"], remaining)

    def test_main_thread_handlers_always_set_event_on_exception(self):
        plugin = self._make_plugin_instance()
        event = threading.Event()
        plugin.harness_thread.ask_human_event = event
        plugin.harness_thread.human_input_event = event
        plugin.dockwidget.ask_human.side_effect = RuntimeError("dialog boom")
        plugin.handle_ask_human("question?")
        self.assertTrue(event.is_set())
        self.assertIn("dialog boom", plugin.harness_thread.human_input_response)


class CodeGuardAndUserToolSecurityTests(unittest.TestCase):
    def test_code_guard_blocks_destructive_deletes_and_builtin_bypass(self):
        for snippet in (
            "import shutil\nshutil.rmtree('/tmp/a')",
            "import os\nos.remove('/tmp/a.tif')",
            "fn = getattr(__builtins__, '__import__')",
            "import ctypes",
            "import importlib\nimportlib.import_module('subprocess')",
        ):
            findings = analyze_main_thread_code(snippet)
            self.assertTrue(findings, f"Expected code guard to reject: {snippet}")

    def test_user_tool_enforces_sha256_integrity_and_code_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("qgis_agent_plugin.core.user_tool_extensions.get_user_tool_root", return_value=Path(tmp)):
                bad_res = create_or_update_user_tool(
                    tool_name="user_bad_loop",
                    description="Tool with a forbidden while loop.",
                    parameters_schema={"type": "object", "properties": {}, "required": []},
                    source_code="def run(iface, arguments):\n    while True:\n        pass\n",
                )
                self.assertFalse(bad_res["ok"])

                good_code = (
                    "def run(iface, arguments):\n"
                    "    return {'ok': True, 'message': 'ran safely', 'data': {'v': 42}}\n"
                )
                created = create_or_update_user_tool(
                    tool_name="user_safe_demo",
                    description="Safe user tool for integrity test.",
                    parameters_schema={"type": "object", "properties": {}, "required": []},
                    source_code=good_code,
                )
                self.assertTrue(created["ok"])
                self.assertTrue(created["data"]["tool"].get("source_sha256"))

                ok_exec = execute_user_tool("user_safe_demo", MagicMock(), {})
                self.assertTrue(ok_exec["ok"])

                # Tamper with file on disk without updating registry
                tampered_path = Path(tmp) / "user_safe_demo.py"
                tampered_path.write_text(
                    "def run(iface, arguments):\n    return {'ok': True, 'message': 'tampered'}\n",
                    encoding="utf-8",
                )
                tampered_exec = execute_user_tool("user_safe_demo", MagicMock(), {})
                self.assertFalse(tampered_exec["ok"])
                self.assertEqual("integrity_error", tampered_exec.get("error_type"))

    def test_declarative_validation_rules_and_update_checker_cleanup(self):
        self.assertGreaterEqual(len(PYQGIS_API_VALIDATION_RULES), 15)
        self.assertGreaterEqual(len(CODE_SECURITY_BLOCKING_RULES), 3)
        self.assertIn("scikit-learn", ALLOWED_INSTALL_PACKAGES)

        report = validate_pyqgis_code("prov = layer.dataProvider()\nprov.bandName(1)")
        self.assertFalse(report.ok)

        from qgis_agent_plugin.utils.update_checker import UpdateChecker

        with patch("qgis_agent_plugin.utils.update_checker.requests.get", side_effect=RuntimeError("network down")):
            ok, msg = UpdateChecker.download_and_install_update("9.9.9")
            self.assertFalse(ok)
            self.assertIn("network down", msg)
            leftover = os.path.join(tempfile.gettempdir(), "qgis_agent_plugin_update_9.9.9.zip")
            self.assertFalse(os.path.exists(leftover))

    def test_runtime_restricted_builtins_blocks_eval_and_blocked_imports(self):
        from qgis_agent_plugin.core.code_execution_guard import (
            MainThreadCodeRejected,
            build_restricted_builtins,
            execute_main_thread_code,
        )

        restricted = build_restricted_builtins()
        for dangerous in ("eval", "exec", "compile", "breakpoint", "input"):
            self.assertNotIn(dangerous, restricted)
        with self.assertRaises(MainThreadCodeRejected):
            restricted["__import__"]("subprocess")

        env = {}
        execute_main_thread_code("x = 2 + 3", env)
        self.assertEqual(5, env.get("x"))
        self.assertNotIn("eval", env.get("__builtins__", {}))

    def test_mock_qgis_paths_never_create_magicmock_folder_on_disk(self):
        from qgis_agent_plugin.core.cache_metrics import default_telemetry_path
        from qgis_agent_plugin.core.processing_catalog import _catalog_path
        from qgis_agent_plugin.core.sqlite_memory import SqliteMemoryDB
        from qgis_agent_plugin.core.user_tool_extensions import get_user_tool_root
        from qgis_agent_plugin.core.validators import qgis_project_home

        for resolved in (
            str(get_user_tool_root()),
            str(default_telemetry_path()),
            str(_catalog_path()),
            qgis_project_home(),
            str(SqliteMemoryDB()._get_db_path() or ""),
        ):
            self.assertNotIn("MagicMock", resolved)
        self.assertFalse((ROOT / "MagicMock").exists())


if __name__ == "__main__":
    unittest.main()
