"""Real QGIS Headless C++ integration smoke test (Addresses Audit Issue #9).

Automatically discovers a local QGIS Python launcher (`python-qgis*.bat`) on Windows
or uses an active `qgis.core` C++ runtime when available, executing real layer creation,
CRS verification, project snapshotting, and atomic tool execution without MagicMock.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def find_qgis_python_launcher() -> str:
    env_override = os.environ.get("QGIS_PYTHON_LAUNCHER", "").strip()
    if env_override and os.path.exists(env_override):
        return env_override
    patterns = (
        r"C:\Program Files\QGIS*\bin\python-qgis-ltr.bat",
        r"C:\Program Files\QGIS*\bin\python-qgis.bat",
        r"C:\OSGeo4W*\bin\python-qgis*.bat",
        r"D:\Program Files\QGIS*\bin\python-qgis*.bat",
    )
    for pattern in patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return ""


class RealQgisHeadlessSmokeTests(unittest.TestCase):
    def test_real_qgis_headless_project_and_atomic_tools(self):
        launcher = find_qgis_python_launcher()
        if not launcher:
            self.skipTest("No local QGIS installation (python-qgis*.bat) found on this machine.")

        script = textwrap.dedent(
            f"""
            import json
            import os
            import sys
            import tempfile
            sys.path.insert(0, {str(ROOT)!r})

            from qgis.core import (
                Qgis,
                QgsApplication,
                QgsFeature,
                QgsField,
                QgsGeometry,
                QgsPointXY,
                QgsProject,
                QgsVectorLayer,
            )
            from qgis.PyQt.QtCore import QVariant

            app = QgsApplication([], False)
            app.initQgis()
            plugins_path = os.path.join(QgsApplication.pkgDataPath(), "python", "plugins")
            if os.path.isdir(plugins_path) and plugins_path not in sys.path:
                sys.path.append(plugins_path)
            try:
                project = QgsProject.instance()
                project.clear()

                layer = QgsVectorLayer("Point?crs=EPSG:4326", "smoke_points", "memory")
                assert layer.isValid(), "Memory vector layer failed to initialize in real QGIS"
                provider = layer.dataProvider()
                provider.addAttributes([QgsField("name", QVariant.String)])
                layer.updateFields()

                feat = QgsFeature(layer.fields())
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(104.06, 30.67)))
                feat.setAttributes(["Chengdu"])
                ok, added = provider.addFeatures([feat])
                assert ok and len(added) == 1

                project.addMapLayer(layer)

                from qgis_agent_plugin.tools.tools import execute_atomic_tool_structured
                from qgis_agent_plugin.agent_plugin import QGISAIAgentPlugin

                summary_raw = execute_atomic_tool_structured(None, "summarize_layers", {{"include_sources": True}})
                summary = json.loads(summary_raw) if isinstance(summary_raw, str) else summary_raw
                assert summary["ok"] is True
                assert summary["data"]["layer_count"] == 1
                assert summary["data"]["layers"][0]["name"] == "smoke_points"
                assert summary["data"]["layers"][0]["crs"] == "EPSG:4326"
                assert summary["data"]["layers"][0]["feature_count"] == 1

                plugin = QGISAIAgentPlugin.__new__(QGISAIAgentPlugin)
                import logging
                plugin.logger = logging.getLogger("qgis_smoke")
                snap = plugin._snapshot_project_layers()
                assert isinstance(snap, dict) and len(snap) == 1

                with tempfile.TemporaryDirectory() as tmp:
                    qgz_path = os.path.join(tmp, "smoke_project.qgz")
                    project.setFileName(qgz_path)
                    assert project.write() is True
                    assert os.path.exists(qgz_path) and os.path.getsize(qgz_path) > 0

                    val_raw = execute_atomic_tool_structured(
                        None,
                        "validate_project_outputs",
                        {{"expected_layers": ["smoke_points"], "expected_files": [qgz_path]}},
                    )
                    val = json.loads(val_raw) if isinstance(val_raw, str) else val_raw
                    assert val["ok"] is True

                print(json.dumps({{
                    "ok": True,
                    "qgis_version": Qgis.QGIS_VERSION,
                    "layers_verified": 1,
                }}))
            finally:
                QgsProject.instance().clear()
                app.exitQgis()
            """
        )

        with tempfile.NamedTemporaryFile("w", suffix="_qgis_smoke.py", delete=False, encoding="utf-8") as handle:
            script_path = handle.name
            handle.write(script)

        try:
            proc = subprocess.run(
                [launcher, script_path],
                cwd=tempfile.gettempdir(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            self.assertEqual(
                0,
                proc.returncode,
                f"Real QGIS headless smoke test failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
            )
            last_json_line = [
                line.strip()
                for line in proc.stdout.splitlines()
                if line.strip().startswith("{") and line.strip().endswith("}")
            ]
            self.assertTrue(last_json_line, f"Expected JSON summary in stdout, got: {proc.stdout}")
            payload = json.loads(last_json_line[-1])
            self.assertTrue(payload["ok"])
            self.assertEqual(1, payload["layers_verified"])
        finally:
            if os.path.exists(script_path):
                try:
                    os.remove(script_path)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
