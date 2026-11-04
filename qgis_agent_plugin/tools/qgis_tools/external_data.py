"""Safe import helpers for file-backed layers outside the QGIS project folder."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List


_RASTER_EXTENSIONS = {
    ".tif", ".tiff", ".img", ".vrt", ".asc", ".bil", ".jp2", ".png", ".jpg", ".jpeg",
}
_VECTOR_EXTENSIONS = {
    ".gpkg", ".geojson", ".json", ".shp", ".kml", ".gml", ".csv", ".dxf", ".tab",
}


def _stream_copy(source: str, target: str, chunk_size: int = 4 * 1024 * 1024) -> None:
    """Copy through Python streams; Windows virtual drive providers can reject CopyFile2."""
    part_path = target + ".part"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        with open(source, "rb") as src, open(part_path, "wb") as dst:
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk)
        if os.path.getsize(source) != os.path.getsize(part_path):
            raise IOError("Copied file size does not match source file size.")
        os.replace(part_path, target)
    except Exception:
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass
        raise


def _sidecar_paths(source_path: str) -> Iterable[str]:
    path = Path(source_path)
    suffix = path.suffix.lower()
    yield str(path)
    if suffix == ".shp":
        for sidecar in (".dbf", ".shx", ".prj", ".cpg", ".qix", ".sbn", ".sbx"):
            candidate = str(path.with_suffix(sidecar))
            if os.path.exists(candidate):
                yield candidate
    elif suffix in {".tif", ".tiff", ".img", ".jp2"}:
        for candidate in (str(path) + ".aux.xml", str(path.with_suffix(".tfw")), str(path) + ".ovr"):
            if os.path.exists(candidate):
                yield candidate


def _copy_dataset_to_project(source_path: str, project_home: str, target_name: str, overwrite: bool) -> List[str]:
    from ...core.validators import sanitize_file_stem, validate_path_within_allowed_roots

    source = Path(source_path)
    name = target_name.strip() if target_name else source.name
    stem = sanitize_file_stem(Path(name).stem, "imported_layer")
    suffix = Path(name).suffix or source.suffix
    destination = os.path.join(project_home, "imported_data", stem + suffix)
    report = validate_path_within_allowed_roots(destination, "destination_path")
    if not report.ok:
        raise ValueError("Project import destination is not inside an allowed project path.")
    copied = []
    for item in _sidecar_paths(source_path):
        item_path = Path(item)
        if item_path == source:
            target = destination
        elif str(item_path).lower().endswith(".aux.xml"):
            target = destination + ".aux.xml"
        elif str(item_path).lower().endswith(".ovr"):
            target = destination + ".ovr"
        else:
            target = str(Path(destination).with_suffix(item_path.suffix))
        if os.path.exists(target) and not overwrite:
            raise FileExistsError(f"Destination already exists: {target}")
        _stream_copy(item, target)
        copied.append(target)
    return copied


def load_external_layer(
    source_path: str,
    layer_name: str = "",
    layer_type: str = "auto",
    copy_to_project: bool = False,
    target_file_name: str = "",
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Load an external vector/raster safely, optionally copying it into the project first."""
    from ...core.tool_result import ToolResult
    from ...core.validators import validate_agent_file_path_argument

    source_report = validate_agent_file_path_argument(source_path, "source_path")
    if not source_report.ok:
        return ToolResult.failure(
            "External source path is invalid.",
            error_type="file_path_error",
            data={"validation": source_report.to_dict()},
        ).to_dict()

    source_path = os.path.abspath(os.path.normpath(source_path))
    if not os.path.isfile(source_path):
        return ToolResult.failure(
            f"External source file does not exist or is not readable: {source_path}",
            error_type="file_path_error",
            data={"source_path": source_path},
            suggestions=["Check the drive connection and file path before retrying."],
        ).to_dict()

    selected_type = str(layer_type or "auto").strip().lower()
    if selected_type not in {"auto", "vector", "raster"}:
        return ToolResult.failure(
            "layer_type must be auto, vector, or raster.",
            error_type="argument_error",
            data={"layer_type": layer_type},
        ).to_dict()

    loaded_path = source_path
    copied_paths: List[str] = []
    if copy_to_project:
        try:
            from qgis.core import QgsProject

            project_home = QgsProject.instance().homePath() or ""
            if not project_home:
                raise ValueError("Save the QGIS project before copying external data into it.")
            copied_paths = _copy_dataset_to_project(
                source_path,
                project_home,
                target_file_name,
                bool(overwrite),
            )
            loaded_path = copied_paths[0]
        except Exception as exc:
            return ToolResult.failure(
                f"Could not copy external data into the project folder: {exc}",
                error_type="file_path_error",
                data={"source_path": source_path, "copy_to_project": True},
            ).to_dict()

    extension = Path(loaded_path).suffix.lower()
    resolved_name = layer_name.strip() or Path(loaded_path).stem
    try:
        from .io_tools import load_raster_layer, load_vector_layer

        loaders = []
        if selected_type == "vector" or (selected_type == "auto" and extension in _VECTOR_EXTENSIONS):
            loaders.append(("vector", load_vector_layer))
        if selected_type == "raster" or (selected_type == "auto" and extension in _RASTER_EXTENSIONS):
            loaders.append(("raster", load_raster_layer))
        if selected_type == "auto" and not loaders:
            loaders = [("raster", load_raster_layer), ("vector", load_vector_layer)]
        elif selected_type == "auto" and len(loaders) == 1:
            other = load_vector_layer if loaders[0][0] == "raster" else load_raster_layer
            loaders.append(("vector" if loaders[0][0] == "raster" else "raster", other))

        errors = []
        for resolved_type, loader in loaders:
            try:
                layer = loader(loaded_path, resolved_name, duplicate_policy="reuse")
                return ToolResult.success(
                    f"Loaded external {resolved_type} layer: {layer.name()}",
                    data={
                        "source_path": source_path,
                        "loaded_path": loaded_path,
                        "layer_name": layer.name(),
                        "layer_id": layer.id(),
                        "layer_type": resolved_type,
                        "copied_to_project": bool(copy_to_project),
                        "copied_paths": copied_paths,
                    },
                    artifacts=[
                        {"type": "external_source", "path": source_path, "description": "Read-only external source"},
                        *[
                            {"type": "project_copy", "path": path, "description": "Project-local imported data"}
                            for path in copied_paths
                        ],
                    ],
                ).to_dict()
            except Exception as exc:
                errors.append(f"{resolved_type}: {exc}")
        raise ValueError("; ".join(errors))
    except Exception as exc:
        return ToolResult.failure(
            f"Could not load external data into QGIS: {exc}",
            error_type="qgis_layer_error",
            data={"source_path": source_path, "loaded_path": loaded_path},
        ).to_dict()
