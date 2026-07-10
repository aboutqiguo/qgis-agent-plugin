from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                                 QLineEdit, QPushButton, QMessageBox,
                                 QListWidget, QStackedWidget, QWidget, QComboBox,
                                 QProgressBar)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsSettings

DEFAULT_GLM_VISION_MODEL = "glm-4v-flash"
FREE_GLM_VISION_MODELS = [
    ("GLM-4V-Flash (免费，默认轻量)", "glm-4v-flash"),
    ("GLM-4.6V-Flash (免费，增强视觉)", "glm-4.6v-flash"),
    ("GLM-4.1V-Thinking-Flash (免费，视觉推理)", "glm-4.1v-thinking-flash"),
]

def _build_glm_verify_image_data_url():
    import base64
    import struct
    import zlib

    width = 64
    height = 64
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            if x < width // 2 and y < height // 2:
                row.extend((31, 111, 235))
            elif x >= width // 2 and y < height // 2:
                row.extend((255, 255, 255))
            elif x < width // 2:
                row.extend((25, 135, 84))
            else:
                row.extend((220, 53, 69))
        rows.append(bytes(row))

    def chunk(tag, data):
        body = tag + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QGIS AI Agent - 供应商配置 (Provider Settings)")
        self.resize(650, 450)
        self.settings = QgsSettings()
        
        main_layout = QVBoxLayout(self)
        
        # Top Splitter: List on Left, Stack on Right
        content_layout = QHBoxLayout()
        
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(160)
        self.nav_list.addItem("🐋 DeepSeek")
        self.nav_list.addItem("🧠 智谱 AI (GLM)")
        self.nav_list.addItem("🌍 Google Earth Engine")
        self.nav_list.addItem("🧬 记忆与性格")
        self.nav_list.addItem("🔄 检查更新")
        self.nav_list.setStyleSheet("""
            QListWidget { border: 1px solid #ced4da; border-radius: 4px; font-size: 13px; }
            QListWidget::item { padding: 10px; }
            QListWidget::item:selected { font-weight: bold; }
        """)
        self.nav_list.currentRowChanged.connect(self.change_page)
        
        self.stack = QStackedWidget()
        
        # Build Pages
        self.stack.addWidget(self.build_deepseek_page())
        self.stack.addWidget(self.build_zhipu_page())
        self.stack.addWidget(self.build_gee_page())
        self.stack.addWidget(self.build_memory_page())
        self.stack.addWidget(self.build_update_page())
        
        content_layout.addWidget(self.nav_list)
        content_layout.addWidget(self.stack)
        main_layout.addLayout(content_layout)
        
        # Bottom Buttons
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        
        self.cancel_btn = QPushButton("取消 (Cancel)")
        self.cancel_btn.clicked.connect(self.reject)
        
        self.save_btn = QPushButton("保存配置 (Save)")
        self.save_btn.setStyleSheet("background-color: #0d6efd; color: white; font-weight: bold; padding: 6px 16px; border-radius: 4px;")
        self.save_btn.clicked.connect(self.save_settings)
        
        bottom_layout.addWidget(self.cancel_btn)
        bottom_layout.addWidget(self.save_btn)
        main_layout.addLayout(bottom_layout)
        
        self.nav_list.setCurrentRow(0)
        self.load_settings()

    def create_form_row(self, label_text, widget, hint_text=None):
        layout = QVBoxLayout()
        layout.setSpacing(4)
        label = QLabel(f"<b>{label_text} <span style='color:red;'>*</span></b>")
        layout.addWidget(label)
        widget.setStyleSheet("padding: 8px; border-radius: 4px;")
        layout.addWidget(widget)
        if hint_text:
            hint = QLabel(hint_text)
            hint.setStyleSheet("font-size: 11px;")
            layout.addWidget(hint)
        layout.addSpacing(15)
        return layout

    def build_deepseek_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignTop)
        
        title = QLabel("<h2>🐋 DeepSeek 配置</h2>")
        layout.addWidget(title)
        
        link = QLabel("<a href='https://platform.deepseek.com/'>👉 前往 DeepSeek 开放平台获取 API Key</a>")
        link.setOpenExternalLinks(True)
        layout.addWidget(link)
        layout.addSpacing(20)
        
        self.ds_url_input = QLineEdit()
        self.ds_url_input.setPlaceholderText("https://api.deepseek.com")
        layout.addLayout(self.create_form_row("API 端点 (Base URL)", self.ds_url_input, "供应商的 API 端点地址。如需使用代理可在此修改。"))
        
        self.ds_key_input = QLineEdit()
        self.ds_key_input.setEchoMode(QLineEdit.Password)
        self.ds_key_input.setPlaceholderText("sk-...")
        layout.addLayout(self.create_form_row("API Key", self.ds_key_input, "您的专属认证密钥。"))
        
        self.verify_ds_btn = QPushButton("验证 DeepSeek 连接 (Verify)")
        self.verify_ds_btn.setStyleSheet("padding: 8px; background-color: #0d6efd; color: white; border: none; border-radius: 4px; font-weight: bold;")
        self.verify_ds_btn.clicked.connect(self.verify_deepseek)
        layout.addWidget(self.verify_ds_btn)
        
        return page

    def build_zhipu_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignTop)
        
        title = QLabel("<h2>🧠 智谱 AI (GLM-4V) 配置</h2>")
        layout.addWidget(title)
        
        link = QLabel("<a href='https://open.bigmodel.cn/'>👉 前往 智谱 AI 开放平台获取 API Key</a>")
        link.setOpenExternalLinks(True)
        layout.addWidget(link)
        layout.addSpacing(20)
        
        self.glm_url_input = QLineEdit()
        self.glm_url_input.setPlaceholderText("https://open.bigmodel.cn/api/paas/v4")
        layout.addLayout(self.create_form_row("API 端点 (Base URL)", self.glm_url_input, "多模态视觉请求端点。默认：https://open.bigmodel.cn/api/paas/v4"))
        
        self.glm_key_input = QLineEdit()
        self.glm_key_input.setEchoMode(QLineEdit.Password)
        self.glm_key_input.setPlaceholderText("您的智谱 API Key")
        layout.addLayout(self.create_form_row("API Key", self.glm_key_input, "您的专属认证密钥。"))
        
        self.glm_vision_combo = QComboBox()
        for label, model_id in FREE_GLM_VISION_MODELS:
            self.glm_vision_combo.addItem(label, model_id)
        layout.addLayout(self.create_form_row("视觉模型 (Vision Model)", self.glm_vision_combo, "用于解析图像、屏幕截图的视觉辅助大模型。"))
        
        self.verify_glm_btn = QPushButton("验证智谱连接 (Verify)")
        self.verify_glm_btn.setStyleSheet("padding: 8px; background-color: #0d6efd; color: white; border: none; border-radius: 4px; font-weight: bold;")
        self.verify_glm_btn.clicked.connect(self.verify_zhipu)
        layout.addWidget(self.verify_glm_btn)
        
        return page

    def build_gee_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignTop)
        
        title = QLabel("<h2>🌍 Google Earth Engine 配置</h2>")
        layout.addWidget(title)
        
        desc = QLabel("配置 GEE 运行环境，Agent 将直接调度您的 GEE 资源进行云端遥感计算。")
        desc.setStyleSheet("color: #6c757d; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addSpacing(20)
        
        self.gee_status_label = QLabel("当前绑定的 Project ID: <b style='color:red;'>未配置</b>")
        self.gee_status_label.setStyleSheet("padding: 15px; background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px; font-size: 13px;")
        layout.addWidget(self.gee_status_label)
        layout.addSpacing(20)
        
        btn_layout = QHBoxLayout()
        self.reauth_btn = QPushButton("重新认证 (Re-Authenticate)")
        self.reauth_btn.setStyleSheet("padding: 8px; background-color: #198754; color: white; border-radius: 4px;")
        self.reauth_btn.clicked.connect(self.reauthenticate_gee)
        
        self.clear_auth_btn = QPushButton("清除缓存 (Clear Auth Cache)")
        self.clear_auth_btn.setStyleSheet("padding: 8px; background-color: #dc3545; color: white; border-radius: 4px;")
        self.clear_auth_btn.clicked.connect(self.clear_gee_auth)
        
        btn_layout.addWidget(self.reauth_btn)
        btn_layout.addWidget(self.clear_auth_btn)
        layout.addLayout(btn_layout)
        
        layout.addSpacing(20)
        
        from qgis.PyQt.QtWidgets import QGroupBox
        download_group = QGroupBox("数据下载策略 (Download Strategy)")
        download_group.setStyleSheet("font-weight: bold;")
        dl_layout = QVBoxLayout()
        download_group.setLayout(dl_layout)
        
        dl_layout.addWidget(QLabel("智能路由：GEE 导出 <=32MB 时优先使用 Drive API 直连下载；超过 32MB 或栅格校验失败时，回退到本地 Google Drive Desktop 同步，仍失败则给出手动下载链接。"))
        
        self.dl_path_label = QLabel("Google Drive 本地挂载路径 (Drive Path):")
        self.dl_path_label.setStyleSheet("font-weight: normal; margin-top: 10px;")
        dl_layout.addWidget(self.dl_path_label)
        
        self.dl_path_input = QLineEdit()
        self.dl_path_input.setStyleSheet("font-weight: normal;")
        dl_layout.addWidget(self.dl_path_input)

        layout.addWidget(download_group)
        layout.addStretch()
        
        return page

    def build_memory_page(self):
        from qgis.PyQt.QtWidgets import QGroupBox, QTextEdit
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignTop)
        
        title = QLabel("<h2>🧬 AI 记忆与性格 (Memory & Personality)</h2>")
        layout.addWidget(title)
        
        desc = QLabel("配置大模型的核心性格和记忆池。全局记忆跨工程共享，工程记忆随当前 QGIS 工程绑定。")
        desc.setStyleSheet("color: #6c757d; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addSpacing(10)
        
        layout.addWidget(QLabel("<b>AI 性格设定 (Personality)</b> - 设定其说话风格和角色身份"))
        self.personality_input = QTextEdit()
        self.personality_input.setPlaceholderText("例如：你是一个幽默的 GIS 专家，回答尽量简洁，并且默认使用中文...")
        self.personality_input.setMaximumHeight(80)
        layout.addWidget(self.personality_input)
        
        layout.addWidget(QLabel("<b>全局经验池 (Global Memory)</b> - 跨项目的共有常识或避坑指南"))
        self.global_memory_input = QTextEdit()
        self.global_memory_input.setPlaceholderText("例如：QGIS 3.44 中某个 API 的名称变了...")
        self.global_memory_input.setMaximumHeight(100)
        layout.addWidget(self.global_memory_input)
        
        layout.addWidget(QLabel("<b>当前工程专属记忆 (Project Memory)</b> - 仅对当前打开的工程有效"))
        self.project_memory_input = QTextEdit()
        self.project_memory_input.setPlaceholderText("例如：本工程所有的矢量数据都使用 EPSG:3857...")
        self.project_memory_input.setMaximumHeight(100)
        layout.addWidget(self.project_memory_input)

        catalog_group = QGroupBox("本地能力目录 (Local QGIS Catalog)")
        catalog_group.setStyleSheet("font-weight: bold;")
        catalog_layout = QVBoxLayout(catalog_group)

        catalog_desc = QLabel(
            "主动构建当前 QGIS Processing Toolbox、参数类型、表达式函数等本地索引。"
            "安装或启用新处理插件后建议刷新一次。"
        )
        catalog_desc.setWordWrap(True)
        catalog_desc.setStyleSheet("font-weight: normal; color: #6c757d; font-size: 12px;")
        catalog_layout.addWidget(catalog_desc)

        self.catalog_status_label = QLabel("Catalog 状态：尚未检查")
        self.catalog_status_label.setWordWrap(True)
        self.catalog_status_label.setStyleSheet(
            "font-weight: normal; padding: 10px; background-color: #f8f9fa; "
            "border: 1px solid #dee2e6; border-radius: 4px;"
        )
        catalog_layout.addWidget(self.catalog_status_label)

        self.catalog_progress = QProgressBar()
        self.catalog_progress.setRange(0, 100)
        self.catalog_progress.setValue(0)
        self.catalog_progress.setTextVisible(True)
        self.catalog_progress.setStyleSheet("font-weight: normal;")
        catalog_layout.addWidget(self.catalog_progress)

        catalog_btn_layout = QHBoxLayout()
        self.build_catalog_btn = QPushButton("构建/刷新本地 Catalog")
        self.build_catalog_btn.setStyleSheet(
            "font-weight: bold; padding: 8px; background-color: #198754; "
            "color: white; border-radius: 4px;"
        )
        self.build_catalog_btn.clicked.connect(self.build_local_catalog)

        self.refresh_catalog_status_btn = QPushButton("刷新状态")
        self.refresh_catalog_status_btn.setStyleSheet("font-weight: normal; padding: 8px; border-radius: 4px;")
        self.refresh_catalog_status_btn.clicked.connect(self.update_catalog_status)

        catalog_btn_layout.addWidget(self.build_catalog_btn)
        catalog_btn_layout.addWidget(self.refresh_catalog_status_btn)
        catalog_layout.addLayout(catalog_btn_layout)

        layout.addWidget(catalog_group)
        
        return page

    def build_update_page(self):
        from qgis.PyQt.QtWidgets import QCheckBox
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignTop)
        
        title = QLabel("<h2>🔄 检查更新 (Updates)</h2>")
        layout.addWidget(title)
        
        from ..utils.update_checker import UpdateChecker
        desc = QLabel(f"当前版本: <b>{UpdateChecker.get_local_version()}</b><br><br>在线热更新机制预留，您可以在此检查 GitHub 上的新版本发布。")
        desc.setStyleSheet("color: #6c757d; font-size: 13px;")
        layout.addWidget(desc)
        layout.addSpacing(20)
        
        self.auto_update_cb = QCheckBox("启动 QGIS 时自动检查更新 (Check for updates on startup)")
        layout.addWidget(self.auto_update_cb)
        layout.addSpacing(20)
        
        self.check_update_btn = QPushButton("立即检查更新 (Check Now)")
        self.check_update_btn.setStyleSheet("padding: 8px; background-color: #0d6efd; color: white; border: none; border-radius: 4px; font-weight: bold;")
        self.check_update_btn.clicked.connect(self.check_for_updates)
        layout.addWidget(self.check_update_btn)
        
        layout.addStretch()
        return page

    def check_for_updates(self):
        from qgis.PyQt.QtCore import QCoreApplication
        from ..utils.update_checker import UpdateChecker
        
        self.check_update_btn.setText("正在连接 GitHub... (Checking...)")
        self.check_update_btn.setEnabled(False)
        QCoreApplication.processEvents()
        
        try:
            local_v = UpdateChecker.get_local_version()
            remote_v = UpdateChecker.get_remote_version()
            
            if not remote_v:
                QMessageBox.warning(self, "检查失败", "无法连接到 GitHub 或网络超时，请检查您的网络设置！")
            elif UpdateChecker.is_newer_version(local_v, remote_v):
                msg = (f"🎉 发现新版本: v{remote_v}\n"
                       f"当前版本: v{local_v}\n\n"
                       f"是否立即自动从 GitHub 下载并覆盖安装该更新？\n\n"
                       f"（点击 Yes 自动安装，点击 No 取消。如果您之前配置过仓库链接，也可以去 QGIS 插件库里更新）")
                reply = QMessageBox.question(self, "发现新版本", msg, QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.check_update_btn.setText("正在下载并覆盖安装...请勿操作界面")
                    self.check_update_btn.setEnabled(False)
                    QCoreApplication.processEvents()
                    
                    success, res_msg = UpdateChecker.download_and_install_update(remote_v)
                    if success:
                        QMessageBox.information(self, "更新成功", res_msg)
                    else:
                        QMessageBox.warning(self, "更新失败", res_msg)
            else:
                QMessageBox.information(self, "已是最新", f"当前版本 (v{local_v}) 已是最新版！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"检查更新时发生错误: {str(e)}")
        finally:
            self.check_update_btn.setText("立即检查更新 (Check Now)")
            self.check_update_btn.setEnabled(True)

    def change_page(self, index):
        self.stack.setCurrentIndex(index)

    def load_settings(self):
        self.ds_url_input.setText(self.settings.value("qgis_agent/deepseek_base_url", "https://api.deepseek.com"))
        self.ds_key_input.setText(self.settings.value("qgis_agent/deepseek_api_key", ""))
        
        self.glm_url_input.setText(self.settings.value("qgis_agent/glm_base_url", "https://open.bigmodel.cn/api/paas/v4"))
        self.glm_key_input.setText(self.settings.value("qgis_agent/glm_api_key", ""))
        
        vision_model = self.settings.value("qgis_agent/glm_vision_model", DEFAULT_GLM_VISION_MODEL)
        index = self.glm_vision_combo.findData(vision_model)
        if index < 0:
            index = self.glm_vision_combo.findData(DEFAULT_GLM_VISION_MODEL)
        if index >= 0:
            self.glm_vision_combo.setCurrentIndex(index)
        
        gee_proj = self.settings.value("gee_agent_project_id", "")
        if gee_proj:
            self.gee_status_label.setText(f"当前绑定的 Project ID: <b style='color:green;'>{gee_proj}</b>")
        else:
            self.gee_status_label.setText("当前绑定的 Project ID: <b style='color:red;'>未配置</b>")
            
        # We only have drive sync path now
        self.dl_path_label.setVisible(True)
        self.dl_path_input.setVisible(True)
        
        sync_path = self.settings.value("qgis_agent/gee_drive_sync_path", r"G:\我的云端硬盘")
        self.dl_path_input.setText(sync_path)

        self.personality_input.setPlainText(self.settings.value("qgis_agent/agent_personality", ""))
        import os
        plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        user_md_path = os.path.join(plugin_dir, "USER.md")
        legacy_user_md_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "USER.md")
        if os.path.exists(user_md_path):
            with open(user_md_path, "r", encoding="utf-8") as f:
                self.global_memory_input.setPlainText(f.read())
        elif os.path.exists(legacy_user_md_path):
            with open(legacy_user_md_path, "r", encoding="utf-8") as f:
                self.global_memory_input.setPlainText(f.read())
        else:
            self.global_memory_input.setPlainText("")
            
        from qgis.core import QgsProject
        project_home = QgsProject.instance().homePath()
        if project_home:
            memory_md_path = os.path.join(project_home, "MEMORY.md")
            if os.path.exists(memory_md_path):
                with open(memory_md_path, "r", encoding="utf-8") as f:
                    self.project_memory_input.setPlainText(f.read())
            else:
                self.project_memory_input.setPlainText("")
        else:
            self.project_memory_input.setPlainText("项目未保存，无法加载项目记忆。")
        
        # 加载自动更新设置
        auto_update = self.settings.value("qgis_agent/auto_check_update", False, type=bool)
        self.auto_update_cb.setChecked(auto_update)
        self.update_catalog_status()

    def save_settings(self):
        self.settings.setValue("qgis_agent/deepseek_base_url", self.ds_url_input.text().strip())
        self.settings.setValue("qgis_agent/deepseek_api_key", self.ds_key_input.text().strip())
        
        self.settings.setValue("qgis_agent/glm_base_url", self.glm_url_input.text().strip())
        self.settings.setValue("qgis_agent/glm_api_key", self.glm_key_input.text().strip())
        self.settings.setValue("qgis_agent/glm_vision_model", self.glm_vision_combo.currentData())
        
        self.settings.setValue("qgis_agent/agent_personality", self.personality_input.toPlainText())
        import os
        plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        user_md_path = os.path.join(plugin_dir, "USER.md")
        try:
            with open(user_md_path, "w", encoding="utf-8") as f:
                f.write(self.global_memory_input.toPlainText())
        except Exception:
            pass
            
        from qgis.core import QgsProject
        project_home = QgsProject.instance().homePath()
        if project_home:
            memory_md_path = os.path.join(project_home, "MEMORY.md")
            try:
                with open(memory_md_path, "w", encoding="utf-8") as f:
                    f.write(self.project_memory_input.toPlainText())
            except Exception:
                pass
        
        self.settings.remove("qgis_agent/gee_download_strategy")
        self.settings.setValue("qgis_agent/gee_drive_sync_path", self.dl_path_input.text().strip())
        self.settings.setValue("qgis_agent/auto_check_update", self.auto_update_cb.isChecked())
        
        QMessageBox.information(self, "设置已保存", "所有配置（包括记忆内容）已成功保存。")
        self.accept()

    def update_catalog_status(self):
        try:
            import os
            import sqlite3
            from ..core.processing_catalog import QgisCatalogDB

            db = QgisCatalogDB()
            path = db.db_path
            if not os.path.exists(path):
                self.catalog_status_label.setText(
                    f"Catalog 状态：未构建<br>数据库路径：<code>{path}</code>"
                )
                return

            conn = sqlite3.connect(path)
            cur = conn.cursor()
            def meta_value(key):
                try:
                    cur.execute("SELECT value FROM catalog_meta WHERE key = ?", (key,))
                    row = cur.fetchone()
                    return row[0] if row else ""
                except Exception:
                    return ""

            def table_count(name):
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {name}")
                    return int(cur.fetchone()[0])
                except Exception:
                    return 0

            processing_built_at = meta_value("processing_built_at") or "未知"
            expression_built_at = meta_value("expression_built_at") or "未知"
            alg_count = table_count("processing_algorithms")
            param_count = table_count("processing_parameters")
            expr_count = table_count("expression_functions")
            conn.close()

            self.catalog_status_label.setText(
                "Catalog 状态：已构建<br>"
                f"Processing 算法：<b>{alg_count}</b>，参数：<b>{param_count}</b>，"
                f"表达式函数：<b>{expr_count}</b><br>"
                f"Processing 构建时间：{processing_built_at}<br>"
                f"Expression 构建时间：{expression_built_at}<br>"
                f"数据库路径：<code>{path}</code>"
            )
        except Exception as e:
            self.catalog_status_label.setText(f"Catalog 状态读取失败：{e}")

    def set_catalog_progress(self, value, message):
        from qgis.PyQt.QtCore import QCoreApplication

        value = max(0, min(int(value), 100))
        self.catalog_progress.setValue(value)
        self.catalog_status_label.setText(f"Catalog 状态：{message}")
        QCoreApplication.processEvents()

    def build_local_catalog(self):
        from qgis.PyQt.QtCore import QCoreApplication

        self.build_catalog_btn.setText("正在构建 Catalog...")
        self.build_catalog_btn.setEnabled(False)
        self.refresh_catalog_status_btn.setEnabled(False)
        self.set_catalog_progress(3, "正在准备本地数据库...")

        try:
            from ..core.processing_catalog import QgisCatalogDB

            db = QgisCatalogDB()

            def processing_progress(current, total, message):
                ratio = current / max(total, 1)
                self.set_catalog_progress(8 + int(ratio * 67), message)

            def expression_progress(current, total, message):
                ratio = current / max(total, 1)
                self.set_catalog_progress(76 + int(ratio * 18), message)

            processing = db.rebuild_processing_catalog(progress_callback=processing_progress)
            self.set_catalog_progress(76, "Processing catalog 已写入，正在扫描表达式函数...")
            expression = db.rebuild_expression_catalog(progress_callback=expression_progress)
            self.set_catalog_progress(96, "正在刷新 Catalog 状态...")
            self.update_catalog_status()
            self.catalog_progress.setValue(100)
            QMessageBox.information(
                self,
                "Catalog 构建完成",
                "本地 QGIS Catalog 已构建完成。\n\n"
                f"Processing 算法：{processing.get('algorithm_count', 0)}\n"
                f"Processing 参数：{processing.get('parameter_count', 0)}\n"
                f"表达式函数：{expression.get('function_count', 0)}\n\n"
                f"数据库：{processing.get('db_path', db.db_path)}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Catalog 构建失败", str(e))
            self.catalog_status_label.setText(f"Catalog 状态：构建失败<br>{e}")
            self.catalog_progress.setValue(0)
        finally:
            self.build_catalog_btn.setText("构建/刷新本地 Catalog")
            self.build_catalog_btn.setEnabled(True)
            self.refresh_catalog_status_btn.setEnabled(True)
            QCoreApplication.processEvents()
        
    def reauthenticate_gee(self):
        from ..bridges.gee_bridge import GEEAuth
        from qgis.PyQt.QtWidgets import QMessageBox
        try:
            if GEEAuth.authenticate_and_initialize(force=True):
                self.load_settings()
                QMessageBox.information(self, "GEE", "GEE 认证成功！")
        except Exception as e:
            QMessageBox.critical(self, "GEE 错误", str(e))
            
    def clear_gee_auth(self):
        from ..bridges.gee_bridge import clear_gee_auth as bridge_clear
        try:
            bridge_clear()
            self.gee_status_label.setText("当前绑定的 Project ID: <b style='color:red;'>未配置 (已清除)</b>")
            QMessageBox.information(self, "成功", "已清除 Google Earth Engine 的认证信息。下次使用将要求重新登录。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"清除认证失败：{e}")

    def verify_deepseek(self):
        from qgis.PyQt.QtCore import QCoreApplication
        url = self.ds_url_input.text().strip() or "https://api.deepseek.com"
        key = self.ds_key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "错误", "请先输入 API Key！")
            return
        
        self.verify_ds_btn.setText("验证中 (Verifying...)")
        self.verify_ds_btn.setEnabled(False)
        QCoreApplication.processEvents()
        
        import requests
        try:
            resp = requests.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
            if resp.status_code == 200:
                QMessageBox.information(self, "成功", "验证成功！您的 DeepSeek API Key 有效且网络连接正常。")
            else:
                QMessageBox.warning(self, "失败", f"验证失败：HTTP {resp.status_code}\n{resp.text}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"请求异常：{str(e)}")
        finally:
            self.verify_ds_btn.setText("验证 DeepSeek 连接 (Verify)")
            self.verify_ds_btn.setEnabled(True)

    def verify_zhipu(self):
        from qgis.PyQt.QtCore import QCoreApplication
        url = self.glm_url_input.text().strip() or "https://open.bigmodel.cn/api/paas/v4"
        key = self.glm_key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "错误", "请先输入 API Key！")
            return
            
        self.verify_glm_btn.setText("验证中 (Verifying...)")
        self.verify_glm_btn.setEnabled(False)
        QCoreApplication.processEvents()
        
        import requests
        try:
            test_image_url = _build_glm_verify_image_data_url()
            payload = {
                "model": self.glm_vision_combo.currentData(),
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请用四个字以内描述这张测试图。"},
                        {"type": "image_url", "image_url": {"url": test_image_url}}
                    ]
                }],
                "max_tokens": 8
            }
            resp = requests.post(f"{url}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=10)
            if resp.status_code == 200:
                QMessageBox.information(self, "成功", "验证成功！您的智谱 API Key 有效且网络连接正常。")
            else:
                QMessageBox.warning(self, "失败", f"验证失败：HTTP {resp.status_code}\n{resp.text}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"请求异常：{str(e)}")
        finally:
            self.verify_glm_btn.setText("验证智谱连接 (Verify)")
            self.verify_glm_btn.setEnabled(True)
