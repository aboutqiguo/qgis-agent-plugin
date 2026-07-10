import os
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional


def _read_qgis_project_xml(project_path: str) -> Optional[bytes]:
    if not project_path or not os.path.exists(project_path):
        return None
    lower = project_path.lower()
    if lower.endswith(".qgz"):
        with zipfile.ZipFile(project_path) as archive:
            qgs_names = [name for name in archive.namelist() if name.lower().endswith(".qgs")]
            if not qgs_names:
                return None
            return archive.read(qgs_names[0])
    if lower.endswith(".qgs"):
        with open(project_path, "rb") as handle:
            return handle.read()
    return None


def inspect_saved_project(project_path: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": False,
        "project_path": project_path,
        "exists": bool(project_path and os.path.exists(project_path)),
        "layer_count": 0,
        "layers": [],
        "warnings": [],
    }
    if not payload["exists"]:
        payload["warnings"].append("Project file does not exist.")
        return payload

    try:
        xml_bytes = _read_qgis_project_xml(project_path)
        if not xml_bytes:
            payload["warnings"].append("Could not read .qgs XML from project file.")
            return payload
        root = ET.fromstring(xml_bytes)
        layers = []
        for map_layer in root.findall(".//maplayer"):
            name = map_layer.findtext("layername") or ""
            source = map_layer.findtext("datasource") or ""
            layers.append(
                {
                    "name": name,
                    "type": map_layer.get("type", ""),
                    "source": source,
                }
            )
        payload["layers"] = layers
        payload["layer_count"] = len(layers)
        payload["ok"] = True
        return payload
    except Exception as exc:
        payload["warnings"].append(f"Could not inspect saved project: {exc}")
        return payload


def save_project_and_verify(
    project_path: str = "",
    expected_layers: Optional[Iterable[str]] = None,
    min_layer_count: int = 1,
) -> Dict[str, Any]:
    from .tool_result import ToolResult
    from .validators import validate_path_within_allowed_roots

    expected = [name for name in (expected_layers or []) if name]
    try:
        from qgis.core import QgsProject
    except Exception as exc:
        return ToolResult.failure(
            f"QGIS project API is unavailable: {exc}",
            error_type="qgis_layer_error",
            data={"project_path": project_path, "expected_layers": expected},
        ).to_dict()

    project = QgsProject.instance()
    if project_path:
        project_path = os.path.abspath(project_path)
        try:
            project.setFileName(project_path)
        except Exception:
            pass
    else:
        try:
            project_path = project.fileName()
        except Exception:
            project_path = ""

    if not project_path:
        return ToolResult.failure(
            "Current QGIS project has no file path. Provide project_path before saving.",
            error_type="file_path_error",
            data={"expected_layers": expected},
        ).to_dict()

    path_report = validate_path_within_allowed_roots(project_path, "project_path")
    if not path_report.ok:
        return ToolResult.failure(
            "Project path is outside the allowed workspace.",
            error_type="file_path_error",
            data={"project_path": project_path, "validation": path_report.to_dict()},
            suggestions=["Save inside the current QGIS project folder or system temp folder."],
        ).to_dict()

    try:
        os.makedirs(os.path.dirname(os.path.abspath(project_path)), exist_ok=True)
        saved = bool(project.write(project_path))
    except TypeError:
        try:
            saved = bool(project.write())
        except Exception as exc:
            return ToolResult.failure(
                f"Failed to save QGIS project: {exc}",
                error_type="file_path_error",
                data={"project_path": project_path, "expected_layers": expected},
            ).to_dict()
    except Exception as exc:
        return ToolResult.failure(
            f"Failed to save QGIS project: {exc}",
            error_type="file_path_error",
            data={"project_path": project_path, "expected_layers": expected},
        ).to_dict()

    inspection = inspect_saved_project(project_path)
    saved_names = {layer.get("name", "") for layer in inspection.get("layers", [])}
    missing = [name for name in expected if name not in saved_names]
    warnings: List[str] = list(inspection.get("warnings", []))
    if not saved:
        warnings.append("QgsProject.write returned False.")
    if inspection.get("layer_count", 0) < int(min_layer_count or 0):
        warnings.append(
            f"Saved project has only {inspection.get('layer_count', 0)} layer(s), below expected minimum {min_layer_count}."
        )
    if missing:
        warnings.append(f"Saved project is missing expected layer(s): {', '.join(missing)}")

    ok = saved and inspection.get("ok") and not missing and inspection.get("layer_count", 0) >= int(min_layer_count or 0)
    data = {
        "project_path": project_path,
        "saved": saved,
        "inspection": inspection,
        "expected_layers": expected,
        "missing_layers": missing,
    }
    if ok:
        return ToolResult.success(
            f"Project saved and verified: {project_path}",
            data=data,
            warnings=warnings,
        ).to_dict()
    return ToolResult.failure(
        f"Project save verification failed: {project_path}",
        error_type="file_path_error",
        data=data,
        warnings=warnings,
        suggestions=[
            "Check that the project path is writable.",
            "Call list_layers and retry with the exact expected layer names.",
            "Save the project after all output layers have been loaded.",
        ],
    ).to_dict()
