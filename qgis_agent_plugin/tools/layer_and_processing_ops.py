# Layer inspection, selection, Processing execution, PyQGIS doc lookup, and Skill file operations.

from qgis.core import QgsExpression, QgsMapLayerType, QgsProject, QgsRasterLayer, QgsVectorLayer
try:
    import processing
except ImportError:
    processing = None

from .osm_workflows import _find_project_layer

LAYER_AND_PROCESSING_TOOLS = frozenset({
    'list_layers',
    'zoom_to_layer',
    'set_layer_visibility',
    'create_geodatabase',
    'inspect_layer_fields',
    'get_selected_features',
    'select_features_by_expression',
    'clear_selection',
    'zoom_to_selected',
    'run_processing_algorithm',
    'query_pyqgis_doc',
    'read_skill',
    'save_or_update_dynamic_skill',
})


def execute_layer_or_processing_tool(iface, tool_name, kwargs):
    if tool_name == "list_layers":
        layers = QgsProject.instance().mapLayers().values()
        if not layers:
            return "No layers found in the project."
        result = []
        for layer in layers:
            result.append(f"- {layer.name()} (ID: {layer.id()}, Type: {'Vector' if layer.type() == QgsMapLayerType.VectorLayer else 'Raster'})")
        return "\n".join(result)
        
    elif tool_name == "zoom_to_layer":
        layer_name = kwargs.get("layer_name")
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if not layers:
            return f"Layer '{layer_name}' not found."
        layer = layers[0]
        iface.mapCanvas().setExtent(layer.extent())
        iface.mapCanvas().refresh()
        return f"Zoomed to layer '{layer_name}' successfully."
        
    elif tool_name == "set_layer_visibility":
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
        
    elif tool_name == "create_geodatabase":
        from qgis.core import QgsVectorFileWriter
        import os
        from ..core.tool_result import ToolResult
        from ..core.validators import validate_path_within_allowed_roots
        
        db_path = kwargs.get("database_path")
        layer_name = kwargs.get("layer_name")
        geom_type = kwargs.get("geometry_type")
        crs = kwargs.get("crs")
        
        if not db_path:
            return "Error: database_path is required."
        path_report = validate_path_within_allowed_roots(db_path, "database_path")
        if not path_report.ok:
            return ToolResult.failure(
                "GeoPackage path is outside the allowed workspace.",
                error_type="file_path_error",
                data={"database_path": db_path, "validation": path_report.to_dict()},
            ).to_dict()
        
        parent_dir = os.path.dirname(db_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        if os.path.exists(db_path):
            return f"Error: database already exists at {db_path}. Refusing to overwrite it."
        
        if not layer_name:
            try:
                from osgeo import ogr
                driver = ogr.GetDriverByName("GPKG")
                if not driver:
                    return "Error: GDAL GPKG driver is not available."
                ds = driver.CreateDataSource(db_path)
                if ds is None:
                    return f"Failed to create GeoPackage database at {db_path}."
                ds = None
                return f"Empty GeoPackage database created at {db_path}."
            except Exception as e:
                return f"Failed to create GeoPackage with GDAL/OGR: {str(e)}"
            
        if not geom_type or not crs:
            return "Error: geometry_type and crs are required when layer_name is provided."

        # Create a layer to initialize the gpkg
        uri = f"{geom_type}?crs={crs}"
        layer = QgsVectorLayer(uri, layer_name, "memory")
        if not layer.isValid():
            return f"Failed to create memory layer for geometry {geom_type} and crs {crs}."
            
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        
        writer_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            db_path,
            QgsProject.instance().transformContext(),
            options
        )
        error = writer_result[0]
        msg = writer_result[1] if len(writer_result) > 1 else ""
        
        if error == QgsVectorFileWriter.NoError:
            # Load the newly created layer into the project
            gpkg_layer = QgsVectorLayer(f"{db_path}|layername={layer_name}", layer_name, "ogr")
            if gpkg_layer.isValid():
                QgsProject.instance().addMapLayer(gpkg_layer)
                return f"GeoPackage database created at {db_path} and initialized with layer '{layer_name}'."
            return f"GeoPackage database created at {db_path}, but failed to load the new layer into QGIS."
        else:
            return f"Failed to create GeoPackage: {msg}"
        
    elif tool_name == "inspect_layer_fields":
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
        
    elif tool_name == "get_selected_features":
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
        
    elif tool_name == "select_features_by_expression":
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
        
    elif tool_name == "clear_selection":
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
            
    elif tool_name == "zoom_to_selected":
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
        
    elif tool_name == "run_processing_algorithm":
        from qgis.core import QgsProcessingFeedback
        from qgis.PyQt.QtCore import QCoreApplication
        from ..core.tool_result import ToolResult
        import os
        alg_id = kwargs.get("alg_id")
        params = dict(kwargs.get("parameters", {}))
        try:
            from ..core.processing_catalog import validate_processing_algorithm_call
            live_validation = validate_processing_algorithm_call(alg_id, params)
            if not live_validation.get("ok"):
                return ToolResult.failure(
                    live_validation.get("message", "Processing algorithm validation failed."),
                    error_type=live_validation.get("error_type", "processing_error"),
                    data=live_validation.get("data", {"alg_id": alg_id, "parameters": params}),
                    suggestions=live_validation.get(
                        "suggestions",
                        ["Search and describe the processing algorithm before retrying."],
                    ),
                ).to_dict()
        except Exception as validation_exc:
            return ToolResult.failure(
                f"Processing catalog validation failed internally: {validation_exc}",
                error_type="processing_error",
                data={"alg_id": alg_id, "parameters": params},
                suggestions=["Rebuild the processing catalog and describe the algorithm before retrying."],
            ).to_dict()
        try:
            from ..core.validators import validate_processing_request
            validation = validate_processing_request(alg_id, params)
            if not validation.ok:
                return ToolResult.failure(
                    "Processing request validation failed.",
                    error_type="processing_error",
                    data={"alg_id": alg_id, "parameters": params, "validation": validation.to_dict()},
                ).to_dict()
        except Exception as validation_exc:
            return ToolResult.failure(
                f"Processing request validation failed internally: {validation_exc}",
                error_type="processing_error",
                data={"alg_id": alg_id, "parameters": params},
            ).to_dict()
        provider_prefix = str(alg_id).split(":", 1)[0].lower() if ":" in str(alg_id) else ""
        is_external_provider = provider_prefix in {"gdal", "grass", "grass7", "saga"}
        exec_params = dict(params)

        def _resolve_proc_input_value(val):
            if not isinstance(val, str) or not val or val in ("TEMPORARY_OUTPUT", "memory:"):
                return val
            if os.path.exists(val):
                return val
            layer_obj = _find_project_layer(val)
            if layer_obj is None:
                return val
            if is_external_provider:
                src_file = str(layer_obj.source() or "").split("|", 1)[0]
                if src_file and os.path.exists(src_file):
                    return src_file
            return layer_obj

        for k, v in list(exec_params.items()):
            if v == "TEMPORARY_OUTPUT":
                exec_params[k] = "TEMPORARY_OUTPUT"
            elif isinstance(v, str):
                exec_params[k] = _resolve_proc_input_value(v)
            elif isinstance(v, list):
                exec_params[k] = [_resolve_proc_input_value(item) for item in v]
                
        class EventPumpingFeedback(QgsProcessingFeedback):
            def setProgress(self, progress):
                super().setProgress(progress)
                QCoreApplication.processEvents()
                
        feedback = EventPumpingFeedback()
        try:
            try:
                import processing.core.Processing
                processing.core.Processing.Processing.initialize()
            except (ImportError, AttributeError, RuntimeError):
                pass
            result = processing.run(alg_id, exec_params, feedback=feedback)
            output_summary = []
            inspection = {}
            try:
                from ..core.result_inspector import inspect_processing_result
                inspection = inspect_processing_result(result)
                for warning in inspection.get("warnings", []):
                    output_summary.append(f"Validation warning: {warning}")
            except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
                pass
            for k, v in result.items():
                if isinstance(v, (QgsVectorLayer, QgsRasterLayer)):
                    from .qgis_tools.io_tools import find_existing_layer
                    layer_type = "raster" if isinstance(v, QgsRasterLayer) else "vector"
                    existing = find_existing_layer(path=v.source(), layer_type=layer_type)
                    if existing:
                        output_summary.append(f"{k}: Reused existing layer {existing.name()} ({v.source()}).")
                        continue
                    QgsProject.instance().addMapLayer(v)
                    output_summary.append(f"{k}: Layer {v.name()} generated and added to project.")
                elif isinstance(v, str) and (k.upper() == 'OUTPUT' or 'layer' in k.lower()):
                    # In QGIS 3/4, sometimes memory: outputs are returned as string IDs
                    layer = QgsProject.instance().mapLayer(v)
                    if layer:
                        output_summary.append(f"{k}: Layer {layer.name()} generated.")
                    elif os.path.exists(v):
                        layer_name = os.path.splitext(os.path.basename(v))[0]
                        from .qgis_tools.io_tools import load_raster_layer, load_vector_layer
                        try:
                            raster_layer = load_raster_layer(v, layer_name)
                            output_summary.append(f"{k}: Raster layer {raster_layer.name()} generated/reused ({v}).")
                        except (OSError, RuntimeError, ValueError, TypeError):
                            try:
                                vector_layer = load_vector_layer(v, layer_name)
                                output_summary.append(f"{k}: Vector layer {vector_layer.name()} generated/reused ({v}).")
                            except (OSError, RuntimeError, ValueError, TypeError):
                                output_summary.append(f"{k}: {v}")
                    else:
                        output_summary.append(f"{k}: {v}")
                else:
                    output_summary.append(f"{k}: {v}")
                    
            # Verify that any explicit file outputs actually exist on disk
            missing_outputs = []
            for param_k, param_v in params.items():
                if isinstance(param_v, str) and (param_v.lower().endswith(('.tif', '.tiff', '.shp', '.geojson', '.gpkg')) or os.path.isabs(param_v)):
                    if param_v not in ("TEMPORARY_OUTPUT", "memory:") and not os.path.exists(param_v):
                        missing_outputs.append((param_k, param_v))

            if missing_outputs:
                return ToolResult.failure(
                    f"Algorithm '{alg_id}' completed, but output file(s) were not created on disk: "
                    + ", ".join(f"{k}='{v}'" for k, v in missing_outputs)
                    + ". The backend (e.g. GRASS/GDAL) may have encountered memory limits or execution errors.",
                    error_type="missing_output_file",
                    data={"alg_id": alg_id, "parameters": params, "missing_outputs": missing_outputs},
                    suggestions=[
                        "Check memory allocation (e.g. memory=2000 for large DEMs in grass:r.watershed).",
                        "Consider using QGIS native processing algorithms (like native:fillsinkswangliu) or a direct PyQGIS script.",
                    ],
                ).to_dict()

            return ToolResult.success(
                f"Algorithm '{alg_id}' completed successfully.",
                data={
                    "alg_id": alg_id,
                    "parameters": params,
                    "outputs": output_summary,
                    "inspection": inspection,
                },
            ).to_dict()
        except Exception as e:
            return ToolResult.failure(
                f"Error running algorithm '{alg_id}': {str(e)}",
                error_type="processing_error",
                data={"alg_id": alg_id, "parameters": params},
            ).to_dict()
            
    elif tool_name == "query_pyqgis_doc":
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
        except (ImportError, AttributeError, TypeError) as e:
            return f"Error importing modules: {str(e)}"
            
        if not target_obj:
            return f"Could not find PyQGIS object '{target_name}'. Are you sure it's in qgis.core or qgis.gui?"
            
        doc = pydoc.render_doc(target_obj, renderer=pydoc.plaintext)
        # Truncate to 10k chars to avoid blowing up context, but keep it long enough for full signatures
        max_len = 10000
        if len(doc) > max_len:
            doc = doc[:max_len] + f"\n... [Truncated, total length was {len(doc)} chars]"
        return f"--- Native PyQGIS Docs for {target_name} ---\n{doc}"
        
    elif tool_name == "read_skill":
        import os
        from ..core.validators import validate_safe_name
        skill_name = kwargs.get("skill_name")
        if not skill_name:
            return "Error: skill_name is required."
        name_report = validate_safe_name(skill_name, "skill_name")
        if not name_report.ok:
            return {
                "ok": False,
                "message": "Invalid skill_name.",
                "data": {"validation": name_report.to_dict()},
                "artifacts": [],
                "warnings": [],
                "error_type": "argument_error",
                "suggestions": ["Use only letters, numbers, underscore, and hyphen in skill_name."],
            }
        
        # Search in core and dynamic directories
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        core_path = os.path.join(base_dir, "skills", "core", f"{skill_name}.md")
        dynamic_path = os.path.join(base_dir, "skills", "dynamic", f"{skill_name}.md")
        
        if os.path.exists(core_path):
            with open(core_path, 'r', encoding='utf-8') as f:
                return f.read()
        elif os.path.exists(dynamic_path):
            with open(dynamic_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return f"Error: Skill '{skill_name}' not found."

    elif tool_name == "save_or_update_dynamic_skill":
        import os
        from ..core.validators import validate_safe_name
        skill_name = kwargs.get("skill_name")
        desc = kwargs.get("description", "")
        rules = kwargs.get("rules")
        action = kwargs.get("action")
        
        if not skill_name or not rules or not action:
            return "Error: skill_name, rules, and action are required."
        name_report = validate_safe_name(skill_name, "skill_name")
        if not name_report.ok:
            return {
                "ok": False,
                "message": "Invalid skill_name.",
                "data": {"validation": name_report.to_dict()},
                "artifacts": [],
                "warnings": [],
                "error_type": "argument_error",
                "suggestions": ["Use only letters, numbers, underscore, and hyphen in skill_name."],
            }
            
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dynamic_dir = os.path.join(base_dir, "skills", "dynamic")
        os.makedirs(dynamic_dir, exist_ok=True)
        
        file_path = os.path.join(dynamic_dir, f"{skill_name}.md")
        
        if action == "create":
            if os.path.exists(file_path):
                return f"Error: Skill '{skill_name}' already exists. Use action='update' instead."
            content = f"<skill>\n<name>{skill_name}</name>\n<description>{desc}</description>\n\n<strict_rules>\n{rules}\n</strict_rules>\n</skill>"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully created dynamic skill '{skill_name}'."
            
        elif action == "update":
            if not os.path.exists(file_path):
                # Check if it's trying to update a core skill
                core_path = os.path.join(base_dir, "skills", "core", f"{skill_name}.md")
                if os.path.exists(core_path):
                    return f"Error: '{skill_name}' is a core skill and cannot be modified directly. You should create a new dynamic skill to override it."
                return f"Error: Dynamic skill '{skill_name}' does not exist to update."
            
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(f"\n\n<!-- UPDATE -->\n<strict_rules>\n{rules}\n</strict_rules>")
            return f"Successfully updated dynamic skill '{skill_name}'."

    return None
