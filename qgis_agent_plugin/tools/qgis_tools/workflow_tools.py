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
                if os.path.exists(out_path):
                    os.remove(out_path)

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
