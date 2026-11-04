import os
from typing import Any, Dict, Iterable, List


def _find_layer_by_name_or_id(project, name_or_id: str):
    if not name_or_id:
        return None
    layer = project.mapLayer(name_or_id)
    if layer:
        return layer
    matches = project.mapLayersByName(name_or_id)
    return matches[0] if matches else None


def _safe_output_name(value: str) -> str:
    name = os.path.basename(str(value or "").replace("\\", "/")).strip()
    if not name:
        raise ValueError("output_name is empty.")
    if any(part in name for part in ("/", "\\", "..")):
        raise ValueError(f"Unsafe output_name: {value}")
    return name


def run_osm_acquisition_workflow(
    iface,
    place_name: str,
    output_dir: str,
    output_prefix: str,
    components=None,
    max_chunk_area: float = 0.25,
    overwrite: bool = False,
    continue_on_error: bool = True,
    save_project: bool = False,
    project_path: str = "",
    progress_callback=None,
    cancel_callback=None,
) -> Dict[str, Any]:
    """Acquire a complete OSM bundle without another model round per dataset."""
    from ...core.progress import emit_progress, raise_if_cancelled
    from ...core.tool_result import ToolResult, parse_tool_result_payload
    from ...core.validators import sanitize_file_stem, validate_path_within_allowed_roots

    allowed_components = ("roads", "buildings", "poi", "waterways", "water")
    requested = list(components or allowed_components)
    requested = list(dict.fromkeys(str(item).strip().lower() for item in requested if str(item).strip()))
    invalid = [item for item in requested if item not in allowed_components]
    if not place_name or not output_dir or not output_prefix or invalid:
        return ToolResult.failure(
            "OSM workflow parameters are incomplete or invalid.",
            error_type="argument_error",
            data={
                "place_name": place_name,
                "output_dir": output_dir,
                "output_prefix": output_prefix,
                "invalid_components": invalid,
                "allowed_components": list(allowed_components),
            },
        ).to_dict()

    path_report = validate_path_within_allowed_roots(output_dir, "output_dir")
    if not path_report.ok:
        return ToolResult.failure(
            "OSM workflow output directory is outside the allowed workspace.",
            error_type="file_path_error",
            data={"output_dir": output_dir, "validation": path_report.to_dict()},
        ).to_dict()

    prefix = sanitize_file_stem(output_prefix, "osm")
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    title = "连续 OSM 数据获取"
    tool_name = "run_osm_acquisition_workflow"
    stage_count = len(requested) + 3
    results: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []

    def emit(stage, stage_index, stage_percent=None, detail=""):
        return emit_progress(
            progress_callback,
            tool_name=tool_name,
            title=title,
            stage=stage,
            stage_index=stage_index,
            stage_count=stage_count,
            stage_percent=stage_percent,
            detail=detail,
        )

    def execute_child(action, arguments, label, stage_index):
        from ..tools import execute_atomic_tool

        def child_progress(event):
            child_percent = event.get("percent") if event.get("determinate") else None
            detail = event.get("detail") or event.get("stage") or ""
            emit(label, stage_index, child_percent, detail)

        raise_if_cancelled(cancel_callback, "Continuous OSM acquisition was cancelled by the user.")
        emit(label, stage_index, 0, f"开始执行 {action}。")
        raw = execute_atomic_tool(
            iface,
            action,
            arguments,
            progress_callback=child_progress,
            cancel_callback=cancel_callback,
        )
        payload = raw if isinstance(raw, dict) else parse_tool_result_payload(raw)
        payload = payload or ToolResult.failure(
            f"{action} returned an unreadable result.",
            error_type="unknown_error",
        ).to_dict()
        emit(label, stage_index, 100 if payload.get("ok") else 0, payload.get("message", ""))
        item = {"component": label, "tool": action, "ok": bool(payload.get("ok")), "result": payload}
        results.append(item)
        artifacts.extend(payload.get("artifacts") or [])
        return payload

    try:
        emit("验证参数", 1, 0, f"目标区域：{place_name}；请求 {len(requested)} 类要素。")
        raise_if_cancelled(cancel_callback, "Continuous OSM acquisition was cancelled by the user.")
        emit("验证参数", 1, 100, f"输出目录：{output_dir}")

        boundary_layer_name = f"{prefix}_boundary"
        boundary_path = os.path.join(output_dir, f"{prefix}_boundary.geojson")
        boundary_result = execute_child(
            "download_osm_boundary",
            {
                "name": place_name,
                "output_file": boundary_path,
                "layer_name": boundary_layer_name,
                "overwrite": bool(overwrite),
            },
            "行政边界",
            2,
        )
        if not boundary_result.get("ok"):
            return ToolResult.failure(
                "Continuous OSM acquisition stopped because the boundary download failed.",
                error_type=boundary_result.get("error_type", "network_error"),
                data={
                    "workflow_complete": False,
                    "place_name": place_name,
                    "requested_components": requested,
                    "steps": results,
                },
                artifacts=artifacts,
                suggestions=boundary_result.get("suggestions") or ["Confirm the place name and retry."],
            ).to_dict()

        for offset, component in enumerate(requested, start=3):
            layer_name = f"{prefix}_{component}"
            output_path = os.path.join(output_dir, f"{prefix}_{component}.gpkg")
            payload = execute_child(
                "download_osm_features",
                {
                    "boundary_layer_name": boundary_layer_name,
                    "preset": component,
                    "output_file": output_path,
                    "layer_name": layer_name,
                    "split_large_bbox": True,
                    "max_chunk_area": float(max_chunk_area or 0.25),
                    "overwrite": bool(overwrite),
                },
                component,
                offset,
            )
            if not payload.get("ok") and not continue_on_error:
                break

        final_stage = stage_count
        emit("汇总验证", final_stage, 0, "正在核对输出文件和 QGIS 图层。")
        successful = [item for item in results if item.get("ok")]
        failed = [item for item in results if not item.get("ok")]
        expected_files = []
        expected_layers = []
        verification = []
        from qgis.core import QgsProject

        project = QgsProject.instance()
        for item in successful:
            data = item.get("result", {}).get("data") or {}
            path = data.get("output_file") or data.get("output_path")
            layer_name = data.get("layer_name")
            if path:
                expected_files.append(path)
                verification.append({
                    "type": "file",
                    "path": path,
                    "ok": os.path.exists(path) and os.path.getsize(path) > 0,
                })
            if layer_name:
                expected_layers.append(layer_name)
                verification.append({
                    "type": "layer",
                    "name": layer_name,
                    "ok": _find_layer_by_name_or_id(project, layer_name) is not None,
                })

        invalid_outputs = [item for item in verification if not item.get("ok")]
        project_save_result = None
        if save_project and not failed and not invalid_outputs:
            from ...core.project_persistence import save_project_and_verify

            project_save_result = save_project_and_verify(
                project_path=project_path,
                expected_layers=expected_layers,
                min_layer_count=len(expected_layers),
            )
            if not project_save_result.get("ok"):
                failed.append({"component": "project_save", "ok": False, "result": project_save_result})

        workflow_complete = not failed and not invalid_outputs and len(successful) == len(requested) + 1
        emit(
            "汇总验证",
            final_stage,
            100 if workflow_complete else 0,
            f"完成 {len(successful)}/{len(requested) + 1} 个数据项。",
        )
        data = {
            "workflow_complete": workflow_complete,
            "place_name": place_name,
            "output_dir": output_dir,
            "output_prefix": prefix,
            "requested_components": requested,
            "completed_components": [item["component"] for item in successful],
            "failed_components": [item["component"] for item in failed],
            "expected_files": expected_files,
            "expected_layers": expected_layers,
            "verification": verification,
            "steps": results,
            "project_save_result": project_save_result,
        }
        if workflow_complete:
            return ToolResult.success(
                f"Continuous OSM acquisition completed: {len(successful)} dataset(s) downloaded and verified.",
                data=data,
                artifacts=artifacts,
            ).to_dict()
        return ToolResult.failure(
            f"Continuous OSM acquisition completed partially: {len(successful)}/{len(requested) + 1} dataset(s) passed.",
            error_type="partial_success_error",
            data=data,
            artifacts=artifacts,
            suggestions=["Review failed_components and retry only those components."],
        ).to_dict()
    except Exception as exc:
        from ...core.progress import DataAcquisitionCancelled

        if isinstance(exc, DataAcquisitionCancelled):
            return ToolResult.failure(
                str(exc),
                error_type="operation_cancelled",
                data={"workflow_complete": False, "steps": results},
                artifacts=artifacts,
            ).to_dict()
        return ToolResult.failure(
            f"Continuous OSM acquisition failed: {exc}",
            error_type="network_error",
            data={"workflow_complete": False, "steps": results},
            artifacts=artifacts,
        ).to_dict()


def clip_vector_layers_to_boundary(
    boundary_layer_name: str,
    clip_tasks: Iterable[Dict[str, Any]],
    output_dir: str,
    overwrite: bool = True,
    create_spatial_index: bool = True,
    save_project: bool = False,
    project_path: str = "",
) -> Dict[str, Any]:
    from ...core.tool_result import ToolResult
    from ...core.validators import validate_path_within_allowed_roots

    try:
        import processing
        import processing.core.Processing
        from qgis.core import QgsProject
        from .io_tools import load_vector_layer, remove_duplicate_layers
    except Exception as exc:
        return ToolResult.failure(
            f"QGIS processing API is unavailable: {exc}",
            error_type="processing_error",
        ).to_dict()

    try:
        processing.core.Processing.Processing.initialize()
    except Exception:
        pass

    project = QgsProject.instance()
    boundary = _find_layer_by_name_or_id(project, boundary_layer_name)
    if boundary is None:
        return ToolResult.failure(
            f"Boundary layer not found: {boundary_layer_name}",
            error_type="qgis_layer_error",
            data={"boundary_layer_name": boundary_layer_name},
        ).to_dict()

    tasks = list(clip_tasks or [])
    if not tasks:
        return ToolResult.failure(
            "clip_tasks is empty.",
            error_type="argument_error",
            data={"boundary_layer_name": boundary_layer_name, "output_dir": output_dir},
        ).to_dict()

    path_report = validate_path_within_allowed_roots(output_dir, "output_dir")
    if not path_report.ok:
        return ToolResult.failure(
            "Output directory is outside the allowed workspace.",
            error_type="file_path_error",
            data={"output_dir": output_dir, "validation": path_report.to_dict()},
        ).to_dict()

    os.makedirs(output_dir, exist_ok=True)
    outputs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    failed: List[Dict[str, Any]] = []

    for task in tasks:
        src_name = task.get("input_layer_name") or task.get("source_layer") or task.get("layer")
        output_name = _safe_output_name(task.get("output_name") or f"{src_name}_clipped.gpkg")
        output_layer_name = task.get("output_layer_name") or os.path.splitext(output_name)[0]
        src_layer = _find_layer_by_name_or_id(project, src_name)
        out_path = os.path.abspath(os.path.join(output_dir, output_name))

        if src_layer is None:
            failed.append({"input_layer_name": src_name, "error": "Input layer not found."})
            continue

        try:
            if overwrite:
                remove_duplicate_layers(path=out_path, name=output_layer_name, layer_type="vector", keep_first=False)
                if os.path.exists(out_path) and not out_path.lower().endswith(".gpkg"):
                    try:
                        os.remove(out_path)
                    except OSError:
                        pass

            result = processing.run(
                "native:clip",
                {
                    "INPUT": src_layer,
                    "OVERLAY": boundary,
                    "OUTPUT": out_path,
                },
            )
            result_path = result.get("OUTPUT", out_path) if isinstance(result, dict) else out_path
            layer = load_vector_layer(result_path, output_layer_name, duplicate_policy="replace" if overwrite else "reuse")
            feature_count = None
            try:
                feature_count = int(layer.featureCount())
            except Exception:
                pass

            if create_spatial_index:
                try:
                    processing.run("native:createspatialindex", {"INPUT": layer})
                except Exception as exc:
                    warnings.append(f"Failed to create spatial index for {output_layer_name}: {exc}")

            outputs.append(
                {
                    "input_layer_name": src_name,
                    "output_layer_name": output_layer_name,
                    "output_path": result_path,
                    "feature_count": feature_count,
                    "valid": bool(layer.isValid()),
                }
            )
        except Exception as exc:
            failed.append(
                {
                    "input_layer_name": src_name,
                    "output_layer_name": output_layer_name,
                    "output_path": out_path,
                    "error": str(exc),
                }
            )

    project_save_result = None
    if save_project:
        try:
            from ...core.project_persistence import save_project_and_verify

            project_save_result = save_project_and_verify(
                project_path=project_path,
                expected_layers=[item["output_layer_name"] for item in outputs],
                min_layer_count=len(outputs),
            )
            if not project_save_result.get("ok"):
                warnings.append(project_save_result.get("message", "Project save verification failed."))
        except Exception as exc:
            warnings.append(f"Failed to save project after clipping: {exc}")

    data = {
        "boundary_layer_name": boundary_layer_name,
        "output_dir": output_dir,
        "outputs": outputs,
        "failed": failed,
        "project_save_result": project_save_result,
    }
    if failed:
        return ToolResult.failure(
            f"Vector clipping completed with {len(failed)} failed task(s).",
            error_type="processing_error",
            data=data,
            warnings=warnings,
            suggestions=[
                "Call list_layers and retry with exact input layer names.",
                "Use one explicit output_name and output_layer_name per input layer.",
                "Keep overwrite=true when regenerating outputs from the same paths.",
            ],
        ).to_dict()

    return ToolResult.success(
        f"Clipped {len(outputs)} vector layer(s) to {boundary_layer_name}.",
        data=data,
        warnings=warnings,
    ).to_dict()
