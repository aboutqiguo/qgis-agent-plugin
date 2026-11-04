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
        
    from qgis.core import QgsCoordinateTransform

    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setBackgroundColor(QColor(255, 255, 255))
    settings.setOutputSize(QSize(width, height))

    target_crs = QgsProject.instance().crs()
    if not target_crs.isValid() and layers:
        for l in layers:
            if hasattr(l, "crs") and l.crs().isValid():
                target_crs = l.crs()
                break
    if target_crs.isValid():
        settings.setDestinationCrs(target_crs)
    
    # Calculate combined extent aligned to target_crs
    extent = QgsRectangle()
    extent.setMinimal()
    for layer in layers:
        if not hasattr(layer, "extent") or layer.extent().isEmpty():
            continue
        l_extent = layer.extent()
        if hasattr(layer, "crs") and layer.crs().isValid() and target_crs.isValid() and layer.crs() != target_crs:
            try:
                ct = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())
                l_extent = ct.transformBoundingBox(l_extent)
            except Exception:
                pass
        extent.combineExtentWith(l_extent)
        
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
