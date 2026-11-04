from qgis.PyQt.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QTextBrowser, QPushButton, QHBoxLayout, QMessageBox, QInputDialog, QTextEdit, QLabel, QSizePolicy, QMenu, QAction, QApplication, QProgressBar, QDialog, QDialogButtonBox, QPlainTextEdit
from qgis.PyQt.QtCore import pyqtSignal, Qt, QPoint
from qgis.PyQt.QtGui import QPalette


class AgentRequestDialog(QDialog):
    """A resizable prompt dialog that preserves readable, wrapped questions."""

    def __init__(self, question, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agent Request")
        self.setMinimumSize(680, 360)
        self.resize(820, 500)

        layout = QVBoxLayout(self)
        question_label = QLabel(str(question or ""), self)
        question_label.setWordWrap(True)
        question_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        question_label.setStyleSheet("padding: 4px 2px;")
        layout.addWidget(question_label)

        self.answer_input = QPlainTextEdit(self)
        self.answer_input.setPlaceholderText("请输入回复…")
        self.answer_input.setMinimumHeight(180)
        layout.addWidget(self.answer_input, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def answer(self):
        return self.answer_input.toPlainText().strip()


class AutoExpandingTextEdit(QTextEdit):
    returnPressed = pyqtSignal()
    image_pasted_signal = pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setPlaceholderText("发消息或创建任务, / 调用指令, @ 文件或对话")
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
    operation_progress_signal = pyqtSignal(dict)
    
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
        
        # Available Models: (display_name, model_id, badge_text)
        self.AVAILABLE_MODELS = [
            ("DeepSeek-V4.1-Flash", "deepseek-v4-flash", "1017"),
            ("DeepSeek-V4.1-Pro", "deepseek-v4-pro", "Pro"),
            ("DeepSeek-Chat", "deepseek-chat", "Vision"),
            ("DeepSeek-Reasoner", "deepseek-reasoner", "R1"),
        ]

        # Available Efforts: (display_name, effort_id, description)
        self.AVAILABLE_EFFORTS = [
            ("Disabled", "Disabled", "关闭思考"),
            ("Low", "Low", "轻度思考"),
            ("High", "High", "常规思考"),
            ("Max", "Max", "极限思考"),
        ]

        from qgis.core import QgsSettings
        s = QgsSettings()
        self.current_model = s.value("qgis_agent/selected_model", "deepseek-v4-flash")
        self.current_effort = s.value("qgis_agent/selected_effort", "High")
        from ..core.mode_state import normalize_mode, MODE_WORKSPACE_WRITE
        self.current_mode = normalize_mode(s.value("qgis_agent/selected_mode", MODE_WORKSPACE_WRITE))

        # Dashboard metrics storage
        self._db_turns = 0
        self._db_steps = 0
        self._db_speed = 185
        self._db_total_tokens = 0
        self._db_cache_rate = 99
        self._db_ctx_percent = 28

        # Model & Effort Capsule Button (DeepSeek Style)
        self.model_btn = QPushButton()
        self.model_btn.setObjectName("modelCapsuleBtn")
        self.model_btn.setStyleSheet("""
            QPushButton#modelCapsuleBtn {
                background-color: #f1f3f7;
                color: #374151;
                border: 1px solid #e5e7eb;
                border-radius: 13px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton#modelCapsuleBtn:hover {
                background-color: #e5e7eb;
                border-color: #d1d5db;
            }
        """)
        self._refresh_model_button_text()
        self.model_btn.clicked.connect(self.show_model_menu_upwards)

        # Mode / Permission Button
        self.mode_btn = QPushButton()
        self.mode_btn.setObjectName("modeBtn")
        self.mode_btn.setStyleSheet("""
            QPushButton#modeBtn {
                background: transparent;
                font-size: 12px;
                color: #374151;
                font-weight: 500;
                padding: 4px 6px;
                border: none;
                border-radius: 4px;
            }
            QPushButton#modeBtn:hover {
                background-color: rgba(0, 0, 0, 0.05);
            }
        """)
        self._refresh_mode_button_text()
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

        # Long-running acquisition progress. Unknown server-side duration uses
        # an indeterminate bar; byte/chunk based work shows a real percentage.
        self.operation_progress_widget = QWidget()
        self.operation_progress_layout = QVBoxLayout(self.operation_progress_widget)
        self.operation_progress_layout.setContentsMargins(0, 0, 0, 2)
        self.operation_progress_layout.setSpacing(4)
        self.operation_progress_header = QHBoxLayout()
        self.operation_progress_title = QLabel("")
        self.operation_progress_title.setStyleSheet("font-size: 12px; font-weight: 600; color: palette(text);")
        self.operation_progress_percent = QLabel("")
        self.operation_progress_percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.operation_progress_percent.setStyleSheet("font-size: 11px; color: palette(mid);")
        self.operation_progress_header.addWidget(self.operation_progress_title, 1)
        self.operation_progress_header.addWidget(self.operation_progress_percent)
        self.operation_progress_layout.addLayout(self.operation_progress_header)
        self.operation_progress_stage = QLabel("")
        self.operation_progress_stage.setWordWrap(True)
        self.operation_progress_stage.setStyleSheet("font-size: 11px; color: palette(mid);")
        self.operation_progress_layout.addWidget(self.operation_progress_stage)
        from .metro_progress import MetroStationWidget
        self.metro_widget = MetroStationWidget()
        self.metro_widget.hide()
        self.operation_progress_layout.addWidget(self.metro_widget)

        self.operation_progress_bar = QProgressBar()
        self.operation_progress_bar.setFixedHeight(8)
        self.operation_progress_bar.setTextVisible(False)
        self.operation_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid palette(mid);
                border-radius: 3px;
                background: palette(base);
            }
            QProgressBar::chunk {
                border-radius: 2px;
                background-color: palette(highlight);
            }
        """)
        self.operation_progress_layout.addWidget(self.operation_progress_bar)
        self.operation_progress_widget.hide()
        self._operation_progress_id = ""
        self.operation_progress_signal.connect(self.set_operation_progress)
        self.layout.addWidget(self.operation_progress_widget)
        
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
        self.bottom_input_layout.addWidget(self.mode_btn)
        
        self.bottom_input_layout.addStretch()
        
        self.bottom_input_layout.addWidget(self.model_btn)
        
        self.stop_button = QPushButton("⏸️")
        self.stop_button.setFixedSize(32, 32)
        self.stop_button.setStyleSheet("""
            QPushButton { background-color: #dc3545; color: white; border-radius: 16px; font-size: 14px; border: none; }
            QPushButton:hover { background-color: #bb2d3b; }
        """)
        self.stop_button.clicked.connect(self.stop_agent)
        self.stop_button.hide()
        
        self.send_button = QPushButton("↑")
        self.send_button.setObjectName("sendBtn")
        self.send_button.setFixedSize(32, 32)
        self.send_button.setStyleSheet("""
            QPushButton#sendBtn {
                background-color: #818cf8;
                color: #ffffff;
                border-radius: 16px;
                font-size: 18px;
                font-weight: bold;
                border: none;
            }
            QPushButton#sendBtn:hover {
                background-color: #6366f1;
            }
            QPushButton#sendBtn:pressed {
                background-color: #4f46e5;
            }
            QPushButton#sendBtn:disabled {
                background-color: #e0e7ff;
                color: #c7d2fe;
            }
        """)
        self.send_button.clicked.connect(self.send_message)
        
        self.bottom_input_layout.addWidget(self.stop_button)
        self.bottom_input_layout.addWidget(self.send_button)
        self.input_layout.addLayout(self.bottom_input_layout)
        
        self.input_frame.setLayout(self.input_layout)
        self.layout.addWidget(self.input_frame)

        # Bottom Dashboard (Telemetry & Resource Metrics Bar)
        self.dashboard_frame = QWidget()
        self.dashboard_layout = QHBoxLayout(self.dashboard_frame)
        self.dashboard_layout.setContentsMargins(6, 2, 6, 2)
        self.dashboard_layout.setSpacing(14)

        self.stat_turns_label = QLabel("⏱️ 0 轮 0 步 · 185 tok/s")
        self.stat_turns_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.stat_turns_label.setToolTip("当前会话已执行的对话轮数、工具步数及实时生成速率")

        self.stat_cache_label = QLabel("💾 0 tok · 缓存命中 99%")
        self.stat_cache_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.stat_cache_label.setToolTip("累计消耗 Token 总量与 DeepSeek 提示词缓存命中率")

        self.stat_ctx_label = QLabel("◌ 28%")
        self.stat_ctx_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.stat_ctx_label.setToolTip("当前上下文窗口占用比例")

        self.dashboard_layout.addStretch()
        self.dashboard_layout.addWidget(self.stat_turns_label)
        self.dashboard_layout.addWidget(self.stat_cache_label)
        self.dashboard_layout.addWidget(self.stat_ctx_label)
        self.dashboard_layout.addStretch()

        self.layout.addWidget(self.dashboard_frame)
        self._init_dashboard_metrics()
        
        self.main_widget.setLayout(self.layout)
        self.setWidget(self.main_widget)
        
    def _refresh_model_button_text(self):
        curr_model_tuple = next((m for m in self.AVAILABLE_MODELS if m[1] == self.current_model), self.AVAILABLE_MODELS[0])
        badge = curr_model_tuple[2]
        badge_str = f" {badge} " if badge else " "
        self.model_btn.setText(f"{curr_model_tuple[0]}{badge_str}{self.current_effort} ˄")

    def _refresh_mode_button_text(self):
        from ..core.mode_state import (
            normalize_mode,
            MODE_WORKSPACE_WRITE,
            MODE_DISPLAY_CONFIG,
        )
        norm = normalize_mode(self.current_mode)
        cfg = MODE_DISPLAY_CONFIG.get(norm, MODE_DISPLAY_CONFIG[MODE_WORKSPACE_WRITE])
        self.mode_btn.setText(f"{cfg['icon']} {cfg['text']} ˅")

    def show_model_menu_upwards(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
                color: #1f2937;
            }
            QMenu::item {
                padding: 8px 32px 8px 12px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #f3f4f6;
            }
        """)

        # 1. Model Submenu (模型独立选择)
        curr_model_tuple = next((m for m in self.AVAILABLE_MODELS if m[1] == self.current_model), self.AVAILABLE_MODELS[0])
        badge_str = f" {curr_model_tuple[2]}" if curr_model_tuple[2] else ""
        model_action_title = f"模型         {curr_model_tuple[0]}{badge_str}"
        model_menu = menu.addMenu(model_action_title)
        model_menu.setStyleSheet(menu.styleSheet())

        for name, m_id, b_text in self.AVAILABLE_MODELS:
            item_text = f"{name} {b_text}" if b_text else name
            action = QAction(item_text, self)
            action.setCheckable(True)
            action.setChecked(m_id == self.current_model)
            action.triggered.connect(lambda checked, mid=m_id: self.update_model_selection(mid))
            model_menu.addAction(action)

        # 2. Effort Submenu (思考深度 / 推理等级独立选择)
        effort_action_title = f"推理等级     {self.current_effort}"
        effort_menu = menu.addMenu(effort_action_title)
        effort_menu.setStyleSheet(menu.styleSheet())

        for name, e_id, desc in self.AVAILABLE_EFFORTS:
            action = QAction(f"{name} ({desc})", self)
            action.setCheckable(True)
            action.setChecked(e_id == self.current_effort)
            action.triggered.connect(lambda checked, eid=e_id: self.update_effort_selection(eid))
            effort_menu.addAction(action)

        from qgis.PyQt.QtCore import QPoint
        pos = self.model_btn.mapToGlobal(QPoint(0, 0))
        pos.setY(pos.y() - menu.sizeHint().height() - 5)
        menu.exec_(pos)

    def update_model_selection(self, model_id):
        self.current_model = model_id
        from qgis.core import QgsSettings
        QgsSettings().setValue("qgis_agent/selected_model", model_id)
        self._refresh_model_button_text()

    def update_effort_selection(self, effort_id):
        self.current_effort = effort_id
        from qgis.core import QgsSettings
        QgsSettings().setValue("qgis_agent/selected_effort", effort_id)
        self._refresh_model_button_text()

    def show_mode_menu_upwards(self):
        from ..core.mode_state import (
            normalize_mode,
            MODE_READ_ONLY,
            MODE_WORKSPACE_WRITE,
            MODE_FULL_ACCESS,
        )
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
                color: #1f2937;
            }
            QMenu::item {
                padding: 8px 32px 8px 12px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #f3f4f6;
            }
        """)

        norm_curr = normalize_mode(self.current_mode)
        mode_actions = [
            ("🛡 仅可查看", MODE_READ_ONLY),
            ("🛡 工作区内修改", MODE_WORKSPACE_WRITE),
            ("🛡 完全权限", MODE_FULL_ACCESS),
        ]
        for label, m_id in mode_actions:
            is_selected = (m_id == norm_curr)
            display_text = f"{label:<14}   ✓" if is_selected else label
            action = QAction(display_text, self)
            action.triggered.connect(lambda checked, m=m_id: self.update_mode_selection(m))
            menu.addAction(action)

        from qgis.PyQt.QtCore import QPoint
        pos = self.mode_btn.mapToGlobal(QPoint(0, 0))
        pos.setY(pos.y() - menu.sizeHint().height() - 5)
        menu.exec_(pos)

    def update_mode_selection(self, mode_id):
        self.current_mode = mode_id
        from qgis.core import QgsSettings
        QgsSettings().setValue("qgis_agent/selected_mode", mode_id)
        self._refresh_mode_button_text()

    def update_dashboard(self, turns=None, steps=None, speed=None, total_tokens=None, cache_rate=None, ctx_percent=None):
        if turns is not None:
            self._db_turns = turns
        if steps is not None:
            self._db_steps = steps
        if speed is not None:
            self._db_speed = speed
        if total_tokens is not None:
            self._db_total_tokens = total_tokens
        if cache_rate is not None:
            self._db_cache_rate = cache_rate
        if ctx_percent is not None:
            self._db_ctx_percent = ctx_percent

        tok = self._db_total_tokens
        if tok >= 1_000_000:
            tok_str = f"{tok / 1_000_000:.1f}M"
        elif tok >= 1_000:
            tok_str = f"{tok / 1_000:.1f}k"
        else:
            tok_str = str(tok)

        self.stat_turns_label.setText(f"⏱️ {self._db_turns} 轮 {self._db_steps} 步 · {self._db_speed} tok/s")
        self.stat_cache_label.setText(f"💾 {tok_str} tok · 缓存命中 {self._db_cache_rate}%")
        self.stat_ctx_label.setText(f"◌ {self._db_ctx_percent}%")

    def on_metrics_updated(self, metrics: dict):
        if not isinstance(metrics, dict):
            return
        speed = metrics.get("speed")
        total = metrics.get("total_tokens")
        hit_rate = metrics.get("cache_hit_rate")
        ctx_pct = metrics.get("ctx_percent")
        step = metrics.get("step")
        steps = (self._db_steps + 1) if step is not None else None
        self.update_dashboard(
            steps=steps,
            speed=speed,
            total_tokens=total,
            cache_rate=hit_rate,
            ctx_percent=ctx_pct,
        )

    def _init_dashboard_metrics(self):
        try:
            from qgis.core import QgsProject
            home = QgsProject.instance().homePath()
            if home and os.path.exists(home):
                from ..core.cache_metrics import get_summary
                summary = get_summary(project_home=home)
                self._db_total_tokens = int(summary.get("total_tokens") or 0)
                cache_rate = summary.get("cache_hit_rate")
                if cache_rate is not None:
                    self._db_cache_rate = int(round(float(cache_rate) * 100))
                else:
                    self._db_cache_rate = 0
            else:
                self._db_total_tokens = 0
                self._db_cache_rate = 0
        except Exception:
            self._db_total_tokens = 0
            self._db_cache_rate = 0
        self._db_turns = 0
        self._db_steps = 0
        self._db_ctx_percent = 0
        self.update_dashboard()

    def reset_for_new_project(self):
        """Reset session dashboard and recompute metrics for the current project."""
        self._db_turns = 0
        self._db_steps = 0
        self._db_speed = 0
        self._db_total_tokens = 0
        self._db_cache_rate = 0
        self._db_ctx_percent = 0
        self._init_dashboard_metrics()

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

    def set_operation_progress(self, event):
        event = dict(event or {})
        operation_id = str(event.get("operation_id") or event.get("tool_name") or "data_acquisition")
        self._operation_progress_id = operation_id
        title = str(event.get("title") or "数据获取")
        stage = str(event.get("stage") or "处理中")
        detail = str(event.get("detail") or "").strip()
        stage_index = max(1, int(event.get("stage_index") or 1))
        stage_count = max(stage_index, int(event.get("stage_count") or stage_index))
        state = str(event.get("state") or "running")

        self.operation_progress_title.setText(title)
        stations = event.get("stations")
        if stations:
            self.metro_widget.set_stations(title, stations)
            self.metro_widget.show()
            self.operation_progress_bar.hide()
            self.operation_progress_stage.hide()
        else:
            self.metro_widget.hide()
            self.operation_progress_bar.show()
            self.operation_progress_stage.show()

        stage_text = f"阶段 {stage_index}/{stage_count} · {stage}"
        if detail:
            stage_text += f"\n{detail}"
        self.operation_progress_stage.setText(stage_text)

        percent = event.get("percent")
        if percent is None and state == "running":
            self.operation_progress_bar.setRange(0, 0)
            self.operation_progress_percent.setText("处理中")
        else:
            value = 100 if state == "completed" else int(round(float(percent or 0)))
            value = min(100, max(0, value))
            self.operation_progress_bar.setRange(0, 100)
            self.operation_progress_bar.setValue(value)
            labels = {
                "completed": "已完成",
                "failed": "失败",
                "cancelled": "已取消",
            }
            self.operation_progress_percent.setText(labels.get(state, f"{value}%"))

        self.operation_progress_widget.show()
        if state == "running":
            self.stop_button.show()

    def clear_operation_progress(self, operation_id=""):
        if operation_id and operation_id != self._operation_progress_id:
            return
        self._operation_progress_id = ""
        self.metro_widget.hide()
        self.operation_progress_bar.setRange(0, 100)
        self.operation_progress_bar.setValue(0)
        self.operation_progress_widget.hide()
        
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

        from ..utils.dependency_manager import check_module_installed, install_packages_in_qgis
        if not check_module_installed("openai"):
            reply = QMessageBox.question(
                self,
                "缺少核心依赖",
                "检测到当前环境尚未安装核心依赖 'openai'，Agent 无法与大模型通信。\n\n是否立即自动为您安装？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                QMessageBox.information(self, "正在安装", "正在后台自动安装 openai，请稍候...")
                ok, msg = install_packages_in_qgis(["openai"])
                if not ok:
                    QMessageBox.critical(self, "安装失败", f"自动安装失败：\n{msg}\n\n建议在命令行运行：pip install openai")
                    return
                else:
                    QMessageBox.information(self, "安装成功", "依赖 openai 安装成功！")
            else:
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
            self._db_turns += 1
            self.update_dashboard()
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
            self._db_steps += 1
            self.update_dashboard()
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
            "muted": "#9ca3af" if is_dark else "#6b7280",
            "system": "#cbd5e1" if is_dark else "#4b5563",
            "border": "#374151" if is_dark else "#e5e7eb",
            "link": "#60a5fa" if is_dark else "#2563eb",
            "agent": "#38bdf8" if is_dark else "#1d4ed8",
            "user": "#818cf8" if is_dark else "#4338ca",
            "user_bg": "#1e293b" if is_dark else "#f3f4f6",
            "user_border": "#334155" if is_dark else "#e5e7eb",
            "pill_bg": "#262b32" if is_dark else "#f8f9fa",
            "code_bg": "#1f242c" if is_dark else "#f3f4f6",
            "code_text": "#f1f5f9" if is_dark else "#1f2937",
            "table_header": "#2d333b" if is_dark else "#f1f5f9",
            "table_alt": "#262b32" if is_dark else "#fcfdfe",
        }
            
    def render_chat(self):
        import time
        colors = self._theme_colors()
        html = ""
        from .markdown_renderer import render_markdown_to_html
        for i, block in enumerate(self._chat_blocks):
            if block["role"] == "USER":
                content = block["content"]
                html_content = render_markdown_to_html(content, colors)
                html += f"""
                <div style='margin: 12px 0 10px 0; padding: 10px 14px; background-color: {colors["user_bg"]}; border-radius: 10px; border: 1px solid {colors["user_border"]};'>
                    <div style='font-size: 11px; font-weight: bold; color: {colors["user"]}; margin-bottom: 4px;'>👤 您 (User)</div>
                    <div style='color: {colors["text"]}; font-size: 13px; line-height: 1.5;'>{html_content}</div>
                </div>
                """

            elif block["role"] == "AGENT":
                content = block["content"]
                html_content = render_markdown_to_html(content, colors)
                html += f"""
                <div style='margin: 12px 0 16px 0;'>
                    <div style='font-size: 11.5px; font-weight: bold; color: {colors["agent"]}; margin-bottom: 6px;'>🤖 AI Agent</div>
                    <div style='color: {colors["text"]}; font-size: 13px; line-height: 1.6;'>{html_content}</div>
                </div>
                """
                
            elif block["role"] == "SYSTEM_GROUP":
                if block.get("end_time"):
                    duration = max(1, int(block["end_time"] - block["start_time"]))
                    time_str = f"🧠 思考与执行过程 · {duration}s"
                else:
                    duration = max(1, int(time.time() - block["start_time"]))
                    time_str = f"⚡ 正在思考与调用工具... ({duration}s)"
                    
                toggle_icon = "▶" if block["collapsed"] else "▼"
                html += f"""
                <div style='margin: 6px 0;'>
                    <a href='toggle:{i}' style='display: inline-block; background-color: {colors["pill_bg"]}; color: {colors["muted"]}; border: 1px solid {colors["border"]}; border-radius: 13px; padding: 3px 10px; text-decoration: none; font-size: 11px; font-weight: 500;'>
                        {toggle_icon} {time_str}
                    </a>
                </div>
                """
                
                if not block["collapsed"]:
                    html += f"<div style='margin-left: 6px; border-left: 2px solid {colors['border']}; padding-left: 10px; margin-top: 4px; margin-bottom: 10px;'>"
                    for msg in block["messages"]:
                        html_msg = render_markdown_to_html(msg, colors)
                        html += f"<div style='color: {colors['system']}; font-size: 11.5px; line-height: 1.5; margin-bottom: 6px;'>{html_msg}</div>"
                    html += "</div>"
                    
        scrollbar = self.chat_history.verticalScrollBar()
        v = scrollbar.value()
        at_bottom = (v >= scrollbar.maximum() - 10)
        
        base_style = f"""
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                font-size: 13px;
                line-height: 1.6;
                color: {colors['text']};
                margin: 6px;
            }}
            p {{ margin: 6px 0; }}
            ul, ol {{ margin: 6px 0; padding-left: 20px; }}
            li {{ margin: 3px 0; }}
            a {{ color: {colors['link']}; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            code {{
                color: {colors['code_text']};
                background-color: {colors['code_bg']};
                padding: 2px 5px;
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
            }}
            pre {{
                background-color: {colors['code_bg']};
                border: 1px solid {colors['border']};
                border-radius: 6px;
                padding: 8px 12px;
                overflow-x: auto;
                margin: 8px 0;
            }}
            pre code {{
                padding: 0;
                background: transparent;
                border: none;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 10px 0;
                font-size: 12px;
            }}
            th, td {{
                border: 1px solid {colors['border']};
                padding: 6px 10px;
                text-align: left;
            }}
            th {{
                background-color: {colors['table_header']};
                font-weight: 600;
            }}
            blockquote {{
                margin: 8px 0;
                padding-left: 10px;
                border-left: 3px solid {colors['link']};
                color: {colors['muted']};
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
        self.clear_operation_progress()
        if hasattr(self, '_chat_blocks') and self._chat_blocks and self._chat_blocks[-1]["role"] == "SYSTEM_GROUP":
            if self._chat_blocks[-1].get("end_time") is None:
                self._chat_blocks[-1]["end_time"] = time.time()
                self._chat_blocks[-1]["collapsed"] = True
                self.render_chat()
        
    def ask_human(self, question):
        self.set_agent_status("⏳ Agent is asking for your input...")
        dialog = AgentRequestDialog(question, self)
        if dialog.exec_() == QDialog.Accepted and dialog.answer():
            text = dialog.answer()
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
