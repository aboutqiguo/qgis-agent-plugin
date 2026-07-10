import ast
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class ValidationIssue:
    level: str
    message: str
    suggestion: str = ""
    field: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "level": self.level,
            "message": self.message,
            "suggestion": self.suggestion,
            "field": self.field,
        }


@dataclass
class ValidationReport:
    ok: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)

    def add_error(self, message: str, suggestion: str = "", field: str = "") -> None:
        self.ok = False
        self.issues.append(ValidationIssue("error", message, suggestion, field))

    def add_warning(self, message: str, suggestion: str = "", field: str = "") -> None:
        self.issues.append(ValidationIssue("warning", message, suggestion, field))

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "issues": [issue.to_dict() for issue in self.issues]}


def validate_required(kwargs: Dict[str, Any], required: Iterable[str]) -> ValidationReport:
    report = ValidationReport()
    for name in required:
        value = kwargs.get(name)
        if value is None or value == "":
            report.add_error(
                f"Missing required argument: {name}",
                "Provide this argument before calling the tool.",
                field=name,
            )
    return report


def validate_schema_values(kwargs: Dict[str, Any], schema: Dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    if not isinstance(schema, dict):
        return report
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return report

    for name, prop_schema in properties.items():
        if name not in kwargs or kwargs.get(name) is None:
            continue
        expected_type = prop_schema.get("type") if isinstance(prop_schema, dict) else ""
        value = kwargs.get(name)
        if expected_type and not _matches_json_type(value, expected_type):
            report.add_error(
                f"Argument '{name}' must be {expected_type}, got {type(value).__name__}.",
                "Pass a value that matches the tool schema.",
                name,
            )
        enum_values = prop_schema.get("enum") if isinstance(prop_schema, dict) else None
        if enum_values and value not in enum_values:
            report.add_error(
                f"Argument '{name}' must be one of: {enum_values}",
                "Use one of the supported enum values.",
                name,
            )
    return report


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    return True


def validate_output_path(
    file_path: str,
    allowed_roots: Optional[Iterable[str]] = None,
    allow_overwrite: bool = False,
) -> ValidationReport:
    report = ValidationReport()
    if not file_path:
        report.add_error("Output path is empty.", "Choose an explicit output path.", "file_path")
        return report

    resolved = os.path.abspath(os.path.normpath(file_path))
    parent = os.path.dirname(resolved)
    if parent and not os.path.exists(parent):
        report.add_warning(
            f"Output parent folder does not exist: {parent}",
            "Create the folder before writing, or choose an existing folder.",
            "file_path",
        )

    if allowed_roots:
        normalized_roots = [os.path.abspath(os.path.normpath(root)) for root in allowed_roots if root]
        try:
            inside_root = any(os.path.commonpath([resolved, root]) == root for root in normalized_roots)
        except ValueError:
            inside_root = False
        if not inside_root:
            report.add_error(
                f"Output path is outside the allowed roots: {resolved}",
                "Write inside the current QGIS project folder or another explicitly allowed folder.",
                "file_path",
            )

    if os.path.exists(resolved) and not allow_overwrite:
        report.add_error(
            f"Output path already exists: {resolved}",
            "Ask the user before overwriting, or choose a new output file.",
            "file_path",
        )
    return report


def validate_agent_file_path_argument(file_path: str, field: str = "file_path") -> ValidationReport:
    report = ValidationReport()
    if not isinstance(file_path, str) or not file_path.strip():
        report.add_error("File path is empty.", "Provide a concrete file path.", field)
        return report
    normalized = file_path.replace("\\", "/").strip()
    parts = [part for part in normalized.split("/") if part]
    if ".." in parts:
        report.add_error(
            f"Path traversal is not allowed: {file_path}",
            "Use a path inside the current project, temp folder, or an agent-managed file.",
            field,
        )
    if any(ord(char) < 32 for char in file_path):
        report.add_error("File path contains control characters.", "Use a normal filesystem path.", field)
    return report


def _path_within(path: str, root: str) -> bool:
    try:
        path = os.path.abspath(os.path.normcase(path))
        root = os.path.abspath(os.path.normcase(root))
        return os.path.commonpath([path, root]) == root
    except Exception:
        return False


def qgis_project_home() -> str:
    try:
        from qgis.core import QgsProject

        return QgsProject.instance().homePath() or ""
    except Exception:
        return ""


def allowed_agent_file_roots(project_home: str = "") -> List[str]:
    roots = [tempfile.gettempdir()]
    project_home = project_home or qgis_project_home()
    if project_home:
        roots.append(project_home)
    return roots


def validate_path_within_allowed_roots(
    file_path: str,
    field: str = "file_path",
    allowed_roots: Optional[Iterable[str]] = None,
) -> ValidationReport:
    report = validate_agent_file_path_argument(file_path, field)
    if not report.ok or not file_path:
        return report

    roots = [root for root in (allowed_roots or allowed_agent_file_roots()) if root]
    if not roots:
        report.add_error(
            "No allowed filesystem root is available.",
            "Save the QGIS project first, or use a system temp path.",
            field,
        )
        return report

    resolved = os.path.abspath(os.path.normpath(file_path))
    if not any(_path_within(resolved, root) for root in roots):
        report.add_error(
            f"Path is outside allowed roots: {resolved}",
            "Use a path inside the current QGIS project folder or system temp folder.",
            field,
        )
    return report


def validate_safe_name(value: str, field: str = "name") -> ValidationReport:
    report = ValidationReport()
    if not isinstance(value, str) or not value.strip():
        report.add_error(f"{field} is empty.", "Use a short ASCII identifier.", field)
        return report
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value.strip()):
        report.add_error(
            f"{field} contains unsafe characters: {value}",
            "Use only letters, numbers, underscore, and hyphen.",
            field,
        )
    return report


def sanitize_file_stem(value: str, fallback: str = "output") -> str:
    text = str(value or "").strip()
    text = os.path.basename(text.replace("\\", "/"))
    text = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", text).strip("._-")
    return text[:80] or fallback


def validate_layer_name(layer_name: str, require_vector: bool = False, require_raster: bool = False) -> ValidationReport:
    report = ValidationReport()
    if not layer_name:
        report.add_error("Layer name is empty.", "Use list_layers first, then pass an exact layer name.", "layer_name")
        return report

    try:
        from qgis.core import QgsMapLayerType, QgsProject
    except Exception as exc:
        report.add_error(
            f"QGIS layer validation is unavailable: {exc}",
            "Run this validation inside QGIS.",
            "layer_name",
        )
        return report

    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        report.add_error(
            f"Layer not found: {layer_name}",
            "Use list_layers first and retry with the exact name.",
            "layer_name",
        )
        return report

    layer = layers[0]
    layer_type = layer.type()
    if require_vector and layer_type != QgsMapLayerType.VectorLayer:
        report.add_error(f"Layer is not vector: {layer_name}", "Choose a vector layer.", "layer_name")
    if require_raster and layer_type != QgsMapLayerType.RasterLayer:
        report.add_error(f"Layer is not raster: {layer_name}", "Choose a raster layer.", "layer_name")

    try:
        crs = layer.crs()
        if not crs or not crs.isValid():
            report.add_warning(
                f"Layer CRS is missing or invalid: {layer_name}",
                "Set or reproject the layer before spatial analysis.",
                "layer_name",
            )
    except Exception:
        pass
    return report


def validate_processing_request(alg_id: str, parameters: Dict[str, Any]) -> ValidationReport:
    report = validate_required({"alg_id": alg_id, "parameters": parameters}, ["alg_id", "parameters"])
    if not report.ok:
        return report

    if ":" not in str(alg_id):
        report.add_warning(
            f"Processing algorithm id looks unusual: {alg_id}",
            "Use a provider-qualified id such as native:buffer or gdal:slope.",
            "alg_id",
        )

    if not isinstance(parameters, dict):
        report.add_error("Processing parameters must be a dictionary.", "Pass a JSON object for parameters.", "parameters")
        return report

    output_keys = [key for key in parameters.keys() if key.upper().endswith("OUTPUT") or key.upper() == "OUTPUT"]
    if not output_keys:
        report.add_warning(
            "No explicit output parameter was provided.",
            "Most processing algorithms require OUTPUT or another *_OUTPUT parameter.",
            "parameters",
        )
    for key in output_keys:
        value = parameters.get(key)
        if isinstance(value, str) and value and value not in {"TEMPORARY_OUTPUT", "memory:"}:
            if ".." in value.replace("\\", "/").split("/"):
                report.add_error(
                    f"Processing output path contains traversal: {value}",
                    "Choose a safe project-relative or absolute output path.",
                    f"parameters.{key}",
                )
            if os.path.exists(value):
                report.add_error(
                    f"Processing output path already exists: {value}",
                    "Choose a new output path or ask the user before overwriting.",
                    f"parameters.{key}",
                )
    return report


def validate_pyqgis_code(code: str) -> ValidationReport:
    report = ValidationReport()
    if not isinstance(code, str) or not code.strip():
        report.add_error("Python code is empty.", "Provide a complete executable script.", "code")
        return report

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        report.add_error(
            f"Python syntax error: {exc.msg}",
            "Fix the code so it can be parsed before execution.",
            "code",
        )
        return report

    _add_code_security_findings(report, code)

    if re.search(r"from\s+qgis\.core\s+import[^\n]*\bQgsRasterCalculator\b", code):
        report.add_error(
            "QgsRasterCalculator is not imported from qgis.core in QGIS 3.44.",
            "Use `from qgis.analysis import QgsRasterCalculator` instead.",
            "code",
        )

    if "QgsColorRampShaderItem" in code:
        report.add_error(
            "QgsColorRampShaderItem is not imported directly from qgis.core in QGIS 3.44.",
            "Call repair_common_qgis_code_issues, or use `QgsColorRampShader.ColorRampItem(...)`.",
            "code",
        )

    if re.search(r"QgsColorRampShader\.ColorRampItem\(\s*[^,\n]+,\s*['\"]#[0-9A-Fa-f]{6,8}['\"]\s*,", code):
        report.add_error(
            "QgsColorRampShader.ColorRampItem color argument must be a QColor object.",
            "Call repair_common_qgis_code_issues, or wrap hex strings as `QColor('#1a9850')`.",
            "code",
        )

    if re.search(r"\bdict\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\.attributes\(\)\s*\)", code):
        report.add_error(
            "QgsFeature.attributes() returns a list, so dict(feature.attributes()) is invalid.",
            "Use `field_names = [f.name() for f in layer.fields()]` then `dict(zip(field_names, feature.attributes()))`.",
            "code",
        )

    if "OSMDownloader.download_features" in code:
        report.add_error(
            "OSMDownloader.download_features does not exist.",
            "Use the registered `download_osm_features` tool, or call `OSMDownloader.query_osm()` and `load_osm_layer()`.",
            "code",
        )

    if re.search(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*,\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*QgsVectorFileWriter\.writeAsVectorFormatV3\s*\(", code, flags=re.MULTILINE):
        report.add_warning(
            "writeAsVectorFormatV3 return arity varies across QGIS builds.",
            "Assign to `result`, then use `err = result[0] if isinstance(result, tuple) else result`.",
            "code",
        )

    if re.search(r"\.type\(\)\.toString\(\)", code):
        report.add_error(
            "LayerType/QgsMapLayerType does not support `.toString()`.",
            "Call repair_common_qgis_code_issues, or use `str(layer.type())`.",
            "code",
        )

    if "download_boundary_nominatim" in code:
        allowed_keywords = {"name", "output_file", "layer_name"}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_nominatim_call = (
                isinstance(func, ast.Attribute)
                and func.attr == "download_boundary_nominatim"
                and isinstance(func.value, ast.Name)
                and func.value.id == "OSMDownloader"
            )
            if not is_nominatim_call:
                continue
            keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
            unsupported = sorted(keyword_names - allowed_keywords)
            if unsupported:
                report.add_error(
                    "OSMDownloader.download_boundary_nominatim was called with unsupported keyword names.",
                    "Use `download_boundary_nominatim(name, output_file, layer_name=None)`. "
                    f"Unsupported keyword(s): {', '.join(unsupported)}.",
                    "code",
                )
            has_output = len(node.args) >= 2 or "output_file" in keyword_names
            if not has_output:
                report.add_error(
                    "OSMDownloader.download_boundary_nominatim is missing output_file.",
                    "Provide the output path as the second positional argument or as `output_file=...`.",
                    "code",
                )

    if re.search(r"\.constGet\(\)\.numPoints\(\)|\.numPoints\(\)", code):
        report.add_warning(
            "numPoints() is fragile on QGIS 3.44 geometry internals.",
            "Call repair_common_qgis_code_issues, or use vertexCount().",
            "code",
        )

    if re.search(r"\.\s*(maximumValue|minimumValue)\s*\(", code):
        report.add_error(
            "Raster maximumValue()/minimumValue() calls are fragile or unavailable in QGIS 3.44.",
            (
                "Use `provider.bandStatistics(1, QgsRasterBandStats.All)` and then read "
                "`stats.maximumValue` or `stats.minimumValue`."
            ),
            "code",
        )

    if re.search(r"QgsProject\.instance\(\)\.addMapLayer\s*\(", code):
        report.add_warning(
            "Direct addMapLayer() can duplicate file-backed layers after retries.",
            "Prefer load_vector_layer/load_raster_layer, or call repair_common_qgis_code_issues for guidance.",
            "code",
        )

    if re.search(r"QgsRasterFileWriter|\.writeRaster\s*\(", code):
        report.add_warning(
            "QgsRasterFileWriter.writeRaster() is deprecated/noisy in recent QGIS.",
            "Prefer processing.run('gdal:translate', ...) or a dedicated raster-save helper.",
            "code",
        )

    if re.search(r"QgsSingleBandPseudoColorRenderer\s*\(\s*(layer|raster_layer|.*_layer)\s*,", code):
        report.add_error(
            "QgsSingleBandPseudoColorRenderer expects a raster data provider as its first argument.",
            "Pass `raster_layer.dataProvider()` instead of the layer object.",
            "code",
        )

    if re.search(r"level\s*=\s*Qgis\.(Info|Warning|Critical|Success)\b", code):
        report.add_warning(
            "Qgis message level aliases are less stable in QGIS 3.44.",
            "Prefer `Qgis.MessageLevel.Info/Warning/Critical/Success`.",
            "code",
        )

    return report


def _add_code_security_findings(report: ValidationReport, code: str) -> None:
    blocking_patterns = [
        (
            r"\bsubprocess\.(run|Popen|call|check_call|check_output)\s*\(",
            "Subprocess calls are blocked in agent PyQGIS scripts.",
            "Use a registered tool or QGIS/Python API instead of launching external processes.",
        ),
        (
            r"\bos\.system\s*\(",
            "os.system calls are blocked in agent PyQGIS scripts.",
            "Use a registered tool or QGIS/Python API instead of shell commands.",
        ),
        (
            r"\bpip_main\s*\(|\bpip\._internal\b|python\s+-m\s+pip|\bpip\s+install\b",
            "Package installation inside PyQGIS scripts is blocked.",
            "Use the install_python_package tool instead.",
        ),
    ]
    warning_patterns = [
        (
            r"\brequests\.(get|post|put|delete|patch)\s*\(|\burllib\.request\b|\bhttpx\.(get|post|put|delete|patch)\s*\(",
            "The script performs network access.",
            "Prefer registered data-source tools and ensure the data source is documented.",
        ),
        (
            r"\bopen\s*\([^)]*,\s*['\"][wa]\b|\bQgsVectorFileWriter\b|\bQgsRasterFileWriter\b|\bwriteAsVectorFormat",
            "The script appears to write files.",
            "Ensure the target path is inside the project or temp folder and approval is requested when needed.",
        ),
        (
            r"\bos\.(remove|unlink|rmdir)\s*\(|\bshutil\.rmtree\s*\(|\bremoveMapLayer\s*\(",
            "The script may delete files, layers, or project data.",
            "This must be explicitly approved before execution.",
        ),
    ]

    for pattern, message, suggestion in blocking_patterns:
        if re.search(pattern, code, flags=re.IGNORECASE):
            report.add_error(message, suggestion, "code")
    for pattern, message, suggestion in warning_patterns:
        if re.search(pattern, code, flags=re.IGNORECASE):
            report.add_warning(message, suggestion, "code")


def validate_tool_call(tool_name: str, kwargs: Dict[str, Any]) -> ValidationReport:
    from .tool_registry import get_tool_spec

    kwargs = kwargs or {}
    report = ValidationReport()
    spec = get_tool_spec(tool_name)
    if not spec:
        report.add_error(
            f"Unknown or unregistered tool: {tool_name}",
            "Use only tools listed in the registry.",
            "tool_name",
        )
        return report

    required = spec.args_schema.get("required", []) if isinstance(spec.args_schema, dict) else []
    required_report = validate_required(kwargs, required)
    report.ok = required_report.ok
    report.issues.extend(required_report.issues)
    if not report.ok:
        return report

    schema_report = validate_schema_values(kwargs, spec.args_schema)
    report.ok = report.ok and schema_report.ok
    report.issues.extend(schema_report.issues)
    if not report.ok:
        return report

    if tool_name in {"zoom_to_layer", "set_layer_visibility"}:
        layer_report = validate_layer_name(kwargs.get("layer_name", ""))
        report.ok = report.ok and layer_report.ok
        report.issues.extend(layer_report.issues)
    elif tool_name in {
        "inspect_layer_fields",
        "get_selected_features",
        "select_features_by_expression",
        "zoom_to_selected",
    }:
        layer_report = validate_layer_name(kwargs.get("layer_name", ""), require_vector=True)
        report.ok = report.ok and layer_report.ok
        report.issues.extend(layer_report.issues)
    elif tool_name == "run_processing_algorithm":
        processing_report = validate_processing_request(
            kwargs.get("alg_id", ""),
            kwargs.get("parameters", {}),
        )
        report.ok = report.ok and processing_report.ok
        report.issues.extend(processing_report.issues)
    elif tool_name == "clip_vector_layers_to_boundary":
        boundary_report = validate_layer_name(kwargs.get("boundary_layer_name", ""), require_vector=True)
        report.ok = report.ok and boundary_report.ok
        report.issues.extend(boundary_report.issues)
        output_dir_report = validate_path_within_allowed_roots(kwargs.get("output_dir", ""), "output_dir")
        report.ok = report.ok and output_dir_report.ok
        report.issues.extend(output_dir_report.issues)
        clip_tasks = kwargs.get("clip_tasks", [])
        if not isinstance(clip_tasks, list) or not clip_tasks:
            report.add_error(
                "clip_tasks must be a non-empty list.",
                "Provide one explicit clipping task per input layer.",
                "clip_tasks",
            )
        else:
            for index, task in enumerate(clip_tasks):
                if not isinstance(task, dict):
                    report.add_error(
                        f"clip_tasks[{index}] must be an object.",
                        "Use input_layer_name, output_name, and output_layer_name.",
                        f"clip_tasks[{index}]",
                    )
                    continue
                for key in ("input_layer_name", "output_name", "output_layer_name"):
                    if not task.get(key):
                        report.add_error(
                            f"clip_tasks[{index}].{key} is required.",
                            "Use explicit layer/file names instead of deriving names from text.",
                            f"clip_tasks[{index}].{key}",
                        )
                output_name = str(task.get("output_name", ""))
                output_parts = [part for part in output_name.replace("\\", "/").split("/") if part]
                if ".." in output_parts or len(output_parts) > 1:
                    report.add_error(
                        f"clip_tasks[{index}].output_name must be a file name, not a path: {output_name}",
                        "Put the folder in output_dir and only the file name in output_name.",
                        f"clip_tasks[{index}].output_name",
                    )
        project_path = kwargs.get("project_path", "")
        if project_path:
            project_path_report = validate_path_within_allowed_roots(project_path, "project_path")
            report.ok = report.ok and project_path_report.ok
            report.issues.extend(project_path_report.issues)
    elif tool_name == "save_project_and_verify":
        project_path = kwargs.get("project_path", "")
        if project_path:
            project_path_report = validate_path_within_allowed_roots(project_path, "project_path")
            report.ok = report.ok and project_path_report.ok
            report.issues.extend(project_path_report.issues)
    elif tool_name == "create_geodatabase":
        db_path = kwargs.get("database_path", "")
        if db_path:
            agent_path_report = validate_path_within_allowed_roots(db_path, "database_path")
            report.ok = report.ok and agent_path_report.ok
            report.issues.extend(agent_path_report.issues)
            path_report = validate_output_path(db_path, allow_overwrite=False)
            report.ok = report.ok and path_report.ok
            report.issues.extend(path_report.issues)
    elif tool_name in {"read_file", "write_file", "replace_file_content"}:
        file_path_report = validate_agent_file_path_argument(kwargs.get("file_path", ""))
        report.ok = report.ok and file_path_report.ok
        report.issues.extend(file_path_report.issues)
    elif tool_name == "cleanup_qgis_project":
        for field in ("cleanup_chunk_files_dir", "cleanup_wal_files_dir"):
            value = kwargs.get(field, "")
            if value:
                path_report = validate_path_within_allowed_roots(value, field)
                report.ok = report.ok and path_report.ok
                report.issues.extend(path_report.issues)
    elif tool_name == "validate_project_outputs":
        for index, value in enumerate(kwargs.get("expected_files", []) or []):
            path_report = validate_path_within_allowed_roots(value, f"expected_files[{index}]")
            report.ok = report.ok and path_report.ok
            report.issues.extend(path_report.issues)
    elif tool_name == "run_qgis_workflow_batch":
        for index, step in enumerate(kwargs.get("steps", []) or []):
            action = (step or {}).get("action", "")
            if action not in {
                "summarize_layers",
                "cleanup_qgis_project",
                "validate_project_outputs",
                "save_project_and_verify",
                "download_osm_features",
                "clip_vector_layers_to_boundary",
                "run_processing_algorithm",
            }:
                report.add_error(
                    f"Unsupported batch action: {action}",
                    "Use a registered workflow action allowed by run_qgis_workflow_batch.",
                    f"steps[{index}].action",
                )
    elif tool_name == "download_osm_data":
        layer_name_report = validate_safe_name(
            sanitize_file_stem(kwargs.get("layer_name", "OSM_Data"), "OSM_Data"),
            "layer_name",
        )
        report.ok = report.ok and layer_name_report.ok
        report.issues.extend(layer_name_report.issues)
        bbox = kwargs.get("bbox", "")
        try:
            values = [float(value) for value in str(bbox).split(",")]
            if len(values) != 4:
                raise ValueError
            min_lon, min_lat, max_lon, max_lat = values
            if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
                report.add_error(
                    "bbox values are outside valid WGS84 bounds or not ordered.",
                    "Use 'min_lon,min_lat,max_lon,max_lat' in EPSG:4326.",
                    "bbox",
                )
            area = (max_lon - min_lon) * (max_lat - min_lat)
            if area > 5.0:
                report.add_error(
                    f"bbox is too large for direct Overpass download: {area:.2f} square degrees.",
                    "Use a smaller bbox, a named boundary workflow, or a regional extract source.",
                    "bbox",
                )
        except Exception:
            report.add_error(
                "bbox must be four comma-separated numbers.",
                "Use 'min_lon,min_lat,max_lon,max_lat' in EPSG:4326.",
                "bbox",
            )
    elif tool_name in {"download_osm_boundary", "download_osm_roads", "download_osm_features"}:
        output_file = kwargs.get("output_file", "")
        if output_file:
            output_path_report = validate_path_within_allowed_roots(output_file, "output_file")
            report.ok = report.ok and output_path_report.ok
            report.issues.extend(output_path_report.issues)
            if not bool(kwargs.get("overwrite", False)):
                output_exists_report = validate_output_path(output_file, allow_overwrite=False)
                report.ok = report.ok and output_exists_report.ok
                report.issues.extend(output_exists_report.issues)
        layer_name = kwargs.get("layer_name", "") or kwargs.get("name", "")
        if layer_name:
            layer_name_report = validate_safe_name(sanitize_file_stem(layer_name, "osm_layer"), "layer_name")
            report.ok = report.ok and layer_name_report.ok
            report.issues.extend(layer_name_report.issues)
        if tool_name == "download_osm_features":
            preset = kwargs.get("preset", "buildings")
            if preset and preset not in {"buildings", "roads", "waterways", "water", "poi", "landuse"}:
                report.add_error(
                    f"Unknown OSM preset: {preset}",
                    "Use one of buildings, roads, waterways, water, poi, or landuse.",
                    "preset",
                )
            bbox = kwargs.get("bbox", "")
            if bbox:
                try:
                    values = [float(value) for value in str(bbox).split(",")]
                    if len(values) != 4:
                        raise ValueError
                    min_lon, min_lat, max_lon, max_lat = values
                    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
                        report.add_error(
                            "bbox values are outside valid WGS84 bounds or not ordered.",
                            "Use 'min_lon,min_lat,max_lon,max_lat' in EPSG:4326.",
                            "bbox",
                        )
                    area = (max_lon - min_lon) * (max_lat - min_lat)
                    if area > 5.0 and not bool(kwargs.get("split_large_bbox", True)):
                        report.add_error(
                            f"bbox is too large for a single Overpass request: {area:.2f} square degrees.",
                            "Set split_large_bbox=true or use a smaller bbox.",
                            "bbox",
                        )
                except Exception:
                    report.add_error(
                        "bbox must be four comma-separated numbers.",
                        "Use 'min_lon,min_lat,max_lon,max_lat' in EPSG:4326.",
                        "bbox",
                    )
            elif not kwargs.get("boundary_layer_name"):
                report.add_error(
                    "download_osm_features requires bbox or boundary_layer_name.",
                    "Provide a WGS84 bbox or an existing boundary layer.",
                    "bbox",
                )
    elif tool_name == "execute_pyqgis_script":
        code_report = validate_pyqgis_code(kwargs.get("code", ""))
        report.ok = report.ok and code_report.ok
        report.issues.extend(code_report.issues)
    elif tool_name in {"read_skill", "save_or_update_dynamic_skill", "save_skill"}:
        name_report = validate_safe_name(kwargs.get("skill_name", ""), "skill_name")
        report.ok = report.ok and name_report.ok
        report.issues.extend(name_report.issues)

    return report
