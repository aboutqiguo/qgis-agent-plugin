import os
import requests
from qgis.PyQt.QtCore import QThread, pyqtSignal

class UpdateChecker:
    GITHUB_METADATA_URL = "https://raw.githubusercontent.com/aboutqiguo/qgis-agent-plugin/main/qgis_agent_plugin/metadata.txt"
    
    @staticmethod
    def get_local_version():
        metadata_path = os.path.join(os.path.dirname(__file__), 'metadata.txt')
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

class AsyncUpdateCheckThread(QThread):
    finished_signal = pyqtSignal(bool, str, str)  # has_update, local_v, remote_v
    
    def run(self):
        local_v = UpdateChecker.get_local_version()
        remote_v = UpdateChecker.get_remote_version()
        if remote_v and UpdateChecker.is_newer_version(local_v, remote_v):
            self.finished_signal.emit(True, local_v, remote_v)
        else:
            self.finished_signal.emit(False, local_v, remote_v or "未知")
