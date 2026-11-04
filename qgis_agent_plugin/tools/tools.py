from qgis.core import QgsProject, QgsMapLayerType, QgsVectorLayer, QgsRasterLayer, QgsExpression, Qgis
try:
    import processing
except ImportError:
    processing = None

from .schemas import ATOMIC_TOOLS_SCHEMA
from .raster_and_project_ops import (
    _cleanup_qgis_project,
    _compute_raster_index_tool,
    _compute_raster_zonal_stats_tool,
    _inspect_raster_file_tool,
    _summarize_layers,
    _validate_project_outputs,
    _validate_raster_has_data_tool,
)

from .osm_workflows import (
    _bbox_from_layer,
    _deduplicate_vector_layer,
    _ensure_output_available,
    _execute_osm_feature_download,
    _remove_existing_output,
    _save_vector_layer,
    _vector_driver_for_path,
)
from .layer_and_processing_ops import (
    LAYER_AND_PROCESSING_TOOLS,
    execute_layer_or_processing_tool,
)
def execute_atomic_tool_structured(
    iface,
    tool_name,
    kwargs,
    progress_callback=None,
    cancel_callback=None,
):
    result = execute_atomic_tool(
        iface,
        tool_name,
        kwargs,
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )
    try:
        from ..core.tool_result import normalize_tool_output
        return normalize_tool_output(tool_name, result)
    except (ImportError, TypeError, ValueError, KeyError, AttributeError):
        return result


def _emit_acquisition_progress(
    callback,
    tool_name,
    title,
    stage,
    stage_index,
    stage_count,
    stage_percent=None,
    detail="",
    state="running",
):
    from ..core.progress import emit_progress

    return emit_progress(
        callback,
        tool_name=tool_name,
        title=title,
        stage=stage,
        stage_index=stage_index,
        stage_count=stage_count,
        stage_percent=stage_percent,
        detail=detail,
        state=state,
    )


def _artifact_entry(path: str, artifact_type: str, description: str):
    return {"type": artifact_type, "path": path, "description": description}


def _find_project_layer(layer_name: str):
    for layer in QgsProject.instance().mapLayers().values():
        if layer.name() == layer_name or layer.id() == layer_name:
            return layer
    return None


def _remove_qgis_layers_and_data(kwargs):
    """Remove explicit project layers and, only when requested, their local datasets."""
    import os
    from pathlib import Path

    from ..core.tool_result import ToolResult
    from qgis.core import QgsApplication, QgsProject

    scope = str(kwargs.get("scope") or "").strip()
    requested_names = {str(name).strip() for name in (kwargs.get("layer_names") or []) if str(name).strip()}
    delete_sources = bool(kwargs.get("delete_source_files"))
    delete_sidecars = kwargs.get("delete_sidecars", True) is not False
    save_project = kwargs.get("save_project", True) is not False
    project = QgsProject.instance()
    all_layers = list(project.mapLayers().values())

    if scope not in {"all_layers", "named_layers"}:
        return ToolResult.failure(
            "scope must be all_layers or named_layers.",
            error_type="argument_error",
            data={"scope": scope},
        ).to_dict()
    if scope == "named_layers" and not requested_names:
        return ToolResult.failure(
            "layer_names is required when scope is named_layers.",
            error_type="argument_error",
            data={"scope": scope},
        ).to_dict()

    selected_layers = all_layers if scope == "all_layers" else [
        layer for layer in all_layers
        if layer.id() in requested_names or layer.name() in requested_names
    ]
    selected_ids = {layer.id() for layer in selected_layers}
    unmatched_names = sorted(requested_names - {
        value for layer in selected_layers for value in (layer.id(), layer.name())
    })
    if unmatched_names:
        return ToolResult.failure(
            "No deletion was performed because one or more requested layer names/IDs are not present.",
            error_type="qgis_layer_error",
            data={
                "unmatched_layer_names": unmatched_names,
                "available_layers": [layer.name() for layer in all_layers],
            },
            suggestions=["Use exact layer names or IDs returned by summarize_layers before retrying."],
        ).to_dict()

    def source_path(layer):
        try:
            source = str(layer.source() or "").strip()
        except (AttributeError, RuntimeError, TypeError):
            return "", "unreadable layer source"
        if not source or source.lower().startswith("memory:"):
            return "", "memory layer"
        candidate = source.split("|", 1)[0].strip()
        if (
            "://" in candidate
            or candidate.lower().startswith(("pg:", "wfs:", "mssql:", "oracle:", "oci:", "/vsi"))
        ):
            return "", "remote or virtual source"
        if not os.path.isfile(candidate):
            return "", "source is not a local file"
        return os.path.abspath(os.path.normpath(candidate)), ""

    all_source_users = {}
    for layer in all_layers:
        path, _reason = source_path(layer)
        if path:
            all_source_users.setdefault(path, set()).add(layer.id())

    source_candidates = {}
    skipped_sources = []
    for layer in selected_layers:
        path, reason = source_path(layer)
        if not path:
            if reason:
                skipped_sources.append({"layer": layer.name(), "reason": reason})
            continue
        users = all_source_users.get(path, set())
        if scope != "all_layers" and not users.issubset(selected_ids):
            skipped_sources.append({
                "layer": layer.name(),
                "path": path,
                "reason": "source is also used by a layer outside the requested scope",
            })
            continue
        source_candidates[path] = {
            "path": path,
            "layers": sorted(
                layer.name() for layer in selected_layers
                if source_path(layer)[0] == path
            ),
        }

    removed_layers = []
    for layer in selected_layers:
        try:
            layer_name = layer.name()
            layer_id = layer.id()
        except (AttributeError, RuntimeError):
            continue
        try:
            project.removeMapLayer(layer_id)
            removed_layers.append({"name": layer_name, "id": layer_id})
        except (AttributeError, RuntimeError, ValueError, TypeError) as exc:
            skipped_sources.append({"layer": layer_name, "reason": f"could not remove layer: {exc}"})

    try:
        QgsApplication.processEvents()
    except (AttributeError, RuntimeError):
        pass

    removed_files = []
    file_failures = []
    if delete_sources:
        sidecar_suffixes = {
            ".shp": (".dbf", ".shx", ".prj", ".cpg", ".qix", ".sbn", ".sbx"),
            ".tif": (".tfw", ".ovr"),
            ".tiff": (".tfw", ".ovr"),
            ".img": (".aux", ".ovr"),
            ".gpkg": (".gpkg-wal", ".gpkg-shm"),
        }
        for source in source_candidates.values():
            path = Path(source["path"])
            targets = [path]
            if delete_sidecars:
                for suffix in sidecar_suffixes.get(path.suffix.lower(), ()):
                    if suffix.startswith(".gpkg-"):
                        targets.append(Path(str(path) + suffix[len(".gpkg"):]))
                    else:
                        targets.append(path.with_suffix(suffix))
                for suffix in (".aux.xml",):
                    targets.append(Path(str(path) + suffix))
            for target in targets:
                if not target.exists():
                    continue
                try:
                    size = target.stat().st_size
                    target.unlink()
                    removed_files.append({"path": str(target), "size": size})
                except OSError as exc:
                    file_failures.append({"path": str(target), "error": str(exc)})

    project_saved = None
    if save_project and project.fileName():
        try:
            project_saved = bool(project.write())
            if not project_saved:
                file_failures.append({"path": project.fileName(), "error": "QGIS project write returned false"})
        except (OSError, RuntimeError, AttributeError, TypeError) as exc:
            file_failures.append({"path": project.fileName(), "error": f"could not save QGIS project: {exc}"})

    data = {
        "scope": scope,
        "delete_source_files": delete_sources,
        "removed_layers": removed_layers,
        "removed_files": removed_files,
        "skipped_sources": skipped_sources,
        "unmatched_layer_names": unmatched_names,
        "project_saved": project_saved,
        "remaining_layer_count": len(project.mapLayers()),
        "file_failures": file_failures,
    }
    if file_failures:
        return ToolResult.failure(
            "Layer removal completed partially, but one or more files or the project could not be removed/saved.",
            error_type="partial_cleanup_error",
            data=data,
            suggestions=["Close file locks and retry only the failed paths; do not assume every source file was deleted."],
        ).to_dict()
    return ToolResult.success(
        f"Removed {len(removed_layers)} layer(s) and {len(removed_files)} local file(s).",
        data=data,
    ).to_dict()


def _boundary_layer_to_ee_geometry(layer, simplify_tolerance=0.0):
    import json
    import ee
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject

    geometries = []
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        if geometry and not geometry.isEmpty():
            geometries.append(QgsGeometry(geometry))
    if not geometries:
        raise ValueError(f"Boundary layer has no geometry: {layer.name()}")

    geometry = QgsGeometry.unaryUnion(geometries) if len(geometries) > 1 else geometries[0]
    if layer.crs().isValid() and layer.crs().authid() != "EPSG:4326":
        transform = QgsCoordinateTransform(layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        geometry.transform(transform)

    tolerance = float(simplify_tolerance or 0.0)
    if tolerance > 0:
        simplified = geometry.simplify(tolerance)
        if simplified and not simplified.isEmpty():
            geometry = simplified

    geojson = json.loads(geometry.asJson())
    geom_type = geojson.get("type")
    coordinates = geojson.get("coordinates")
    if geom_type == "Polygon":
        return ee.Geometry.Polygon(coordinates)
    if geom_type == "MultiPolygon":
        return ee.Geometry.MultiPolygon(coordinates)
    return ee.Geometry(geojson)


def _run_gee_dem_download_workflow(iface, kwargs, progress_callback=None, cancel_callback=None):
    import os
    import ee
    from ..bridges.gee_bridge import GEEDownloader, GEEManualDownloadRequired, init_gee
    from ..core.raster_validation import validate_raster_has_data
    from ..core.tool_result import ToolResult
    from qgis.core import QgsMapLayerType

    required = ["boundary_layer_name", "output_dir", "output_name", "dataset_id", "scale", "crs", "load_layer"]
    missing = [name for name in required if kwargs.get(name) in (None, "", [])]
    if missing or not kwargs.get("user_confirmed_parameters"):
        return ToolResult.failure(
            "DEM download parameters are incomplete or not user-confirmed.",
            error_type="missing_user_parameters",
            data={
                "missing": missing,
                "user_confirmed_parameters": bool(kwargs.get("user_confirmed_parameters")),
                "required_parameters": required + ["user_confirmed_parameters"],
            },
            suggestions=[
                "Call ask_human before downloading DEM data.",
                "Ask the user to confirm DEM dataset, scale/resolution, output CRS, output name, and whether to load the layer.",
                "Supported datasets are COPERNICUS/DEM/GLO30, NASA/NASADEM_HGT/001, and USGS/SRTMGL1_003.",
            ],
        ).to_dict()

    boundary_name = kwargs.get("boundary_layer_name")
    output_dir = kwargs.get("output_dir")
    dataset_id = str(kwargs.get("dataset_id") or "").strip()
    scale = float(kwargs.get("scale") or 30)
    crs = str(kwargs.get("crs") or "EPSG:4326").strip()
    output_name = kwargs.get("output_name") or "dem.tif"
    output_stem = os.path.splitext(os.path.basename(output_name))[0] or "dem"
    min_valid_percent = float(kwargs.get("min_valid_percent", 0.01) or 0.01)
    simplify_tolerance = float(kwargs.get("simplify_tolerance", 0.0) or 0.0)
    progress_context = {
        "tool_name": "run_gee_dem_download_workflow",
        "title": "GEE DEM 数据获取",
        "stage_count": 6,
    }

    dem_catalog = {
        "COPERNICUS/DEM/GLO30": {
            "band": "DEM",
            "kind": "image_collection",
            "description": "Copernicus DEM GLO-30",
        },
        "NASA/NASADEM_HGT/001": {
            "band": "elevation",
            "kind": "image",
            "description": "NASA NASADEM HGT",
        },
        "USGS/SRTMGL1_003": {
            "band": "elevation",
            "kind": "image",
            "description": "USGS SRTMGL1 30m",
        },
    }
    spec = dem_catalog.get(dataset_id)
    if not spec:
        return ToolResult.failure(
            f"Unsupported DEM dataset_id: {dataset_id}",
            error_type="argument_error",
            data={"dataset_id": dataset_id, "supported_dataset_ids": sorted(dem_catalog.keys())},
            suggestions=["Ask the user to choose one supported DEM dataset or add a tested dataset mapping before retrying."],
        ).to_dict()

    boundary_layer = _find_project_layer(boundary_name)
    if boundary_layer is None:
        return ToolResult.failure(
            f"Boundary layer not found: {boundary_name}",
            error_type="qgis_layer_error",
            data={"boundary_layer_name": boundary_name},
            suggestions=["Call summarize_layers or search_project_layers and retry with the exact layer name."],
        ).to_dict()
    if boundary_layer.type() != QgsMapLayerType.VectorLayer:
        return ToolResult.failure(
            f"Boundary layer must be a vector layer: {boundary_layer.name()}",
            error_type="qgis_layer_error",
            data={"layer": boundary_layer.name()},
        ).to_dict()

    try:
        from ..core.progress import raise_if_cancelled
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "认证 Earth Engine", 1, 6, None, "正在初始化 Earth Engine 会话。",
        )
        raise_if_cancelled(cancel_callback, "GEE DEM acquisition was cancelled by the user.")
        init_gee()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "认证 Earth Engine", 1, 6, 100, "Earth Engine 会话可用。",
        )
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "构建 DEM 云端影像", 2, 6, None, f"数据集 {dataset_id}",
        )
        ee_geometry = _boundary_layer_to_ee_geometry(boundary_layer, simplify_tolerance=simplify_tolerance)
        if spec["kind"] == "image_collection":
            image = ee.ImageCollection(dataset_id).mosaic().select(spec["band"])
        else:
            image = ee.Image(dataset_id).select(spec["band"])

        export_image = image.clip(ee_geometry).toFloat()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "构建 DEM 云端影像", 2, 6, 100, "裁剪影像表达式已构建。",
        )
        os.makedirs(output_dir, exist_ok=True)
        output_path = GEEDownloader.download_ee_object(
            export_image,
            output_stem,
            output_dir,
            scale=scale,
            region=ee_geometry,
            crs=crs,
            exact_geom=ee_geometry,
            no_data=-9999,
            min_coverage_ratio=max(0.0, min(1.0, min_valid_percent / 100.0)),
            progress_callback=progress_callback,
            progress_context=progress_context,
            cancel_callback=cancel_callback,
        )
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "验证本地栅格", 5, 6, None, os.path.basename(output_path),
        )
        validation = validate_raster_has_data(
            output_path,
            bands=[1],
            min_valid_percent=min_valid_percent,
            force_read=True,
        )
        if not validation.get("ok"):
            return ToolResult.failure(
                "Downloaded DEM raster failed validation.",
                error_type=validation.get("error_type", "raster_no_data_error"),
                data={"output_path": output_path, "validation": validation},
                suggestions=validation.get("suggestions", []),
            ).to_dict()

        layer_id = ""
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "加载到 QGIS", 6, 6, 0,
            "正在完成最终加载。" if kwargs.get("load_layer", True) else "用户选择不加载图层。",
        )
        if kwargs.get("load_layer", True):
            from .qgis_tools import load_raster_layer
            layer_name = os.path.splitext(os.path.basename(output_path))[0]
            layer = load_raster_layer(output_path, layer_name, duplicate_policy="replace")
            layer_id = layer.id()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "加载到 QGIS", 6, 6, 100, f"输出已验证{'并加载' if layer_id else ''}。",
        )

        return ToolResult.success(
            "DEM download workflow completed and output raster was validated.",
            data={
                "workflow_complete": True,
                "output_path": output_path,
                "layer_id": layer_id,
                "dataset_id": dataset_id,
                "dataset_description": spec["description"],
                "band": spec["band"],
                "scale": scale,
                "crs": crs,
                "boundary_layer": boundary_layer.name(),
                "simplify_tolerance": simplify_tolerance,
                "validation": validation,
            },
            artifacts=[_artifact_entry(output_path, "raster", "Validated DEM GeoTIFF.")],
        ).to_dict()
    except GEEManualDownloadRequired as exc:
        return ToolResult.failure(
            str(exc),
            error_type="manual_download_required",
            data=exc.to_dict(),
            suggestions=["Complete the listed Google Drive manual download steps, then validate and load the file."],
        ).to_dict()
    except Exception as exc:
        from ..core.progress import DataAcquisitionCancelled
        if isinstance(exc, DataAcquisitionCancelled):
            return ToolResult.failure(
                str(exc),
                error_type="operation_cancelled",
                data={
                    "boundary_layer_name": boundary_name,
                    "output_dir": output_dir,
                    "dataset_id": dataset_id,
                    "cloud_export_may_continue": "task_id=" in str(exc),
                },
                suggestions=["Check Earth Engine Tasks before retrying; a submitted cloud export may still be running."],
            ).to_dict()
        return ToolResult.failure(
            f"DEM download workflow failed: {exc}",
            error_type="gee_download_error",
            data={
                "boundary_layer_name": boundary_name,
                "output_dir": output_dir,
                "dataset_id": dataset_id,
                "scale": scale,
                "crs": crs,
            },
            suggestions=[
                "Do not retry with ee.Image('COPERNICUS/DEM/GLO30'); Copernicus GLO-30 must be loaded as an ImageCollection.",
                "If the boundary is complex, increase simplify_tolerance or export by bbox, then clip locally.",
                "Run inspect_raster_file on any partial output before reusing it.",
            ],
        ).to_dict()


def _run_gee_sentinel2_download_workflow(iface, kwargs, progress_callback=None, cancel_callback=None):
    import os
    import ee
    from ..bridges.gee_bridge import GEEDownloader, GEEManualDownloadRequired, init_gee
    from ..core.raster_validation import validate_raster_has_data
    from ..core.tool_result import ToolResult
    from qgis.core import QgsMapLayerType, QgsProject, QgsRasterLayer

    boundary_name = kwargs.get("boundary_layer_name")
    output_dir = kwargs.get("output_dir")
    required = [
        "boundary_layer_name",
        "output_dir",
        "collection_id",
        "start_date",
        "end_date",
        "bands",
        "cloud_pct",
        "scale",
        "crs",
        "processing_method",
        "output_name",
        "load_layer",
    ]
    missing = [name for name in required if kwargs.get(name) in (None, "", [])]
    if missing or not kwargs.get("user_confirmed_parameters"):
        return ToolResult.failure(
            "Sentinel-2 download parameters are incomplete or not user-confirmed.",
            error_type="missing_user_parameters",
            data={
                "missing": missing,
                "user_confirmed_parameters": bool(kwargs.get("user_confirmed_parameters")),
                "required_parameters": required + ["user_confirmed_parameters"],
            },
            suggestions=[
                "Call ask_human before downloading Sentinel-2 data.",
                "Ask the user to confirm: collection_id, date range, bands, cloud_pct, scale, processing_method, output name.",
                "Do not assume NDVI, RGB, date range, cloud masking, or resolution unless the user explicitly asks for it.",
            ],
        ).to_dict()

    boundary_layer = _find_project_layer(boundary_name)
    if boundary_layer is None:
        return ToolResult.failure(
            f"Boundary layer not found: {boundary_name}",
            error_type="qgis_layer_error",
            data={"boundary_layer_name": boundary_name},
            suggestions=["Call summarize_layers or search_project_layers and retry with the exact layer name."],
        ).to_dict()
    if boundary_layer.type() != QgsMapLayerType.VectorLayer:
        return ToolResult.failure(
            f"Boundary layer must be a vector layer: {boundary_layer.name()}",
            error_type="qgis_layer_error",
            data={"layer": boundary_layer.name()},
        ).to_dict()

    start_date = kwargs.get("start_date")
    end_date = kwargs.get("end_date")
    bands = [str(b).strip() for b in (kwargs.get("bands") or []) if str(b).strip()]
    cloud_pct = float(kwargs.get("cloud_pct"))
    scale = float(kwargs.get("scale"))
    collection_id = kwargs.get("collection_id")
    processing_method = kwargs.get("processing_method")
    min_valid_percent = float(kwargs.get("min_valid_percent", 0.01) or 0.01)
    output_name = kwargs.get("output_name")
    output_stem = os.path.splitext(os.path.basename(output_name))[0] or "sentinel2_export"
    output_crs = str(kwargs.get("crs") or "").strip()
    progress_context = {
        "tool_name": "run_gee_sentinel2_download_workflow",
        "title": "GEE Sentinel-2 数据获取",
        "stage_count": 6,
    }

    supported_collections = {
        "COPERNICUS/S2_SR_HARMONIZED",
        "COPERNICUS/S2_HARMONIZED",
    }
    if collection_id not in supported_collections:
        return ToolResult.failure(
            f"Unsupported Sentinel-2 collection_id: {collection_id}",
            error_type="argument_error",
            data={"collection_id": collection_id, "supported_collection_ids": sorted(supported_collections)},
            suggestions=["Ask the user to choose one of the supported Sentinel-2 Harmonized collections."],
        ).to_dict()

    if not bands:
        return ToolResult.failure(
            "No Sentinel-2 bands were specified.",
            error_type="missing_user_parameters",
            data={"bands": bands},
            suggestions=["Call ask_human and ask which Sentinel-2 bands should be downloaded, such as B2/B3/B4/B8 or RGB B4/B3/B2."],
        ).to_dict()

    try:
        from ..core.progress import raise_if_cancelled
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "认证 Earth Engine", 1, 6, None, "正在初始化 Earth Engine 会话。",
        )
        raise_if_cancelled(cancel_callback, "GEE Sentinel-2 acquisition was cancelled by the user.")
        init_gee()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "认证 Earth Engine", 1, 6, 100, "Earth Engine 会话可用。",
        )
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "筛选影像并构建合成", 2, 6, None,
            f"{start_date} 至 {end_date} · 云量 < {cloud_pct}% · {','.join(bands)}",
        )
        ee_geometry = _boundary_layer_to_ee_geometry(boundary_layer)
        collection = (
            ee.ImageCollection(collection_id)
            .filterDate(start_date, end_date)
            .filterBounds(ee_geometry)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
        )
        image_count = int(collection.size().getInfo())
        if image_count <= 0:
            return ToolResult.failure(
                "No Sentinel-2 scenes matched the boundary/date/cloud filters.",
                error_type="gee_no_data_error",
                data={
                    "collection_id": collection_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "cloud_pct": cloud_pct,
                    "boundary_layer": boundary_layer.name(),
                },
                suggestions=["Relax cloud_pct or expand the date range, then retry."],
            ).to_dict()

        available_bands = [str(value) for value in collection.first().bandNames().getInfo()]
        missing_bands = [band for band in bands if band not in available_bands]
        if missing_bands:
            return ToolResult.failure(
                "Requested Sentinel-2 bands do not exist in the selected collection.",
                error_type="argument_error",
                data={"missing_bands": missing_bands, "available_bands": available_bands, "collection_id": collection_id},
                suggestions=["Ask the user to choose bands available in the confirmed Sentinel-2 collection."],
            ).to_dict()

        if processing_method == "cloud_masked_median":
            if "SCL" in available_bands:
                def _mask_s2_clouds(image):
                    scl = image.select("SCL")
                    mask = (
                        scl.neq(0)
                        .And(scl.neq(1))
                        .And(scl.neq(3))
                        .And(scl.neq(8))
                        .And(scl.neq(9))
                        .And(scl.neq(10))
                        .And(scl.neq(11))
                    )
                    return image.updateMask(mask)
            elif "QA60" in available_bands:
                def _mask_s2_clouds(image):
                    qa = image.select("QA60")
                    cloud_bit = 1 << 10
                    cirrus_bit = 1 << 11
                    return image.updateMask(qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(cirrus_bit).eq(0)))
            else:
                return ToolResult.failure(
                    "The selected Sentinel-2 collection has neither SCL nor QA60 for the requested cloud mask.",
                    error_type="argument_error",
                    data={"collection_id": collection_id, "available_bands": available_bands},
                    suggestions=["Choose median without cloud masking or select a collection with SCL/QA60."],
                ).to_dict()
            image = collection.map(_mask_s2_clouds).median()
        elif processing_method == "median":
            image = collection.median()
        elif processing_method == "mosaic":
            image = collection.mosaic()
        elif processing_method == "least_cloudy":
            image = collection.sort("CLOUDY_PIXEL_PERCENTAGE").first()
        else:
            return ToolResult.failure(
                f"Unsupported Sentinel-2 processing_method: {processing_method}",
                error_type="argument_error",
                data={"processing_method": processing_method},
            ).to_dict()

        export_image = image.select(bands).clip(ee_geometry).toFloat()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "筛选影像并构建合成", 2, 6, 100,
            f"匹配 {image_count} 景影像，处理方法 {processing_method}。",
        )
        os.makedirs(output_dir, exist_ok=True)
        output_path = GEEDownloader.download_ee_object(
            export_image,
            output_stem,
            output_dir,
            scale=scale,
            region=ee_geometry,
            crs=output_crs,
            exact_geom=ee_geometry,
            no_data=-9999,
            min_coverage_ratio=max(0.0, min(1.0, min_valid_percent / 100.0)),
            progress_callback=progress_callback,
            progress_context=progress_context,
            cancel_callback=cancel_callback,
        )
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "验证本地栅格", 5, 6, None, os.path.basename(output_path),
        )
        validation = validate_raster_has_data(
            output_path,
            bands=list(range(1, len(bands) + 1)),
            min_valid_percent=min_valid_percent,
            force_read=True,
        )
        if not validation.get("ok"):
            return ToolResult.failure(
                "Downloaded Sentinel-2 raster failed validation.",
                error_type=validation.get("error_type", "raster_no_data_error"),
                data={"output_path": output_path, "validation": validation},
                suggestions=validation.get("suggestions", []),
            ).to_dict()

        layer_id = ""
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "加载到 QGIS", 6, 6, 0,
            "正在完成最终加载。" if kwargs.get("load_layer", True) else "用户选择不加载图层。",
        )
        if kwargs.get("load_layer", True):
            from .qgis_tools import load_raster_layer
            layer_name = os.path.splitext(os.path.basename(output_path))[0]
            layer = load_raster_layer(output_path, layer_name, duplicate_policy="replace")
            layer_id = layer.id()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "加载到 QGIS", 6, 6, 100, f"输出已验证{'并加载' if layer_id else ''}。",
        )

        return ToolResult.success(
            "Sentinel-2 download workflow completed and output raster was validated.",
            data={
                "workflow_complete": True,
                "output_path": output_path,
                "layer_id": layer_id,
                "scene_count": image_count,
                "collection_id": collection_id,
                "start_date": start_date,
                "end_date": end_date,
                "bands": bands,
                "cloud_pct": cloud_pct,
                "scale": scale,
                "crs": output_crs,
                "processing_method": processing_method,
                "validation": validation,
            },
            artifacts=[_artifact_entry(output_path, "raster", "Validated Sentinel-2 GeoTIFF.")],
        ).to_dict()
    except GEEManualDownloadRequired as exc:
        return ToolResult.failure(
            str(exc),
            error_type="manual_download_required",
            data=exc.to_dict(),
            suggestions=["Complete the listed Google Drive manual download steps, then validate and load the file."],
        ).to_dict()
    except Exception as exc:
        from ..core.progress import DataAcquisitionCancelled
        if isinstance(exc, DataAcquisitionCancelled):
            return ToolResult.failure(
                str(exc),
                error_type="operation_cancelled",
                data={
                    "boundary_layer_name": boundary_name,
                    "output_dir": output_dir,
                    "collection_id": collection_id,
                    "cloud_export_may_continue": "task_id=" in str(exc),
                },
                suggestions=["Check Earth Engine Tasks before retrying; a submitted cloud export may still be running."],
            ).to_dict()
        return ToolResult.failure(
            f"Sentinel-2 download workflow failed: {exc}",
            error_type="gee_download_error",
            data={
                "boundary_layer_name": boundary_name,
                "output_dir": output_dir,
                "collection_id": collection_id,
                "start_date": start_date,
                "end_date": end_date,
                "bands": bands,
                "processing_method": processing_method,
            },
            suggestions=[
                "Run inspect_raster_file on any partial output before reusing it.",
                "Retry only after confirming the user's Sentinel-2 parameters and GEE authentication.",
            ],
        ).to_dict()


def _run_qgis_workflow_batch(iface, kwargs, progress_callback=None, cancel_callback=None):
    from ..core.tool_result import ToolResult
    from ..core.tool_registry import BATCHABLE_TOOLS
    from ..core.validators import validate_tool_call

    allowed = BATCHABLE_TOOLS
    steps = list(kwargs.get("steps") or [])
    stop_on_error = kwargs.get("stop_on_error", True)
    results = []
    for index, step in enumerate(steps, start=1):
        action = (step or {}).get("action", "")
        arguments = (step or {}).get("arguments") or {}
        if action not in allowed:
            result = ToolResult.failure(
                f"Batch step {index} action is not allowed: {action}",
                error_type="argument_error",
                data={"index": index, "action": action},
            ).to_dict()
        else:
            validation = validate_tool_call(action, arguments)
            if not validation.ok:
                result = ToolResult.failure(
                    f"Batch step {index} failed validation before execution.",
                    error_type="argument_error",
                    data={"index": index, "action": action, "validation": validation.to_dict()},
                ).to_dict()
            else:
                result = execute_atomic_tool(
                    iface,
                    action,
                    arguments,
                    progress_callback=progress_callback,
                    cancel_callback=cancel_callback,
                )
        result_ok = bool(result.get("ok")) if isinstance(result, dict) else "error" not in str(result).lower()
        results.append({"index": index, "action": action, "ok": result_ok, "result": result})
        if stop_on_error and not result_ok:
            break
    ok = all(item["ok"] for item in results)
    message = f"Batch workflow finished: {sum(1 for item in results if item['ok'])}/{len(results)} step(s) passed."
    if ok:
        return ToolResult.success(message, data={"steps": results}).to_dict()
    return ToolResult.failure(message, error_type="unknown_error", data={"steps": results}).to_dict()


def execute_atomic_tool(iface, tool_name, kwargs, progress_callback=None, cancel_callback=None):
    try:
        if tool_name == "summarize_layers":
            return _summarize_layers(kwargs)

        if tool_name == "cleanup_qgis_project":
            return _cleanup_qgis_project(kwargs)

        if tool_name == "remove_qgis_layers_and_data":
            return _remove_qgis_layers_and_data(kwargs)

        if tool_name == "validate_project_outputs":
            return _validate_project_outputs(kwargs)

        if tool_name == "inspect_raster_file":
            return _inspect_raster_file_tool(kwargs)

        if tool_name == "validate_raster_has_data":
            return _validate_raster_has_data_tool(kwargs)

        if tool_name == "compute_raster_zonal_stats":
            return _compute_raster_zonal_stats_tool(kwargs)

        if tool_name == "compute_raster_index":
            return _compute_raster_index_tool(kwargs)

        if tool_name == "create_or_update_user_tool":
            from ..core.user_tool_extensions import create_or_update_user_tool

            return create_or_update_user_tool(
                tool_name=kwargs.get("tool_name", ""),
                description=kwargs.get("description", ""),
                parameters_schema=kwargs.get("parameters_schema", {}),
                source_code=kwargs.get("source_code", ""),
                domains=kwargs.get("domains") or ["general"],
            )

        if tool_name == "list_user_tool_extensions":
            from ..core.user_tool_extensions import list_user_tools

            rows = list_user_tools(include_candidates=kwargs.get("include_candidates", True))
            return {
                "ok": True,
                "message": f"Found {len(rows)} user tool extension(s).",
                "data": {"tools": rows},
                "artifacts": [],
                "warnings": [],
            }

        if tool_name == "run_user_tool_extension":
            from ..core.user_tool_extensions import execute_user_tool, get_user_tool
            from ..core.validators import validate_required, validate_schema_values

            extension_name = kwargs.get("tool_name", "")
            definition = get_user_tool(extension_name, include_candidates=True)
            if definition is None:
                return {
                    "ok": False,
                    "message": f"User tool '{extension_name}' is not available.",
                    "data": {},
                    "artifacts": [],
                    "warnings": [],
                    "error_type": "not_found",
                    "suggestions": ["Create the candidate first or list available user tools."],
                }
            arguments = kwargs.get("arguments") or {}
            required_report = validate_required(
                arguments,
                definition.get("parameters_schema", {}).get("required", []),
            )
            argument_report = validate_schema_values(arguments, definition.get("parameters_schema", {}))
            if not required_report.ok or not argument_report.ok:
                issues = required_report.to_dict().get("issues", []) + argument_report.to_dict().get("issues", [])
                return {
                    "ok": False,
                    "message": "User tool arguments do not match its registered parameter schema.",
                    "data": {"validation_issues": issues},
                    "artifacts": [],
                    "warnings": [],
                    "error_type": "argument_error",
                    "suggestions": ["Correct the arguments and retry the candidate test."],
                }
            return execute_user_tool(extension_name, iface, arguments)

        if tool_name == "register_user_tool_extension":
            from ..core.user_tool_extensions import register_user_tool

            return register_user_tool(
                tool_name=kwargs.get("tool_name", ""),
                verification_summary=kwargs.get("verification_summary", ""),
            )

        if tool_name == "run_gee_sentinel2_download_workflow":
            return _run_gee_sentinel2_download_workflow(
                iface,
                kwargs,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        if tool_name == "run_gee_dem_download_workflow":
            return _run_gee_dem_download_workflow(
                iface,
                kwargs,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        if tool_name == "run_osm_acquisition_workflow":
            from .qgis_tools.workflow_tools import run_osm_acquisition_workflow

            return run_osm_acquisition_workflow(
                iface,
                place_name=kwargs.get("place_name", ""),
                output_dir=kwargs.get("output_dir", ""),
                output_prefix=kwargs.get("output_prefix", ""),
                components=kwargs.get("components"),
                max_chunk_area=kwargs.get("max_chunk_area", 0.25),
                overwrite=kwargs.get("overwrite", False),
                continue_on_error=kwargs.get("continue_on_error", True),
                save_project=kwargs.get("save_project", False),
                project_path=kwargs.get("project_path", ""),
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        if tool_name == "load_external_layer":
            from .qgis_tools.external_data import load_external_layer

            return load_external_layer(
                source_path=kwargs.get("source_path", ""),
                layer_name=kwargs.get("layer_name", ""),
                layer_type=kwargs.get("layer_type", "auto"),
                copy_to_project=kwargs.get("copy_to_project", False),
                target_file_name=kwargs.get("target_file_name", ""),
                overwrite=kwargs.get("overwrite", False),
            )

        if tool_name == "run_qgis_workflow_batch":
            return _run_qgis_workflow_batch(
                iface,
                kwargs,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        if tool_name == "repair_common_qgis_code_issues":
            from ..core.code_repair import repair_common_qgis_code_issues
            return repair_common_qgis_code_issues(
                code=kwargs.get("code", ""),
                error_message=kwargs.get("error_message", ""),
                context=kwargs.get("context", ""),
            )

        if tool_name == "rebuild_qgis_catalog":
            from ..core.processing_catalog import rebuild_qgis_catalog
            return rebuild_qgis_catalog(force=kwargs.get("force", True))

        if tool_name == "search_processing_algorithms":
            from ..core.processing_catalog import search_processing_algorithms
            return search_processing_algorithms(
                query=kwargs.get("query", ""),
                provider=kwargs.get("provider", ""),
                limit=kwargs.get("limit", 8),
            )

        if tool_name == "describe_processing_algorithm":
            from ..core.processing_catalog import describe_processing_algorithm
            return describe_processing_algorithm(alg_id=kwargs.get("alg_id", ""))

        if tool_name == "validate_processing_algorithm_call":
            from ..core.processing_catalog import validate_processing_algorithm_call
            return validate_processing_algorithm_call(
                alg_id=kwargs.get("alg_id", ""),
                parameters=kwargs.get("parameters", {}),
            )

        if tool_name == "search_qgis_expression_functions":
            from ..core.processing_catalog import search_qgis_expression_functions
            return search_qgis_expression_functions(
                query=kwargs.get("query", ""),
                limit=kwargs.get("limit", 8),
            )

        if tool_name == "describe_qgis_expression_function":
            from ..core.processing_catalog import describe_qgis_expression_function
            return describe_qgis_expression_function(name=kwargs.get("name", ""))

        if tool_name == "validate_qgis_expression":
            from ..core.processing_catalog import validate_qgis_expression
            return validate_qgis_expression(
                expression=kwargs.get("expression", ""),
                layer_name=kwargs.get("layer_name", ""),
            )

        if tool_name == "search_project_layers":
            from ..core.processing_catalog import search_project_layers
            return search_project_layers(
                query=kwargs.get("query", ""),
                limit=kwargs.get("limit", 20),
            )

        if tool_name == "describe_project_layer":
            from ..core.processing_catalog import describe_project_layer
            return describe_project_layer(layer_name=kwargs.get("layer_name", ""))

        if tool_name == "search_layer_fields":
            from ..core.processing_catalog import search_layer_fields
            return search_layer_fields(
                layer_name=kwargs.get("layer_name", ""),
                query=kwargs.get("query", ""),
                limit=kwargs.get("limit", 20),
            )

        if tool_name == "clip_vector_layers_to_boundary":
            from .qgis_tools.workflow_tools import clip_vector_layers_to_boundary
            return clip_vector_layers_to_boundary(
                boundary_layer_name=kwargs.get("boundary_layer_name", ""),
                clip_tasks=kwargs.get("clip_tasks", []),
                output_dir=kwargs.get("output_dir", ""),
                overwrite=kwargs.get("overwrite", True),
                create_spatial_index=kwargs.get("create_spatial_index", True),
                save_project=kwargs.get("save_project", False),
                project_path=kwargs.get("project_path", ""),
            )

        if tool_name == "save_project_and_verify":
            from ..core.project_persistence import save_project_and_verify
            return save_project_and_verify(
                project_path=kwargs.get("project_path", ""),
                expected_layers=kwargs.get("expected_layers", []),
                min_layer_count=kwargs.get("min_layer_count", 1),
            )

        if tool_name == "search_gee_python_api":
            tool_name = "search_gee_api"

        if tool_name == "install_python_package":
            package_name = kwargs.get("package_name", "")
            if not package_name:
                return "Error: package_name is empty."
            if package_name.strip().startswith("-") or any(sep in package_name for sep in ("\\", "/")):
                return "Error: package_name looks unsafe. Please provide a normal package spec such as 'pandas' or 'pandas==2.2.0'."
                
            iface.messageBar().pushMessage("QGIS Agent", f"正在自动为您安装缺失的依赖库: {package_name}...", level=Qgis.MessageLevel.Info)
            
            try:
                # 1. 内存级调用 (Primary Method)
                from pip._internal import main as pip_main
                ret_code = pip_main(['install', '--user', package_name])
                if ret_code != 0:
                    raise Exception(f"pip_main returned {ret_code}")
            except Exception as e1:
                iface.messageBar().pushMessage("QGIS Agent", f"自动安装库失败: {str(e1)}", level=Qgis.MessageLevel.Warning)
                return f"Failed to install {package_name}. Error: {str(e1)}"
            
            import importlib
            importlib.invalidate_caches()
            iface.messageBar().pushMessage("QGIS Agent", f"依赖库 {package_name} 安装成功！正在恢复任务...", level=Qgis.MessageLevel.Success)
            return f"Successfully installed {package_name}. You can now import it."
            
        if tool_name == "search_gee_api":
            query = kwargs.get("query", "").lower()
            if not query:
                return "Error: query is empty."
                
            import ee
            try:
                algorithms = ee.apifunction.ApiFunction.algorithms()
            except Exception:
                try:
                    from ..bridges.gee_bridge import init_gee
                    init_gee()
                    algorithms = ee.apifunction.ApiFunction.algorithms()
                except Exception as e:
                    return f"Failed to initialize Earth Engine to fetch algorithms. Error: {str(e)}\nPlease check GEE authentication."
            
            results = []
            for name, func in algorithms.items():
                if query in name.lower() or query in func.getSignature().get('description', '').lower():
                    sig = func.getSignature()
                    args_list = []
                    for arg in sig.get('args', []):
                        arg_name = arg.get('name')
                        arg_type = arg.get('type')
                        if arg.get('optional'):
                            args_list.append(f"{arg_name}={arg_type} (optional)")
                        else:
                            args_list.append(f"{arg_name}={arg_type}")
                    
                    sig_str = f"def ee.{name}({', '.join(args_list)}) -> {sig.get('returns')}:"
                    desc = sig.get('description', '')
                    results.append(f"### ee.{name}\n```python\n{sig_str}\n```\n{desc}")
                    
                    if len(results) >= 5: # Limit to top 5 matches
                        break
            
            if not results:
                return f"No API found matching '{query}'"
            
            return "\n\n".join(results)

        if tool_name == "search_data_sources":
            from ..core.data_sources import format_search_results_markdown, search_data_sources

            result = search_data_sources(
                query=kwargs.get("query", ""),
                theme=kwargs.get("theme", ""),
                geometry_type=kwargs.get("geometry_type", ""),
                region=kwargs.get("region", ""),
                limit=kwargs.get("limit", 5),
                allow_auth=kwargs.get("allow_auth", None),
                allow_network=kwargs.get("allow_network", None),
            )
            count = len(result.get("matches", []))
            return {
                "ok": True,
                "message": f"Found {count} matching data source(s).",
                "data": {
                    "search": result,
                    "markdown": format_search_results_markdown(result),
                },
                "artifacts": [
                    {
                        "type": "data_source_search",
                        "path": "data_sources/latest_search.md",
                        "description": "Data source handbook search report.",
                    }
                ],
                "warnings": [],
            }

        if tool_name == "create_data_acquisition_plan":
            from ..core.data_sources import build_data_acquisition_plan

            try:
                plan = build_data_acquisition_plan(
                    task=kwargs.get("task", ""),
                    region=kwargs.get("region", ""),
                    data_type=kwargs.get("data_type", ""),
                    bbox=kwargs.get("bbox", ""),
                    preferred_source_id=kwargs.get("preferred_source_id", ""),
                    output_folder=kwargs.get("output_folder", "data"),
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "message": f"Failed to create data acquisition plan: {exc}",
                    "data": {},
                    "artifacts": [],
                    "warnings": [],
                    "error_type": "argument_error",
                    "suggestions": ["Provide a task or data_type and retry with a concrete data need."],
                }

            primary = ""
            if plan.get("recommended_sources"):
                primary = plan["recommended_sources"][0].get("name", "")
            return {
                "ok": True,
                "message": f"Created data acquisition plan{f' using {primary}' if primary else ''}.",
                "data": {
                    "acquisition_plan": plan,
                    "markdown": plan.get("markdown", ""),
                },
                "artifacts": [
                    {
                        "type": "data_acquisition_plan",
                        "path": "data_sources/acquisition_plan.md",
                        "description": "Data acquisition plan report.",
                    }
                ],
                "warnings": plan.get("warnings", []),
            }
            
        if tool_name in LAYER_AND_PROCESSING_TOOLS:
            return execute_layer_or_processing_tool(iface, tool_name, kwargs)

        if tool_name == 'download_osm_data':
            import os
            import tempfile
            from ..core.tool_result import ToolResult
            from ..core.validators import sanitize_file_stem
            from ..bridges.osm_bridge import (
                OSMDownloader,
                OverpassQueryError,
                build_bbox_query,
                classify_overpass_error,
                safe_feature_count,
            )
            
            bbox_str = kwargs.get("bbox")
            tags = kwargs.get("tags")
            raw_layer_name = kwargs.get("layer_name", "OSM_Data")
            layer_name = str(raw_layer_name or "OSM_Data").strip() or "OSM_Data"
            safe_file_stem = sanitize_file_stem(layer_name, "OSM_Data")
            geometry_type = kwargs.get("geometry_type", "lines")
            valid_geometry_types = {"points", "lines", "multilinestrings", "multipolygons", "other_relations"}
            if geometry_type not in valid_geometry_types:
                return ToolResult.failure(
                    f"Invalid geometry_type '{geometry_type}'.",
                    error_type="argument_error",
                    data={"valid_geometry_types": sorted(valid_geometry_types)},
                ).to_dict()
            
            try:
                w, s, e, n = [float(x) for x in bbox_str.split(',')]
            except (ValueError, TypeError, AttributeError):
                return ToolResult.failure(
                    "bbox must be 'min_lon,min_lat,max_lon,max_lat'.",
                    error_type="argument_error",
                    data={"bbox": bbox_str},
                ).to_dict()
                
            try:
                from ..core.progress import raise_if_cancelled
                _emit_acquisition_progress(
                    progress_callback,
                    tool_name,
                    "OSM 数据下载",
                    "准备 Overpass 查询",
                    1,
                    4,
                    0,
                    "正在验证范围、标签和几何类型。",
                )
                raise_if_cancelled(cancel_callback, "OSM download was cancelled by the user.")
                query = build_bbox_query(tags, (w, s, e, n), geometry_type=geometry_type, timeout_seconds=180)
                _emit_acquisition_progress(
                    progress_callback,
                    tool_name,
                    "OSM 数据下载",
                    "准备 Overpass 查询",
                    1,
                    4,
                    100,
                    "查询已构建。",
                )
            except Exception as exc:
                from ..core.progress import DataAcquisitionCancelled
                if isinstance(exc, DataAcquisitionCancelled):
                    return ToolResult.failure(
                        str(exc),
                        error_type="operation_cancelled",
                        data={"bbox": bbox_str, "tags": tags, "geometry_type": geometry_type},
                    ).to_dict()
                return ToolResult.failure(
                    f"Invalid OSM query parameters: {exc}",
                    error_type="argument_error",
                    data={"bbox": bbox_str, "tags": tags, "geometry_type": geometry_type},
                ).to_dict()

            try:
                tmp_dir = tempfile.gettempdir()
                file_path = os.path.join(tmp_dir, f"{safe_file_stem}.osm")

                def _transfer_progress(received, total, endpoint):
                    if total > 0:
                        stage_percent = min(100.0, received / total * 100.0)
                        detail = f"{received / (1024 * 1024):.1f}/{total / (1024 * 1024):.1f} MB · {endpoint}"
                    else:
                        stage_percent = None
                        detail = f"已接收 {received / (1024 * 1024):.1f} MB · {endpoint}"
                    _emit_acquisition_progress(
                        progress_callback,
                        tool_name,
                        "OSM 数据下载",
                        "下载 Overpass 响应",
                        2,
                        4,
                        stage_percent,
                        detail,
                    )

                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 数据下载", "下载 Overpass 响应", 2, 4, 0,
                    "正在连接 Overpass 服务。",
                )
                OSMDownloader.query_osm(
                    query,
                    file_path,
                    timeout_seconds=180,
                    transfer_progress_callback=_transfer_progress,
                    cancel_callback=cancel_callback,
                )
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 数据下载", "解析 OSM 数据", 3, 4, 0,
                    f"正在解析 {geometry_type} 子图层。",
                )
                    
                from .qgis_tools.io_tools import load_vector_layer
                try:
                    uri = f"{file_path}|layername={geometry_type}"
                    layer = load_vector_layer(uri, layer_name)
                    _emit_acquisition_progress(
                        progress_callback, tool_name, "OSM 数据下载", "解析 OSM 数据", 3, 4, 100,
                        f"图层 {layer_name} 已加载。",
                    )
                    feature_count = safe_feature_count(layer)
                    _emit_acquisition_progress(
                        progress_callback, tool_name, "OSM 数据下载", "验证结果", 4, 4, 100,
                        f"要素数 {feature_count}。",
                    )
                    return ToolResult.success(
                        f"Successfully downloaded OSM data and loaded layer '{layer_name}'.",
                        data={
                            "file_path": file_path,
                            "layer_name": layer_name,
                            "geometry_type": geometry_type,
                            "feature_count": feature_count,
                            "query_debug_file": os.path.join(tmp_dir, "last_overpass_query.ql"),
                        },
                        artifacts=[
                            _artifact_entry(file_path, "osm_raw_xml", "Raw OSM XML downloaded from Overpass."),
                            _artifact_entry(os.path.join(tmp_dir, "last_overpass_query.ql"), "overpass_query", "Last Overpass query used by download_osm_data."),
                        ],
                    ).to_dict()
                except Exception as exc:
                    return ToolResult.failure(
                        f"Downloaded OSM data but QGIS failed to load sublayer '{geometry_type}': {exc}",
                        error_type="qgis_layer_error",
                        data={"file_path": file_path, "layer_name": layer_name, "geometry_type": geometry_type},
                        suggestions=[
                            "Retry with another geometry_type such as multipolygons, lines, or points.",
                            "Use clip_vector_layers_to_boundary after the source layer is loaded.",
                        ],
                    ).to_dict()
            except OverpassQueryError as e:
                return ToolResult.failure(
                    f"Error downloading OSM data: {str(e)}",
                    error_type=getattr(e, "error_type", "network_error"),
                    data={
                        "bbox": bbox_str,
                        "tags": tags,
                        "layer_name": layer_name,
                        "geometry_type": geometry_type,
                        "endpoint": getattr(e, "endpoint", ""),
                    },
                    warnings=[f"Check Overpass debug files near {file_path} if they were created."],
                ).to_dict()
            except Exception as e:
                from ..core.progress import DataAcquisitionCancelled
                if isinstance(e, DataAcquisitionCancelled):
                    return ToolResult.failure(
                        str(e),
                        error_type="operation_cancelled",
                        data={"bbox": bbox_str, "tags": tags, "layer_name": layer_name, "geometry_type": geometry_type},
                    ).to_dict()
                error_type = classify_overpass_error(str(e))
                return ToolResult.failure(
                    f"Error downloading OSM data: {str(e)}",
                    error_type=error_type if error_type != "overpass_error" else "network_error",
                    data={"bbox": bbox_str, "tags": tags, "layer_name": layer_name, "geometry_type": geometry_type},
                ).to_dict()

        elif tool_name == "download_osm_boundary":
            import os
            from ..bridges.osm_bridge import OSMDownloader, safe_feature_count
            from ..core.tool_result import ToolResult
            from ..core.validators import sanitize_file_stem

            name = kwargs.get("name", "")
            output_file = kwargs.get("output_file", "")
            layer_name = kwargs.get("layer_name") or sanitize_file_stem(name, "osm_boundary")
            overwrite = bool(kwargs.get("overwrite", False))
            try:
                if not name or not output_file:
                    return ToolResult.failure(
                        "name and output_file are required.",
                        error_type="argument_error",
                        data={"name": name, "output_file": output_file},
                    ).to_dict()
                from ..core.progress import raise_if_cancelled
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 行政边界下载", "验证请求", 1, 4, 100,
                    f"目标地名：{name}",
                )
                raise_if_cancelled(cancel_callback, "OSM boundary download was cancelled by the user.")
                _ensure_output_available(output_file, overwrite)
                iface.messageBar().pushMessage("OSM Boundary", f"Downloading boundary for {name}...", Qgis.MessageLevel.Info)
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 行政边界下载", "查询 Nominatim", 2, 4, None,
                    "正在检索具有面几何的行政区结果。",
                )

                def _boundary_transfer(received, total, endpoint):
                    if total > 0:
                        stage_percent = min(100.0, received / total * 100.0)
                        detail = f"{received / 1024:.1f}/{total / 1024:.1f} KB · {endpoint}"
                    else:
                        stage_percent = None
                        detail = f"已接收 {received / 1024:.1f} KB · {endpoint}"
                    _emit_acquisition_progress(
                        progress_callback, tool_name, "OSM 行政边界下载", "查询 Nominatim", 2, 4,
                        stage_percent, detail,
                    )

                layer = OSMDownloader.download_boundary_nominatim(
                    name,
                    output_file,
                    layer_name=layer_name,
                    transfer_progress_callback=_boundary_transfer,
                    cancel_callback=cancel_callback,
                )
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 行政边界下载", "写入 GeoJSON", 3, 4, 100,
                    os.path.basename(output_file),
                )
                feature_count = safe_feature_count(layer)
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 行政边界下载", "加载并验证", 4, 4, 100,
                    f"图层有效，要素数 {feature_count}。",
                )
                return ToolResult.success(
                    f"Downloaded OSM boundary '{layer_name}' to {output_file}.",
                    data={"name": name, "output_file": output_file, "layer_name": layer_name, "feature_count": feature_count},
                    artifacts=[_artifact_entry(output_file, "osm_boundary", "Downloaded OSM/Nominatim boundary GeoJSON.")],
                ).to_dict()
            except Exception as exc:
                from ..core.progress import DataAcquisitionCancelled
                if isinstance(exc, DataAcquisitionCancelled):
                    return ToolResult.failure(
                        str(exc),
                        error_type="operation_cancelled",
                        data={"name": name, "output_file": output_file, "layer_name": layer_name},
                    ).to_dict()
                return ToolResult.failure(
                    f"Failed to download OSM boundary: {exc}",
                    error_type="network_error",
                    data={"name": name, "output_file": output_file, "layer_name": layer_name},
                ).to_dict()

        elif tool_name == "download_osm_roads":
            import os
            from ..bridges.osm_bridge import OSMDownloader, classify_overpass_error, safe_feature_count
            from ..core.tool_result import ToolResult

            boundary_layer_name = kwargs.get("boundary_layer_name", "")
            output_file = kwargs.get("output_file", "")
            network_type = kwargs.get("network_type", "roads") or "roads"
            overwrite = bool(kwargs.get("overwrite", False))
            try:
                if not boundary_layer_name or not output_file:
                    return ToolResult.failure(
                        "boundary_layer_name and output_file are required.",
                        error_type="argument_error",
                        data={"boundary_layer_name": boundary_layer_name, "output_file": output_file},
                    ).to_dict()
                from ..core.progress import raise_if_cancelled
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "验证边界", 1, 4, 0,
                    f"边界图层：{boundary_layer_name}",
                )
                raise_if_cancelled(cancel_callback, "OSM network download was cancelled by the user.")
                _ensure_output_available(output_file, overwrite)
                boundary_layer = _find_project_layer(boundary_layer_name)
                if boundary_layer is None:
                    return ToolResult.failure(
                        f"Boundary layer '{boundary_layer_name}' was not found.",
                        error_type="qgis_layer_error",
                        data={"boundary_layer_name": boundary_layer_name},
                    ).to_dict()
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "验证边界", 1, 4, 100,
                    f"边界图层 {boundary_layer.name()} 有效。",
                )
                iface.messageBar().pushMessage("OSM Roads", f"Downloading {network_type} network...", Qgis.MessageLevel.Info)
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "构建 OSMnx 网络", 2, 4, None,
                    "正在请求网络并构建拓扑，此阶段服务端不提供百分比。",
                )

                def _network_progress(stage_percent, detail):
                    _emit_acquisition_progress(
                        progress_callback, tool_name, "OSM 路网下载", "构建 OSMnx 网络", 2, 4,
                        stage_percent, detail,
                    )

                try:
                    layer = OSMDownloader.download_and_clean_network(
                        boundary_layer,
                        network_type,
                        output_file,
                        task_progress_callback=_network_progress,
                        cancel_callback=cancel_callback,
                    )
                except Exception as net_exc:
                    if "osmnx" not in str(net_exc).lower() and not isinstance(net_exc, ImportError):
                        raise
                    # Automatic zero-dependency fallback via chunked Overpass download
                    fallback_preset = "waterways" if network_type == "water" else "roads"
                    return _execute_osm_feature_download(
                        {
                            "boundary_layer_name": boundary_layer_name,
                            "preset": fallback_preset,
                            "output_file": output_file,
                            "layer_name": os.path.splitext(os.path.basename(output_file))[0],
                            "overwrite": overwrite,
                            "split_large_bbox": True,
                        },
                        progress_callback=progress_callback,
                        cancel_callback=cancel_callback,
                    )
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "写入网络文件", 3, 4, 100,
                    os.path.basename(output_file),
                )
                feature_count = safe_feature_count(layer)
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "加载并验证", 4, 4, 100,
                    f"网络要素数 {feature_count}。",
                )
                return ToolResult.success(
                    f"Downloaded OSM {network_type} network to {output_file}.",
                    data={
                        "boundary_layer_name": boundary_layer_name,
                        "output_file": output_file,
                        "layer_name": layer.name() if hasattr(layer, "name") else os.path.splitext(os.path.basename(output_file))[0],
                        "network_type": network_type,
                        "feature_count": feature_count,
                        "osmnx_cache": os.path.join(os.path.dirname(os.path.abspath(output_file)), "osmnx_cache"),
                    },
                    artifacts=[_artifact_entry(output_file, "osm_network", "Downloaded and cleaned OSM network output.")],
                ).to_dict()
            except Exception as exc:
                from ..core.progress import DataAcquisitionCancelled
                if isinstance(exc, DataAcquisitionCancelled):
                    return ToolResult.failure(
                        str(exc),
                        error_type="operation_cancelled",
                        data={"boundary_layer_name": boundary_layer_name, "output_file": output_file, "network_type": network_type},
                    ).to_dict()
                error_type = getattr(exc, "error_type", None) or classify_overpass_error(str(exc))
                return ToolResult.failure(
                    f"Failed to download OSM network: {exc}",
                    error_type=error_type if error_type != "overpass_error" else "network_error",
                    data={"boundary_layer_name": boundary_layer_name, "output_file": output_file, "network_type": network_type},
                ).to_dict()

        elif tool_name == "download_osm_features":
            return _execute_osm_feature_download(
                kwargs,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        else:
            from ..core.user_tool_extensions import get_user_tool, execute_user_tool

            if get_user_tool(tool_name, include_candidates=False) is not None:
                return execute_user_tool(tool_name, iface, kwargs)
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        try:
            from ..utils.logger import get_logger
            get_logger().error("Uncaught exception in execute_atomic_tool(%s): %s\n%s", tool_name, e, tb)
        except (ImportError, OSError, RuntimeError, ValueError, TypeError):
            pass
        return f"Error executing tool {tool_name}: {str(e)}\n{tb}"
