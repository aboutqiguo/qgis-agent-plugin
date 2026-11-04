"""Live development sync script: mirrors local changes to active QGIS profile directory."""

import os
import shutil
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_SRC = os.path.join(SRC_DIR, "qgis_agent_plugin")
QGIS_PLUGINS_DIR = os.path.expandvars(r"%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\qgis_agent_plugin")

EXCLUDE_DIRS = {"__pycache__", ".git", ".idea", "test_data"}
EXCLUDE_EXTS = {".log", ".tmp", ".pyc"}


def sync():
    if not os.path.exists(PLUGIN_SRC):
        print(f"Error: Source directory {PLUGIN_SRC} does not exist.")
        return False

    os.makedirs(QGIS_PLUGINS_DIR, exist_ok=True)
    synced_count = 0

    for root, dirs, files in os.walk(PLUGIN_SRC):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        rel_dir = os.path.relpath(root, PLUGIN_SRC)
        target_dir = os.path.join(QGIS_PLUGINS_DIR, rel_dir)
        os.makedirs(target_dir, exist_ok=True)

        for file in files:
            if any(file.endswith(ext) for ext in EXCLUDE_EXTS):
                continue
            src_file = os.path.join(root, file)
            target_file = os.path.join(target_dir, file)

            try:
                # Check mtime or size difference
                if not os.path.exists(target_file) or os.path.getmtime(src_file) > os.path.getmtime(target_file):
                    shutil.copy2(src_file, target_file)
                    synced_count += 1
            except PermissionError:
                # In case file is locked by QGIS (e.g. running logs)
                continue
            except Exception as e:
                print(f"Warning: could not sync {file}: {e}")

    print(f"Sync complete! {synced_count} file(s) updated in QGIS plugin directory.")
    return True


if __name__ == "__main__":
    sync()
