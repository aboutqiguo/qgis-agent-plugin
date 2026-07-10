import logging
import os
import sys

class QgsMessageLogHandler(logging.Handler):
    """Custom logging handler to push Warning and Error messages to QGIS native Message Log."""
    def emit(self, record):
        try:
            from qgis.core import QgsMessageLog, Qgis
            msg = self.format(record)
            message_level = getattr(Qgis, "MessageLevel", Qgis)
            if record.levelno >= logging.ERROR:
                level = getattr(message_level, "Critical", getattr(Qgis, "Critical", None))
            elif record.levelno >= logging.WARNING:
                level = getattr(message_level, "Warning", getattr(Qgis, "Warning", None))
            else:
                level = getattr(message_level, "Info", getattr(Qgis, "Info", None))
            QgsMessageLog.logMessage(msg, 'QGIS AI Agent', level)
        except Exception:
            pass

def get_logger():
    logger = logging.getLogger('QGISAIAgent')
    # Prevent adding multiple handlers if get_logger is called multiple times
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        log_file = os.path.join(os.path.dirname(__file__), 'agent_run.log')
        
        # Rotating File handler (Max 5MB, keep 3 backups)
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        
        # Stream handler for console debugging
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        
        # QGIS Message Log handler for criticals and warnings
        qh = QgsMessageLogHandler()
        qh.setLevel(logging.WARNING)
        
        # Formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
        fh.setFormatter(formatter)
        sh.setFormatter(formatter)
        qh.setFormatter(formatter)
        
        logger.addHandler(fh)
        logger.addHandler(sh)
        logger.addHandler(qh)
        
    return logger

def close_logger():
    """Removes and closes all handlers attached to the logger so the log file is released."""
    logger = logging.getLogger('QGISAIAgent')
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
