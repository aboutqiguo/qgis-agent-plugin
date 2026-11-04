import sys
import site
import os


def _ensure_user_site_packages():
    """Ensure user site-packages are on sys.path even when QGIS isolates Python."""
    try:
        user_site = site.getusersitepackages()
        if user_site and os.path.exists(user_site) and user_site not in sys.path:
            sys.path.insert(0, user_site)
    except Exception:
        pass

    appdata = os.environ.get("APPDATA")
    if appdata:
        py_ver = f"Python{sys.version_info.major}{sys.version_info.minor}"
        roaming_site = os.path.join(appdata, "Python", py_ver, "site-packages")
        if os.path.exists(roaming_site) and roaming_site not in sys.path:
            sys.path.insert(0, roaming_site)


_ensure_user_site_packages()


def classFactory(iface):
    _ensure_user_site_packages()
    from .agent_plugin import QGISAIAgentPlugin
    return QGISAIAgentPlugin(iface)
