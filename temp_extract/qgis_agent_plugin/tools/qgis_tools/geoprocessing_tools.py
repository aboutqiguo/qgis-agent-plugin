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

def clip_raster(input_layer, mask_layer, output_path: str = "TEMPORARY_OUTPUT"):
    """
    Clips a raster layer using a vector mask layer.
    Strictly preserves data type, NoData values, and clones the visual renderer.
    """
    import processing
    from qgis.core import QgsProject, QgsRasterLayer
    
    provider = input_layer.dataProvider()
    nodata_val = provider.sourceNoDataValue(1)
    
    params = {
        'INPUT': input_layer,
        'MASK': mask_layer,
        'SOURCE_CRS': input_layer.crs().authid(),
        'TARGET_CRS': input_layer.crs().authid(),
        'DATA_TYPE': 0,  # 0 = Use Input Layer Data Type
        'ALPHA_BAND': False,
        'CROP_TO_CUTLINE': True,
        'KEEP_RESOLUTION': True,
        'MULTITHREADING': True,
        'OUTPUT': output_path
    }
    
    # Ensure NODATA is ALWAYS set so exterior pixels are ignored in downstream analysis!
    import math
    from qgis.core import Qgis
    if nodata_val is not None and not math.isnan(nodata_val):
        params['NODATA'] = nodata_val
    else:
        # User explicitly noted 0 could be valid reflectance. 
        # We dynamically pick a safe out-of-bounds NoData value based on the native data type.
        dtype = provider.dataType(1)
        if dtype == Qgis.DataType.Byte:
            params['NODATA'] = 255
        elif dtype in [Qgis.DataType.UInt16, Qgis.DataType.UInt32]:
            params['NODATA'] = 65535
        else:
            params['NODATA'] = -9999
        
    result = processing.run("gdal:cliprasterbymasklayer", params)
    out_path = result['OUTPUT']
    
    out_layer = QgsRasterLayer(out_path, f"{input_layer.name()}_clipped")
    if out_layer.isValid():
        QgsProject.instance().addMapLayer(out_layer)
        
        # Clone the renderer to perfectly preserve MinMax statistics and RGB mappings!
        if input_layer.renderer():
            out_layer.setRenderer(input_layer.renderer().clone())
            out_layer.triggerRepaint()
            
    return out_layer
