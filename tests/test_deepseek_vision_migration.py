"""Tests for DeepSeek Native Vision Integration and Complete Removal of Zhipu GLM."""

import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)


def _install_qgis_import_stubs():
    qgis_module = sys.modules.setdefault("qgis", types.ModuleType("qgis"))
    core_module = sys.modules.setdefault("qgis.core", types.ModuleType("qgis.core"))
    for name in (
        "QgsProject", "QgsSettings", "QgsMapLayerType", "QgsVectorLayer",
        "QgsRasterLayer", "QgsExpression", "Qgis", "QgsCoordinateReferenceSystem",
        "QgsCoordinateTransform", "QgsRectangle", "QgsMapSettings",
        "QgsMapRendererParallelJob", "QgsVectorFileWriter", "QgsTask",
    ):
        if not hasattr(core_module, name):
            setattr(core_module, name, type(name, (), {}))

    qgis_module.core = core_module

    pyqt_module = sys.modules.setdefault("qgis.PyQt", types.ModuleType("qgis.PyQt"))
    pyqt_core = sys.modules.setdefault("qgis.PyQt.QtCore", types.ModuleType("qgis.PyQt.QtCore"))
    for name in ("QThread", "QSize", "QEventLoop", "QUrl", "QByteArray", "QTimer", "Qt", "QBuffer", "QIODevice"):
        if not hasattr(pyqt_core, name):
            setattr(pyqt_core, name, type(name, (), {}))
    if not hasattr(pyqt_core, "pyqtSignal"):
        pyqt_core.pyqtSignal = lambda *args, **kwargs: MagicMock()

    pyqt_gui = sys.modules.setdefault("qgis.PyQt.QtGui", types.ModuleType("qgis.PyQt.QtGui"))
    for name in ("QColor", "QImage", "QAction"):
        if not hasattr(pyqt_gui, name):
            setattr(pyqt_gui, name, type(name, (), {}))

    pyqt_widgets = sys.modules.setdefault("qgis.PyQt.QtWidgets", types.ModuleType("qgis.PyQt.QtWidgets"))
    for name in (
        "QInputDialog", "QLineEdit", "QMessageBox", "QDialog", "QVBoxLayout",
        "QHBoxLayout", "QLabel", "QPushButton", "QListWidget", "QStackedWidget",
        "QWidget", "QComboBox", "QProgressBar", "QGridLayout", "QGroupBox",
        "QScrollArea", "QFrame", "QMenu",
    ):
        if not hasattr(pyqt_widgets, name):
            setattr(pyqt_widgets, name, type(name, (), {}))

    pyqt_network = sys.modules.setdefault("qgis.PyQt.QtNetwork", types.ModuleType("qgis.PyQt.QtNetwork"))

    pyqt_module.QtCore = pyqt_core
    pyqt_module.QtGui = pyqt_gui
    pyqt_module.QtWidgets = pyqt_widgets
    pyqt_module.QtNetwork = pyqt_network
    qgis_module.PyQt = pyqt_module


_install_qgis_import_stubs()

from qgis_agent_plugin.core.vision_manager import (
    IMAGE_ATTACHMENT_REGEX,
    build_multimodal_message,
    call_deepseek_vision,
    extract_image_attachment_and_text,
    extract_text_content,
    image_to_data_url,
)


class TestDeepSeekVisionManager(unittest.TestCase):
    """Test vision manager functions for multimodal formatting and encoding."""

    def test_extract_image_attachment_formats(self):
        # Format 1: [IMAGE_ATTACHMENT]path
        text1, path1 = extract_image_attachment_and_text("请分析这张图：\n[IMAGE_ATTACHMENT]C:/test/map.png")
        self.assertEqual(text1, "请分析这张图：")
        self.assertEqual(path1, "C:/test/map.png")

        # Format 2: [IMAGE_ATTACHMENT:path]
        text2, path2 = extract_image_attachment_and_text("请分析：[IMAGE_ATTACHMENT:D:/test/canvas.jpg]")
        self.assertEqual(text2, "请分析：")
        self.assertEqual(path2, "D:/test/canvas.jpg")

        # Format 3: No attachment
        text3, path3 = extract_image_attachment_and_text("仅纯文本需求")
        self.assertEqual(text3, "仅纯文本需求")
        self.assertIsNone(path3)

    def test_extract_text_content_from_multimodal_and_plain(self):
        # Plain string
        self.assertEqual(extract_text_content("Hello QGIS"), "Hello QGIS")

        # Multimodal block list
        blocks = [
            {"type": "text", "text": "Analyze the map layout."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "text", "text": "Focus on the north arrow."},
        ]
        extracted = extract_text_content(blocks)
        self.assertIn("Analyze the map layout.", extracted)
        self.assertIn("Focus on the north arrow.", extracted)
        self.assertNotIn("base64", extracted)

    def test_image_to_data_url_and_multimodal_builder(self):
        # Create a temporary dummy image file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"\x89PNG\r\n\x1a\nfake_image_bytes")
            tmp_path = tmp.name

        try:
            data_url = image_to_data_url(tmp_path)
            self.assertTrue(data_url.startswith("data:image/"))
            self.assertIn(";base64,", data_url)

            # Build multimodal message
            msg = build_multimodal_message("用户说明", tmp_path)
            self.assertEqual(msg["role"], "user")
            self.assertIsInstance(msg["content"], list)
            self.assertEqual(len(msg["content"]), 2)
            self.assertEqual(msg["content"][0]["type"], "text")
            self.assertEqual(msg["content"][0]["text"], "用户说明")
            self.assertEqual(msg["content"][1]["type"], "image_url")
            self.assertTrue(msg["content"][1]["image_url"]["url"].startswith("data:image/"))

            # Build message without image
            plain_msg = build_multimodal_message("纯文本", None)
            self.assertEqual(plain_msg["role"], "user")
            self.assertEqual(plain_msg["content"], "纯文本")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_call_deepseek_vision_client(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "地图配色和谐，图例位置合理。"
        mock_client.chat.completions.create.return_value = mock_resp

        result = call_deepseek_vision(
            client=mock_client,
            model="deepseek-v4-flash",
            prompt="评审排版",
            image_path_or_url="data:image/png;base64,ZmFrZQ==",
            system_prompt="GIS专家",
        )

        self.assertEqual(result, "地图配色和谐，图例位置合理。")
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        self.assertEqual(call_kwargs["model"], "deepseek-v4-flash")
        self.assertEqual(len(call_kwargs["messages"]), 2)
        self.assertEqual(call_kwargs["messages"][0]["role"], "system")
        self.assertEqual(call_kwargs["messages"][1]["role"], "user")

    def test_call_deepseek_vision_reasoner_fallback(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "视觉分析结果"
        mock_client.chat.completions.create.return_value = mock_resp

        # When pure reasoning model is passed, it should automatically route to deepseek-chat
        result = call_deepseek_vision(
            client=mock_client,
            model="deepseek-reasoner",
            prompt="评审",
            image_path_or_url="data:image/png;base64,ZmFrZQ==",
        )
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        self.assertEqual(call_kwargs["model"], "deepseek-chat")


class TestZeroZhipuGlmPresence(unittest.TestCase):
    """Verify that Zhipu GLM API has been completely removed across the codebase."""

    def test_no_glm_in_plugin_codebase(self):
        plugin_dir = os.path.join(PLUGIN_ROOT, "qgis_agent_plugin")
        occurrences = []
        for root, _, files in os.walk(plugin_dir):
            for f in files:
                if f.endswith(".py"):
                    file_path = os.path.join(root, f)
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                        for idx, line in enumerate(fp, 1):
                            if "glm" in line.lower():
                                occurrences.append(f"{file_path}:{idx}: {line.strip()}")

        self.assertEqual(occurrences, [], f"Residual GLM references found: {occurrences}")


if __name__ == "__main__":
    unittest.main()
