import os
import time
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon

class QGISAIAgentPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dockwidget = None
        self.harness_thread = None
        from .utils.logger import get_logger
        self.logger = get_logger()
        self.global_messages = []
        self._project_event_debounce_seconds = 1.2
        self._last_project_event_signature = None
        self._last_project_event_time = 0.0
        self._memory_loading = False
        self._loaded_memory_project_key = None
        self._last_memory_load_time = 0.0
        
        from qgis.core import QgsProject
        QgsProject.instance().readProject.connect(self.on_project_loaded)
        QgsProject.instance().cleared.connect(self.on_project_cleared)
        QgsProject.instance().projectSaved.connect(self.on_project_saved)
        
        # Load memory for whatever project is initially active
        self.load_memory(force=True)
        
        # Check for updates on startup if enabled
        from qgis.core import QgsSettings
        settings = QgsSettings()
        if settings.value("qgis_agent/auto_check_update", False, type=bool):
            self.run_auto_update_check()

    def run_auto_update_check(self):
        from .utils.update_checker import AsyncUpdateCheckThread
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
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        self.action = QAction(icon, "QGIS AI Agent Copilot", self.iface.mainWindow())
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
            self.handle_stop_agent()
            if not self.harness_thread.wait(5000):
                self.logger.warning("Agent thread did not stop within 5 seconds during unload.")
            
        # Ensure logger handles are closed so QGIS can delete the folder on uninstall
        from .utils.logger import close_logger
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
            from .ui.chat_dockwidget import ChatDockWidget
            self.dockwidget = ChatDockWidget(self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
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
            self.harness_thread.canvas_image_event.set()
            self.harness_thread.atomic_tool_event.set()

    def handle_user_message(self, message, model, effort, mode):
        from .core.harness_thread import HarnessThread
        if self.harness_thread and self.harness_thread.isRunning():
            # Continuous Interaction (Insert Task)
            self.logger.info("Injecting new user message into running thread.")
            
            # HOT FIX: Hot Switching Model and Mode mid-conversation
            self.harness_thread.model_name = model
            self.harness_thread.effort_level = effort
            self.harness_thread.work_mode = mode
            if mode == "PLAN":
                self.harness_thread.plan_approved = False
                self.harness_thread.plan_approval_response = ""
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
                from .tools.tools import execute_atomic_tool_structured
                result = execute_atomic_tool_structured(self.iface, name, kwargs)
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
            
    def handle_destructive_auth(self, code):
        try:
            auth = self.dockwidget.ask_destructive_confirmation(code)
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

    def _canonical_layer_source(self, source):
        if not source:
            return ""
        source = str(source).strip().strip('"')
        head, sep, tail = source.partition("|")
        normalized_head = head.replace("\\", "/")
        try:
            if os.path.isabs(head) or os.path.exists(head):
                normalized_head = os.path.normcase(os.path.abspath(head)).replace("\\", "/")
        except Exception:
            pass
        return f"{normalized_head}{sep}{tail}"

    def _snapshot_project_layers(self):
        try:
            from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
            snapshot = {}
            for layer_id, layer in QgsProject.instance().mapLayers().items():
                if isinstance(layer, QgsRasterLayer):
                    layer_type = "raster"
                elif isinstance(layer, QgsVectorLayer):
                    layer_type = "vector"
                else:
                    layer_type = "other"
                try:
                    source = self._canonical_layer_source(layer.source())
                except Exception:
                    source = ""
                try:
                    name = layer.name()
                except Exception:
                    name = layer_id
                snapshot[layer_id] = {"id": layer_id, "name": name, "source": source, "type": layer_type}
            return snapshot
        except Exception as e:
            self.logger.warning(f"Failed to snapshot project layers: {e}")
            return {}

    def _cleanup_new_duplicate_layers(self, before_snapshot):
        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            after_snapshot = self._snapshot_project_layers()
            groups = {}
            for layer_id, info in after_snapshot.items():
                source = info.get("source", "")
                if not source or source.startswith("memory:"):
                    continue
                groups.setdefault(source, []).append(info)

            removed = []
            for source, layers in groups.items():
                if len(layers) < 2:
                    continue
                existing_ids = [info["id"] for info in layers if info["id"] in before_snapshot]
                new_ids = [info["id"] for info in layers if info["id"] not in before_snapshot]
                if existing_ids:
                    remove_ids = new_ids
                else:
                    remove_ids = new_ids[1:]
                for layer_id in remove_ids:
                    info = after_snapshot.get(layer_id, {})
                    try:
                        project.removeMapLayer(layer_id)
                        removed.append(f"{info.get('name', layer_id)} -> {source}")
                    except Exception as e:
                        self.logger.warning(f"Failed to remove duplicate layer {layer_id}: {e}")
            if removed:
                self.logger.info(f"Removed duplicate layers added by script: {removed}")
            return removed
        except Exception as e:
            self.logger.warning(f"Failed to clean duplicate layers: {e}")
            return []

    def _format_layer_delta(self, before_snapshot, after_snapshot, removed_duplicates=None):
        removed_duplicates = removed_duplicates or []
        added = [info for layer_id, info in after_snapshot.items() if layer_id not in before_snapshot]
        removed = [info for layer_id, info in before_snapshot.items() if layer_id not in after_snapshot]
        lines = []
        if added:
            lines.append("Added layers:")
            for info in added[:10]:
                lines.append(f"- {info.get('name')} ({info.get('type')}): {info.get('source')}")
        if removed:
            lines.append("Removed layers:")
            for info in removed[:10]:
                lines.append(f"- {info.get('name')} ({info.get('type')}): {info.get('source')}")
        if removed_duplicates:
            lines.append("Automatically removed duplicate layers added by this script:")
            for item in removed_duplicates[:10]:
                lines.append(f"- {item}")
        return "\n".join(lines)

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
            from qgis.core import QgsProcessingFeedback, Qgis, QgsApplication, QgsRasterBandStats
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
            env_dict['Qgis'] = Qgis
            env_dict['QgsApplication'] = QgsApplication
            env_dict['QgsProcessingFeedback'] = QgsProcessingFeedback
            env_dict['QgsRasterBandStats'] = QgsRasterBandStats
            env_dict['QCoreApplication'] = QCoreApplication
            
            # Setup global message log interceptor for async warnings (e.g. WMS tile failures)
            captured_logs = []
            message_level = getattr(Qgis, "MessageLevel", Qgis)
            warning_level = getattr(message_level, "Warning", getattr(Qgis, "Warning", None))
            critical_level = getattr(message_level, "Critical", getattr(Qgis, "Critical", None))
            def log_interceptor(msg, tag, level):
                if level in (warning_level, critical_level):
                    # Filter out benign warnings if necessary, but capture most
                    captured_logs.append(f"[{tag}] {msg}")
            
            QgsApplication.messageLog().messageReceived.connect(log_interceptor)
            
        except ImportError:
            pass
        
        f = io.StringIO()
        layer_snapshot_before = self._snapshot_project_layers()
        try:
            import ast
            class SecurityASTVisitor(ast.NodeVisitor):
                def visit_Call(self, node):
                    if isinstance(node.func, ast.Attribute) and node.func.attr == 'sleep':
                        raise RuntimeError("UIFreezeError: 检测到 time.sleep() 或类似的轮询循环！这会彻底卡死 QGIS 主线程！请立刻停止手动轮询，必须改用 qgis_agent_plugin.gee_bridge.GEEDownloader 进行下载。")
                    if isinstance(node.func, ast.Name) and node.func.id == 'sleep':
                        raise RuntimeError("UIFreezeError: 检测到 sleep() 或类似的轮询循环！这会彻底卡死 QGIS 主线程！请立刻停止手动轮询，必须改用 qgis_agent_plugin.gee_bridge.GEEDownloader 进行下载。")
                    self.generic_visit(node)
                    
            try:
                tree = ast.parse(code)
                SecurityASTVisitor().visit(tree)
                
                # Auto-inject QCoreApplication.processEvents() into all loops to prevent UI freeze
                class LoopInjector(ast.NodeTransformer):
                    def visit_For(self, node):
                        self.generic_visit(node)
                        stmt = ast.parse('import qgis.PyQt.QtCore as _qtcore; _qtcore.QCoreApplication.processEvents()').body
                        node.body = stmt + node.body
                        return node
                    def visit_While(self, node):
                        self.generic_visit(node)
                        stmt = ast.parse('import qgis.PyQt.QtCore as _qtcore; _qtcore.QCoreApplication.processEvents()').body
                        node.body = stmt + node.body
                        return node
                tree = LoopInjector().visit(tree)
                ast.fix_missing_locations(tree)
                if hasattr(ast, 'unparse'):
                    code = ast.unparse(tree)
            except Exception:
                pass # Let exec() handle syntax errors
                
            from qgis.PyQt.QtWidgets import QApplication
            from qgis.PyQt.QtCore import Qt
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                with redirect_stdout(f):
                    exec(code, env_dict)
            finally:
                QApplication.restoreOverrideCursor()
                
            stdout_str = f.getvalue().strip()
            
            if captured_logs:
                sys_logs = "\nQGIS System Warnings:\n" + "\n".join(captured_logs)
            else:
                sys_logs = ""
                
            if stdout_str:
                output = f"Code executed successfully.\nStandard Output:\n{stdout_str}{sys_logs}"
            else:
                output = f"Code executed successfully.{sys_logs}"
                
            if getattr(self, 'previous_execution_failed', False):
                output += "\n\n[SYSTEM: 你的代码终于执行成功了！但这说明你刚才犯了错并完成了自我修正。在此刻，你【必须】立刻停下手中的主线任务，优先使用 write_file 工具将错误原因和修复代码写入 MEMORY.md！不准直接进行下一步！]"
            self.previous_execution_failed = False
        except Exception:
            self.previous_execution_failed = True
            stdout_str = f.getvalue().strip()
            tb = traceback.format_exc()
            if stdout_str:
                output = f"[EXECUTION_FAILED_TRACEBACK]\n{tb}\nStandard Output before error:\n{stdout_str}"
            else:
                output = f"[EXECUTION_FAILED_TRACEBACK]\n{tb}"
                
            if "ee." in tb:
                try:
                    import re
                    from .tools.tools import execute_atomic_tool
                    matches = re.findall(r'ee\.[a-zA-Z0-9_\.]+', tb)
                    if matches:
                        # Find the most specific API mentioned
                        best_match = sorted(matches, key=len, reverse=True)[0]
                        search_term = best_match.split('.')[-1]
                        fallback_info = execute_atomic_tool(self.iface, "search_gee_api", {"query": search_term})
                        if not fallback_info.startswith("No API found") and not fallback_info.startswith("Error") and not fallback_info.startswith("Failed"):
                            output += f"\n\n[GEE API FALLBACK (AUTO-RETRIEVED)]\nIt looks like a GEE API call failed. Here is the official signature for `{best_match}` (and related) to help you fix it:\n\n{fallback_info}"
                except Exception:
                    pass
                    
            output += "\n\n[SYSTEM REMINDER: If you successfully fix this error in your next attempt, you MUST use the `replace_file_content` or `write_file` tool to document what went wrong and how you fixed it into `MEMORY.md` immediately!]"
        finally:
            # Always disconnect the interceptor
            try:
                from qgis.core import QgsApplication
                QgsApplication.messageLog().messageReceived.disconnect(log_interceptor)
            except:
                pass

        try:
            removed_duplicates = self._cleanup_new_duplicate_layers(layer_snapshot_before)
            layer_snapshot_after = self._snapshot_project_layers()
            layer_delta = self._format_layer_delta(layer_snapshot_before, layer_snapshot_after, removed_duplicates)
            if layer_delta:
                output += "\n\n[PROJECT LAYER CHANGES]\n" + layer_delta
        except Exception as e:
            self.logger.warning(f"Failed to append layer change summary: {e}")
            
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
        try:
            from .core.sqlite_memory import SqliteMemoryDB
            db = SqliteMemoryDB()
            if self.harness_thread:
                messages_to_save = [m for m in self.harness_thread.messages if m.get("role") != "system"]
            else:
                messages_to_save = [m for m in self.global_messages if m.get("role") != "system"]
                
            db.save_messages(messages_to_save)
            self.logger.info("Saved sandbox memory to SQLite")
        except Exception as e:
            self.logger.error(f"Failed to save sandbox memory: {e}")

    def _current_project_key(self):
        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            project_path = ""
            for attr in ("absoluteFilePath", "fileName"):
                try:
                    value = getattr(project, attr)()
                except Exception:
                    value = ""
                if value:
                    project_path = value
                    break
            home_path = project.homePath() or ""
            return "|".join([
                os.path.normcase(os.path.abspath(project_path)) if project_path else "<unsaved>",
                os.path.normcase(os.path.abspath(home_path)) if home_path else "<no_home>",
            ])
        except Exception as e:
            self.logger.warning(f"Failed to build project key: {e}")
            return "<unknown_project>"

    def _handle_project_context_changed(self, event_type):
        project_key = self._current_project_key()
        signature = f"{event_type}:{project_key}"
        now = time.monotonic()
        if (
            signature == self._last_project_event_signature
            and now - self._last_project_event_time < self._project_event_debounce_seconds
        ):
            self.logger.info(f"Skipped duplicate project event: {signature}")
            return

        self._last_project_event_signature = signature
        self._last_project_event_time = now
        self.logger.info(f"Project {event_type}, switching agent sandbox. project_key={project_key}")
        if self.harness_thread and self.harness_thread.isRunning():
            self.handle_stop_agent()
        self.load_memory()

    def load_memory(self, force=False):
        project_key = self._current_project_key()
        now = time.monotonic()
        if self._memory_loading:
            self.logger.info(f"Skipped re-entrant memory load for project_key={project_key}")
            return
        if (
            not force
            and project_key == self._loaded_memory_project_key
            and now - self._last_memory_load_time < self._project_event_debounce_seconds
        ):
            self.logger.info(f"Skipped duplicate memory load for project_key={project_key}")
            return

        self._memory_loading = True
        self.global_messages = []
        try:
            from .core.sqlite_memory import SqliteMemoryDB
            db = SqliteMemoryDB()
            self.global_messages = db.load_messages()
            self._loaded_memory_project_key = project_key
            self._last_memory_load_time = now
            self.logger.info(
                f"Loaded sandbox memory from SQLite: {len(self.global_messages)} messages, "
                f"project_key={project_key}"
            )
        except Exception as e:
            self.logger.error(f"Failed to load sandbox memory: {e}")
        finally:
            self._memory_loading = False
                
        if self.dockwidget:
            self.dockwidget.load_history(self.global_messages)

    def on_project_loaded(self):
        self._handle_project_context_changed("loaded")

    def on_project_cleared(self):
        self._handle_project_context_changed("cleared")

    def on_project_saved(self):
        self.save_memory()
