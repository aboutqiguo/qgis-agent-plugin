from qgis.core import QgsProject, QgsMapLayerType, QgsVectorLayer, QgsRasterLayer, QgsFeatureRequest, QgsExpression, QgsCoordinateReferenceSystem
import processing

REGISTERED_TOOLS = {}

def agent_tool(description, parameters, requires_confirmation=False, is_destructive=False):
    def decorator(func):
        tool_name = func.__name__
        REGISTERED_TOOLS[tool_name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": description,
                    "parameters": parameters
                },
                "metadata": {
                    "destructive": is_destructive,
                    "requires_confirmation": requires_confirmation
                }
            },
            "callable": func
        }
        return func
    return decorator

def get_all_tools_schema():
    return [t["schema"] for t in REGISTERED_TOOLS.values()]

def execute_atomic_tool(iface, tool_name, kwargs):
    if tool_name not in REGISTERED_TOOLS:
        return f"Unknown tool: {tool_name}"
    try:
        func = REGISTERED_TOOLS[tool_name]["callable"]
        return func(iface, **kwargs)
    except Exception as e:
        import traceback
        return f"Error executing tool {tool_name}: {str(e)}\n{traceback.format_exc()}"

@agent_tool(
    description='List all vector and raster layers in the current QGIS project.',
    parameters={'type': 'object', 'properties': {}, 'required': []},
    requires_confirmation=False,
    is_destructive=False
)
def list_layers(iface, **kwargs):
    layers = QgsProject.instance().mapLayers().values()
    if not layers:
        return "No layers found in the project."
    result = []
    for layer in layers:
        result.append(f"- {layer.name()} (ID: {layer.id()}, Type: {'Vector' if layer.type() == QgsMapLayerType.VectorLayer else 'Raster'})")
    return "\n".join(result)
@agent_tool(
    description='Zoom the map canvas to the extent of a specific layer by its exact name.',
    parameters={'type': 'object', 'properties': {'layer_name': {'type': 'string', 'description': 'The exact name of the layer to zoom to.'}}, 'required': ['layer_name']},
    requires_confirmation=False,
    is_destructive=False
)
def zoom_to_layer(iface, **kwargs):
    layer_name = kwargs.get("layer_name")
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        return f"Layer '{layer_name}' not found."
    layer = layers[0]
    iface.mapCanvas().setExtent(layer.extent())
    iface.mapCanvas().refresh()
    return f"Zoomed to layer '{layer_name}' successfully."
@agent_tool(
    description='Turn the visibility of a specific layer on or off.',
    parameters={'type': 'object', 'properties': {'layer_name': {'type': 'string', 'description': 'The exact name of the layer.'}, 'visible': {'type': 'boolean', 'description': 'True to show, False to hide.'}}, 'required': ['layer_name', 'visible']},
    requires_confirmation=False,
    is_destructive=False
)
def set_layer_visibility(iface, **kwargs):
    layer_name = kwargs.get("layer_name")
    visible = kwargs.get("visible")
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        return f"Layer '{layer_name}' not found."
    layer = layers[0]
    root = QgsProject.instance().layerTreeRoot()
    node = root.findLayer(layer.id())
    if node:
        node.setItemVisibilityChecked(visible)
        return f"Layer '{layer_name}' visibility set to {visible}."
    return f"Layer node for '{layer_name}' not found in the layer tree."
@agent_tool(
    description='Create a new GeoPackage database (the QGIS native equivalent of a file geodatabase) and optionally create a new empty vector layer in it.',
    parameters={'type': 'object', 'properties': {'database_path': {'type': 'string', 'description': "Absolute path to the new .gpkg file (e.g. 'D:/project/data/mydb.gpkg')."}, 'layer_name': {'type': 'string', 'description': 'Optional name of an initial empty vector layer to create inside the database.'}, 'geometry_type': {'type': 'string', 'description': "Geometry type for the initial layer (e.g. 'Point', 'LineString', 'Polygon'). Required if layer_name is provided."}, 'crs': {'type': 'string', 'description': "EPSG code for the layer (e.g. 'EPSG:4326'). Required if layer_name is provided."}}, 'required': ['database_path']},
    requires_confirmation=False,
    is_destructive=False
)
def create_geodatabase(iface, **kwargs):
    from qgis.core import QgsVectorLayer, QgsVectorFileWriter
    import os

    db_path = kwargs.get("database_path")
    layer_name = kwargs.get("layer_name")
    geom_type = kwargs.get("geometry_type")
    crs = kwargs.get("crs")

    if not db_path:
        return "Error: database_path is required."

    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if not layer_name:
        # Just create an empty GeoPackage using processing or sqlite
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.close()
        return f"Empty GeoPackage database created at {db_path}."

    # Create a layer to initialize the gpkg
    uri = f"{geom_type}?crs={crs}"
    layer = QgsVectorLayer(uri, layer_name, "memory")
    if not layer.isValid():
        return f"Failed to create memory layer for geometry {geom_type} and crs {crs}."

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = layer_name

    error, msg = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer,
        db_path,
        QgsProject.instance().transformContext(),
        options
    )

    if error == QgsVectorFileWriter.NoError:
        # Load the newly created layer into the project
        gpkg_layer = QgsVectorLayer(f"{db_path}|layername={layer_name}", layer_name, "ogr")
        if gpkg_layer.isValid():
            QgsProject.instance().addMapLayer(gpkg_layer)
            return f"GeoPackage database created at {db_path} and initialized with layer '{layer_name}'."
        return f"GeoPackage database created at {db_path}, but failed to load the new layer into QGIS."
    else:
        return f"Failed to create GeoPackage: {msg}"
@agent_tool(
    description='Get a list of fields and their data types for a vector layer.',
    parameters={'type': 'object', 'properties': {'layer_name': {'type': 'string', 'description': 'The exact name of the vector layer.'}}, 'required': ['layer_name']},
    requires_confirmation=False,
    is_destructive=False
)
def inspect_layer_fields(iface, **kwargs):
    layer_name = kwargs.get("layer_name")
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        return f"Layer '{layer_name}' not found."
    layer = layers[0]
    if layer.type() != QgsMapLayerType.VectorLayer:
        return f"Layer '{layer_name}' is not a vector layer."
    fields = layer.fields()
    result = [f"Fields for vector layer '{layer_name}':"]
    for field in fields:
        result.append(f"- {field.name()}: {field.typeName()}")
    return "\n".join(result)
@agent_tool(
    description='Get a summary of the currently selected features in a vector layer.',
    parameters={'type': 'object', 'properties': {'layer_name': {'type': 'string', 'description': 'The exact name of the vector layer.'}, 'limit': {'type': 'integer', 'description': 'Maximum number of features to return (default 10).'}}, 'required': ['layer_name']},
    requires_confirmation=False,
    is_destructive=False
)
def get_selected_features(iface, **kwargs):
    layer_name = kwargs.get("layer_name")
    limit = kwargs.get("limit", 10)
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        return f"Layer '{layer_name}' not found."
    layer = layers[0]
    if layer.type() != QgsMapLayerType.VectorLayer:
        return f"Layer '{layer_name}' is not a vector layer."
    selected = layer.selectedFeatures()
    if not selected:
        return f"No features are currently selected in layer '{layer_name}'."
    result = [f"Total selected features: {len(selected)}"]
    result.append(f"Showing up to {limit} features:")
    for i, feat in enumerate(selected[:limit]):
        attrs = feat.attributes()
        result.append(f"  Feature {feat.id()}: {attrs}")
    return "\n".join(result)
@agent_tool(
    description='Select features in a vector layer using a QGIS expression.',
    parameters={'type': 'object', 'properties': {'layer_name': {'type': 'string', 'description': 'The exact name of the vector layer.'}, 'expression': {'type': 'string', 'description': 'A valid QGIS expression (e.g. "type" = \'road\' or "area" > 1000).'}}, 'required': ['layer_name', 'expression']},
    requires_confirmation=False,
    is_destructive=False
)
def select_features_by_expression(iface, **kwargs):
    layer_name = kwargs.get("layer_name")
    expression_str = kwargs.get("expression")
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        return f"Layer '{layer_name}' not found."
    layer = layers[0]
    if layer.type() != QgsMapLayerType.VectorLayer:
        return f"Layer '{layer_name}' is not a vector layer."

    exp = QgsExpression(expression_str)
    if exp.hasParserError():
        return f"Expression error: {exp.parserErrorString()}"

    layer.selectByExpression(expression_str)
    count = layer.selectedFeatureCount()
    return f"Successfully selected {count} features using expression: {expression_str}"
@agent_tool(
    description='Clear the selection of a specific layer or all layers.',
    parameters={'type': 'object', 'properties': {'layer_name': {'type': 'string', 'description': 'The name of the layer to clear selection from. If omitted, clears all selections across all layers.'}}, 'required': []},
    requires_confirmation=False,
    is_destructive=False
)
def clear_selection(iface, **kwargs):
    layer_name = kwargs.get("layer_name")
    if layer_name:
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if not layers:
            return f"Layer '{layer_name}' not found."
        layer = layers[0]
        if layer.type() == QgsMapLayerType.VectorLayer:
            layer.removeSelection()
            return f"Selection cleared for layer '{layer_name}'."
        return f"Layer '{layer_name}' is not a vector layer."
    else:
        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() == QgsMapLayerType.VectorLayer:
                layer.removeSelection()
        return "Selection cleared for all vector layers."
@agent_tool(
    description='Zoom the map canvas to the bounding box of the currently selected features of a layer.',
    parameters={'type': 'object', 'properties': {'layer_name': {'type': 'string', 'description': 'The name of the layer with selected features.'}}, 'required': ['layer_name']},
    requires_confirmation=False,
    is_destructive=False
)
def zoom_to_selected(iface, **kwargs):
    layer_name = kwargs.get("layer_name")
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        return f"Layer '{layer_name}' not found."
    layer = layers[0]
    if layer.type() != QgsMapLayerType.VectorLayer:
        return f"Layer '{layer_name}' is not a vector layer."
    if layer.selectedFeatureCount() == 0:
        return f"No selected features in layer '{layer_name}' to zoom to."
    box = layer.boundingBoxOfSelected()
    iface.mapCanvas().setExtent(box)
    iface.mapCanvas().refresh()
    return f"Zoomed to selected features in layer '{layer_name}'."
@agent_tool(
    description="Run a QGIS processing algorithm safely. It automatically handles 'TEMPORARY_OUTPUT' strings for output parameters. Returns the log and generated layer IDs.",
    parameters={'type': 'object', 'properties': {'alg_id': {'type': 'string', 'description': "The processing algorithm ID (e.g. 'native:buffer', 'gdal:slope', 'gdal:contour')."}, 'parameters': {'type': 'object', 'description': "Dictionary of algorithm parameters. For inputs, use layer IDs or names. For memory outputs, use the string 'TEMPORARY_OUTPUT'."}}, 'required': ['alg_id', 'parameters']},
    requires_confirmation=False,
    is_destructive=False
)
def run_processing_algorithm(iface, **kwargs):
    from qgis.core import QgsProcessingFeedback, QgsProcessingContext
    from qgis.PyQt.QtCore import QCoreApplication
    alg_id = kwargs.get("alg_id")
    params = kwargs.get("parameters", {})

    for k, v in params.items():
        if v == "TEMPORARY_OUTPUT":
            params[k] = "memory:"

    class EventPumpingFeedback(QgsProcessingFeedback):
        def setProgress(self, progress):
            super().setProgress(progress)
            QCoreApplication.processEvents()

    feedback = EventPumpingFeedback()
    try:
        result = processing.run(alg_id, params, feedback=feedback)
        output_summary = []
        for k, v in result.items():
            if isinstance(v, (QgsVectorLayer, QgsRasterLayer)):
                QgsProject.instance().addMapLayer(v)
                output_summary.append(f"{k}: Layer {v.name()} generated and added to project.")
            elif isinstance(v, str) and (k.upper() == 'OUTPUT' or 'layer' in k.lower()):
                # In QGIS 3/4, sometimes memory: outputs are returned as string IDs
                layer = QgsProject.instance().mapLayer(v)
                if layer:
                    output_summary.append(f"{k}: Layer {layer.name()} generated.")
                else:
                    output_summary.append(f"{k}: {v}")
            else:
                output_summary.append(f"{k}: {v}")

        return f"Algorithm '{alg_id}' completed successfully.\nOutputs:\n" + "\n".join(output_summary)
@agent_tool(
    description='Perform Native RAG by introspecting a PyQGIS module or class to get its exact methods, properties, and docstrings. Use this if you are unsure about the PyQGIS API before writing scripts.',
    parameters={'type': 'object', 'properties': {'target_name': {'type': 'string', 'description': "The exact name of the QGIS class or module to inspect (e.g., 'QgsVectorLayer', 'QgsFeatureRequest', 'QgsGeometry')."}}, 'required': ['target_name']},
    requires_confirmation=False,
    is_destructive=False
)
def query_pyqgis_doc(iface, **kwargs):
    import pydoc
    target_name = kwargs.get("target_name", "")

    target_obj = None
    try:
        import qgis.core
        if hasattr(qgis.core, target_name):
            target_obj = getattr(qgis.core, target_name)
        else:
            import qgis.gui
            if hasattr(qgis.gui, target_name):
                target_obj = getattr(qgis.gui, target_name)
            else:
                import processing
                if hasattr(processing, target_name) or target_name == "processing":
                    target_obj = getattr(processing, target_name) if hasattr(processing, target_name) else processing
@agent_tool(
    description='Download OpenStreetMap data using the Overpass API based on a bounding box and OSM tags.',
    parameters={'type': 'object', 'properties': {'bbox': {'type': 'string', 'description': "Bounding box string 'min_lon,min_lat,max_lon,max_lat' (e.g. '116.3,39.9,116.4,40.0'). Must be in WGS84 (EPSG:4326)."}, 'tags': {'type': 'string', 'description': 'OSM tags in Overpass QL format, e.g. \'node["amenity"="hospital"]\' or \'way["highway"]\'.'}, 'layer_name': {'type': 'string', 'description': 'Name for the imported QGIS layer.'}}, 'required': ['bbox', 'tags', 'layer_name']},
    requires_confirmation=False,
    is_destructive=False
)
def download_osm_data(iface, **kwargs):
    import requests
    import os
    import tempfile
    from qgis.core import QgsVectorLayer

    bbox_str = kwargs.get("bbox")
    tags = kwargs.get("tags")
    layer_name = kwargs.get("layer_name", "OSM_Data")

    try:
        w, s, e, n = [float(x) for x in bbox_str.split(',')]
    except Exception:
        return "Error: bbox must be 'min_lon,min_lat,max_lon,max_lat'."

    query = f"""
    [out:xml][timeout:25];
    (
      {tags}({s},{w},{n},{e});
    );
    out body;
    >;
    out skel qt;
    """
    try:
        url = "http://overpass-api.de/api/interpreter"
        response = requests.post(url, data={'data': query}, timeout=30)
        response.raise_for_status()

        tmp_dir = tempfile.gettempdir()
        file_path = os.path.join(tmp_dir, f"{layer_name}.osm")
        with open(file_path, 'wb') as f:
            f.write(response.content)

        layer = QgsVectorLayer(file_path, layer_name, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            return f"Successfully downloaded OSM data and loaded layer '{layer_name}'."
