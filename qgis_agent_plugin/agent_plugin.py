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
        self._pending_user_requests = []
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
        except (ImportError, TypeError, RuntimeError, AttributeError):
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
        pending_count = len(self._pending_user_requests)
        self._pending_user_requests.clear()
        if pending_count and self.dockwidget:
            self.dockwidget.append_message("SYSTEM", f"已取消 {pending_count} 个排队任务。")
        if self.harness_thread and self.harness_thread.isRunning():
            self.harness_thread.is_killed = True
            if self.dockwidget:
                self.dockwidget.operation_progress_signal.emit({
                    "operation_id": "user_interrupted",
                    "title": "任务已暂停",
                    "state": "cancelled",
                    "detail": "用户已点击暂停按钮",
                })
            # Unblock any waiting events so it can die gracefully
            self.harness_thread.human_input_event.set()
            self.harness_thread.plan_approval_event.set()
            self.harness_thread.code_exec_event.set()
            self.harness_thread.destructive_auth_event.set()
            self.harness_thread.canvas_image_event.set()
            self.harness_thread.atomic_tool_event.set()

    def handle_user_message(self, message, model, effort, mode):
        from .core.harness_thread import HarnessThread
        from .core.mode_state import (
            build_gee_retry_message,
            is_gee_retry_confirmation,
            should_resume_approved_plan,
        )
        if self.harness_thread and self.harness_thread.isRunning():
            self._pending_user_requests.append({
                "message": message,
                "model": model,
                "effort": effort,
                "mode": mode,
            })
            queue_position = len(self._pending_user_requests)
            self.logger.info("Queued user request behind the active task. position=%s", queue_position)
            if self.dockwidget:
                self.dockwidget.append_message(
                    "SYSTEM",
                    f"当前任务仍在执行；新请求已排队（第 {queue_position} 个），将在当前任务完全结束后启动。",
                )
            return

        resume_plan_payload = None
        resume_project_home = ""
        retry_message = ""
        if self.harness_thread:
            recovery_context = getattr(self.harness_thread, "recovery_context", None)
            if is_gee_retry_confirmation(message, recovery_context):
                retry_message = build_gee_retry_message(message, recovery_context)
                self.harness_thread.recovery_context = None
                self.logger.info("Resuming the last confirmed GEE workflow after user configuration acknowledgement.")
            controller = getattr(self.harness_thread, "step_controller", None)
            plan = getattr(controller, "plan", None)
            has_active_step = bool(plan and plan.active_step())
            if should_resume_approved_plan(
                message,
                mode,
                self.harness_thread.plan_approved,
                has_active_step,
            ):
                resume_plan_payload = plan.to_dict()
                resume_project_home = getattr(controller, "project_home", "")

        if self.harness_thread:
            signal_slots = (
                (self.harness_thread.append_message_signal, self.dockwidget.append_message),
                (self.harness_thread.finished_signal, self.dockwidget.on_agent_finished),
                (self.harness_thread.request_human_input_signal, self.handle_ask_human),
                (self.harness_thread.request_destructive_auth_signal, self.handle_destructive_auth),
                (self.harness_thread.request_plan_approval_signal, self.handle_request_plan_approval),
                (self.harness_thread.request_code_execution_signal, self.handle_code_execution),
                (self.harness_thread.request_canvas_image_signal, self.handle_canvas_image),
                (self.harness_thread.request_atomic_tool_signal, self.handle_atomic_tool),
                (self.harness_thread.metrics_signal, self.dockwidget.on_metrics_updated),
                (self.harness_thread.finished, self._start_next_pending_request),
            )
            for signal, slot in signal_slots:
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
                
        self.harness_thread = HarnessThread(self.plugin_dir, existing_messages=self.global_messages)
        self.harness_thread.user_input = retry_message or message
        self.harness_thread.model_name = model
        self.harness_thread.effort_level = effort
        self.harness_thread.work_mode = mode
        if resume_plan_payload:
            from .core.task_state import TaskPlan
            self.harness_thread.plan_approved = True
            self.harness_thread.step_controller.load_plan(
                TaskPlan.from_dict(resume_plan_payload),
                resume_project_home,
                "",
            )
            self.logger.info("Resumed an approved, incomplete PLAN task for the new turn.")
        
        self.harness_thread.append_message_signal.connect(self.dockwidget.append_message)
        self.harness_thread.finished_signal.connect(self.dockwidget.on_agent_finished)
        self.harness_thread.request_human_input_signal.connect(self.handle_ask_human)
        self.harness_thread.request_destructive_auth_signal.connect(self.handle_destructive_auth)
        self.harness_thread.request_plan_approval_signal.connect(self.handle_request_plan_approval)
        self.harness_thread.request_code_execution_signal.connect(self.handle_code_execution)
        self.harness_thread.request_canvas_image_signal.connect(self.handle_canvas_image)
        self.harness_thread.request_atomic_tool_signal.connect(self.handle_atomic_tool)
        self.harness_thread.metrics_signal.connect(self.dockwidget.on_metrics_updated)
        self.harness_thread.operation_progress_signal.connect(self.dockwidget.operation_progress_signal.emit)
        self.harness_thread.finished.connect(self._start_next_pending_request)
        
        self.harness_thread.start()

    def _start_next_pending_request(self):
        if not self._pending_user_requests or not self.dockwidget:
            return
        request = self._pending_user_requests.pop(0)
        remaining = len(self._pending_user_requests)
        self.logger.info("Starting queued user request. remaining=%s", remaining)
        self.dockwidget.append_message("SYSTEM", "当前任务已结束，正在启动下一条排队请求。")
        self.dockwidget.set_agent_status("Agent is thinking...", is_running=True)

        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(
            0,
            lambda request=request: self.handle_user_message(
                request["message"],
                request["model"],
                request["effort"],
                request["mode"],
            ),
        )

    @staticmethod
    def _prune_temp_images(temp_dir, max_files=20):
        try:
            entries = [
                os.path.join(temp_dir, fn)
                for fn in os.listdir(temp_dir)
                if fn.startswith("qgis_window_") and fn.lower().endswith(".png")
            ]
            if len(entries) <= max_files:
                return
            entries.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for stale_path in entries[max_files:]:
                try:
                    os.remove(stale_path)
                except OSError:
                    pass
        except OSError:
            pass

    def handle_atomic_tool(self, name, kwargs):
        progress_callback = None
        cancel_callback = None
        operation_id = ""
        is_acquisition = False
        result = "Error: Atomic tool execution did not complete."
        try:
            try:
                from .core.progress import DATA_ACQUISITION_TOOLS, emit_progress
                is_acquisition = name in DATA_ACQUISITION_TOOLS
                if is_acquisition:
                    operation_id = f"{name}:{time.monotonic_ns()}"
                    titles = {
                        "download_osm_data": "OSM 数据下载",
                        "download_osm_boundary": "OSM 行政边界下载",
                        "download_osm_roads": "OSM 路网下载",
                        "download_osm_features": "OSM 要素下载",
                        "run_osm_acquisition_workflow": "连续 OSM 数据获取",
                        "run_gee_sentinel2_download_workflow": "GEE Sentinel-2 数据获取",
                        "run_gee_dem_download_workflow": "GEE DEM 数据获取",
                    }
                    title = titles.get(name, "数据获取")
                    last_log = {"signature": None, "time": 0.0}

                    def _publish_progress(event):
                        payload = dict(event or {})
                        payload["operation_id"] = operation_id
                        if self.dockwidget:
                            self.dockwidget.operation_progress_signal.emit(payload)
                        signature = (
                            payload.get("state"),
                            payload.get("stage_index"),
                            payload.get("stage"),
                            int(float(payload.get("percent") or 0) // 10),
                        )
                        now = time.monotonic()
                        if signature != last_log["signature"] or now - last_log["time"] >= 10.0:
                            self.logger.info(
                                "Acquisition progress: tool=%s state=%s stage=%s/%s %s percent=%s detail=%s",
                                name,
                                payload.get("state", "running"),
                                payload.get("stage_index", 1),
                                payload.get("stage_count", 1),
                                payload.get("stage", ""),
                                payload.get("percent"),
                                payload.get("detail", ""),
                            )
                            last_log["signature"] = signature
                            last_log["time"] = now

                    progress_callback = _publish_progress
                    cancel_callback = lambda: bool(self.harness_thread and self.harness_thread.is_killed)
                    emit_progress(
                        progress_callback,
                        tool_name=name,
                        title=title,
                        stage="准备参数",
                        stage_index=1,
                        stage_count=1,
                        stage_percent=0,
                        detail="正在启动数据获取工具。",
                    )

                if name == "take_qgis_window_snapshot":
                    import os, uuid
                    window = self.iface.mainWindow()
                    pixmap = window.grab()
                    temp_dir = os.path.join(self.plugin_dir, "temp_images")
                    os.makedirs(temp_dir, exist_ok=True)
                    self._prune_temp_images(temp_dir, max_files=19)
                    img_path = os.path.join(temp_dir, f"qgis_window_{uuid.uuid4().hex[:8]}.png")
                    pixmap.save(img_path)
                    result = f"[IMAGE_PATH]{img_path}"
                else:
                    from .tools.tools import execute_atomic_tool_structured
                    result = execute_atomic_tool_structured(
                        self.iface,
                        name,
                        kwargs,
                        progress_callback=progress_callback,
                        cancel_callback=cancel_callback,
                    )
            except Exception as e:
                self.logger.error("Atomic tool %s failed on main thread: %s", name, e, exc_info=True)
                result = f"Error: {str(e)}"

            if is_acquisition and progress_callback:
                try:
                    from .core.progress import emit_progress
                    from .core.tool_result import parse_tool_result_payload
                    result_payload = parse_tool_result_payload(result) or {}
                    result_ok = bool(result_payload.get("ok"))
                    error_type = str(result_payload.get("error_type") or "")
                    state = "completed" if result_ok else "cancelled" if error_type == "operation_cancelled" else "failed"
                    message = result_payload.get("message", str(result))
                    emit_progress(
                        progress_callback,
                        tool_name=name,
                        title={
                            "download_osm_data": "OSM 数据下载",
                            "download_osm_boundary": "OSM 行政边界下载",
                            "download_osm_roads": "OSM 路网下载",
                            "download_osm_features": "OSM 要素下载",
                            "run_osm_acquisition_workflow": "连续 OSM 数据获取",
                            "run_gee_sentinel2_download_workflow": "GEE Sentinel-2 数据获取",
                            "run_gee_dem_download_workflow": "GEE DEM 数据获取",
                        }.get(name, "数据获取"),
                        stage="完成" if result_ok else "已取消" if state == "cancelled" else "失败",
                        stage_index=1,
                        stage_count=1,
                        stage_percent=100 if result_ok else 0,
                        detail=str(message)[:240],
                        state=state,
                    )
                except Exception as e:
                    self.logger.debug("Failed to emit final acquisition progress for %s: %s", name, e, exc_info=True)
        finally:
            if self.harness_thread:
                self.harness_thread.atomic_tool_response = result
                self.harness_thread.atomic_tool_event.set()

    def handle_canvas_image(self):
        img_path = ""
        try:
            import tempfile
            candidate_path = os.path.join(tempfile.gettempdir(), "qgis_canvas_snap.png")
            self.iface.mapCanvas().saveAsImage(candidate_path)
            img_path = candidate_path
        except Exception as e:
            self.logger.error("Error saving canvas: %s", e, exc_info=True)
        finally:
            if self.harness_thread:
                self.harness_thread.canvas_image_path = img_path
                self.harness_thread.canvas_image_event.set()

    def handle_ask_human(self, question):
        answer = "GUI Error: ask_human did not complete"
        try:
            answer = self.dockwidget.ask_human(question)
        except Exception as e:
            self.logger.error("GUI Crash in ask_human: %s", e, exc_info=True)
            answer = "GUI Error: " + str(e)
        finally:
            if self.harness_thread:
                self.harness_thread.human_input_response = answer
                self.harness_thread.human_input_event.set()
            
    def handle_destructive_auth(self, code):
        auth = False
        try:
            auth = self.dockwidget.ask_destructive_confirmation(code)
        except Exception as e:
            self.logger.error("GUI Crash in ask_destructive_confirmation: %s", e, exc_info=True)
            auth = False
        finally:
            if self.harness_thread:
                self.harness_thread.destructive_auth_response = auth
                self.harness_thread.destructive_auth_event.set()

    def handle_request_plan_approval(self):
        try:
            self.dockwidget.show_action_panel()
        except Exception as e:
            self.logger.error("GUI Crash in show_action_panel: %s", e, exc_info=True)
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
        lowered = normalized_head.lower()
        is_uri_or_service = (
            lowered.startswith(("http://", "https://", "memory:", "postgres:", "wms:", "wfs:", "crs=", "url=", "type="))
            or "://" in lowered
        )
        if not is_uri_or_service:
            try:
                if os.path.isabs(head) or os.path.exists(head):
                    normalized_head = os.path.normcase(os.path.abspath(head)).replace("\\", "/")
                else:
                    normalized_head = os.path.normcase(os.path.normpath(head)).replace("\\", "/")
            except (OSError, ValueError) as e:
                if hasattr(self, "logger") and self.logger:
                    self.logger.debug("Failed to canonicalize layer source %r: %s", source, e)
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
                except (AttributeError, RuntimeError, TypeError, ValueError) as e:
                    self.logger.debug("Failed to read source for layer %s: %s", layer_id, e)
                    source = ""
                try:
                    name = layer.name()
                except (AttributeError, RuntimeError, TypeError) as e:
                    self.logger.debug("Failed to read name for layer %s: %s", layer_id, e)
                    name = layer_id
                snapshot[layer_id] = {"id": layer_id, "name": name, "source": source, "type": layer_type}
            return snapshot
        except (ImportError, AttributeError, RuntimeError, TypeError) as e:
            self.logger.warning("Failed to snapshot project layers: %s", e, exc_info=True)
            return None

    def _cleanup_new_duplicate_layers(self, before_snapshot):
        if before_snapshot is None:
            self.logger.warning("Skipping duplicate layer cleanup because pre-execution layer snapshot failed.")
            return []
        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            after_snapshot = self._snapshot_project_layers()
            if after_snapshot is None:
                self.logger.warning("Skipping duplicate layer cleanup because post-execution layer snapshot failed.")
                return []
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
                    except (AttributeError, RuntimeError, TypeError) as e:
                        self.logger.warning("Failed to remove duplicate layer %s: %s", layer_id, e, exc_info=True)
            if removed:
                self.logger.info("Removed duplicate layers added by script: %s", removed)
            return removed
        except (ImportError, AttributeError, RuntimeError, TypeError) as e:
            self.logger.warning("Failed to clean duplicate layers: %s", e, exc_info=True)
            return []

    def _format_layer_delta(self, before_snapshot, after_snapshot, removed_duplicates=None):
        removed_duplicates = removed_duplicates or []
        if before_snapshot is None or after_snapshot is None:
            added = []
            removed = []
        else:
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

        output = "[EXECUTION_FAILED_TRACEBACK]\nMain-thread code execution did not complete."
        captured_logs = []
        log_interceptor = None
        try:
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
                message_level = getattr(Qgis, "MessageLevel", Qgis)
                warning_level = getattr(message_level, "Warning", getattr(Qgis, "Warning", None))
                critical_level = getattr(message_level, "Critical", getattr(Qgis, "Critical", None))
                def _interceptor(msg, tag, level):
                    if level in (warning_level, critical_level):
                        captured_logs.append(f"[{tag}] {msg}")
                log_interceptor = _interceptor
                QgsApplication.messageLog().messageReceived.connect(log_interceptor)
            except ImportError as e:
                self.logger.debug("Optional QGIS classes unavailable for code execution interceptor: %s", e)
            
            f = io.StringIO()
            layer_snapshot_before = self._snapshot_project_layers()
            try:
                from qgis.PyQt.QtWidgets import QApplication
                from qgis.PyQt.QtCore import Qt
                from .core.code_execution_guard import execute_main_thread_code
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    with redirect_stdout(f):
                        execute_main_thread_code(
                            code,
                            env_dict,
                            cancel_callback=lambda: bool(self.harness_thread and self.harness_thread.is_killed),
                        )
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
                    
            except Exception:
                stdout_str = f.getvalue().strip()
                tb = traceback.format_exc()
                self.logger.warning("Main-thread PyQGIS execution failed:\n%s", tb)
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
                            best_match = sorted(matches, key=len, reverse=True)[0]
                            search_term = best_match.split('.')[-1]
                            fallback_info = execute_atomic_tool(self.iface, "search_gee_api", {"query": search_term})
                            if not fallback_info.startswith("No API found") and not fallback_info.startswith("Error") and not fallback_info.startswith("Failed"):
                                output += f"\n\n[GEE API FALLBACK (AUTO-RETRIEVED)]\nIt looks like a GEE API call failed. Here is the official signature for `{best_match}` (and related) to help you fix it:\n\n{fallback_info}"
                    except Exception as e:
                        self.logger.debug("Failed to retrieve GEE API fallback info: %s", e, exc_info=True)
            finally:
                if log_interceptor is not None:
                    try:
                        from qgis.core import QgsApplication
                        QgsApplication.messageLog().messageReceived.disconnect(log_interceptor)
                    except (ImportError, TypeError, RuntimeError, AttributeError) as e:
                        self.logger.debug("Failed to disconnect messageLog interceptor: %s", e)

            try:
                removed_duplicates = self._cleanup_new_duplicate_layers(layer_snapshot_before)
                layer_snapshot_after = self._snapshot_project_layers()
                layer_delta = self._format_layer_delta(layer_snapshot_before, layer_snapshot_after, removed_duplicates)
                if layer_delta:
                    output += "\n\n[PROJECT LAYER CHANGES]\n" + layer_delta
            except (AttributeError, RuntimeError, TypeError, ValueError) as e:
                self.logger.warning("Failed to append layer change summary: %s", e, exc_info=True)
        finally:
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
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as e:
            self.logger.error(f"Failed to save sandbox memory: {e}", exc_info=True)

    def _current_project_key(self):
        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            project_path = ""
            for attr in ("absoluteFilePath", "fileName"):
                try:
                    value = getattr(project, attr)()
                except (AttributeError, RuntimeError, TypeError):
                    value = ""
                if isinstance(value, str) and value.strip() and "MagicMock" not in value:
                    project_path = value
                    break
            raw_home = project.homePath()
            home_path = raw_home if isinstance(raw_home, str) and raw_home.strip() and "MagicMock" not in raw_home else ""
            return "|".join([
                os.path.normcase(os.path.abspath(project_path)) if project_path else "<unsaved>",
                os.path.normcase(os.path.abspath(home_path)) if home_path else "<no_home>",
            ])
        except (ImportError, OSError, AttributeError, RuntimeError, TypeError, ValueError) as e:
            self.logger.warning(f"Failed to build project key: {e}", exc_info=True)
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
        if self.dockwidget:
            self.dockwidget.reset_for_new_project()

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
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as e:
            self.logger.error(f"Failed to load sandbox memory: {e}", exc_info=True)
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
