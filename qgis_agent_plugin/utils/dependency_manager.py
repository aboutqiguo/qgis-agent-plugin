"""Dependency management utility for automatic checking and installation of Python packages in QGIS."""

import os
import site
import subprocess
import sys
from typing import List, Tuple


def get_user_site_dir() -> str:
    """Return the user site-packages directory path."""
    try:
        user_site = site.getusersitepackages()
        if user_site and os.path.exists(user_site):
            return user_site
    except Exception:
        pass
    appdata = os.environ.get("APPDATA")
    if appdata:
        py_ver = f"Python{sys.version_info.major}{sys.version_info.minor}"
        roaming = os.path.join(appdata, "Python", py_ver, "site-packages")
        if os.path.exists(roaming):
            return roaming
    return ""


def ensure_sys_path():
    """Ensure user site-packages is in sys.path."""
    user_site = get_user_site_dir()
    if user_site and user_site not in sys.path:
        sys.path.insert(0, user_site)


def check_module_installed(module_name: str) -> bool:
    """Check if a Python module can be imported, attempting sys.path recovery first."""
    ensure_sys_path()
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def install_packages_in_qgis(packages: List[str]) -> Tuple[bool, str]:
    """Install missing packages using the current QGIS Python interpreter."""
    if not packages:
        return True, "No packages to install."

    python_exe = sys.executable
    cmd = [python_exe, "-m", "pip", "install", "--user"] + packages

    try:
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=creation_flags,
            timeout=300,
        )

        ensure_sys_path()

        if proc.returncode == 0:
            return True, proc.stdout
        return False, proc.stderr or proc.stdout
    except Exception as e:
        return False, str(e)
