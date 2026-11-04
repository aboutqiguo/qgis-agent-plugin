# OSM feature download, deduplication, and vector layer persistence helpers.

from qgis.core import QgsProject, QgsVectorLayer

from ..core.progress import emit_progress


def _emit_acquisition_progress(callback, tool_name, title, stage, stage_index, stage_count, stage_percent=None, detail='', state='running'):
    return emit_progress(callback, tool_name=tool_name, title=title, stage=stage, stage_index=stage_index, stage_count=stage_count, stage_percent=stage_percent, detail=detail, state=state)


def _artifact_entry(path: str, artifact_type: str, description: str):
    return {'type': artifact_type, 'path': path, 'description': description}


def _find_project_layer(layer_name: str):
    for layer in QgsProject.instance().mapLayers().values():
        if layer.name() == layer_name or layer.id() == layer_name:
            return layer
    return None


def _remove_existing_output(output_file: str) -> None:
    import os
    from pathlib import Path

    if not os.path.exists(output_file):
        return
    path = Path(output_file)
    if path.is_dir():
        raise ValueError(f"Refusing to overwrite directory output: {output_file}")
    try:
        from .qgis_tools.io_tools import _canonical_source
        from qgis.core import QgsProject

        target = _canonical_source(output_file).split("|", 1)[0]
        project = QgsProject.instance()
        remove_ids = []
        for layer_id, layer in project.mapLayers().items():
            try:
                source = _canonical_source(layer.source()).split("|", 1)[0]
                if source == target:
                    remove_ids.append(layer_id)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        for layer_id in remove_ids:
            project.removeMapLayer(layer_id)
    except (ImportError, AttributeError, RuntimeError, TypeError):
        pass
    # GeoPackage is overwritten by QgsVectorFileWriter after loaded layers have
    # been released. Other formats still require sidecar cleanup.
    if path.suffix.lower() != ".gpkg":
        os.remove(output_file)
    if path.suffix.lower() == ".shp":
        for suffix in (".dbf", ".shx", ".prj", ".cpg", ".qix"):
            sidecar = path.with_suffix(suffix)
            if sidecar.exists():
                sidecar.unlink()


def _ensure_output_available(output_file: str, overwrite: bool) -> None:
    import os

    if os.path.exists(output_file):
        if not overwrite:
            raise FileExistsError(f"Output already exists: {output_file}. Set overwrite=true to replace it.")
        _remove_existing_output(output_file)


def _vector_driver_for_path(output_file: str):
    from pathlib import Path

    suffix = Path(output_file).suffix.lower()
    if suffix == ".gpkg":
        return "GPKG", output_file
    if suffix in {".geojson", ".json"}:
        return "GeoJSON", output_file
    if suffix == ".shp":
        return "ESRI Shapefile", output_file
    raise ValueError("Unsupported output format. Use .gpkg, .geojson, or .shp.")


def _save_vector_layer(layer, output_file: str, layer_name: str):
    from qgis.core import QgsVectorFileWriter
    import os

    driver, load_uri = _vector_driver_for_path(output_file)
    parent = os.path.dirname(output_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    if driver == "GPKG":
        options.layerName = layer_name
        if os.path.exists(output_file):
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
    result = QgsVectorFileWriter.writeAsVectorFormatV2(
        layer,
        output_file,
        QgsProject.instance().transformContext(),
        options,
    )
    error = result[0] if isinstance(result, tuple) else result
    if error != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Failed to save vector layer to {output_file}: {result}")
    if driver == "GPKG":
        return f"{output_file}|layername={layer_name}"
    return load_uri


def _bbox_from_layer(layer):
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

    extent = layer.extent()
    if layer.crs().isValid() and layer.crs().authid() != "EPSG:4326":
        transform = QgsCoordinateTransform(
            layer.crs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance(),
        )
        extent = transform.transformBoundingBox(extent)
    return (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())


def _deduplicate_vector_layer(layer, layer_name: str):
    """Return an in-memory layer deduplicated by OSM id or exact geometry."""
    from qgis.core import QgsFeature, QgsVectorLayer, QgsWkbTypes

    crs = layer.crs().authid() if layer.crs().isValid() else "EPSG:4326"
    geometry_name = QgsWkbTypes.displayString(layer.wkbType())
    output = QgsVectorLayer(f"{geometry_name}?crs={crs}", layer_name, "memory")
    provider = output.dataProvider()
    provider.addAttributes(layer.fields())
    output.updateFields()
    field_names = [field.name() for field in layer.fields()]
    osm_id_index = field_names.index("osm_id") if "osm_id" in field_names else -1
    seen = set()
    features = []
    for source_feature in layer.getFeatures():
        osm_id = source_feature.attribute(osm_id_index) if osm_id_index >= 0 else None
        if osm_id not in (None, "", "NULL"):
            key = ("osm_id", str(osm_id))
        else:
            geometry_key = bytes(source_feature.geometry().asWkb()) if source_feature.hasGeometry() else b""
            key = ("geometry", geometry_key, tuple(str(value) for value in source_feature.attributes()))
        if key in seen:
            continue
        seen.add(key)
        feature = QgsFeature(output.fields())
        feature.setAttributes(source_feature.attributes())
        if source_feature.hasGeometry():
            feature.setGeometry(source_feature.geometry())
        features.append(feature)
    provider.addFeatures(features)
    output.updateExtents()
    return output


def _execute_osm_feature_download(kwargs, progress_callback=None, cancel_callback=None):
    import os
    import shutil
    import tempfile
    from ..bridges.osm_bridge import (
        OSMDownloader,
        classify_overpass_error,
        build_bbox_query,
        parse_bbox,
        resolve_tag_template,
        safe_feature_count,
        split_bbox,
        bbox_area,
    )
    from ..core.tool_result import ToolResult
    from ..core.validators import sanitize_file_stem

    output_file = kwargs.get("output_file")
    layer_name = kwargs.get("layer_name") or sanitize_file_stem(os.path.splitext(os.path.basename(output_file))[0], "osm_features")
    overwrite = bool(kwargs.get("overwrite", False))
    split_large_bbox = kwargs.get("split_large_bbox", True)
    max_chunk_area = float(kwargs.get("max_chunk_area", 0.25) or 0.25)
    tmp_dir = ""
    tool_name = "download_osm_features"
    title = "OSM 要素下载"

    try:
        from ..core.progress import raise_if_cancelled
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "准备查询", 1, 5, 0,
            "正在验证范围、标签和输出路径。",
        )
        raise_if_cancelled(cancel_callback, "OSM feature download was cancelled by the user.")
        _ensure_output_available(output_file, overwrite)
        tags, geometry_type = resolve_tag_template(
            preset=kwargs.get("preset", "buildings"),
            tags=kwargs.get("tags"),
            geometry_type=kwargs.get("geometry_type", ""),
        )
        bbox_value = kwargs.get("bbox")
        if bbox_value:
            bbox = parse_bbox(bbox_value)
        else:
            boundary_layer_name = kwargs.get("boundary_layer_name")
            boundary_layer = _find_project_layer(boundary_layer_name)
            if boundary_layer is None:
                return ToolResult.failure(
                    "boundary_layer_name was not found and bbox was not provided.",
                    error_type="qgis_layer_error",
                    data={"boundary_layer_name": boundary_layer_name},
                ).to_dict()
            bbox = parse_bbox(_bbox_from_layer(boundary_layer))

        chunks = split_bbox(bbox, max_area=max_chunk_area) if split_large_bbox else [bbox]
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "准备查询", 1, 5, 100,
            f"已生成 {len(chunks)} 个初始下载分块。",
        )
        tmp_dir = tempfile.mkdtemp(prefix="qgis_agent_osm_")
        loaded_layers = []
        chunk_records = []

        queue = list(chunks)
        index = 0
        while queue:
            raise_if_cancelled(cancel_callback, "OSM feature download was cancelled by the user.")
            chunk = queue.pop(0)
            index += 1
            completed_chunks = len(loaded_layers)
            current_total = max(1, completed_chunks + len(queue) + 1)
            _emit_acquisition_progress(
                progress_callback,
                tool_name,
                title,
                "下载 Overpass 分块",
                2,
                5,
                completed_chunks / current_total * 100.0,
                f"正在请求分块 {completed_chunks + 1}/{current_total}。",
            )
            query = build_bbox_query(tags, chunk, geometry_type=geometry_type, timeout_seconds=180)
            chunk_osm = os.path.join(tmp_dir, f"{sanitize_file_stem(layer_name, 'osm')}_{index:03d}.osm")

            def _chunk_transfer(received, total, endpoint):
                pending_total = max(1, len(loaded_layers) + len(queue) + 1)
                if total > 0:
                    current_ratio = min(1.0, max(0.0, received / total))
                    stage_percent = (len(loaded_layers) + current_ratio) / pending_total * 100.0
                    size_detail = f"{received / (1024 * 1024):.1f}/{total / (1024 * 1024):.1f} MB"
                else:
                    stage_percent = None
                    size_detail = f"已接收 {received / (1024 * 1024):.1f} MB"
                _emit_acquisition_progress(
                    progress_callback,
                    tool_name,
                    title,
                    "下载 Overpass 分块",
                    2,
                    5,
                    stage_percent,
                    f"分块 {len(loaded_layers) + 1}/{pending_total} · {size_detail} · {endpoint}",
                )

            try:
                OSMDownloader.query_osm(
                    query,
                    chunk_osm,
                    timeout_seconds=180,
                    transfer_progress_callback=_chunk_transfer,
                    cancel_callback=cancel_callback,
                )
            except Exception as chunk_exc:
                error_type = getattr(chunk_exc, "error_type", "") or classify_overpass_error(str(chunk_exc))
                area = bbox_area(chunk)
                if split_large_bbox and error_type in {"overpass_timeout", "overpass_rate_limited"} and area > 0.0004 and len(queue) < 250:
                    smaller = split_bbox(chunk, max_area=max(area / 4.0, 0.0001))
                    queue = smaller + queue
                    chunk_records.append({"index": index, "bbox": chunk, "status": "resplit", "error_type": error_type})
                    continue
                raise
            chunk_layer_name = f"{layer_name}_chunk_{index:03d}" if len(chunks) > 1 else layer_name
            chunk_layer = OSMDownloader.load_osm_layer(
                chunk_osm,
                geometry_type,
                chunk_layer_name,
                add_to_project=False,
            )
            loaded_layers.append(chunk_layer)
            finished_total = max(1, len(loaded_layers) + len(queue))
            _emit_acquisition_progress(
                progress_callback,
                tool_name,
                title,
                "下载 Overpass 分块",
                2,
                5,
                len(loaded_layers) / finished_total * 100.0,
                f"已完成 {len(loaded_layers)}/{finished_total} 个分块。",
            )
            chunk_records.append(
                {
                    "index": index,
                    "bbox": chunk,
                    "feature_count": safe_feature_count(chunk_layer),
                }
            )

        _emit_acquisition_progress(
            progress_callback, tool_name, title, "合并并去重", 3, 5, 0,
            f"正在整理 {len(loaded_layers)} 个分块。",
        )
        if len(loaded_layers) == 1:
            source_layer = loaded_layers[0]
        else:
            import processing
            merge_result = processing.run(
                "native:mergevectorlayers",
                {
                    "LAYERS": loaded_layers,
                    "CRS": "EPSG:4326",
                    "OUTPUT": "TEMPORARY_OUTPUT",
                },
            )
            source_layer = merge_result["OUTPUT"]
            source_layer.setName(layer_name)

        source_layer = _deduplicate_vector_layer(source_layer, layer_name)
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "合并并去重", 3, 5, 100,
            "分块合并与 OSM 要素去重完成。",
        )
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "写入输出文件", 4, 5, 0,
            os.path.basename(output_file),
        )
        load_uri = _save_vector_layer(source_layer, output_file, layer_name)
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "写入输出文件", 4, 5, 100,
            os.path.basename(output_file),
        )
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "加载并验证", 5, 5, 0,
            f"正在加载图层 {layer_name}。",
        )
        from .qgis_tools.io_tools import load_vector_layer
        try:
            final_layer = load_vector_layer(load_uri, layer_name, duplicate_policy="replace")
        except (OSError, RuntimeError, ValueError, TypeError):
            from qgis.core import QgsVectorLayer, QgsProject
            final_layer = QgsVectorLayer(load_uri, layer_name, "ogr")
            if not final_layer.isValid():
                final_layer = QgsVectorLayer(output_file, layer_name, "ogr")
            if not final_layer.isValid():
                raise
            QgsProject.instance().addMapLayer(final_layer)
            final_layer.setName(layer_name)
        feature_count = safe_feature_count(final_layer)
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "加载并验证", 5, 5, 100,
            f"图层有效，要素数 {feature_count}。",
        )
        artifacts = [_artifact_entry(output_file, "osm_output", "Final OSM vector output.")]
        return ToolResult.success(
            f"Downloaded OSM features to '{output_file}' and loaded layer '{layer_name}'.",
            data={
                "output_file": output_file,
                "layer_name": layer_name,
                "geometry_type": geometry_type,
                "tags": tags,
                "bbox": bbox,
                "chunk_count": len(loaded_layers),
                "chunks": chunk_records,
                "feature_count": feature_count,
                "temporary_files_cleaned": True,
            },
            artifacts=artifacts,
        ).to_dict()
    except Exception as exc:
        from ..core.progress import DataAcquisitionCancelled
        from ..bridges.osm_bridge import classify_overpass_error

        if isinstance(exc, DataAcquisitionCancelled):
            return ToolResult.failure(
                str(exc),
                error_type="operation_cancelled",
                data={"output_file": output_file, "layer_name": layer_name},
            ).to_dict()
        error_type = getattr(exc, "error_type", None) or classify_overpass_error(str(exc))
        return ToolResult.failure(
            f"Failed to download OSM features: {exc}",
            error_type=error_type if error_type != "overpass_error" else "network_error",
            data={"output_file": output_file, "layer_name": layer_name},
        ).to_dict()
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except OSError:
                pass


