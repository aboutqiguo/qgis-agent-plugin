import processing
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorLayer,
)

def _crs_guard(layer: QgsVectorLayer) -> QgsVectorLayer:
    """
    CRS Guard (Data Digestion Agent): 
    Checks if the layer uses a geographic CRS (e.g. WGS84).
    If it does, auto-reprojects it to a local UTM CRS selected from the
    layer centroid. Polar/out-of-UTM data falls back to EPSG:6933.
    """
    crs = layer.crs()
    if crs.isGeographic():
        center = layer.extent().center()
        if crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
            center = transform.transform(center)
        lon, lat = center.x(), center.y()
        if -80.0 <= lat <= 84.0:
            zone = max(1, min(60, int((lon + 180.0) // 6.0) + 1))
            epsg = (32600 if lat >= 0 else 32700) + zone
        else:
            epsg = 6933
        target_crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
        print(f"[CRS Guard] Reprojecting geographic layer '{layer.name()}' to {target_crs.authid()} for metric analysis.")
        import processing.core.Processing
        processing.core.Processing.Processing.initialize()
        params = {
            'INPUT': layer,
            'TARGET_CRS': target_crs,
            'OUTPUT': 'memory:'
        }
        result = processing.run("native:reprojectlayer", params)
        out_layer = result['OUTPUT']
        out_layer.setName(f"{layer.name()}_{target_crs.authid().replace(':', '_')}")
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
        
    if (isinstance(QgsVectorLayer, type) and isinstance(out_layer, QgsVectorLayer)) or hasattr(out_layer, "setName"):
        out_layer.setName(f"{layer.name()}_buffered")
        QgsProject.instance().addMapLayer(out_layer)
        
    return out_layer

def clip(input_layer: QgsVectorLayer, overlay_layer: QgsVectorLayer, output_path: str = "memory:") -> QgsVectorLayer:
    """Clips the input layer with the overlay layer."""
    import processing.core.Processing
    processing.core.Processing.Processing.initialize()

    overlay_to_use = overlay_layer
    if (
        hasattr(input_layer, "crs")
        and hasattr(overlay_layer, "crs")
        and input_layer.crs().isValid()
        and overlay_layer.crs().isValid()
        and input_layer.crs() != overlay_layer.crs()
    ):
        reproject_params = {
            'INPUT': overlay_layer,
            'TARGET_CRS': input_layer.crs(),
            'OUTPUT': 'memory:'
        }
        reproject_result = processing.run("native:reprojectlayer", reproject_params)
        overlay_to_use = reproject_result['OUTPUT']
    
    params = {
        'INPUT': input_layer,
        'OVERLAY': overlay_to_use,
        'OUTPUT': output_path
    }
    result = processing.run("native:clip", params)
    
    out_layer = result['OUTPUT']
    if isinstance(out_layer, str) and output_path != "memory:":
        from .io_tools import load_vector_layer
        return load_vector_layer(out_layer)
        
    try:
        if isinstance(QgsVectorLayer, type) and isinstance(out_layer, QgsVectorLayer):
            out_layer.setName(f"{input_layer.name()}_clipped")
            if hasattr(QgsProject.instance(), "addMapLayer"):
                QgsProject.instance().addMapLayer(out_layer)
    except (AttributeError, RuntimeError, TypeError):
        pass
        
    return out_layer

def clip_raster(input_layer, mask_layer, output_path: str = "TEMPORARY_OUTPUT", validate_output: bool = True, min_valid_percent: float = 0.01):
    """
    Clips a raster layer using a vector mask layer.
    Preserves the input data type. Existing NoData is retained; when the input
    has no declared NoData, an alpha mask is used instead of inventing a value
    that may collide with valid pixels.
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
    
    # Never invent an integer NoData value: every candidate may be valid data.
    import math
    if nodata_val is not None and not math.isnan(nodata_val):
        params['NODATA'] = nodata_val
    else:
        params['ALPHA_BAND'] = True
        
    result = processing.run("gdal:cliprasterbymasklayer", params)
    out_path = result['OUTPUT']

    if validate_output and isinstance(out_path, str) and out_path != "TEMPORARY_OUTPUT":
        from ...core.raster_validation import validate_raster_has_data
        validation = validate_raster_has_data(out_path, min_valid_percent=min_valid_percent, force_read=True)
        if not validation.get("ok"):
            raise Exception(
                "Raster clip output is not usable: "
                f"{validation.get('message', 'validation failed')} "
                f"({out_path})"
            )
    
    from .io_tools import load_raster_layer
    out_layer = load_raster_layer(out_path, f"{input_layer.name()}_clipped")
    if out_layer.isValid():
        
        # Reuse the renderer configuration; output statistics may still differ.
        if input_layer.renderer():
            out_layer.setRenderer(input_layer.renderer().clone())
            out_layer.triggerRepaint()
            
    return out_layer
