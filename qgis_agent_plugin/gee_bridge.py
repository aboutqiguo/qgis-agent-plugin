import logging
import json
import ee
from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit, QMessageBox
from qgis.core import QgsProject, QgsRasterLayer, Qgis
from qgis.utils import iface

logger = logging.getLogger(__name__)

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

class GEEAuth:
    @staticmethod
    def prompt_for_project():
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
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        layout.addWidget(label)
        
        input_field = QLineEdit()
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
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            project = input_field.text().strip()
            if project:
                return project
        return None

    @staticmethod
    def authenticate_and_initialize(force=False):
        """Attempts to initialize EE, falling back to auth prompts if needed."""
        from qgis.core import QgsSettings
        settings = QgsSettings()
        
        try:
            if not force:
                # First, try to initialize with the saved project ID from QGIS settings
                saved_project = settings.value("gee_agent_project_id", "")
                if saved_project:
                    try:
                        ee.Initialize(project=saved_project)
                        return True
                    except Exception:
                        pass # Fall back to default init
                
                # Try to initialize without a project (might work if global default exists)
                try:
                    ee.Initialize()
                    return True
                except Exception as e:
                    err_str = str(e).lower()
                    if "no project found" in err_str:
                        # Token is valid, but missing project ID! Don't re-auth, just ask for project.
                        project_id = GEEAuth.prompt_for_project()
                        if not project_id:
                            iface.messageBar().pushMessage("GEE", "Earth Engine 需要绑定 Project ID。", level=Qgis.Critical)
                            return False
                    
                    settings.setValue("gee_agent_project_id", project_id)
                    ee.Initialize(project=project_id)
                    iface.messageBar().pushMessage("GEE", f"已成功绑定至项目 {project_id}。", level=Qgis.Success)
                    return True
                else:
                    # Token expired or other error, proceed to full auth
                    pass
                
            if not force:
                # Pop up a warning explaining we need full auth
                msg = """未找到 Google Earth Engine 凭证，或凭证已过期。<br><br>
                请点击【确定】打开浏览器并完成授权认证过程。<br>
                登录成功后，系统将提示您输入 Google Cloud Project ID。"""
                
                reply = QMessageBox.warning(
                    None,
                    "授权 Google Earth Engine",
                    msg,
                    QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                )
                
                if reply == QMessageBox.StandardButton.Cancel:
                    iface.messageBar().pushMessage("GEE", "认证已取消。", level=Qgis.Warning)
                    return False
                
            # Perform localhost auth (opens browser)
            ee.Authenticate(auth_mode="localhost", force=True)
            
            # Now prompt for project ID
            project_id = GEEAuth.prompt_for_project()
            if not project_id:
                iface.messageBar().pushMessage("GEE", "Project ID required for Earth Engine.", level=Qgis.Critical)
                return False
                
            settings.setValue("gee_agent_project_id", project_id)
            ee.Initialize(project=project_id)
            iface.messageBar().pushMessage("GEE", f"Successfully authenticated to project {project_id}.", level=Qgis.Success)
            return True
            
        except Exception as e:
            # 必须抛出异常，否则 settings_dialog 的自定义 10013 错误窗口永远无法触发！
            raise e

class AgentMap:
    @staticmethod
    def addLayer(ee_object, vis_params=None, name="GEE Layer", shown=True, opacity=1.0):
        """
        Adds a given EE object to the QGIS map as an XYZ raster layer.
        Mimics Map.addLayer from the JavaScript API.
        """
        if vis_params is None:
            vis_params = {}
            
        try:
            # Ensure initialized
            ee.Initialize()
        except Exception:
            # Try to init via dialog
            if not GEEAuth.authenticate_and_initialize():
                raise Exception("Earth Engine is not initialized and authentication failed.")
        
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
            bounds = ee_object.geometry().bounds().getInfo()["coordinates"][0]
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
            
        iface.messageBar().pushMessage("GEE", f"Layer '{name}' added successfully.", level=Qgis.Success)
        return layer

import os
import time
import shutil

from qgis.core import QgsTask

class GEEDownloadTask(QgsTask):
    def __init__(self, description, download_url, dest_path, headers=None):
        super().__init__(description, QgsTask.CanCancel)
        self.download_url = download_url
        self.dest_path = dest_path
        self.headers = headers or {}
        self.exception = None
        
    def run(self):
        import requests
        import os
        try:
            with requests.get(self.download_url, headers=self.headers, stream=True) as r:
                r.raise_for_status()
                total_length = r.headers.get('content-length')
                
                os.makedirs(os.path.dirname(self.dest_path), exist_ok=True)
                with open(self.dest_path, 'wb') as f:
                    if total_length is None:
                        # No content length header
                        for chunk in r.iter_content(chunk_size=8192):
                            if self.isCanceled():
                                return False
                            f.write(chunk)
                    else:
                        total_length = int(total_length)
                        downloaded = 0
                        for chunk in r.iter_content(chunk_size=8192):
                            if self.isCanceled():
                                return False
                            f.write(chunk)
                            downloaded += len(chunk)
                            self.setProgress(downloaded / total_length * 100.0)
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
        
    def run(self):
        import ee
        import time
        task = ee.batch.Task(self.task_id, 'UNKNOWN', 'UNKNOWN', 'UNKNOWN')
        start_time = time.time()
        while True:
            if self.isCanceled():
                return False
                
            status = task.status()
            state = status.get('state')
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
    def __init__(self, description, drive_path, timeout=3600):
        super().__init__(description, QgsTask.CanCancel)
        self.drive_path = drive_path
        self.timeout = timeout
        self.exception = None
        
    def run(self):
        import time, os
        start_time = time.time()
        while True:
            if self.isCanceled():
                return False
            if os.path.exists(self.drive_path):
                size1 = os.path.getsize(self.drive_path)
                time.sleep(2)
                size2 = os.path.getsize(self.drive_path)
                if size1 == size2 and size1 > 0:
                    return True
            if time.time() - start_time > self.timeout:
                self.exception = Exception("Timeout waiting for local Google Drive sync.")
                return False
            for _ in range(5):
                if self.isCanceled(): return False
                time.sleep(1)


class GEEDownloader:
    @staticmethod
    def run_qgs_task_sync(task):
        from qgis.core import QgsApplication, QgsTask
        from qgis.PyQt.QtCore import QEventLoop, QCoreApplication
        
        loop = QEventLoop()
        task.taskCompleted.connect(loop.quit)
        task.taskTerminated.connect(loop.quit)
        
        # Prevent crash if user closes QGIS while task is running
        app = QCoreApplication.instance()
        if app:
            app.aboutToQuit.connect(loop.quit)
        
        QgsApplication.taskManager().addTask(task)
        loop.exec()
        
        if app:
            try:
                app.aboutToQuit.disconnect(loop.quit)
            except:
                pass
                
        if task.status() == QgsTask.Terminated:
            raise Exception("Task was cancelled by user.")
        
        if hasattr(task, 'exception') and task.exception:
            raise task.exception

        return True

    @staticmethod
    def wait_for_drive_sync(task_id, folder_name, filename, dest_dir, drive_root=r"G:\我的云端硬盘", timeout=3600):
        """
        Monitors a GEE export task and waits for Google Drive Desktop to sync the file locally.
        Once synced, copies the file to the destination directory and optionally cleans up the Drive copy.
        """
        # 1. Wait for GEE Task to complete
        wait_task = GEEWaitTask(f"Waiting for GEE Cloud: {filename}", task_id, timeout)
        GEEDownloader.run_qgs_task_sync(wait_task)
        iface.messageBar().pushMessage("GEE", "GEE Task completed! Waiting for local Drive sync...", level=Qgis.MessageLevel.Success)
        
        # 2. Wait for Google Drive Desktop to sync the file
        drive_path = os.path.join(drive_root, folder_name, f"{filename}.tif")
        iface.messageBar().pushMessage("GEE Sync", f"Waiting for file to appear at {drive_path}", level=Qgis.MessageLevel.Info)
        sync_task = GEEDriveSyncTask(f"Waiting for local sync: {filename}", drive_path, timeout)
        GEEDownloader.run_qgs_task_sync(sync_task)
        iface.messageBar().pushMessage("GEE Sync", "File synced locally!", level=Qgis.MessageLevel.Success)
        
        # 3. Copy to destination
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, f"{filename}.tif")
        
        iface.messageBar().pushMessage("GEE", f"Copying file to {dest_path}", level=Qgis.MessageLevel.Info)
        shutil.copy2(drive_path, dest_path)
        
        # 4. Clean up the original file in Drive to save space
        try:
            os.remove(drive_path)
            iface.messageBar().pushMessage("GEE", "Cleaned up original file from Google Drive.", level=Qgis.MessageLevel.Success)
        except Exception as e:
            logger.warning(f"Failed to remove original file from Google Drive: {e}")
            
        return dest_path

    @staticmethod
    def _download_via_drive_api(task_id, folder_name, filename, dest_dir, timeout=3600):
        import ee
        import requests
        
        # 1. Wait for task to complete
        wait_task = GEEWaitTask(f"Waiting for GEE Cloud: {filename}", task_id, timeout)
        GEEDownloader.run_qgs_task_sync(wait_task)
        iface.messageBar().pushMessage("GEE", "GEE Task completed! Fetching via Google Drive API...", level=Qgis.MessageLevel.Success)
            
        # 2. Authenticate against Drive API
        credentials = ee.data.get_persistent_credentials()
        headers = {}
        credentials.apply(headers)
        
        # 3. Search for the file in Drive
        search_url = "https://www.googleapis.com/drive/v3/files"
        params = {'q': f"name='{filename}.tif' and trashed=false", 'fields': 'files(id, name)'}
        res = requests.get(search_url, params=params, headers=headers)
        res.raise_for_status()
        files = res.json().get('files', [])
        
        if not files:
            raise Exception(f"File {filename}.tif not found in Google Drive!")
            
        file_id = files[0]['id']
        
        # 4. Download file
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        dest_path = os.path.join(dest_dir, f"{filename}.tif")
        
        iface.messageBar().pushMessage("GEE", f"Downloading {filename}.tif from Cloud...", level=Qgis.MessageLevel.Info)
        
        dl_task = GEEDownloadTask(f"Downloading {filename} from Cloud", download_url, dest_path, headers)
        GEEDownloader.run_qgs_task_sync(dl_task)
                    
        # 5. Clean up from Drive
        try:
            requests.delete(f"https://www.googleapis.com/drive/v3/files/{file_id}", headers=headers)
            iface.messageBar().pushMessage("GEE", "Cleaned up file from Google Drive.", level=Qgis.MessageLevel.Success)
        except:
            pass
            
        return dest_path

    @staticmethod
    def download_ee_object(ee_object, filename, dest_dir, scale=30, region=None, crs='EPSG:4326'):
        from qgis.core import QgsSettings
        settings = QgsSettings()
        strategy = settings.value("qgis_agent/gee_download_strategy", "smart")
        
        if isinstance(ee_object, ee.FeatureCollection):
            raise NotImplementedError("Vector download wrapper not yet implemented, please use ee.batch.Export.table.")
            
        if strategy == "smart":
            # Attempt direct download first
            try:
                iface.messageBar().pushMessage("GEE", "Attempting direct download (Smart Routing)...", level=Qgis.MessageLevel.Info)
                params = {'scale': scale, 'crs': crs, 'format': 'GEO_TIFF'}
                if region:
                    params['region'] = region
                    
                url = ee_object.getDownloadURL(params)
                dest_path = os.path.join(dest_dir, f"{filename}.tif")
                
                dl_task = GEEDownloadTask(f"Direct downloading {filename}", url, dest_path)
                GEEDownloader.run_qgs_task_sync(dl_task)
                
                iface.messageBar().pushMessage("GEE", "Direct download successful!", level=Qgis.MessageLevel.Success)
                return dest_path
            except Exception as e:
                err_str = str(e).lower()
                if "too large" in err_str or "exceeds" in err_str or "request payload size exceeds" in err_str:
                    iface.messageBar().pushMessage("GEE", "Image too large for direct download. Falling back to Drive API...", level=Qgis.MessageLevel.Warning)
                else:
                    iface.messageBar().pushMessage("GEE", f"Direct download failed: {str(e)}. Falling back to Drive API...", level=Qgis.MessageLevel.Warning)
                    
                # Fallback to Export + Drive API
                task = ee.batch.Export.image.toDrive(
                    image=ee_object,
                    description=filename,
                    folder='QGIS_Agent_Exports',
                    fileNamePrefix=filename,
                    scale=scale,
                    crs=crs,
                    region=region,
                    maxPixels=1e13
                )
                task.start()
                return GEEDownloader._download_via_drive_api(task.id, 'QGIS_Agent_Exports', filename, dest_dir)
                
        else:
            # Traditional Client Sync
            sync_path = settings.value("qgis_agent/gee_drive_sync_path", r"G:\我的云端硬盘")
            task = ee.batch.Export.image.toDrive(
                image=ee_object,
                description=filename,
                folder='QGIS_Agent_Exports',
                fileNamePrefix=filename,
                scale=scale,
                crs=crs,
                region=region,
                maxPixels=1e13
            )
            task.start()
            return GEEDownloader.wait_for_drive_sync(task.id, 'QGIS_Agent_Exports', filename, dest_dir, drive_root=sync_path)

