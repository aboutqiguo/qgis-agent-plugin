from qgis.core import QgsProject, QgsMapSettings, QgsMapRendererParallelJob, QgsRectangle
from qgis.PyQt.QtCore import QSize, QEventLoop
from qgis.PyQt.QtGui import QColor

def render_quick_map(output_path: str, layers: list = None, width: int = 800, height: int = 600):
    """
    Renders a quick map of the specified layers (or all map layers if None) to an image file.
    Example: render_quick_map("output.png")
    """
    if layers is None:
        layers = list(QgsProject.instance().mapLayers().values())
        
    if not layers:
        raise ValueError("No layers to render.")
        
    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setBackgroundColor(QColor(255, 255, 255))
    settings.setOutputSize(QSize(width, height))
    
    # Calculate combined extent
    extent = QgsRectangle()
    extent.setMinimal()
    for layer in layers:
        extent.combineExtentWith(layer.extent())
        
    # Add a 5% margin
    extent.scale(1.05)
    settings.setExtent(extent)
    
    job = QgsMapRendererParallelJob(settings)
    
    # Run the job synchronously using QEventLoop
    loop = QEventLoop()
    job.finished.connect(loop.quit)
    job.start()
    loop.exec()
    
    image = job.renderedImage()
    image.save(output_path)
    return output_path
