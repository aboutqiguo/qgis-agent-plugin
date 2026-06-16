from qgis.PyQt.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QTextBrowser, QLineEdit, QPushButton, QHBoxLayout, QMessageBox, QInputDialog, QComboBox, QTextEdit, QLabel, QGridLayout
from qgis.PyQt.QtCore import pyqtSignal, Qt

class AutoExpandingTextEdit(QTextEdit):
    returnPressed = pyqtSignal()
    image_pasted_signal = pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setPlaceholderText("在这里输入您的 GIS 任务... (支持 Ctrl+V 粘贴截图)")
        self.document().contentsChanged.connect(self.adjust_height)
        self.adjust_height()

    def adjust_height(self):
        doc_height = int(self.document().size().height())
        target_height = min(max(doc_height + 10, 40), 150)
        self.setFixedHeight(target_height)

    def keyPressEvent(self, event):
        from qgis.PyQt.QtCore import Qt
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if event.modifiers() == Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
        else:
            super().keyPressEvent(event)

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
            QTextBrowser { background-color: #ffffff; border: 1px solid #e9ecef; border-radius: 8px; padding: 12px; font-size: 13px; }
            QComboBox { border: 1px solid #ced4da; border-radius: 4px; padding: 4px; background: white; color: black; }
            QComboBox QAbstractItemView { background: white; selection-background-color: #0d6efd; selection-color: white; color: black; }
            QPushButton { background-color: #0d6efd; color: white; border: none; border-radius: 6px; padding: 6px 12px; font-weight: bold; }
            QPushButton:hover { background-color: #0b5ed7; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        
        self.main_widget = QWidget()
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        
        # Top Toolbar
        self.toolbar_layout = QGridLayout()
        self.toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar_layout.setSpacing(5)
        
        self.model_combo = QComboBox()
        self.model_combo.addItem("V4 极速版", "deepseek-v4-flash")
        self.model_combo.addItem("V4 旗舰版", "deepseek-v4-pro")
        
        self.effort_combo = QComboBox()
        self.effort_combo.addItem("思考: 常规", "High")
        self.effort_combo.addItem("思考: 极限", "Max")
        self.effort_combo.addItem("思考: 关闭", "Disabled")
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("执行: 安全计划", "PLAN")
        self.mode_combo.addItem("执行: 自动执行", "WORK")
        
        self.settings_btn = QPushButton("⚙️ 设置")
        self.settings_btn.setStyleSheet("background: transparent; border: 1px solid #ced4da; border-radius: 4px; padding: 4px; color: #495057;")
        self.settings_btn.clicked.connect(self.open_settings)
        
        # Row 0
        self.toolbar_layout.addWidget(self.model_combo, 0, 0)
        self.toolbar_layout.addWidget(self.settings_btn, 0, 1)
        
        # Row 1
        self.toolbar_layout.addWidget(self.effort_combo, 1, 0)
        self.toolbar_layout.addWidget(self.mode_combo, 1, 1)
        
        self.layout.addLayout(self.toolbar_layout)
        
        # Chat history
        self.chat_history = QTextBrowser()
        self.chat_history.setOpenExternalLinks(True)
        self.layout.addWidget(self.chat_history)
        
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
        self.status_label.setStyleSheet("color: #6c757d; font-size: 12px; font-style: italic;")
        self.status_label.hide()
        self.layout.addWidget(self.status_label)
        
        # Premium Input Area
        from qgis.PyQt.QtWidgets import QFrame
        self.input_frame = QFrame()
        self.input_frame.setStyleSheet("""
            QFrame { border: 1px solid #ced4da; border-radius: 8px; background-color: white; }
            QFrame:focus-within { border: 1px solid #86b7fe; }
        """)
        self.input_layout = QVBoxLayout()
        self.input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_layout.setSpacing(0)
        
        self.image_preview_label = QLabel()
        self.image_preview_label.hide()
        self.image_preview_label.setStyleSheet("padding: 5px; background-color: #f8f9fa; border-bottom: 1px solid #dee2e6;")
        self.image_preview_label.mousePressEvent = self.remove_attachment
        self.input_layout.addWidget(self.image_preview_label)
        
        self.input_field = AutoExpandingTextEdit()
        self.input_field.setStyleSheet("border: none; background: transparent; padding: 8px;")
        self.input_field.returnPressed.connect(self.send_message)
        self.input_field.image_pasted_signal.connect(self.handle_pasted_image)
        self.input_layout.addWidget(self.input_field)
        
        self.bottom_input_layout = QHBoxLayout()
        self.bottom_input_layout.setContentsMargins(5, 0, 5, 5)
        self.bottom_input_layout.addStretch()
        
        self.stop_button = QPushButton("⏹")
        self.stop_button.setFixedSize(30, 30)
        self.stop_button.setStyleSheet("""
            QPushButton { background-color: #dc3545; color: white; border-radius: 15px; font-size: 14px; }
            QPushButton:hover { background-color: #bb2d3b; }
        """)
        self.stop_button.clicked.connect(self.stop_agent)
        self.stop_button.hide()
        
        self.send_button = QPushButton("➤")
        self.send_button.setFixedSize(30, 30)
        self.send_button.setStyleSheet("""
            QPushButton { background-color: #0d6efd; color: white; border-radius: 15px; font-size: 14px; font-weight: bold; }
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
        if not s.value("qgis_agent/deepseek_api_key", "") or not s.value("qgis_agent/glm_api_key", ""):
            QMessageBox.warning(self, "API Keys Required", "Please configure your API keys (DeepSeek and Zhipu) before using the agent.")
            self.open_settings()
            if not s.value("qgis_agent/deepseek_api_key", "") or not s.value("qgis_agent/glm_api_key", ""):
                return
                
        text = self.input_field.toPlainText().strip()
        has_image = bool(getattr(self, 'attached_image_path', None))
        
        if text or has_image:
            model = self.model_combo.currentData()
            effort = self.effort_combo.currentData()
            mode = self.mode_combo.currentData()
            
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
        self.chat_history.setHtml("")

    def load_history(self, messages):
        self.clear_chat()
        for msg in messages:
            role_map = {"user": "USER", "assistant": "AGENT", "system": "SYSTEM"}
            if msg["role"] in role_map:
                self.append_message(role_map[msg["role"]], msg.get("content", ""))

    def append_message(self, role, content):
        if role == "USER":
            color = "#0d6efd"
            icon = "👤"
        elif role == "AGENT":
            color = "#198754"
            icon = "🤖"
        else:
            color = "#dc3545"
            icon = "⚙️"
            
        try:
            import markdown
            content = content.replace("- [ ]", "☐").replace("- [x]", "☑").replace("- [/]", "🔄")
            html_content = markdown.markdown(content, extensions=['tables', 'fenced_code'])
        except Exception:
            html_content = content.replace('\n', '<br>')
            
        html = f"""
        <div style='margin-bottom: 10px;'>
            <b><span style='color: {color}; font-size: 14px;'>{icon} {role}</span></b><br>
            <div style='color: #212529; margin-top: 5px;'>{html_content}</div>
        </div>
        """
        self.chat_history.append(html)
        
    def on_agent_finished(self):
        self.set_agent_status("", is_running=False)
        
    def ask_human(self, question):
        self.set_agent_status("⏳ Agent is asking for your input...")
        text, ok = QInputDialog.getMultiLineText(self, "Agent Request", question)
        if ok and text:
            self.append_message("USER (Reply)", text)
            self.set_agent_status("✨ Agent is thinking...", is_running=True)
            return text
        self.set_agent_status("✨ Agent is thinking...", is_running=True)
        return "User cancelled or provided no input."
        
    def ask_destructive_confirmation(self):
        self.set_agent_status("⚠️ Agent requires destructive operation approval!")
        reply = QMessageBox.question(self, 'Warning: Destructive Operation', 
                                     'The AI Agent is about to execute a destructive operation.\nDo you allow this?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        self.set_agent_status("✨ Agent is thinking...", is_running=True)
        return reply == QMessageBox.Yes
