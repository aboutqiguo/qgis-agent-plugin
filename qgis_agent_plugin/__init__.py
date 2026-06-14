def classFactory(iface):
    import sys
    import site
    import os
    
    # 修复因为非管理员运行 pip 导致 QGIS 找不到 user site-packages 的经典 Bug
    user_site = site.getusersitepackages()
    if user_site and os.path.exists(user_site) and user_site not in sys.path:
        sys.path.append(user_site)
        
    from .agent_plugin import QGISAIAgentPlugin
    return QGISAIAgentPlugin(iface)
