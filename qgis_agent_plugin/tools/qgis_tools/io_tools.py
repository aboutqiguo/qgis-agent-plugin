from qgis.core import QgsVectorLayer, QgsRasterLayer, QgsProject, QgsVectorFileWriter

def load_vector_layer(path: str, layer_name: str = None) -> QgsVectorLayer:
    """Loads a vector layer from a file path and adds it to the current QGIS project."""
    name = layer_name or path.replace('\\', '/').split('/')[-1]
    layer = QgsVectorLayer(path, name, "ogr")
    if not layer.isValid():
        raise ValueError(f"Failed to load vector layer from {path}")
    QgsProject.instance().addMapLayer(layer)
    return layer

def load_raster_layer(path: str, layer_name: str = None) -> QgsRasterLayer:
    """Loads a raster layer from a file path and adds it to the current QGIS project."""
    name = layer_name or path.replace('\\', '/').split('/')[-1]
    layer = QgsRasterLayer(path, name)
    if not layer.isValid():
        raise ValueError(f"Failed to load raster layer from {path}")
    QgsProject.instance().addMapLayer(layer)
    return layer

def save_layer(layer: QgsVectorLayer, output_path: str):
    """Saves a vector layer to a specified file path."""
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "ESRI Shapefile" if output_path.endswith('.shp') else "GeoJSON"
    error = QgsVectorFileWriter.writeAsVectorFormatV3(layer, output_path, QgsProject.instance().transformContext(), options)
    if error[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Failed to save layer to {output_path}. Error code: {error[0]}")
    return output_path

def open_georeferencer():
    """
    Opens the QGIS Georeferencer window.
    Note: PyQGIS does not currently allow auto-loading a raster into the Georeferencer via Python.
    The user must manually click 'Open Raster' once the window opens.
    """
    try:
        from qgis.utils import iface
        from qgis.PyQt.QtWidgets import QAction
        
        for action in iface.mainWindow().findChildren(QAction):
            if action.objectName() in ['mActionShowGeoreferencer', 'mActionGeoreferencer']:
                action.trigger()
                return True
                
        for action in iface.mainWindow().findChildren(QAction):
            if 'Georeferencer' in action.text() or '地理配准' in action.text() or 'georeferencer' in action.objectName().lower():
                action.trigger()
                return True
                
        print("Failed to open Georeferencer automatically. Menu item not found.")
        return False
    except Exception as e:
        print(f"Error opening Georeferencer: {e}")
        return False
