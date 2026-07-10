from qgis.PyQt.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QTextBrowser, QPushButton, QHBoxLayout, QMessageBox, QInputDialog, QTextEdit, QLabel, QSizePolicy, QMenu, QAction, QApplication
from qgis.PyQt.QtCore import pyqtSignal, Qt, QPoint
from qgis.PyQt.QtGui import QPalette

class AutoExpandingTextEdit(QTextEdit):
    returnPressed = pyqtSignal()
    image_pasted_signal = pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setPlaceholderText("在这里输入您的 GIS 任务... (支持 Ctrl+V 粘贴截图)")
        self.document().contentsChanged.connect(self.adjust_height)
        self.document().contentsChanged.connect(self.check_mention)
        self.adjust_height()
        
        # Mention popup
        from qgis.PyQt.QtWidgets import QListWidget
        self.mention_popup = QListWidget()
        self.mention_popup.setWindowFlags(Qt.ToolTip)
        self.mention_popup.setFocusPolicy(Qt.NoFocus)
        self.mention_popup.setStyleSheet("QListWidget { border: 1px solid #ced4da; border-radius: 4px; padding: 4px; } QListWidget::item { padding: 4px; border-radius: 4px; } QListWidget::item:selected { font-weight: bold; }")
        self.mention_popup.hide()
        self.mention_popup.itemClicked.connect(self.insert_mention)
        self._mention_start_pos = -1

    def adjust_height(self):
        doc_height = int(self.document().size().height())
        target_height = min(max(doc_height + 10, 40), 100)
        self.setFixedHeight(target_height)

    def keyPressEvent(self, event):
        from qgis.PyQt.QtCore import Qt
        
        if self.mention_popup.isVisible():
            if event.key() == Qt.Key_Up:
                row = self.mention_popup.currentRow()
                if row > 0:
                    self.mention_popup.setCurrentRow(row - 1)
                return
            elif event.key() == Qt.Key_Down:
                row = self.mention_popup.currentRow()
                if row < self.mention_popup.count() - 1:
                    self.mention_popup.setCurrentRow(row + 1)
                return
            elif event.key() in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab):
                if self.mention_popup.currentItem():
                    self.insert_mention(self.mention_popup.currentItem())
                else:
                    self.mention_popup.hide()
                return
            elif event.key() == Qt.Key_Escape:
                self.mention_popup.hide()
                return

        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if event.modifiers() == Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
        else:
            super().keyPressEvent(event)

    def check_mention(self):
        cursor = self.textCursor()
        text = self.toPlainText()
        pos = cursor.position()
        
        mention_started = False
        self._mention_start_pos = -1
        for i in range(pos - 1, -1, -1):
            if text[i] == '@':
                self._mention_start_pos = i
                mention_started = True
                break
            elif text[i] in (' ', '\n', '\t'):
                break
                
        if mention_started:
            query = text[self._mention_start_pos + 1 : pos]
            self.show_mention_popup(query)
        else:
            self.mention_popup.hide()

    def show_mention_popup(self, query):
        from qgis.core import QgsProject
        layers = QgsProject.instance().mapLayers().values()
        layer_names = [layer.name() for layer in layers]
        
        filtered = [name for name in layer_names if query.lower() in name.lower()]
        
        if not filtered:
            self.mention_popup.hide()
            return
            
        self.mention_popup.clear()
        self.mention_popup.addItems(filtered)
        self.mention_popup.setCurrentRow(0)
        
        cursor_rect = self.cursorRect()
        popup_height = min(len(filtered) * 30 + 10, 150)
        self.mention_popup.setFixedSize(200, popup_height)
        
        global_pos = self.mapToGlobal(cursor_rect.topLeft())
        self.mention_popup.move(global_pos.x(), global_pos.y() - popup_height - 5)
        self.mention_popup.show()

    def insert_mention(self, item):
        layer_name = item.text()
        cursor = self.textCursor()
        cursor.setPosition(self._mention_start_pos)
        cursor.setPosition(self.textCursor().position(), cursor.KeepAnchor)
        cursor.insertText(f"@{layer_name} ")
        self.mention_popup.hide()


    def insertFromMimeData(self, source):
        if source.hasImage():
            image = source.imageData()
            self.image_pasted_signal.emit(image)
        else:
            super().insertFromMimeData(source)

class ChatDockWidget(QDockWidget):
    send_message_signal = pyqtSignal(str, str, str, str) # text, model, effort, mode
    action_panel_signal = pyqtSignal(str) # "APPROVE" or "REJECT"
    stop_agent_signal = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__("QGIS AI Agent Copilot", parent)
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        
        self.setStyleSheet("""
            QWidget { font-family: 'Segoe UI', Arial, sans-serif; }
            QTextBrowser { color: palette(text); background-color: palette(base); border: 1px solid palette(mid); border-radius: 8px; padding: 12px; font-size: 13px; }
            QComboBox { border: none; background: transparent; font-weight: bold; font-size: 12px; padding: 2px 4px; }
            QComboBox::drop-down { border: none; }
        """)
        
        self.main_widget = QWidget()
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        
        # Model, Effort, Mode (Antigravity Style Button Menus)
        self.current_model = "deepseek-v4-flash"
        self.current_effort = "High"
        self.current_mode = "PLAN"
        
        self.model_btn = QPushButton("V4 极速版 (常规) ⌃")
        self.model_btn.setStyleSheet("QPushButton { background: transparent; font-size: 13px; font-weight: 500; padding: 4px; border: none; text-align: left; }")
        self.model_menu = QMenu(self)
        self.model_menu.setStyleSheet("QMenu { border-radius: 6px; padding: 4px; font-size: 13px; } QMenu::item { padding: 6px 24px 6px 12px; border-radius: 4px; }")
        
        actions = [
            ("V4 极速版 (常规)", "deepseek-v4-flash", "High"),
            ("V4 极速版 (极限)", "deepseek-v4-flash", "Max"),
            ("V4 旗舰版 (常规)", "deepseek-v4-pro", "High"),
            ("V4 旗舰版 (极限)", "deepseek-v4-pro", "Max"),
            ("V4 极速版 (关闭思考)", "deepseek-v4-flash", "Disabled")
        ]
        for text, m_id, e_id in actions:
            action = QAction(text, self)
            action.triggered.connect(lambda checked, t=text, m=m_id, e=e_id: self.update_model_selection(t, m, e))
            self.model_menu.addAction(action)
        self.model_btn.clicked.connect(self.show_model_menu_upwards)
        
        self.mode_btn = QPushButton("安全计划 ⌃")
        self.mode_btn.setStyleSheet(self.model_btn.styleSheet())
        self.mode_menu = QMenu(self)
        self.mode_menu.setStyleSheet(self.model_menu.styleSheet())
        
        mode_actions = [
            ("安全计划 (推荐)", "PLAN"),
            ("自动执行 (高风险)", "WORK")
        ]
        for text, m_id in mode_actions:
            action = QAction(text, self)
            action.triggered.connect(lambda checked, t=text, m=m_id: self.update_mode_selection(t, m))
            self.mode_menu.addAction(action)
        self.mode_btn.clicked.connect(self.show_mode_menu_upwards)
        
        # Top Tab & Settings Bar
        self.top_bar_layout = QHBoxLayout()
        self.top_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.top_bar_layout.setSpacing(15)
        
        self.tab_chat_btn = QPushButton("💬 对话")
        self.tab_task_btn = QPushButton("✔️ 任务")
        
        self.tab_style_inactive = "QPushButton { background: transparent; color: palette(mid); font-size: 14px; font-weight: bold; border: none; padding-bottom: 4px; } QPushButton:hover { color: palette(window-text); }"
        self.tab_style_active = "QPushButton { background: transparent; color: #0d6efd; font-size: 14px; font-weight: bold; border: none; border-bottom: 2px solid #0d6efd; padding-bottom: 4px; }"
        
        for btn in [self.tab_chat_btn, self.tab_task_btn]:
            btn.setStyleSheet(self.tab_style_inactive)
            btn.setCursor(Qt.PointingHandCursor)
            self.top_bar_layout.addWidget(btn)
            
        self.tab_task_btn.hide()
        self.tab_chat_btn.setStyleSheet(self.tab_style_active)
        
        self.top_bar_layout.addStretch()
        
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setFixedSize(28, 28)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: palette(window-text);
                border: 1px solid transparent;
                border-radius: 4px;
                font-size: 18px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(128, 128, 128, 0.14);
                border: 1px solid rgba(128, 128, 128, 0.25);
            }
            QPushButton:pressed {
                background-color: rgba(128, 128, 128, 0.24);
            }
        """)
        self.settings_btn.clicked.connect(self.open_settings)
        self.top_bar_layout.addWidget(self.settings_btn)
        
        self.layout.addLayout(self.top_bar_layout)
        
        # Stacked Widget
        from qgis.PyQt.QtWidgets import QStackedWidget
        self.stacked_widget = QStackedWidget()
        
        # 0: Chat history
        self.chat_history = QTextBrowser()
        self.chat_history.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chat_history.setOpenExternalLinks(False)
        self.chat_history.anchorClicked.connect(self.handle_chat_link)
        self.stacked_widget.addWidget(self.chat_history)
        self._chat_blocks = []
        
        # 1: Plan viewer
        self.plan_viewer = QTextBrowser()
        self.plan_viewer.setOpenExternalLinks(True)
        self.plan_viewer.setStyleSheet("QTextBrowser { color: palette(text); background-color: palette(base); border: 1px solid palette(mid); border-radius: 8px; padding: 12px; font-size: 13px; }")
        self.stacked_widget.addWidget(self.plan_viewer)
        
        # 2: Task viewer
        self.task_viewer = QTextBrowser()
        self.task_viewer.setOpenExternalLinks(True)
        self.task_viewer.setStyleSheet("QTextBrowser { color: palette(text); background-color: palette(base); border: 1px solid palette(mid); border-radius: 8px; padding: 12px; font-size: 13px; }")
        self.stacked_widget.addWidget(self.task_viewer)
        
        self.layout.addWidget(self.stacked_widget)
        
        self.tab_chat_btn.clicked.connect(lambda: self.switch_tab(0))
        self.tab_task_btn.clicked.connect(lambda: self.switch_tab(2))
        
        # Setup File Watcher
        self.setup_file_watchers()
        
        # Action Panel
        self.action_layout = QHBoxLayout()
        self.approve_btn = QPushButton("✅ Approve Plan")
        self.approve_btn.setStyleSheet("background-color: #198754; color: white; font-weight: bold; padding: 8px; border-radius: 6px;")
        self.approve_btn.clicked.connect(lambda: self.trigger_action("APPROVE"))
        
        self.revise_btn = QPushButton("✏️ Revise Plan")
        self.revise_btn.setStyleSheet("background-color: #ffc107; color: black; font-weight: bold; padding: 8px; border-radius: 6px;")
        self.revise_btn.clicked.connect(self.prompt_revise_plan)
        
        self.reject_btn = QPushButton("❌ Reject Plan")
        self.reject_btn.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; padding: 8px; border-radius: 6px;")
        self.reject_btn.clicked.connect(lambda: self.trigger_action("REJECT"))
        
        self.action_layout.addWidget(self.approve_btn)
        self.action_layout.addWidget(self.revise_btn)
        self.action_layout.addWidget(self.reject_btn)
        
        self.action_widget = QWidget()
        self.action_widget.setLayout(self.action_layout)
        self.action_widget.hide()
        self.layout.addWidget(self.action_widget)
        
        # Status Label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: palette(mid); font-size: 12px; font-style: italic;")
        self.status_label.hide()
        self.layout.addWidget(self.status_label)
        
        # Premium Input Area
        from qgis.PyQt.QtWidgets import QFrame
        self.input_frame = QFrame()
        self.input_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.input_frame.setStyleSheet("""
            QFrame { border: 1px solid #ced4da; border-radius: 8px; background-color: palette(base); }
            QFrame:focus-within { border: 1px solid #86b7fe; }
        """)
        self.input_layout = QVBoxLayout()
        self.input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_layout.setSpacing(0)
        
        self.image_preview_label = QLabel()
        self.image_preview_label.hide()
        self.image_preview_label.setStyleSheet("padding: 5px; border-bottom: 1px solid #dee2e6;")
        self.image_preview_label.mousePressEvent = self.remove_attachment
        self.input_layout.addWidget(self.image_preview_label)
        
        self.input_field = AutoExpandingTextEdit()
        self.input_field.setStyleSheet("border: none; background: transparent; padding: 8px;")
        self.input_field.returnPressed.connect(self.send_message)
        self.input_field.image_pasted_signal.connect(self.handle_pasted_image)
        self.input_layout.addWidget(self.input_field)
        
        self.bottom_input_layout = QHBoxLayout()
        self.bottom_input_layout.setContentsMargins(8, 4, 8, 8)
        self.bottom_input_layout.setSpacing(10)
        
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(26, 26)
        self.add_btn.setStyleSheet("""
            QPushButton { background-color: transparent; font-size: 22px; font-weight: bold; border: none; padding-bottom: 2px; }
            QPushButton:hover { background-color: rgba(128, 128, 128, 0.2); border-radius: 13px; }
        """)
        self.add_btn.setToolTip("添加附件或提及数据 (@)")
        
        self.bottom_input_layout.addWidget(self.add_btn)
        self.bottom_input_layout.addWidget(self.model_btn)
        self.bottom_input_layout.addWidget(self.mode_btn)
        
        self.bottom_input_layout.addStretch()
        
        self.stop_button = QPushButton("⏸️")
        self.stop_button.setFixedSize(32, 32)
        self.stop_button.setStyleSheet("""
            QPushButton { background-color: #dc3545; color: white; border-radius: 16px; font-size: 14px; }
            QPushButton:hover { background-color: #bb2d3b; }
        """)
        self.stop_button.clicked.connect(self.stop_agent)
        self.stop_button.hide()
        
        self.send_button = QPushButton("➤")
        self.send_button.setFixedSize(32, 32)
        self.send_button.setStyleSheet("""
            QPushButton { background-color: #0d6efd; color: white; border-radius: 16px; font-size: 16px; font-weight: bold; }
            QPushButton:hover { background-color: #0b5ed7; }
        """)
        self.send_button.clicked.connect(self.send_message)
        
        self.bottom_input_layout.addWidget(self.stop_button)
        self.bottom_input_layout.addWidget(self.send_button)
        self.input_layout.addLayout(self.bottom_input_layout)
        
        self.input_frame.setLayout(self.input_layout)
        self.layout.addWidget(self.input_frame)
        
        self.main_widget.setLayout(self.layout)
        self.setWidget(self.main_widget)
        
    def show_model_menu_upwards(self):
        pos = self.model_btn.mapToGlobal(QPoint(0, 0))
        pos.setY(pos.y() - self.model_menu.sizeHint().height() - 5)
        self.model_menu.exec_(pos)

    def update_model_selection(self, text, model_id, effort_id):
        self.model_btn.setText(f"{text} ⌃")
        self.current_model = model_id
        self.current_effort = effort_id

    def show_mode_menu_upwards(self):
        pos = self.mode_btn.mapToGlobal(QPoint(0, 0))
        pos.setY(pos.y() - self.mode_menu.sizeHint().height() - 5)
        self.mode_menu.exec_(pos)

    def update_mode_selection(self, text, mode_id):
        # Extract just the prefix for the button text
        short_text = text.split(" ")[0]
        self.mode_btn.setText(f"{short_text} ⌃")
        self.current_mode = mode_id

    def switch_tab(self, index):
        self.stacked_widget.setCurrentIndex(index)
        self.tab_chat_btn.setStyleSheet(self.tab_style_active if index == 0 else self.tab_style_inactive)
        self.tab_task_btn.setStyleSheet(self.tab_style_active if index == 2 else self.tab_style_inactive)
        
    def setup_file_watchers(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtCore import QFileSystemWatcher, QTimer
        
        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.directoryChanged.connect(self.on_project_dir_changed)
        self.file_watcher.fileChanged.connect(self.on_project_dir_changed)
        
        self.reload_timer = QTimer(self)
        self.reload_timer.setSingleShot(True)
        self.reload_timer.timeout.connect(self.check_and_load_artifacts)
        
        QgsProject.instance().readProject.connect(self.rebind_watcher)
        QgsProject.instance().projectSaved.connect(self.rebind_watcher)
        self.rebind_watcher()
        
    def rebind_watcher(self):
        from qgis.core import QgsProject
        import os
        dirs = self.file_watcher.directories()
        if dirs:
            self.file_watcher.removePaths(dirs)
        files = self.file_watcher.files()
        if files:
            self.file_watcher.removePaths(files)
            
        home = QgsProject.instance().homePath()
        if home and os.path.exists(home):
            self.file_watcher.addPath(home)
            task_path = os.path.join(home, "task.md")
            if os.path.exists(task_path): self.file_watcher.addPath(task_path)
            
        self.check_and_load_artifacts()
        
    def on_project_dir_changed(self, path):
        self.reload_timer.start(500)
        
    def check_and_load_artifacts(self):
        from qgis.core import QgsProject
        import os
        import re
        try:
            import markdown
        except ImportError:
            markdown = None
            
        home = QgsProject.instance().homePath()
        if not home:
            self.tab_task_btn.hide()
            self.switch_tab(0)
            return
            
        task_path = os.path.join(home, "task.md")
        if os.path.exists(task_path):
            self.tab_task_btn.show()
            try:
                with open(task_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    colors = self._theme_colors()
                    
                    # Regex replacement to catch [ ], [x], [/] even if preceded by #, *, -, or spaces
                    # Styled like Antigravity Checkboxes
                    pending_icon = f"<span style='color: {colors['muted']}; font-family: sans-serif; font-size: 14px; margin-right: 4px;'>◯</span>"
                    done_icon = f"<span style='color: {colors['agent']}; font-family: sans-serif; font-size: 14px; margin-right: 4px;'>✅</span>"
                    prog_icon = f"<span style='color: {colors['link']}; font-family: sans-serif; font-size: 14px; margin-right: 4px;'>🔄</span>"
                    
                    # Capture the prefix (e.g. "### ", "- **") and preserve it, only replace the bracket part
                    content = re.sub(r'^([ \t*#>-]*?)\[\s*\]', r'\1' + pending_icon, content, flags=re.MULTILINE)
                    content = re.sub(r'^([ \t*#>-]*?)\[[xX]\]', r'\1' + done_icon, content, flags=re.MULTILINE)
                    content = re.sub(r'^([ \t*#>-]*?)\[/\]', r'\1' + prog_icon, content, flags=re.MULTILINE)
                    
                    if markdown:
                        html = markdown.markdown(content, extensions=['tables'])
                        styled_html = f"""
                        <style>
                            body {{ color: {colors['text']}; }}
                            p, li, td, th {{ color: {colors['text']}; }}
                            a {{ color: {colors['link']}; }}
                            code, pre {{
                                color: {colors['text']};
                                background-color: {colors['code_bg']};
                                border: 1px solid {colors['border']};
                            }}
                        </style>
                        <div style='color: {colors['text']}; line-height: 1.8; font-size: 14px; font-family: "Segoe UI", sans-serif;'>{html}</div>
                        """
                        self.task_viewer.setHtml(styled_html)
                    else:
                        self.task_viewer.setPlainText(content)
            except: pass
        else:
            self.tab_task_btn.hide()
            if self.stacked_widget.currentIndex() == 2: self.switch_tab(0)

    def prompt_revise_plan(self):
        text, ok = QInputDialog.getText(self, "Revise Plan", "Enter your modification feedback:")
        if ok and text.strip():
            self.trigger_action(f"REVISE:{text.strip()}")

    def trigger_action(self, action):
        self.action_widget.hide()
        self.input_frame.show()
        self.append_message("USER", f"*{action} PLAN*")
        self.action_panel_signal.emit(action)
        self.set_agent_status("✨ Agent is executing plan...")
        
    def show_action_panel(self):
        self.input_frame.hide()
        self.action_widget.show()
        self.set_agent_status("⏳ Waiting for human approval...")
        
    def set_agent_status(self, status_text, is_running=True):
        if status_text:
            self.status_label.setText(status_text)
            self.status_label.show()
        else:
            self.status_label.hide()
            
        if is_running:
            self.stop_button.show()
        else:
            self.stop_button.hide()
            self.action_widget.hide()
            self.input_frame.show()
            self.input_field.setFocus()
            
    def stop_agent(self):
        self.append_message("SYSTEM", "🛑 Interrupt signal sent to Agent.")
        self.stop_agent_signal.emit()
        
    def handle_pasted_image(self, image):
        import os, uuid
        from qgis.PyQt.QtGui import QPixmap
        from qgis.PyQt.QtCore import Qt
        
        temp_dir = os.path.join(os.path.dirname(__file__), "temp_images")
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        path = os.path.join(temp_dir, f"paste_{uuid.uuid4().hex[:8]}.png")
        image.save(path, "PNG")
        self.attached_image_path = path
        
        pixmap = QPixmap.fromImage(image).scaledToHeight(60, Qt.SmoothTransformation)
        self.image_preview_label.setPixmap(pixmap)
        self.image_preview_label.setToolTip("Click to remove image attachment")
        self.image_preview_label.show()

    def remove_attachment(self, event):
        self.attached_image_path = None
        self.image_preview_label.hide()

    def open_settings(self):
        from .settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        dialog.exec()

    def send_message(self):
        from qgis.core import QgsSettings
        s = QgsSettings()
        text = self.input_field.toPlainText().strip()
        has_image = bool(getattr(self, 'attached_image_path', None))
        
        if not s.value("qgis_agent/deepseek_api_key", ""):
            QMessageBox.warning(self, "API Key Required", "Please configure your DeepSeek API key before using the agent.")
            self.open_settings()
            if not s.value("qgis_agent/deepseek_api_key", ""):
                return
        
        if has_image and not s.value("qgis_agent/glm_api_key", ""):
            QMessageBox.warning(self, "Vision API Key Required", "Please configure your GLM API key before sending images.")
            self.open_settings()
            if not s.value("qgis_agent/glm_api_key", ""):
                return
        
        if text or has_image:
            model = getattr(self, 'current_model', 'deepseek-v4-flash')
            effort = getattr(self, 'current_effort', 'High')
            mode = getattr(self, 'current_mode', 'PLAN')
            
            display_text = text
            if has_image:
                display_text += "\n[Image Attached]"
                text += f"\n\n[IMAGE_ATTACHMENT]{self.attached_image_path}"
                self.attached_image_path = None
                self.image_preview_label.hide()
            
            self.append_message("USER", display_text)
            self.input_field.clear()
            self.set_agent_status("✨ Agent is thinking...", is_running=True)
            self.send_message_signal.emit(text, model, effort, mode)
            
    def clear_chat(self):
        self._chat_blocks = []
        self.render_chat()

    def load_history(self, messages):
        self._chat_blocks = []
        for msg in messages:
            role_map = {"user": "USER", "assistant": "AGENT", "system": "SYSTEM"}
            if msg["role"] in role_map:
                self.append_message(role_map[msg["role"]], msg.get("content", ""))
                
        # Collapse all loaded system blocks by default
        for block in self._chat_blocks:
            if block["role"] == "SYSTEM_GROUP":
                block["end_time"] = block["start_time"] + 1
                block["collapsed"] = True
        self.render_chat()

    def append_message(self, role, content):
        import time
        if role in ("USER", "AGENT"):
            # Auto-collapse any currently "Working" system block before speaking
            if self._chat_blocks and self._chat_blocks[-1]["role"] == "SYSTEM_GROUP" and self._chat_blocks[-1].get("end_time") is None:
                self._chat_blocks[-1]["end_time"] = time.time()
                self._chat_blocks[-1]["collapsed"] = True
                
            self._chat_blocks.append({
                "role": role,
                "content": content
            })
        else:
            if not self._chat_blocks or self._chat_blocks[-1]["role"] != "SYSTEM_GROUP" or self._chat_blocks[-1].get("end_time") is not None:
                self._chat_blocks.append({
                    "role": "SYSTEM_GROUP",
                    "messages": [],
                    "collapsed": False,
                    "start_time": time.time(),
                    "end_time": None
                })
            self._chat_blocks[-1]["messages"].append(content)
        self.render_chat()
        
    def handle_chat_link(self, url):
        from qgis.PyQt.QtGui import QDesktopServices
        url_str = url.toString()
        if url_str.startswith("toggle:"):
            try:
                idx = int(url_str.split(":")[1])
                self._chat_blocks[idx]["collapsed"] = not self._chat_blocks[idx]["collapsed"]
                self.render_chat()
            except ValueError:
                pass
        else:
            QDesktopServices.openUrl(url)

    def _theme_colors(self):
        palette = QApplication.palette()
        base = palette.color(QPalette.Base)
        text = palette.color(QPalette.Text)
        is_dark = base.lightness() < 128
        return {
            "text": text.name(),
            "muted": "#adb5bd" if is_dark else "#6c757d",
            "system": "#ced4da" if is_dark else "#495057",
            "border": "#495057" if is_dark else "#dee2e6",
            "link": "#4dabf7" if is_dark else "#0d6efd",
            "agent": "#51cf66" if is_dark else "#198754",
            "user": "#4dabf7" if is_dark else "#0d6efd",
            "code_bg": "#2b3035" if is_dark else "#f8f9fa",
        }
            
    def render_chat(self):
        import time
        colors = self._theme_colors()
        html = ""
        for i, block in enumerate(self._chat_blocks):
            if block["role"] in ("USER", "AGENT"):
                role = block["role"]
                content = block["content"]
                color = colors["user"] if role == "USER" else colors["agent"]
                icon = "👤" if role == "USER" else "🤖"
                try:
                    import markdown
                    content = content.replace("- [ ]", "☐").replace("- [x]", "☑").replace("- [/]", "🔄")
                    html_content = markdown.markdown(content, extensions=['tables', 'fenced_code'])
                except Exception:
                    html_content = content.replace('\n', '<br>')
                
                html += f"<div style='margin-bottom: 10px;'><b><span style='color: {color}; font-size: 14px;'>{icon} {role}</span></b><br><div style='color: {colors['text']}; margin-top: 5px;'>{html_content}</div></div>"
                
            elif block["role"] == "SYSTEM_GROUP":
                if block.get("end_time"):
                    duration = max(1, int(block["end_time"] - block["start_time"]))
                    time_str = f"Worked for {duration}s"
                else:
                    duration = max(1, int(time.time() - block["start_time"]))
                    time_str = f"Working... ({duration}s)"
                    
                toggle_icon = "▶" if block["collapsed"] else "▼"
                html += f"<div style='margin-bottom: 5px; margin-top: 10px;'><a href='toggle:{i}' style='color: {colors['muted']}; text-decoration: none; font-size: 13px; font-weight: bold;'>{toggle_icon} {time_str}</a></div>"
                
                if not block["collapsed"]:
                    html += f"<div style='margin-left: 10px; border-left: 3px solid {colors['border']}; padding-left: 10px; margin-bottom: 15px;'>"
                    for msg in block["messages"]:
                        try:
                            import markdown
                            html_msg = markdown.markdown(msg, extensions=['tables', 'fenced_code'])
                        except:
                            html_msg = msg.replace('\n', '<br>')
                        html += f"<div style='color: {colors['system']}; font-size: 12px; margin-bottom: 8px;'>{html_msg}</div>"
                    html += "</div>"
                    
        scrollbar = self.chat_history.verticalScrollBar()
        v = scrollbar.value()
        at_bottom = (v >= scrollbar.maximum() - 10)
        
        base_style = f"""
        <style>
            body {{ color: {colors['text']}; }}
            p, li, td, th {{ color: {colors['text']}; }}
            a {{ color: {colors['link']}; }}
            code, pre {{
                color: {colors['text']};
                background-color: {colors['code_bg']};
                border: 1px solid {colors['border']};
            }}
        </style>
        """
        self.chat_history.setHtml(base_style + html)
        
        if at_bottom:
            from qgis.PyQt.QtCore import QTimer
            QTimer.singleShot(50, lambda: scrollbar.setValue(scrollbar.maximum()))
        else:
            scrollbar.setValue(v)

    def on_agent_finished(self):
        import time
        self.set_agent_status("", is_running=False)
        if hasattr(self, '_chat_blocks') and self._chat_blocks and self._chat_blocks[-1]["role"] == "SYSTEM_GROUP":
            if self._chat_blocks[-1].get("end_time") is None:
                self._chat_blocks[-1]["end_time"] = time.time()
                self._chat_blocks[-1]["collapsed"] = True
                self.render_chat()
        
    def ask_human(self, question):
        self.set_agent_status("⏳ Agent is asking for your input...")
        text, ok = QInputDialog.getMultiLineText(self, "Agent Request", question)
        if ok and text:
            self.append_message("USER (Reply)", text)
            self.set_agent_status("✨ Agent is thinking...", is_running=True)
            return text
        self.set_agent_status("✨ Agent is thinking...", is_running=True)
        return "User cancelled or provided no input."
        
    def ask_destructive_confirmation(self, code):
        self.set_agent_status("⚠️ Agent requires destructive operation approval!")
        
        msgBox = QMessageBox(self)
        msgBox.setIcon(QMessageBox.Warning)
        msgBox.setWindowTitle("⚠️ 高危操作警告")
        msgBox.setText("AI Agent 正在尝试执行具有破坏性的代码（如删除或修改本地文件）。\n\n请点击下方的“详细信息 (Show Details...)”按钮查看具体的代码。您是否允许执行？")
        msgBox.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msgBox.setDefaultButton(QMessageBox.No)
        msgBox.setDetailedText(code)
        
        reply = msgBox.exec_()
        
        self.set_agent_status("⏳ Agent is thinking...", is_running=True)
        return reply == QMessageBox.Yes
