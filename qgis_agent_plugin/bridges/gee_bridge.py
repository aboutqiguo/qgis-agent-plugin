import logging
import json
import re

try:
    import ee
except ImportError:
    ee = None

from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit, QMessageBox
from qgis.core import QgsProject, QgsRasterLayer, Qgis
from qgis.utils import iface

logger = logging.getLogger(__name__)

GEE_EXPORT_FOLDER = "QGIS_Agent_Exports"


def is_ee_available():
    """Check if the Earth Engine API is installed and importable."""
    global ee
    if ee is not None:
        return True
    try:
        from ..utils.dependency_manager import ensure_sys_path
        ensure_sys_path()
        import ee as _ee
        ee = _ee
        return True
    except ImportError:
        return False


class GEEManualDownloadRequired(Exception):
    def __init__(self, message, target_files=None, folder_name="", dest_dir=""):
        super().__init__(message)
        self.target_files = target_files or []
        self.folder_name = folder_name
        self.dest_dir = dest_dir

    def to_dict(self):
        return {
            "target_files": self.target_files,
            "folder_name": self.folder_name,
            "dest_dir": self.dest_dir,
        }


class GEEProjectConfigurationError(RuntimeError):
    """Raised when a selected Cloud project cannot use the Earth Engine API."""

    def __init__(self, project_id, message):
        self.project_id = str(project_id or "").strip()
        super().__init__(message)

def init_gee():
    """Helper function for the Agent to securely initialize GEE with UI fallback."""
    if not GEEAuth.authenticate_and_initialize():
        raise Exception("Google Earth Engine authentication failed or was cancelled by the user.")

def clear_gee_auth():
    """Clears the local GEE credentials cache and project ID."""
    from qgis.core import QgsSettings
    settings = QgsSettings()
    settings.remove("gee_agent_project_id")
    # EE credentials path
    import os, shutil
    ee_path = os.path.expanduser("~/.config/earthengine")
    if os.path.exists(ee_path):
        try:
            shutil.rmtree(ee_path)
        except:
            pass
    try:
        reset = getattr(ee, "Reset", None)
        if callable(reset):
            reset()
    except Exception:
        pass

class GEEAuth:
    @staticmethod
    def prompt_for_project(default_project=""):
        from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
        from qgis.PyQt.QtCore import Qt
        
        dialog = QDialog()
        dialog.setWindowTitle("绑定 Earth Engine 项目")
        dialog.resize(450, 200)
        
        layout = QVBoxLayout(dialog)
        
        msg = """访问 Earth Engine 需要绑定一个 Google Cloud Project (GCP) 项目。<br>
        <br>
        如何获取您的 Project ID：<br>
        1. 前往 <a href="https://console.cloud.google.com/">Google Cloud Console (控制台)</a>。<br>
        2. 您的 Project ID 可以直接在 URL 中看到，或者在左上角的资源列表中找到。<br>
        <br><b>请输入您的 Google Cloud Project ID：</b>"""
        
        label = QLabel(msg)
        label.setOpenExternalLinks(True)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        layout.addWidget(label)
        
        input_field = QLineEdit()
        input_field.setText(str(default_project or "").strip())
        input_field.setPlaceholderText("例如 my-gcp-project-123")
        layout.addWidget(input_field)
        
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确定 (OK)")
        cancel_btn = QPushButton("取消 (Cancel)")
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        if dialog.exec() == QDialog.Accepted:
            project = input_field.text().strip()
            if project:
                return project
        return None

    @staticmethod
    def _project_from_error(error, fallback_project=""):
        message = str(error or "")
        match = re.search(r"project\s+([a-z][a-z0-9-]{2,})", message, flags=re.IGNORECASE)
        return match.group(1) if match else str(fallback_project or "").strip()

    @staticmethod
    def _normalize_configuration_error(error, project_id=""):
        message = str(error or "")
        lowered = message.lower()
        project = GEEAuth._project_from_error(error, project_id)
        disabled_markers = (
            "earth engine api has not been used",
            "earthengine.googleapis.com",
            "api is disabled",
            "service disabled",
        )
        if any(marker in lowered for marker in disabled_markers):
            console_url = (
                "https://console.cloud.google.com/apis/library/earthengine.googleapis.com"
                + (f"?project={project}" if project else "")
            )
            return GEEProjectConfigurationError(
                project,
                "Google Earth Engine API 尚未在当前 Google Cloud Project 中启用，或启用尚未生效。\n\n"
                f"Project ID：{project or '未识别'}\n"
                f"请在浏览器打开并启用 API：{console_url}\n"
                "启用后等待 2-5 分钟，再在插件设置中点击“验证并连接”。",
            )
        return error

    @staticmethod
    def user_facing_error(error):
        normalized = GEEAuth._normalize_configuration_error(error)
        return str(normalized)

    @staticmethod
    def _initialize_and_verify(project_id):
        if not is_ee_available():
            raise RuntimeError("未检测到 Google Earth Engine API (earthengine-api) 依赖。请在插件设置中点击【安装依赖】或在终端运行：pip install earthengine-api")
        project_id = str(project_id or "").strip()
        if not project_id:
            raise ValueError("Earth Engine 需要明确的 Google Cloud Project ID。")
        try:
            # Never fall back to ee.Initialize() without a project: that can silently
            # use an old quota project from the local credential cache.
            ee.Initialize(project=project_id)
            # Initialization alone does not prove that the Earth Engine API is enabled.
            ee.Number(1).getInfo()
            return True
        except Exception as exc:
            normalized = GEEAuth._normalize_configuration_error(exc, project_id)
            if normalized is exc:
                raise
            raise normalized from exc

    @staticmethod
    def authenticate_and_initialize(force=False, project_id=""):
        """Initialize a selected GCP project and verify API access before work starts."""
        if not is_ee_available():
            raise RuntimeError("未检测到 Google Earth Engine API (earthengine-api) 依赖。请在插件设置中点击【安装依赖】或在终端运行：pip install earthengine-api")
        from qgis.core import QgsSettings
        settings = QgsSettings()

        selected_project = str(project_id or settings.value("gee_agent_project_id", "") or "").strip()
        last_error = None
        try:
            if not force:
                if not selected_project:
                    selected_project = GEEAuth.prompt_for_project()
                    if not selected_project:
                        iface.messageBar().pushMessage("GEE", "Earth Engine 需要绑定 Project ID。", level=Qgis.MessageLevel.Warning)
                        return False
                try:
                    GEEAuth._initialize_and_verify(selected_project)
                    settings.setValue("gee_agent_project_id", selected_project)
                    return True
                except GEEProjectConfigurationError:
                    raise
                except Exception as exc:
                    last_error = exc
                    logger.info("GEE saved credentials require re-authentication: %s", exc)

                msg = (
                    "无法使用当前 Earth Engine 凭证或其已失效。\n\n"
                    "点击“确定”将在浏览器中重新认证。认证完成后，插件会使用下方已选择的 Project ID 进行验证。"
                )
                reply = QMessageBox.warning(None, "重新认证 Google Earth Engine", msg, QMessageBox.Cancel | QMessageBox.Ok)
                if reply == QMessageBox.Cancel:
                    iface.messageBar().pushMessage("GEE", "认证已取消。", level=Qgis.MessageLevel.Warning)
                    return False

            # Use localhost:0 to tell the OS to allocate a dynamic random port!
            # This completely bypasses WinError 10013 caused by firewall blocking the default 8085 port.
            scopes = [
                'https://www.googleapis.com/auth/earthengine',
                'https://www.googleapis.com/auth/devstorage.full_control',
                'https://www.googleapis.com/auth/drive'
            ]
            ee.Authenticate(auth_mode="localhost:0", force=True, scopes=scopes)

            if not selected_project:
                selected_project = GEEAuth.prompt_for_project()
            if not selected_project:
                iface.messageBar().pushMessage("GEE", "Earth Engine 需要绑定 Project ID。", level=Qgis.MessageLevel.Critical)
                return False

            GEEAuth._initialize_and_verify(selected_project)
            settings.setValue("gee_agent_project_id", selected_project)
            iface.messageBar().pushMessage("GEE", f"已成功认证并验证 Project：{selected_project}。", level=Qgis.MessageLevel.Success)
            return True

        except GEEProjectConfigurationError:
            raise
        except Exception:
            # The settings dialog needs the real error in order to show a useful recovery action.
            raise

class AgentMap:
    @staticmethod
    def addLayer(ee_object, vis_params=None, name="GEE Layer", shown=True, opacity=1.0):
        """
        Adds a given EE object to the QGIS map as an XYZ raster layer.
        Mimics Map.addLayer from the JavaScript API.
        """
        if vis_params is None:
            vis_params = {}
            
        init_gee()
        
        if isinstance(ee_object, ee.FeatureCollection) or isinstance(ee_object, ee.Geometry):
            # For vectors, just paint them so we can display them as a raster
            ee_object = ee.Image().paint(ee_object, 0, 2)
            
        if isinstance(ee_object, ee.ImageCollection):
            # Render median of collection by default if not an image
            ee_object = ee_object.median()

        if not isinstance(ee_object, ee.Image):
            raise TypeError("Unsupported EE object type. Please provide an ee.Image, ee.FeatureCollection, or ee.Geometry.")

        # Get Map ID from EE
        map_id_dict = ee_object.getMapId(vis_params)
        tile_url = map_id_dict['tile_fetcher'].urlFormat
        
        # Construct QGIS XYZ URL
        qgis_url = f"type=xyz&url={tile_url}"
        
        # Check if layer already exists to update it, else create new
        existing_layers = QgsProject.instance().mapLayersByName(name)
        if existing_layers:
            layer = existing_layers[0]
            layer.setDataSource(qgis_url, name, "wms")
            layer.triggerRepaint()
        else:
            layer = QgsRasterLayer(qgis_url, name, "wms")
            if not layer.isValid():
                raise Exception(f"Failed to load GEE Layer: {name}")
            QgsProject.instance().addMapLayer(layer)
            
        # Set opacity
        if opacity is not None and layer.renderer():
            layer.renderer().setOpacity(opacity)
            
        # Set visibility
        if shown is not None:
            layer_node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            if layer_node:
                layer_node.setItemVisibilityChecked(shown)
                
        # Try to zoom to extent if possible
        try:
            coords = ee_object.geometry().bounds().getInfo().get("coordinates", [])
            bounds = coords[0] if coords else []
            xs = [pt[0] for pt in bounds]
            ys = [pt[1] for pt in bounds]
            from qgis.core import QgsRectangle, QgsCoordinateReferenceSystem, QgsCoordinateTransform
            rect4326 = QgsRectangle(min(xs), min(ys), max(xs), max(ys))
            crs_src = QgsCoordinateReferenceSystem("EPSG:4326")
            crs_dest = QgsCoordinateReferenceSystem(QgsProject.instance().crs())
            xform = QgsCoordinateTransform(crs_src, crs_dest, QgsProject.instance())
            rect_proj = xform.transform(rect4326)
            
            # Zoom to extent
            iface.mapCanvas().zoomToFeatureExtent(rect_proj)
        except Exception as e:
            logger.debug(f"Could not set extent from ee_object: {e}")
            
        iface.messageBar().pushMessage("GEE", f"Layer '{name}' added successfully.", level=Qgis.MessageLevel.Success)
        return layer

import os
import time
import shutil

from qgis.core import QgsTask

class GEEDownloadTask(QgsTask):
    def __init__(self, description, download_url, dest_path, headers=None, expected_size=None):
        super().__init__(description, QgsTask.CanCancel)
        self.download_url = download_url
        self.dest_path = dest_path
        self.headers = headers or {}
        self.expected_size = int(expected_size or 0)
        self.exception = None
        self.downloaded_bytes = 0
        self.total_bytes = self.expected_size

    def progress_detail(self):
        if self.total_bytes > 0:
            return f"已下载 {self.downloaded_bytes / (1024 * 1024):.1f}/{self.total_bytes / (1024 * 1024):.1f} MB"
        return f"已下载 {self.downloaded_bytes / (1024 * 1024):.1f} MB"
        
    def run(self):
        import requests
        import os
        part_path = f"{self.dest_path}.part"
        try:
            existing_size = os.path.getsize(part_path) if os.path.exists(part_path) else 0
            request_headers = dict(self.headers)
            if existing_size > 0:
                request_headers["Range"] = f"bytes={existing_size}-"
            with requests.get(self.download_url, headers=request_headers, stream=True, timeout=(30, 300)) as r:
                r.raise_for_status()
                total_length = r.headers.get('content-length')
                total_length = int(total_length) if total_length else 0
                resume_accepted = existing_size > 0 and r.status_code == 206
                if not resume_accepted:
                    existing_size = 0
                
                os.makedirs(os.path.dirname(self.dest_path), exist_ok=True)
                downloaded = existing_size
                with open(part_path, 'ab' if resume_accepted else 'wb') as f:
                    progress_total = (
                        self.expected_size
                        or (existing_size + total_length if resume_accepted else total_length)
                    )
                    self.total_bytes = progress_total
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if self.isCanceled():
                            return False
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.downloaded_bytes = downloaded
                        if progress_total > 0:
                            self.setProgress(min(100.0, downloaded / progress_total * 100.0))
                expected_response_total = existing_size + total_length if resume_accepted else total_length
                if expected_response_total > 0 and downloaded != expected_response_total:
                    raise IOError(f"Incomplete download: got {downloaded} bytes, expected {expected_response_total} bytes.")
                if self.expected_size > 0 and downloaded != self.expected_size:
                    raise IOError(f"Downloaded size mismatch: got {downloaded} bytes, Drive reported {self.expected_size} bytes.")
                os.replace(part_path, self.dest_path)
            return True
        except Exception as e:
            self.exception = e
            return False

class GEEWaitTask(QgsTask):
    def __init__(self, description, task_id, timeout=3600):
        super().__init__(description, QgsTask.CanCancel)
        self.task_id = task_id
        self.timeout = timeout
        self.exception = None
        self.started_at = 0.0
        self.elapsed_seconds = 0
        self.latest_state = "SUBMITTED"

    def progress_detail(self):
        elapsed = int(time.time() - self.started_at) if self.started_at else self.elapsed_seconds
        return f"服务端状态 {self.latest_state} · 已等待 {elapsed} 秒 · 任务 {self.task_id}"
        
    def run(self):
        import ee
        import time
        import warnings
        start_time = time.time()
        self.started_at = start_time
        while True:
            if self.isCanceled():
                return False
                
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=r".*getTaskStatus\(\) is deprecated.*",
                        category=DeprecationWarning,
                    )
                    status_list = ee.data.getTaskStatus(self.task_id)
                if not status_list:
                    self.exception = Exception(f"Task ID {self.task_id} not found.")
                    return False
                status = status_list[0]
            except Exception as e:
                self.exception = Exception(f"Failed to get task status: {e}")
                return False
                
            state = status.get('state')
            self.latest_state = str(state or "UNKNOWN")
            self.elapsed_seconds = int(time.time() - start_time)
            if state == 'COMPLETED':
                return True
            elif state in ['FAILED', 'CANCELLED']:
                error_msg = status.get('error_message', 'Unknown error')
                self.exception = Exception(f"GEE Task {state}: {error_msg}")
                return False
                
            if time.time() - start_time > self.timeout:
                self.exception = Exception("Timeout waiting for GEE Task to complete.")
                return False
                
            # Sleep in small chunks to remain responsive to cancellation
            for _ in range(10):
                if self.isCanceled():
                    return False
                time.sleep(1)

class GEEDriveSyncTask(QgsTask):
    def __init__(self, description, drive_dir, filename_prefix, timeout=3600):
        super().__init__(description, QgsTask.CanCancel)
        self.drive_dir = drive_dir
        self.filename_prefix = filename_prefix
        self.timeout = timeout
        self.exception = None
        self.synced_files = []
        self.started_at = 0.0
        self.elapsed_seconds = 0

    def progress_detail(self):
        elapsed = int(time.time() - self.started_at) if self.started_at else self.elapsed_seconds
        return f"等待 Google Drive 本地同步 · 已等待 {elapsed} 秒"
        
    def run(self):
        import time, os, glob
        start_time = time.time()
        self.started_at = start_time
        while True:
            if self.isCanceled():
                return False
            
            pattern = os.path.join(self.drive_dir, f"{self.filename_prefix}*.tif")
            files = glob.glob(pattern)
            self.elapsed_seconds = int(time.time() - start_time)
            
            if files:
                time.sleep(2) # Wait a bit for potential file size changes
                all_stable = True
                for f in files:
                    try:
                        size1 = os.path.getsize(f)
                        time.sleep(0.5)
                        size2 = os.path.getsize(f)
                        if size1 != size2 or size1 == 0:
                            all_stable = False
                            break
                    except Exception:
                        all_stable = False
                        break
                        
                if all_stable:
                    self.synced_files = files
                    return True
                    
            if time.time() - start_time > self.timeout:
                self.exception = Exception("Timeout waiting for local Google Drive sync.")
                return False
            for _ in range(5):
                if self.isCanceled(): return False
                time.sleep(1)

class GEECopyTask(QgsTask):
    def __init__(self, description, src_path, dest_path):
        super().__init__(description, QgsTask.CanCancel)
        self.src_path = src_path
        self.dest_path = dest_path
        self.exception = None
        self.copied_bytes = 0
        self.total_bytes = 0

    def progress_detail(self):
        if self.total_bytes > 0:
            return f"已复制 {self.copied_bytes / (1024 * 1024):.1f}/{self.total_bytes / (1024 * 1024):.1f} MB"
        return "正在复制文件"
        
    def run(self):
        import os
        part_path = f"{self.dest_path}.part"
        try:
            total_length = os.path.getsize(self.src_path)
            self.total_bytes = total_length
            copied = 0
            with open(self.src_path, 'rb') as f_in:
                os.makedirs(os.path.dirname(self.dest_path), exist_ok=True)
                with open(part_path, 'wb') as f_out:
                    while True:
                        if self.isCanceled():
                            try:
                                f_out.close()
                                os.remove(part_path)
                            except Exception:
                                pass
                            return False
                        chunk = f_in.read(1024 * 1024 * 5) # 5MB chunks
                        if not chunk:
                            break
                        f_out.write(chunk)
                        copied += len(chunk)
                        self.copied_bytes = copied
                        if total_length > 0:
                            self.setProgress(copied / total_length * 100.0)
            if total_length > 0 and copied != total_length:
                raise IOError(f"Incomplete local copy: got {copied} bytes, expected {total_length} bytes.")
            os.replace(part_path, self.dest_path)
            return True
        except Exception as e:
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)
            except Exception:
                pass
            self.exception = e
            return False


class GEEDownloader:
    @staticmethod
    def _emit_progress(callback, context, stage_percent=None, detail="", state="running"):
        if not callback or not context:
            return
        from ..core.progress import emit_progress

        emit_progress(
            callback,
            tool_name=context.get("tool_name", "gee_download"),
            title=context.get("title", "GEE 数据获取"),
            stage=context.get("stage", "处理中"),
            stage_index=context.get("stage_index", 1),
            stage_count=context.get("stage_count", 1),
            stage_percent=stage_percent,
            detail=detail,
            state=state,
        )

    @staticmethod
    def _format_drive_manual_download_message(target_files, folder_name, dest_dir, reason="", sync_path=""):
        lines = [
            "GEE export finished, but the plugin could not automatically download the exported file(s).",
        ]
        if reason:
            lines.append(f"Reason: {reason}")
        lines.extend([
            "",
            "Manual download steps:",
            "1. Open Google Drive in your browser.",
            f"2. Go to folder: {folder_name}",
            "3. Download the following exported GeoTIFF file(s):",
        ])
        for f_info in target_files or []:
            size_bytes = int(f_info.get("size", 0) or 0)
            size_mb = size_bytes / (1024 * 1024) if size_bytes else 0
            file_id = f_info.get("id", "")
            link = f"https://drive.google.com/file/d/{file_id}/view" if file_id else ""
            size_text = f"{size_mb:.1f} MB" if size_bytes else "unknown size"
            lines.append(f"   - {f_info.get('name', '')} ({size_text})")
            if link:
                lines.append(f"     {link}")
        lines.extend([
            f"4. Save/copy the downloaded file(s) into: {dest_dir}",
            "5. In QGIS Agent, run inspect_raster_file / validate_raster_has_data before using them.",
        ])
        if sync_path:
            lines.extend([
                "",
                f"Configured local Google Drive path was: {sync_path}",
                f"Expected synced folder: {os.path.join(sync_path, folder_name)}",
            ])
        return "\n".join(lines)

    @staticmethod
    def _raise_manual_drive_download(target_files, folder_name, dest_dir, reason="", sync_path=""):
        message = GEEDownloader._format_drive_manual_download_message(
            target_files,
            folder_name,
            dest_dir,
            reason=reason,
            sync_path=sync_path,
        )
        try:
            iface.messageBar().pushMessage("GEE Manual Download", message[:500], level=Qgis.MessageLevel.Critical, duration=30)
        except Exception:
            pass
        raise GEEManualDownloadRequired(
            message,
            target_files=target_files,
            folder_name=folder_name,
            dest_dir=dest_dir,
        )

    @staticmethod
    def run_qgs_task_sync(
        task,
        progress_callback=None,
        progress_context=None,
        cancel_callback=None,
    ):
        from qgis.core import QgsApplication, QgsTask
        from qgis.PyQt.QtCore import QEventLoop, QCoreApplication, QTimer
        from ..core.progress import DataAcquisitionCancelled
        
        loop = QEventLoop()
        task.taskCompleted.connect(loop.quit)
        task.taskTerminated.connect(loop.quit)
        cancel_requested = {"value": False}

        def _task_detail():
            try:
                return str(task.progress_detail())
            except Exception:
                return str(getattr(task, "description", lambda: "")())

        def _on_progress(value):
            GEEDownloader._emit_progress(
                progress_callback,
                progress_context,
                stage_percent=float(value),
                detail=_task_detail(),
            )

        try:
            task.progressChanged.connect(_on_progress)
        except Exception:
            pass

        heartbeat = QTimer()
        heartbeat.setInterval(1000)

        def _heartbeat():
            try:
                should_cancel = bool(cancel_callback and cancel_callback())
            except Exception:
                should_cancel = False
            if should_cancel:
                cancel_requested["value"] = True
                task.cancel()
                return
            if progress_context and progress_context.get("indeterminate", False):
                GEEDownloader._emit_progress(
                    progress_callback,
                    progress_context,
                    stage_percent=None,
                    detail=_task_detail(),
                )

        heartbeat.timeout.connect(_heartbeat)
        GEEDownloader._emit_progress(
            progress_callback,
            progress_context,
            stage_percent=None if (progress_context or {}).get("indeterminate", False) else 0,
            detail=_task_detail(),
        )
        
        # Prevent crash if user closes QGIS while task is running
        app = QCoreApplication.instance()
        if app:
            app.aboutToQuit.connect(loop.quit)
        
        QgsApplication.taskManager().addTask(task)
        heartbeat.start()
        loop.exec()
        heartbeat.stop()
        
        if app:
            try:
                app.aboutToQuit.disconnect(loop.quit)
            except:
                pass
                
        # A QgsTask whose run() returns False is also marked Terminated. Its
        # captured exception must win over cancellation classification.
        if hasattr(task, 'exception') and task.exception:
            raise task.exception

        if task.status() == QgsTask.Terminated:
            cloud_task_id = str((progress_context or {}).get("cloud_task_id") or "")
            if cloud_task_id:
                raise DataAcquisitionCancelled(
                    "Local monitoring was cancelled. The Earth Engine cloud export may still be running "
                    f"(task_id={cloud_task_id}); check Earth Engine Tasks before retrying."
                )
            raise DataAcquisitionCancelled("The local data transfer task was cancelled by the user.")

        GEEDownloader._emit_progress(
            progress_callback,
            progress_context,
            stage_percent=100,
            detail=_task_detail(),
        )

        return True

    @staticmethod
    def wait_for_drive_sync(
        task_id,
        folder_name,
        filename,
        dest_dir,
        drive_root=r"G:\我的云端硬盘",
        timeout=3600,
        target_files=None,
        progress_callback=None,
        progress_context=None,
        cancel_callback=None,
    ):
        """
        Monitors a GEE export task and waits for Google Drive Desktop to sync the file locally.
        Once synced, copies the file to the destination directory while retaining the Drive source.
        """
        import os
        # 1. Wait for GEE Task to complete
        wait_task = GEEWaitTask(f"Waiting for GEE Cloud: {filename}", task_id, timeout)
        cloud_context = dict(progress_context or {})
        cloud_context.update(
            stage="GEE 云端处理",
            stage_index=3,
            stage_count=cloud_context.get("stage_count", 6),
            indeterminate=True,
            cloud_task_id=task_id,
        )
        GEEDownloader.run_qgs_task_sync(
            wait_task,
            progress_callback=progress_callback,
            progress_context=cloud_context,
            cancel_callback=cancel_callback,
        )
        iface.messageBar().pushMessage("GEE", "GEE Task completed! Waiting for local Drive sync...", level=Qgis.MessageLevel.Success)
        
        # 2. Wait for Google Drive Desktop to sync the file
        drive_dir = os.path.join(drive_root, folder_name)
        if not os.path.exists(drive_root) or not os.path.isdir(drive_root):
            GEEDownloader._raise_manual_drive_download(
                target_files or [{"name": f"{filename}.tif"}],
                folder_name,
                dest_dir,
                reason=f"Configured local Google Drive path does not exist: {drive_root}",
                sync_path=drive_root,
            )
        iface.messageBar().pushMessage("GEE Sync", f"Waiting for files to appear at {drive_dir}", level=Qgis.MessageLevel.Info)
        sync_task = GEEDriveSyncTask(f"Waiting for local sync: {filename}", drive_dir, filename, timeout)
        try:
            sync_context = dict(progress_context or {})
            sync_context.update(
                stage="等待 Google Drive 本地同步",
                stage_index=4,
                stage_count=sync_context.get("stage_count", 6),
                indeterminate=True,
            )
            GEEDownloader.run_qgs_task_sync(
                sync_task,
                progress_callback=progress_callback,
                progress_context=sync_context,
                cancel_callback=cancel_callback,
            )
        except Exception as exc:
            from ..core.progress import DataAcquisitionCancelled
            if isinstance(exc, DataAcquisitionCancelled):
                raise
            GEEDownloader._raise_manual_drive_download(
                target_files or [{"name": f"{filename}.tif"}],
                folder_name,
                dest_dir,
                reason=f"Local Google Drive sync failed or timed out: {exc}",
                sync_path=drive_root,
            )
        iface.messageBar().pushMessage("GEE Sync", f"{len(sync_task.synced_files)} file(s) synced locally!", level=Qgis.MessageLevel.Success)
        
        # 3. Copy to destination
        os.makedirs(dest_dir, exist_ok=True)
        copied_paths = []
        for drive_path in sync_task.synced_files:
            f_name = os.path.basename(drive_path)
            dest_path = os.path.join(dest_dir, f_name)
            
            iface.messageBar().pushMessage("GEE", f"Copying {f_name} to project folder...", level=Qgis.MessageLevel.Info)
            try:
                copy_task = GEECopyTask(f"Copying {f_name} from Google Drive", drive_path, dest_path)
                copy_context = dict(progress_context or {})
                copy_context.update(
                    stage="复制到项目目录",
                    stage_index=4,
                    stage_count=copy_context.get("stage_count", 6),
                    indeterminate=False,
                )
                GEEDownloader.run_qgs_task_sync(
                    copy_task,
                    progress_callback=progress_callback,
                    progress_context=copy_context,
                    cancel_callback=cancel_callback,
                )
                GEEDownloader._validate_downloaded_raster(dest_path)
            except Exception as exc:
                from ..core.progress import DataAcquisitionCancelled
                if isinstance(exc, DataAcquisitionCancelled):
                    raise
                GEEDownloader._raise_manual_drive_download(
                    target_files or [{"name": f_name}],
                    folder_name,
                    dest_dir,
                    reason=f"Local Google Drive synced file failed copy or validation: {exc}",
                    sync_path=drive_root,
                )
            copied_paths.append(dest_path)
            
            # Retain the Drive Desktop source. Deleting this local mirror may delete
            # the cloud export as well, and deletion was not explicitly requested.
            logger.info("Retained Google Drive Desktop source after verified copy: %s", drive_path)

        iface.messageBar().pushMessage("GEE", "已保留 Google Drive 导出源文件；项目副本已验证。", level=Qgis.MessageLevel.Success)
        
        if len(copied_paths) == 1:
            return copied_paths[0]
        else:
            iface.messageBar().pushMessage("GEE", f"Merging {len(copied_paths)} tiles into a VRT...", level=Qgis.MessageLevel.Info)
            vrt_path = os.path.join(dest_dir, f"{filename}.vrt")
            try:
                from osgeo import gdal
                gdal.BuildVRT(vrt_path, copied_paths)
                return vrt_path
            except Exception as e:
                logger.error(f"Failed to build VRT: {e}")
                return copied_paths[0]

    @staticmethod
    def _download_via_drive_api(
        task_id,
        folder_name,
        filename,
        dest_dir,
        timeout=3600,
        not_before="",
        progress_callback=None,
        progress_context=None,
        cancel_callback=None,
    ):
        import ee
        import requests
        import os
        from qgis.core import QgsSettings
        
        # 1. Wait for task to complete
        wait_task = GEEWaitTask(f"Waiting for GEE Cloud: {filename}", task_id, timeout)
        cloud_context = dict(progress_context or {})
        cloud_context.update(
            stage="GEE 云端处理",
            stage_index=3,
            stage_count=cloud_context.get("stage_count", 6),
            indeterminate=True,
            cloud_task_id=task_id,
        )
        GEEDownloader.run_qgs_task_sync(
            wait_task,
            progress_callback=progress_callback,
            progress_context=cloud_context,
            cancel_callback=cancel_callback,
        )
        iface.messageBar().pushMessage("GEE", "GEE Task completed! Querying Google Drive API...", level=Qgis.MessageLevel.Success)
            
        # 2. Authenticate against Drive API
        credentials = ee.data.get_persistent_credentials()
        headers = {}
        credentials.apply(headers)
        
        # 3. Search for the file in Drive and get size
        search_url = "https://www.googleapis.com/drive/v3/files"
        safe_filename = str(filename).replace("'", "\\'")
        query_parts = [f"name contains '{safe_filename}'", "trashed=false"]
        if not_before:
            query_parts.append(f"createdTime >= '{not_before}'")
        params = {
            'q': " and ".join(query_parts),
            'fields': 'files(id, name, size, createdTime, parents)',
            'pageSize': 1000,
            'orderBy': 'createdTime desc',
        }
        drive_context = dict(progress_context or {})
        drive_context.update(
            stage="查询 Google Drive 导出文件",
            stage_index=4,
            stage_count=drive_context.get("stage_count", 6),
            indeterminate=True,
        )
        GEEDownloader._emit_progress(
            progress_callback,
            drive_context,
            stage_percent=None,
            detail="正在查询本次任务生成的 GeoTIFF。",
        )
        res = requests.get(search_url, params=params, headers=headers, timeout=60)
        res.raise_for_status()
        files = res.json().get('files', [])
        
        target_files = [f for f in files if f['name'] == f"{filename}.tif" or (f['name'].startswith(f"{filename}-") and f['name'].endswith(".tif"))]
        
        if not target_files:
            raise Exception(f"File(s) for {filename} not found in Google Drive!")
            
        total_size_bytes = sum(int(f.get('size', 0)) for f in target_files)
        total_size_mb = total_size_bytes / (1024 * 1024)
        
        iface.messageBar().pushMessage("GEE", f"File size on Drive: {total_size_mb:.1f} MB", level=Qgis.MessageLevel.Info)
        
        # Drive media downloads are not limited by Earth Engine's 32 MB
        # getDownloadURL limit. Use streaming + size/raster validation for all
        # export sizes, then fall back to local sync only on real API failure.
        settings = QgsSettings()
        sync_path = settings.value("qgis_agent/gee_drive_sync_path", r"G:\我的云端硬盘")
        os.makedirs(dest_dir, exist_ok=True)
        downloaded_paths = []
        
        # 4. Download file(s)
        try:
            for idx, f_info in enumerate(target_files):
                file_id = f_info['id']
                f_name = f_info['name']
                download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
                dest_path = os.path.join(dest_dir, f_name)
                expected_size = int(f_info.get('size', 0) or 0)
                
                iface.messageBar().pushMessage("GEE", f"Downloading {f_name} ({idx+1}/{len(target_files)}) via Drive API...", level=Qgis.MessageLevel.Info)
                dl_task = GEEDownloadTask(f"Downloading {f_name}", download_url, dest_path, headers, expected_size=expected_size)
                download_context = dict(progress_context or {})
                download_context.update(
                    stage="下载到本地",
                    stage_index=4,
                    stage_count=download_context.get("stage_count", 6),
                    indeterminate=False,
                )
                GEEDownloader.run_qgs_task_sync(
                    dl_task,
                    progress_callback=progress_callback,
                    progress_context=download_context,
                    cancel_callback=cancel_callback,
                )
                GEEDownloader._validate_downloaded_raster(dest_path)
                downloaded_paths.append(dest_path)

            # Keep the cloud export by default. It is the fallback artifact for a
            # failed local copy and should only be deleted after explicit approval.
            if target_files:
                logger.info("Retained %s verified GEE export file(s) in Google Drive.", len(target_files))
                iface.messageBar().pushMessage(
                    "GEE",
                    f"已下载并验证 {len(target_files)} 个文件；Google Drive 源文件已保留。",
                    level=Qgis.MessageLevel.Success,
                )
        except Exception as api_exc:
            from ..core.progress import DataAcquisitionCancelled
            if isinstance(api_exc, DataAcquisitionCancelled):
                raise
            iface.messageBar().pushMessage(
                "GEE",
                f"Drive API download/validation failed. Falling back to local Google Drive sync: {api_exc}",
                level=Qgis.MessageLevel.Warning,
                duration=20,
            )
            logger.warning(f"Drive API download failed, falling back to local sync: {api_exc}")
            return GEEDownloader.wait_for_drive_sync(
                task_id,
                folder_name,
                filename,
                dest_dir,
                drive_root=sync_path,
                timeout=timeout,
                target_files=target_files,
                progress_callback=progress_callback,
                progress_context=progress_context,
                cancel_callback=cancel_callback,
            )
            
        # 6. Merge if multiple slices
        if len(downloaded_paths) == 1:
            return downloaded_paths[0]
        else:
            iface.messageBar().pushMessage("GEE", f"Merging {len(downloaded_paths)} tiles into a VRT...", level=Qgis.MessageLevel.Info)
            vrt_path = os.path.join(dest_dir, f"{filename}.vrt")
            try:
                from osgeo import gdal
                gdal.BuildVRT(vrt_path, downloaded_paths)
                return vrt_path
            except Exception as e:
                logger.error(f"Failed to build VRT: {e}")
                return downloaded_paths[0]

    @staticmethod
    def _validate_downloaded_raster(path):
        from ..core.raster_validation import inspect_raster_file, validate_raster_has_data

        inspection = inspect_raster_file(path, force_read=True)
        if not inspection.get("ok"):
            message = inspection.get("message") or f"Raster integrity check failed: {path}"
            raise Exception(message)
        validation = validate_raster_has_data(path, bands=[1], min_valid_percent=0.01, force_read=True)
        if not validation.get("ok"):
            message = validation.get("message") or f"Raster contains no usable data: {path}"
            raise Exception(message)
        return validation

    @staticmethod
    def download_ee_object(
        ee_object,
        filename,
        dest_dir,
        scale=30,
        region=None,
        crs='EPSG:4326',
        exact_geom=None,
        no_data=-9999,
        min_coverage_ratio=0.99,
        progress_callback=None,
        progress_context=None,
        cancel_callback=None,
    ):
        import re
        import time
        import uuid
        from ..core.progress import DataAcquisitionCancelled, raise_if_cancelled

        context = dict(progress_context or {})
        context.setdefault("tool_name", "gee_download")
        context.setdefault("title", "GEE 数据获取")
        context.setdefault("stage_count", 6)
        raise_if_cancelled(cancel_callback, "GEE data acquisition was cancelled by the user.")
        
        if isinstance(ee_object, ee.FeatureCollection):
            raise NotImplementedError("Vector download wrapper not yet implemented, please use ee.batch.Export.table.")
            
        iface.messageBar().pushMessage(
            "GEE",
            "Evaluating direct download and batch export routes...",
            level=Qgis.MessageLevel.Info,
        )
        route_context = dict(context)
        route_context.update(stage="评估下载路线与覆盖率", stage_index=3, indeterminate=True)
        GEEDownloader._emit_progress(
            progress_callback,
            route_context,
            stage_percent=None,
            detail="正在评估 direct 或 batch/Drive 路线。",
        )
        
        # --- Strict Coverage Detection ---
        if exact_geom is not None:
            iface.messageBar().pushMessage("GEE", "Calculating spatial coverage against exact geometry...", level=Qgis.MessageLevel.Info)
            try:
                # Get the mask of the first band (1 if valid, 0 if NoData)
                mask_img = ee_object.select(0).mask()
                
                # Calculate total area of the exact geometry
                geom_area = exact_geom.area(maxError=1).getInfo()
                
                # Calculate the area of valid pixels within the exact geometry
                valid_area_img = mask_img.multiply(ee.Image.pixelArea())
                stats = valid_area_img.reduceRegion(
                    reducer=ee.Reducer.sum(),
                    geometry=exact_geom,
                    scale=scale,
                    maxPixels=1e10
                )
                
                stats_dict = stats.getInfo()
                if stats_dict:
                    valid_area = list(stats_dict.values())[0]
                    coverage_ratio = valid_area / geom_area if geom_area > 0 else 0
                    
                    logger.info(f"GEE Coverage Check: {coverage_ratio*100:.2f}% (Valid Area: {valid_area}, Total Area: {geom_area})")
                    
                    if coverage_ratio < float(min_coverage_ratio or 0):
                        error_msg = f"Download aborted: Image only covers {coverage_ratio*100:.2f}% of the target geometry. Please use mosaic or select a different image."
                        iface.messageBar().pushMessage("GEE Error", error_msg, level=Qgis.MessageLevel.Critical, duration=10)
                        raise Exception(error_msg)
            except Exception as e:
                if "Download aborted" in str(e):
                    raise
                raise RuntimeError(f"Could not verify image coverage before download: {e}") from e
        # ---------------------------------
        
        # GEE task description only allows specific alphanumeric characters and max 100 length.
        safe_desc = re.sub(r'[^a-zA-Z0-9.\-:_]', '_', filename)
        if not safe_desc.replace('_', ''):
            safe_desc = f"export_{int(time.time())}"
        safe_desc = safe_desc[:70]

        # Direct EE download is only for genuinely small grids. This is a
        # separate limit from Google Drive API media downloads.
        direct_plan = None
        if exact_geom is not None:
            try:
                import math
                from ..core.gee_routing import estimate_direct_download_route

                area_m2 = float(exact_geom.area(maxError=1).getInfo())
                bounds = exact_geom.bounds(maxError=1).coordinates().getInfo()
                points = []
                def _collect(value):
                    if isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(item, (int, float)) for item in value):
                        points.append(value)
                    elif isinstance(value, (list, tuple)):
                        for item in value:
                            _collect(item)
                _collect(bounds)
                lons = [point[0] for point in points]
                lats = [point[1] for point in points]
                mid_lat = (min(lats) + max(lats)) / 2.0
                width_m = (max(lons) - min(lons)) * 111320.0 * max(math.cos(math.radians(mid_lat)), 0.01)
                height_m = (max(lats) - min(lats)) * 110574.0
                band_count = int(ee_object.bandNames().size().getInfo())
                direct_plan = estimate_direct_download_route(area_m2, width_m, height_m, band_count, scale)
            except Exception as route_exc:
                logger.warning(f"Could not estimate direct GEE route; using batch export: {route_exc}")

        if direct_plan and direct_plan.get("eligible"):
            try:
                raise_if_cancelled(cancel_callback, "GEE data acquisition was cancelled by the user.")
                os.makedirs(dest_dir, exist_ok=True)
                direct_path = os.path.join(dest_dir, f"{filename}.tif")
                GEEDownloader._release_project_layers_for_path(direct_path)
                download_image = ee_object.unmask(float(no_data), sameFootprint=False)
                url = download_image.getDownloadURL({
                    "name": filename,
                    "scale": scale,
                    "region": region,
                    "crs": crs,
                    "format": "GEO_TIFF",
                    "filePerBand": False,
                })
                download_task = GEEDownloadTask(f"Downloading {filename} directly from GEE", url, direct_path)
                direct_context = dict(context)
                direct_context.update(stage="下载到本地", stage_index=4, indeterminate=False)
                GEEDownloader.run_qgs_task_sync(
                    download_task,
                    progress_callback=progress_callback,
                    progress_context=direct_context,
                    cancel_callback=cancel_callback,
                )
                GEEDownloader._set_raster_nodata(direct_path, no_data)
                validation_context = dict(context)
                validation_context.update(stage="验证本地栅格", stage_index=5, indeterminate=True)
                GEEDownloader._emit_progress(
                    progress_callback,
                    validation_context,
                    stage_percent=None,
                    detail=os.path.basename(direct_path),
                )
                GEEDownloader._validate_downloaded_raster(direct_path)
                GEEDownloader._emit_progress(
                    progress_callback,
                    validation_context,
                    stage_percent=100,
                    detail="本地栅格完整且含有效像元。",
                )
                return direct_path
            except DataAcquisitionCancelled:
                raise
            except Exception as direct_exc:
                logger.warning(f"Direct GEE download failed; falling back to batch export: {direct_exc}")

        run_id = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "_" + uuid.uuid4().hex[:8]
        export_prefix = f"{safe_desc}_{run_id}"[:100]
        not_before = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
        
        task = ee.batch.Export.image.toDrive(
            image=ee_object,
            description=export_prefix,
            folder=GEE_EXPORT_FOLDER,
            fileNamePrefix=export_prefix,
            scale=scale,
            crs=crs,
            region=region,
            maxPixels=1e13,
            formatOptions={"noData": no_data, "cloudOptimized": True},
        )
        task.start()

        cloud_context = dict(context)
        cloud_context.update(stage="GEE 云端处理", stage_index=3, indeterminate=True, cloud_task_id=task.id)
        GEEDownloader._emit_progress(
            progress_callback,
            cloud_context,
            stage_percent=None,
            detail=f"云端导出已提交 · 任务 {task.id}",
        )

        downloaded = GEEDownloader._download_via_drive_api(
            task.id,
            GEE_EXPORT_FOLDER,
            export_prefix,
            dest_dir,
            not_before=not_before,
            progress_callback=progress_callback,
            progress_context=context,
            cancel_callback=cancel_callback,
        )
        validation_context = dict(context)
        validation_context.update(stage="整理并验证本地栅格", stage_index=5, indeterminate=True)
        GEEDownloader._emit_progress(
            progress_callback,
            validation_context,
            stage_percent=None,
            detail="正在整理导出文件并强制读取栅格。",
        )
        final_path = GEEDownloader._finalize_export_output(downloaded, filename, dest_dir)
        GEEDownloader._set_raster_nodata(final_path, no_data)
        GEEDownloader._validate_downloaded_raster(final_path)
        GEEDownloader._emit_progress(
            progress_callback,
            validation_context,
            stage_percent=100,
            detail="本地栅格完整且含有效像元。",
        )
        return final_path

    @staticmethod
    def _set_raster_nodata(path, no_data):
        if not path or not str(path).lower().endswith((".tif", ".tiff")):
            return
        try:
            from osgeo import gdal

            dataset = gdal.Open(path, gdal.GA_Update)
            if dataset is None:
                return
            for band_index in range(1, dataset.RasterCount + 1):
                dataset.GetRasterBand(band_index).SetNoDataValue(float(no_data))
            dataset.FlushCache()
            dataset = None
        except Exception as exc:
            logger.warning(f"Could not set raster NoData metadata for {path}: {exc}")

    @staticmethod
    def _release_project_layers_for_path(path):
        try:
            target_norm = os.path.normcase(os.path.abspath(path)).replace("\\", "/")
            for layer_id, layer in list(QgsProject.instance().mapLayers().items()):
                layer_source = os.path.normcase(
                    os.path.abspath(str(layer.source()).split("|", 1)[0])
                ).replace("\\", "/")
                if layer_source == target_norm:
                    QgsProject.instance().removeMapLayer(layer_id)
        except Exception as exc:
            logger.warning(f"Could not release an existing raster layer for overwrite: {exc}")

    @staticmethod
    def _finalize_export_output(downloaded_path, filename, dest_dir):
        final_tif = os.path.join(dest_dir, f"{filename}.tif")
        source = os.path.abspath(downloaded_path)
        final_tif = os.path.abspath(final_tif)
        if source == final_tif:
            return final_tif
        GEEDownloader._release_project_layers_for_path(final_tif)
        if source.lower().endswith(".vrt"):
            from osgeo import gdal

            translated = gdal.Translate(final_tif, source, format="GTiff", creationOptions=["TILED=YES", "BIGTIFF=IF_SAFER"])
            if translated is None:
                raise IOError(f"Could not convert exported VRT to GeoTIFF: {source}")
            translated.FlushCache()
            translated = None
            return final_tif
        os.replace(source, final_tif)
        return final_tif
