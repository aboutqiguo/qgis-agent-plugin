import processing
from qgis.core import QgsVectorLayer, QgsProject, QgsCoordinateReferenceSystem

def _crs_guard(layer: QgsVectorLayer) -> QgsVectorLayer:
    """
    CRS Guard (Data Digestion Agent): 
    Checks if the layer uses a geographic CRS (e.g. WGS84).
    If it does, auto-reprojects it to Pseudo-Mercator (EPSG:3857) to ensure physical math calculations (like buffer distance) are correct.
    """
    crs = layer.crs()
    if crs.isGeographic():
        print(f"[CRS Guard] Warning: Layer '{layer.name()}' uses Geographic CRS ({crs.authid()}). Auto-reprojecting to EPSG:3857 for physical calculation.")
        import processing.core.Processing
        processing.core.Processing.Processing.initialize()
        params = {
            'INPUT': layer,
            'TARGET_CRS': QgsCoordinateReferenceSystem('EPSG:3857'),
            'OUTPUT': 'memory:'
        }
        result = processing.run("native:reprojectlayer", params)
        out_layer = result['OUTPUT']
        out_layer.setName(f"{layer.name()}_3857")
        return out_layer
    return layer

def buffer(layer: QgsVectorLayer, distance: float, output_path: str = "memory:") -> QgsVectorLayer:
    """Creates a buffer around features in the input layer."""
    # Enforce metric CRS via CRS Guard
    layer_to_process = _crs_guard(layer)
    
    # Ensure processing is initialized
    import processing.core.Processing
    processing.core.Processing.Processing.initialize()
    
    params = {
        'INPUT': layer_to_process,
        'DISTANCE': distance,
        'SEGMENTS': 5,
        'END_CAP_STYLE': 0,
        'JOIN_STYLE': 0,
        'MITER_LIMIT': 2,
        'DISSOLVE': False,
        'OUTPUT': output_path
    }
    result = processing.run("native:buffer", params)
    
    out_layer = result['OUTPUT']
    if isinstance(out_layer, str) and output_path != "memory:":
        from .io_tools import load_vector_layer
        return load_vector_layer(out_layer)
        
    if isinstance(out_layer, QgsVectorLayer):
        out_layer.setName(f"{layer.name()}_buffered")
        QgsProject.instance().addMapLayer(out_layer)
        
    return out_layer

def clip(input_layer: QgsVectorLayer, overlay_layer: QgsVectorLayer, output_path: str = "memory:") -> QgsVectorLayer:
    """Clips the input layer with the overlay layer."""
    import processing.core.Processing
    processing.core.Processing.Processing.initialize()
    
    params = {
        'INPUT': input_layer,
        'OVERLAY': overlay_layer,
        'OUTPUT': output_path
    }
    result = processing.run("native:clip", params)
    
    out_layer = result['OUTPUT']
    if isinstance(out_layer, str) and output_path != "memory:":
        from .io_tools import load_vector_layer
        return load_vector_layer(out_layer)
        
    if isinstance(out_layer, QgsVectorLayer):
        out_layer.setName(f"{input_layer.name()}_clipped")
        QgsProject.instance().addMapLayer(out_layer)
        
    return out_layer
