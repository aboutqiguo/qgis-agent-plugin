import os
import requests
from qgis.PyQt.QtCore import QThread, pyqtSignal

class UpdateChecker:
    GITHUB_METADATA_URL = "https://raw.githubusercontent.com/aboutqiguo/qgis-agent-plugin/main/qgis_agent_plugin/metadata.txt"
    
    @staticmethod
    def get_local_version():
        metadata_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'metadata.txt')
        if not os.path.exists(metadata_path):
            return "0.0.0"
        with open(metadata_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('version='):
                    return line.strip().split('=')[1]
        return "0.0.0"

    @staticmethod
    def get_remote_version():
        try:
            resp = requests.get(UpdateChecker.GITHUB_METADATA_URL, timeout=5)
            if resp.status_code == 200:
                for line in resp.text.split('\n'):
                    if line.startswith('version='):
                        return line.strip().split('=')[1]
        except Exception:
            pass
        return None

    @staticmethod
    def is_newer_version(local_v, remote_v):
        if not remote_v:
            return False
        try:
            l_parts = tuple(map(int, local_v.split('.')))
            r_parts = tuple(map(int, remote_v.split('.')))
            return r_parts > l_parts
        except Exception:
            # Fallback to string comparison if not standard X.Y.Z format
            return remote_v != local_v

    @staticmethod
    def download_and_install_update(version):
        import urllib.request
        import zipfile
        import tempfile
        import shutil
        
        # fallback zip url (since user might name it differently, we will try the standard format)
        url = f"https://github.com/aboutqiguo/qgis-agent-plugin/releases/download/v{version}/qgis_agent_plugin_v{version}.zip"
        
        try:
            tmp_zip = os.path.join(tempfile.gettempdir(), f"qgis_agent_plugin_update_{version}.zip")
            urllib.request.urlretrieve(url, tmp_zip)
            
            plugin_dir = os.path.dirname(__file__)
            plugins_root = os.path.dirname(plugin_dir)
            
            with zipfile.ZipFile(tmp_zip, 'r') as zip_ref:
                zip_ref.extractall(plugins_root)
                
            os.remove(tmp_zip)
            return True, "🎉 更新下载并覆盖成功！\n\n请彻底关闭并重启 QGIS 以使新版本生效。"
        except Exception as e:
            return False, f"自动更新失败（可能是网络问题或包名不匹配）:\n{str(e)}\n\n请尝试手动下载 ZIP 包或使用插件库进行更新。"

class AsyncUpdateCheckThread(QThread):
    finished_signal = pyqtSignal(bool, str, str)  # has_update, local_v, remote_v
    
    def run(self):
        local_v = UpdateChecker.get_local_version()
        remote_v = UpdateChecker.get_remote_version()
        if remote_v and UpdateChecker.is_newer_version(local_v, remote_v):
            self.finished_signal.emit(True, local_v, remote_v)
        else:
            self.finished_signal.emit(False, local_v, remote_v or "未知")
