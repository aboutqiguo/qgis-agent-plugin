import os
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from .chat_dockwidget import ChatDockWidget
from .harness_thread import HarnessThread

class QGISAIAgentPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dockwidget = None
        self.harness_thread = None
        from .logger import get_logger
        self.logger = get_logger()
        self.global_messages = []
        
        from qgis.core import QgsProject
        QgsProject.instance().readProject.connect(self.on_project_loaded)
        QgsProject.instance().cleared.connect(self.on_project_cleared)
        QgsProject.instance().projectSaved.connect(self.on_project_saved)
        
        # Load memory for whatever project is initially active
        self.load_memory()
        
        # Check for updates on startup if enabled
        from qgis.core import QgsSettings
        settings = QgsSettings()
        if settings.value("qgis_agent/auto_check_update", False, type=bool):
            self.run_auto_update_check()

    def run_auto_update_check(self):
        from .update_checker import AsyncUpdateCheckThread
        self.update_thread = AsyncUpdateCheckThread()
        self.update_thread.finished_signal.connect(self.on_update_checked)
        self.update_thread.start()

    def on_update_checked(self, has_update, local_v, remote_v):
        if has_update:
            from qgis.core import Qgis
            msg = f"发现新版本 v{remote_v}！请前往设置或插件管理器进行热更新。"
            self.iface.messageBar().pushMessage("QGIS AI Agent", msg, level=Qgis.MessageLevel.Info, duration=10)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(QIcon(icon_path), "QGIS AI Agent Copilot", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("&QGIS AI Agent", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu("&QGIS AI Agent", self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget = None
        if self.harness_thread and self.harness_thread.isRunning():
            self.harness_thread.is_killed = True
            self.harness_thread.wait()
            
        # Ensure logger handles are closed so QGIS can delete the folder on uninstall
        from .logger import close_logger
        close_logger()
            
        try:
            from qgis.core import QgsProject
            QgsProject.instance().readProject.disconnect(self.on_project_loaded)
            QgsProject.instance().cleared.disconnect(self.on_project_cleared)
            QgsProject.instance().projectSaved.disconnect(self.on_project_saved)
        except Exception:
            pass

    def run(self):
        self.logger.info("Starting QGIS AI Agent.")
        if not self.dockwidget:
            from .chat_dockwidget import ChatDockWidget
            self.dockwidget = ChatDockWidget(self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dockwidget)
            self.dockwidget.send_message_signal.connect(self.handle_user_message)
            self.dockwidget.action_panel_signal.connect(self.handle_action_panel)
            self.dockwidget.stop_agent_signal.connect(self.handle_stop_agent)

        self.dockwidget.show()

    def handle_stop_agent(self):
        if self.harness_thread and self.harness_thread.isRunning():
            self.harness_thread.is_killed = True
            # Unblock any waiting events so it can die gracefully
            self.harness_thread.human_input_event.set()
            self.harness_thread.plan_approval_event.set()
            self.harness_thread.code_exec_event.set()
            self.harness_thread.destructive_auth_event.set()

    def handle_user_message(self, message, model, effort, mode):
        from .harness_thread import HarnessThread
        if self.harness_thread and self.harness_thread.isRunning():
            # Continuous Interaction (Insert Task)
            self.logger.info("Injecting new user message into running thread.")
            
            # HOT FIX: Hot Switching Model and Mode mid-conversation
            self.harness_thread.model_name = model
            self.harness_thread.effort_level = effort
            self.harness_thread.work_mode = mode
            self.logger.info(f"Hot switched model to {model}, effort to {effort}, and mode to {mode}")
            
            self.harness_thread.messages.append({"role": "user", "content": message})
            # If the thread is waiting for plan approval, auto-reject it to force re-planning with new context
            # If the thread is waiting for plan approval, auto-reject it to force re-planning with new context
            if not self.harness_thread.plan_approval_event.is_set():
                self.harness_thread.plan_approval_response = "REJECT"
                self.harness_thread.plan_approval_event.set()
            return
            
        if self.harness_thread:
            try:
                self.harness_thread.append_message_signal.disconnect()
                self.harness_thread.finished_signal.disconnect()
                self.harness_thread.request_human_input_signal.disconnect()
                self.harness_thread.request_destructive_auth_signal.disconnect()
                self.harness_thread.request_plan_approval_signal.disconnect()
                self.harness_thread.request_code_execution_signal.disconnect()
                self.harness_thread.request_canvas_image_signal.disconnect()
                self.harness_thread.request_atomic_tool_signal.disconnect()
            except TypeError:
                pass
                
        self.harness_thread = HarnessThread(self.plugin_dir, existing_messages=self.global_messages)
        self.harness_thread.user_input = message
        self.harness_thread.model_name = model
        self.harness_thread.effort_level = effort
        self.harness_thread.work_mode = mode
        
        self.harness_thread.append_message_signal.connect(self.dockwidget.append_message)
        self.harness_thread.finished_signal.connect(self.dockwidget.on_agent_finished)
        self.harness_thread.request_human_input_signal.connect(self.handle_ask_human)
        self.harness_thread.request_destructive_auth_signal.connect(self.handle_destructive_auth)
        self.harness_thread.request_plan_approval_signal.connect(self.handle_request_plan_approval)
        self.harness_thread.request_code_execution_signal.connect(self.handle_code_execution)
        self.harness_thread.request_canvas_image_signal.connect(self.handle_canvas_image)
        self.harness_thread.request_atomic_tool_signal.connect(self.handle_atomic_tool)
        
        self.harness_thread.start()

    def handle_atomic_tool(self, name, kwargs):
        try:
            if name == "take_qgis_window_snapshot":
                import os, uuid
                window = self.iface.mainWindow()
                pixmap = window.grab()
                temp_dir = os.path.join(self.plugin_dir, "temp_images")
                if not os.path.exists(temp_dir):
                    os.makedirs(temp_dir)
                img_path = os.path.join(temp_dir, f"qgis_window_{uuid.uuid4().hex[:8]}.png")
                pixmap.save(img_path)
                result = f"[IMAGE_PATH]{img_path}"
            else:
                from .tools import execute_atomic_tool
                result = execute_atomic_tool(self.iface, name, kwargs)
        except Exception as e:
            result = f"Error: {str(e)}"
            
        if self.harness_thread:
            self.harness_thread.atomic_tool_response = result
            self.harness_thread.atomic_tool_event.set()

    def handle_canvas_image(self):
        try:
            import tempfile
            img_path = os.path.join(tempfile.gettempdir(), "qgis_canvas_snap.png")
            self.iface.mapCanvas().saveAsImage(img_path)
            if self.harness_thread:
                self.harness_thread.canvas_image_path = img_path
                self.harness_thread.canvas_image_event.set()
        except Exception as e:
            self.logger.error(f"Error saving canvas: {e}")
            if self.harness_thread:
                self.harness_thread.canvas_image_path = ""
                self.harness_thread.canvas_image_event.set()

    def handle_ask_human(self, question):
        try:
            answer = self.dockwidget.ask_human(question)
        except Exception as e:
            self.logger.error(f"GUI Crash in ask_human: {e}")
            answer = "GUI Error: " + str(e)
            
        if self.harness_thread:
            self.harness_thread.human_input_response = answer
            self.harness_thread.human_input_event.set()
            
    def handle_destructive_auth(self):
        try:
            auth = self.dockwidget.ask_destructive_confirmation()
        except Exception as e:
            self.logger.error(f"GUI Crash in ask_destructive_confirmation: {e}")
            auth = False # Fail safe
            
        if self.harness_thread:
            self.harness_thread.destructive_auth_response = auth
            self.harness_thread.destructive_auth_event.set()

    def handle_request_plan_approval(self):
        try:
            self.dockwidget.show_action_panel()
        except Exception as e:
            self.logger.error(f"GUI Crash in show_action_panel: {e}")
            if self.harness_thread:
                self.harness_thread.plan_approval_response = "REJECT"
                self.harness_thread.plan_approval_event.set()
            
    def handle_action_panel(self, action):
        if self.harness_thread and self.harness_thread.isRunning():
            self.harness_thread.plan_approval_response = action
            self.harness_thread.plan_approval_event.set()

    def handle_code_execution(self, code):
        """Executes the Python code safely on the main Qt thread and captures stdout."""
        import sys
        import traceback
        import io
        from contextlib import redirect_stdout
        from qgis.utils import iface
        from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer, QgsFeature, QgsGeometry
        
        tools_path = self.plugin_dir
        if tools_path not in sys.path:
            sys.path.append(tools_path)
            
        env_dict = globals().copy()
        env_dict['iface'] = iface
        env_dict['QgsProject'] = QgsProject
        env_dict['QgsVectorLayer'] = QgsVectorLayer
        env_dict['QgsRasterLayer'] = QgsRasterLayer
        env_dict['QgsFeature'] = QgsFeature
        env_dict['QgsGeometry'] = QgsGeometry
        
        try:
            from qgis.core import QgsProcessingFeedback, Qgis, QgsApplication
            from qgis.PyQt.QtCore import QCoreApplication
            class PrintFeedback(QgsProcessingFeedback):
                def setProgress(self, progress):
                    super().setProgress(progress)
                    QCoreApplication.processEvents()
                def reportError(self, error, fatalError=False):
                    print(f"QGIS ERROR: {error}")
                    QCoreApplication.processEvents()
                def pushInfo(self, info):
                    print(f"QGIS INFO: {info}")
                    QCoreApplication.processEvents()
                def pushCommandInfo(self, info):
                    print(f"QGIS CMD: {info}")
                def pushDebugInfo(self, info):
                    print(f"QGIS DEBUG: {info}")
                def pushConsoleInfo(self, info):
                    print(f"QGIS CONSOLE: {info}")
            env_dict['PrintFeedback'] = PrintFeedback
            
            # Setup global message log interceptor for async warnings (e.g. WMS tile failures)
            captured_logs = []
            def log_interceptor(msg, tag, level):
                if level in (Qgis.Warning, Qgis.Critical):
                    # Filter out benign warnings if necessary, but capture most
                    captured_logs.append(f"[{tag}] {msg}")
            
            QgsApplication.messageLog().messageReceived.connect(log_interceptor)
            
        except ImportError:
            pass
        
        f = io.StringIO()
        try:
            with redirect_stdout(f):
                exec(code, env_dict)
                
            stdout_str = f.getvalue().strip()
            
            if captured_logs:
                sys_logs = "\nQGIS System Warnings:\n" + "\n".join(captured_logs)
            else:
                sys_logs = ""
                
            if stdout_str:
                output = f"Code executed successfully.\nStandard Output:\n{stdout_str}{sys_logs}"
            else:
                output = f"Code executed successfully.{sys_logs}"
        except Exception as e:
            stdout_str = f.getvalue().strip()
            tb = traceback.format_exc()
            if stdout_str:
                output = f"Error executing code:\n{tb}\nStandard Output before error:\n{stdout_str}"
            else:
                output = f"Error executing code:\n{tb}"
            output += "\n\n[SYSTEM REMINDER: If you successfully fix this error in your next attempt, you MUST call `update_agent_memory` immediately to document what went wrong and how you fixed it!]"
        finally:
            # Always disconnect the interceptor
            try:
                from qgis.core import QgsApplication
                QgsApplication.messageLog().messageReceived.disconnect(log_interceptor)
            except:
                pass
            
        if self.harness_thread:
            self.harness_thread.code_exec_response = output
            self.harness_thread.code_exec_event.set()

    def _get_memory_path(self):
        from qgis.core import QgsProject
        import os
        proj_path = QgsProject.instance().absoluteFilePath()
        if proj_path:
            return proj_path + ".agent.json"
        else:
            return os.path.join(self.plugin_dir, "untitled.agent.json")

    def save_memory(self):
        import json
        import os
        mem_path = self._get_memory_path()
        try:
            if self.harness_thread and self.harness_thread.isRunning():
                # Save from active thread
                messages_to_save = [m for m in self.harness_thread.messages if m.get("role") != "system"]
            else:
                messages_to_save = [m for m in self.global_messages if m.get("role") != "system"]
                
            with open(mem_path, 'w', encoding='utf-8') as f:
                json.dump(messages_to_save, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Saved sandbox memory to {mem_path}")
        except Exception as e:
            self.logger.error(f"Failed to save sandbox memory: {e}")

    def load_memory(self):
        import json
        import os
        mem_path = self._get_memory_path()
        self.global_messages = []
        if os.path.exists(mem_path):
            try:
                with open(mem_path, 'r', encoding='utf-8') as f:
                    self.global_messages = json.load(f)
                self.logger.info(f"Loaded sandbox memory from {mem_path}")
            except Exception as e:
                self.logger.error(f"Failed to load sandbox memory: {e}")
                
        if self.dockwidget:
            self.dockwidget.load_history(self.global_messages)

    def on_project_loaded(self):
        self.logger.info("Project loaded, switching agent sandbox.")
        if self.harness_thread and self.harness_thread.isRunning():
            self.handle_stop_agent()
        self.load_memory()

    def on_project_cleared(self):
        self.logger.info("Project cleared, resetting agent sandbox.")
        if self.harness_thread and self.harness_thread.isRunning():
            self.handle_stop_agent()
        self.load_memory()

    def on_project_saved(self):
        self.save_memory()
