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
        label.setTextFormat(Qt.RichText)
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
        
        if dialog.exec() == QDialog.Accepted:
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
                    QMessageBox.Cancel | QMessageBox.Ok,
                )
                
                if reply == QMessageBox.Cancel:
                    iface.messageBar().pushMessage("GEE", "认证已取消。", level=Qgis.Warning)
                    return False
                
            # Use localhost:0 to tell the OS to allocate a dynamic random port!
            # This completely bypasses WinError 10013 caused by firewall blocking the default 8085 port.
            scopes = [
                'https://www.googleapis.com/auth/earthengine',
                'https://www.googleapis.com/auth/devstorage.full_control',
                'https://www.googleapis.com/auth/drive'
            ]
            ee.Authenticate(auth_mode="localhost:0", force=True, scopes=scopes)
            
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
        start_time = time.time()
        while True:
            if self.isCanceled():
                return False
                
            try:
                status_list = ee.data.getTaskStatus(self.task_id)
                if not status_list:
                    self.exception = Exception(f"Task ID {self.task_id} not found.")
                    return False
                status = status_list[0]
            except Exception as e:
                self.exception = Exception(f"Failed to get task status: {e}")
                return False
                
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
    def __init__(self, description, drive_dir, filename_prefix, timeout=3600):
        super().__init__(description, QgsTask.CanCancel)
        self.drive_dir = drive_dir
        self.filename_prefix = filename_prefix
        self.timeout = timeout
        self.exception = None
        self.synced_files = []
        
    def run(self):
        import time, os, glob
        start_time = time.time()
        while True:
            if self.isCanceled():
                return False
            
            pattern = os.path.join(self.drive_dir, f"{self.filename_prefix}*.tif")
            files = glob.glob(pattern)
            
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
        
    def run(self):
        import os
        try:
            total_length = os.path.getsize(self.src_path)
            copied = 0
            with open(self.src_path, 'rb') as f_in:
                with open(self.dest_path, 'wb') as f_out:
                    while True:
                        if self.isCanceled():
                            return False
                        chunk = f_in.read(1024 * 1024 * 5) # 5MB chunks
                        if not chunk:
                            break
                        f_out.write(chunk)
                        copied += len(chunk)
                        if total_length > 0:
                            self.setProgress(copied / total_length * 100.0)
            return True
        except Exception as e:
            self.exception = e
            return False


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
        import os
        # 1. Wait for GEE Task to complete
        wait_task = GEEWaitTask(f"Waiting for GEE Cloud: {filename}", task_id, timeout)
        GEEDownloader.run_qgs_task_sync(wait_task)
        iface.messageBar().pushMessage("GEE", "GEE Task completed! Waiting for local Drive sync...", level=Qgis.MessageLevel.Success)
        
        # 2. Wait for Google Drive Desktop to sync the file
        drive_dir = os.path.join(drive_root, folder_name)
        iface.messageBar().pushMessage("GEE Sync", f"Waiting for files to appear at {drive_dir}", level=Qgis.MessageLevel.Info)
        sync_task = GEEDriveSyncTask(f"Waiting for local sync: {filename}", drive_dir, filename, timeout)
        GEEDownloader.run_qgs_task_sync(sync_task)
        iface.messageBar().pushMessage("GEE Sync", f"{len(sync_task.synced_files)} file(s) synced locally!", level=Qgis.MessageLevel.Success)
        
        # 3. Copy to destination
        os.makedirs(dest_dir, exist_ok=True)
        copied_paths = []
        for drive_path in sync_task.synced_files:
            f_name = os.path.basename(drive_path)
            dest_path = os.path.join(dest_dir, f_name)
            
            iface.messageBar().pushMessage("GEE", f"Copying {f_name} to project folder...", level=Qgis.MessageLevel.Info)
            copy_task = GEECopyTask(f"Copying {f_name} from Google Drive", drive_path, dest_path)
            GEEDownloader.run_qgs_task_sync(copy_task)
            copied_paths.append(dest_path)
            
            # 4. Clean up original file in Drive to save space
            try:
                os.remove(drive_path)
            except Exception as e:
                logger.warning(f"Failed to remove original file from Google Drive: {e}")
                
        iface.messageBar().pushMessage("GEE", "Cleaned up original files from Google Drive.", level=Qgis.MessageLevel.Success)
        
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
    def _download_via_drive_api(task_id, folder_name, filename, dest_dir, timeout=3600):
        import ee
        import requests
        import os
        from qgis.core import QgsSettings
        
        # 1. Wait for task to complete
        wait_task = GEEWaitTask(f"Waiting for GEE Cloud: {filename}", task_id, timeout)
        GEEDownloader.run_qgs_task_sync(wait_task)
        iface.messageBar().pushMessage("GEE", "GEE Task completed! Querying Google Drive API...", level=Qgis.MessageLevel.Success)
            
        # 2. Authenticate against Drive API
        credentials = ee.data.get_persistent_credentials()
        headers = {}
        credentials.apply(headers)
        
        # 3. Search for the file in Drive and get size
        search_url = "https://www.googleapis.com/drive/v3/files"
        params = {'q': f"name contains '{filename}' and trashed=false", 'fields': 'files(id, name, size)', 'pageSize': 1000}
        res = requests.get(search_url, params=params, headers=headers)
        res.raise_for_status()
        files = res.json().get('files', [])
        
        target_files = [f for f in files if f['name'] == f"{filename}.tif" or (f['name'].startswith(f"{filename}-") and f['name'].endswith(".tif"))]
        
        if not target_files:
            raise Exception(f"File(s) for {filename} not found in Google Drive!")
            
        total_size_bytes = sum(int(f.get('size', 0)) for f in target_files)
        total_size_mb = total_size_bytes / (1024 * 1024)
        
        iface.messageBar().pushMessage("GEE", f"File size on Drive: {total_size_mb:.1f} MB", level=Qgis.MessageLevel.Info)
        
        # Smart Routing Tier Logic
        if total_size_mb > 500:
            iface.messageBar().pushMessage("GEE", f"Data >500MB ({total_size_mb:.1f}MB). Falling back to Local Client Sync...", level=Qgis.MessageLevel.Warning)
            settings = QgsSettings()
            sync_path = settings.value("qgis_agent/gee_drive_sync_path", r"G:\我的云端硬盘")
            
            if not os.path.exists(sync_path):
                iface.messageBar().pushMessage("CRITICAL", f"Local drive path '{sync_path}' not found! Please manually download from Google Drive web.", level=Qgis.MessageLevel.Critical, duration=20)
            
            return GEEDownloader.wait_for_drive_sync(task_id, folder_name, filename, dest_dir, drive_root=sync_path, timeout=timeout)
            
        # Else: <= 500MB, download via API
        os.makedirs(dest_dir, exist_ok=True)
        downloaded_paths = []
        
        # 4. Download file(s)
        for idx, f_info in enumerate(target_files):
            file_id = f_info['id']
            f_name = f_info['name']
            download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
            dest_path = os.path.join(dest_dir, f_name)
            
            iface.messageBar().pushMessage("GEE", f"Downloading {f_name} ({idx+1}/{len(target_files)})...", level=Qgis.MessageLevel.Info)
            dl_task = GEEDownloadTask(f"Downloading {f_name}", download_url, dest_path, headers)
            GEEDownloader.run_qgs_task_sync(dl_task)
            downloaded_paths.append(dest_path)
            
            # 5. Clean up from Drive
            try:
                requests.delete(f"https://www.googleapis.com/drive/v3/files/{file_id}", headers=headers)
            except:
                pass
                
        if len(target_files) > 0:
            iface.messageBar().pushMessage("GEE", f"Cleaned up {len(target_files)} file(s) from Google Drive.", level=Qgis.MessageLevel.Success)
            
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
    def download_ee_object(ee_object, filename, dest_dir, scale=30, region=None, crs='EPSG:4326', exact_geom=None):
        import re
        import time
        
        if isinstance(ee_object, ee.FeatureCollection):
            raise NotImplementedError("Vector download wrapper not yet implemented, please use ee.batch.Export.table.")
            
        iface.messageBar().pushMessage("GEE", "Initiating Smart Routing: Exporting to Google Drive...", level=Qgis.MessageLevel.Info)
        
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
                    
                    if coverage_ratio < 0.99:
                        error_msg = f"Download aborted: Image only covers {coverage_ratio*100:.2f}% of the target geometry. Please use mosaic or select a different image."
                        iface.messageBar().pushMessage("GEE Error", error_msg, level=Qgis.MessageLevel.Critical, duration=10)
                        raise Exception(error_msg)
            except Exception as e:
                if "Download aborted" in str(e):
                    raise
                else:
                    logger.warning(f"Failed to calculate coverage, skipping check: {e}")
        # ---------------------------------
        
        # GEE task description only allows specific alphanumeric characters and max 100 length.
        safe_desc = re.sub(r'[^a-zA-Z0-9.\-:_]', '_', filename)
        if not safe_desc.replace('_', ''):
            safe_desc = f"export_{int(time.time())}"
        safe_desc = safe_desc[:100]
        
        task = ee.batch.Export.image.toDrive(
            image=ee_object,
            description=safe_desc,
            folder='QGIS_Agent_Exports',
            fileNamePrefix=filename,
            scale=scale,
            crs=crs,
            region=region,
            maxPixels=1e13
        )
        task.start()
        
        return GEEDownloader._download_via_drive_api(task.id, 'QGIS_Agent_Exports', filename, dest_dir)
