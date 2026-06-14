def classFactory(iface):
    from .agent_plugin import QGISAIAgentPlugin
    return QGISAIAgentPlugin(iface)
