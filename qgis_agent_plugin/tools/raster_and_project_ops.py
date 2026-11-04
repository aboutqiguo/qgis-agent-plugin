# Project summary, cleanup, output validation, and raster inspection/index tool implementations.

def _summarize_layers(kwargs):
    from ..bridges.osm_bridge import safe_feature_count
    from ..core.tool_result import ToolResult
    from qgis.core import QgsProject, QgsMapLayerType, QgsWkbTypes

    include_sources = bool(kwargs.get("include_sources", False))
    max_layers = int(kwargs.get("max_layers", 50) or 50)
    layers = []
    for layer in list(QgsProject.instance().mapLayers().values())[:max_layers]:
        try:
            layer_type = "vector" if layer.type() == QgsMapLayerType.VectorLayer else "raster"
            item = {
                "name": layer.name(),
                "id": layer.id(),
                "type": layer_type,
                "crs": layer.crs().authid() if hasattr(layer, "crs") else "",
            }
            if layer_type == "vector":
                item["feature_count"] = safe_feature_count(layer)
                item["geometry"] = QgsWkbTypes.displayString(layer.wkbType())
                item["fields"] = [field.name() for field in layer.fields()][:20]
            if include_sources:
                item["source"] = layer.source()
            layers.append(item)
        except RuntimeError:
            continue
        except (AttributeError, TypeError, ValueError) as exc:
            layers.append({"name": getattr(layer, "name", lambda: "<unknown>")(), "error": str(exc)})
    return ToolResult.success(
        f"Found {len(layers)} layer(s).",
        data={"layer_count": len(layers), "layers": layers, "truncated": len(QgsProject.instance().mapLayers()) > max_layers},
    ).to_dict()


def _cleanup_qgis_project(kwargs):
    import os
    from pathlib import Path
    from ..core.tool_result import ToolResult
    from qgis.core import QgsProject

    project = QgsProject.instance()
    removed_layers = []
    if kwargs.get("remove_memory_output_layers", True):
        candidates = []
        for layer in project.mapLayers().values():
            try:
                name = layer.name()
                source = layer.source()
                if name.lower() in {"output", "temporary_output"} or source.lower().startswith("memory:"):
                    candidates.append((layer.id(), name, source))
            except RuntimeError:
                continue
        for layer_id, name, source in candidates:
            try:
                project.removeMapLayer(layer_id)
                removed_layers.append({"name": name, "source": source})
            except (AttributeError, RuntimeError, TypeError):
                pass

    removed_files = []
    chunk_dir = kwargs.get("cleanup_chunk_files_dir") or ""
    if chunk_dir and os.path.isdir(chunk_dir):
        for path in Path(chunk_dir).glob("_chunk_*.osm"):
            try:
                size = path.stat().st_size
                path.unlink()
                removed_files.append({"path": str(path), "size": size})
            except OSError:
                pass

    wal_dir = kwargs.get("cleanup_wal_files_dir") or ""
    if wal_dir and os.path.isdir(wal_dir):
        for pattern in ("*.gpkg-wal", "*.gpkg-shm"):
            for path in Path(wal_dir).rglob(pattern):
                try:
                    size = path.stat().st_size
                    if size == 0:
                        path.unlink()
                        removed_files.append({"path": str(path), "size": size})
                except OSError:
                    pass

    return ToolResult.success(
        f"Cleanup complete: removed {len(removed_layers)} layer(s), {len(removed_files)} file(s).",
        data={"removed_layers": removed_layers, "removed_files": removed_files},
    ).to_dict()



def _validate_project_outputs(kwargs):
    import os
    from ..core.tool_result import ToolResult
    from qgis.core import QgsProject

    expected_layers = list(kwargs.get("expected_layers") or [])
    expected_files = list(kwargs.get("expected_files") or [])
    include_layer_details = kwargs.get("include_layer_details", True)
    current_layers = {layer.name(): layer for layer in QgsProject.instance().mapLayers().values()}
    missing_layers = [name for name in expected_layers if name not in current_layers]
    file_results = []
    missing_files = []
    for path in expected_files:
        exists = os.path.exists(path)
        item = {"path": path, "exists": exists}
        if exists:
            item["size"] = os.path.getsize(path)
        else:
            missing_files.append(path)
        file_results.append(item)
    data = {
        "expected_layers": expected_layers,
        "missing_layers": missing_layers,
        "expected_files": file_results,
        "missing_files": missing_files,
    }
    if include_layer_details:
        data["layers"] = _summarize_layers({"include_sources": False, "max_layers": 100}).get("data", {}).get("layers", [])
    ok = not missing_layers and not missing_files
    if ok:
        return ToolResult.success("All expected layers and files are present.", data=data).to_dict()
    return ToolResult.failure(
        "Some expected layers or files are missing.",
        error_type="qgis_layer_error" if missing_layers else "file_path_error",
        data=data,
    ).to_dict()


def _inspect_raster_file_tool(kwargs):
    from ..core.raster_validation import inspect_raster_file

    return inspect_raster_file(
        kwargs.get("file_path", ""),
        force_read=kwargs.get("force_read", True),
    )


def _validate_raster_has_data_tool(kwargs):
    from ..core.raster_validation import validate_raster_has_data

    return validate_raster_has_data(
        kwargs.get("file_path", ""),
        bands=kwargs.get("bands"),
        min_valid_percent=float(kwargs.get("min_valid_percent", 0.01) or 0.01),
        force_read=kwargs.get("force_read", True),
    )


def _compute_raster_zonal_stats_tool(kwargs):
    from ..core.raster_validation import compute_raster_zonal_stats

    return compute_raster_zonal_stats(
        source_layer_or_path=kwargs.get("source_layer_or_path", ""),
        mask_layer_or_path=kwargs.get("mask_layer_or_path", ""),
        mask_valid_value=float(kwargs.get("mask_valid_value", 1.0) if kwargs.get("mask_valid_value") is not None else 1.0),
        rank_band_pairs=bool(kwargs.get("rank_band_pairs", True)),
    )


def _compute_raster_index_tool(kwargs):
    from ..core.raster_validation import compute_raster_index

    return compute_raster_index(
        source_layer_or_path=kwargs.get("source_layer_or_path", ""),
        output_path=kwargs.get("output_path", ""),
        band_a=int(kwargs.get("band_a")),
        band_b=int(kwargs.get("band_b")),
        index_name=str(kwargs.get("index_name") or "INDEX"),
        mask_layer_or_path=str(kwargs.get("mask_layer_or_path") or ""),
        mask_valid_value=float(kwargs.get("mask_valid_value", 1.0) if kwargs.get("mask_valid_value") is not None else 1.0),
        clip_range=bool(kwargs.get("clip_range", True)),
        load_layer=bool(kwargs.get("load_layer", True)),
        layer_name=str(kwargs.get("layer_name") or ""),
        overwrite=bool(kwargs.get("overwrite", True)),
    )


