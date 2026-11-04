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
    except (ValueError, TypeError, OSError):
        return False


def qgis_project_home() -> str:
    try:
        from qgis.core import QgsProject

        home = QgsProject.instance().homePath()
        if not isinstance(home, str) or not home.strip() or "MagicMock" in home:
            return ""
        return home
    except (ImportError, AttributeError, RuntimeError, TypeError):
        return ""


def base_agent_file_roots(project_home: str = "") -> List[str]:
    roots = [tempfile.gettempdir()]
    project_home = project_home or qgis_project_home()
    if project_home:
        roots.append(project_home)
    return roots


def allowed_agent_file_roots(project_home: str = "") -> List[str]:
    """Return normal roots plus one-task external roots approved by the user."""
    roots = base_agent_file_roots(project_home)
    try:
        from .path_access import list_granted_write_roots

        roots.extend(list_granted_write_roots())
    except (ImportError, AttributeError, RuntimeError, TypeError):
        pass
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


def _is_internal_output_path(path: str) -> bool:
    return any(
        _path_within(path, root)
        for root in base_agent_file_roots()
        if root
    )


def _add_external_write_target(targets: List[Dict[str, Any]], field: str, path: Any, is_directory: bool) -> None:
    value = str(path or "").strip()
    if not value or value in {"TEMPORARY_OUTPUT", "memory:"}:
        return
    if _is_internal_output_path(value):
        return
    targets.append({"field": field, "path": os.path.abspath(os.path.normpath(value)), "is_directory": is_directory})


def external_write_targets(tool_name: str, kwargs: Dict[str, Any], field_prefix: str = "") -> List[Dict[str, Any]]:
    """List output locations requiring one-task approval outside project/temp roots."""
    kwargs = kwargs or {}
    targets: List[Dict[str, Any]] = []
    prefix = field_prefix
    file_fields = {
        "save_project_and_verify": ("project_path",),
        "create_geodatabase": ("database_path",),
        "download_osm_data": ("output_file",),
        "download_osm_boundary": ("output_file",),
        "download_osm_roads": ("output_file",),
        "download_osm_features": ("output_file",),
    }
    directory_fields = {
        "clip_vector_layers_to_boundary": ("output_dir",),
        "cleanup_qgis_project": ("cleanup_chunk_files_dir", "cleanup_wal_files_dir"),
        "run_gee_sentinel2_download_workflow": ("output_dir",),
        "run_gee_dem_download_workflow": ("output_dir",),
        "run_osm_acquisition_workflow": ("output_dir",),
    }
    for field in file_fields.get(tool_name, ()):
        _add_external_write_target(targets, f"{prefix}{field}", kwargs.get(field), False)
    for field in directory_fields.get(tool_name, ()):
        _add_external_write_target(targets, f"{prefix}{field}", kwargs.get(field), True)
    if tool_name in {"clip_vector_layers_to_boundary", "run_osm_acquisition_workflow"}:
        _add_external_write_target(targets, f"{prefix}project_path", kwargs.get("project_path"), False)
    if tool_name == "run_processing_algorithm":
        parameters = kwargs.get("parameters") or {}
        if isinstance(parameters, dict):
            for key, value in parameters.items():
                if str(key).upper().endswith("OUTPUT") or str(key).upper() == "OUTPUT":
                    _add_external_write_target(targets, f"{prefix}parameters.{key}", value, False)
    if tool_name == "run_qgis_workflow_batch":
        for index, step in enumerate(kwargs.get("steps") or []):
            if not isinstance(step, dict):
                continue
            child_name = str(step.get("action") or "")
            child_args = step.get("arguments") or {}
            targets.extend(external_write_targets(
                child_name,
                child_args,
                field_prefix=f"{prefix}steps[{index}].arguments.",
            ))
    deduped = []
    seen = set()
    for target in targets:
        key = (target["path"], target["is_directory"])
        if key not in seen:
            seen.add(key)
            deduped.append(target)
    return deduped


def report_has_only_external_path_errors(report: ValidationReport) -> bool:
    errors = [issue for issue in report.issues if issue.level == "error"]
    if not errors:
        return False
    return all(
        "outside allowed roots" in issue.message.lower()
        or "no allowed filesystem root" in issue.message.lower()
        for issue in errors
    )


def redirect_external_outputs_to_project(
    tool_name: str,
    kwargs: Dict[str, Any],
    project_home: str,
) -> List[Dict[str, str]]:
    """Rewrite known output arguments into a saved project's agent_external_outputs folder."""
    if not project_home:
        return []
    project_home = os.path.abspath(project_home)
    redirect_root = os.path.join(project_home, "agent_external_outputs")
    changes: List[Dict[str, str]] = []

    def rewrite(container: Dict[str, Any], key: str, is_directory: bool, field: str) -> None:
        old = str(container.get(key) or "").strip()
        if not old or _is_internal_output_path(old):
            return
        base = os.path.basename(os.path.normpath(old))
        if not base:
            base = "output"
        new = os.path.join(redirect_root, base)
        container[key] = new
        changes.append({"field": field, "old_path": old, "new_path": new})

    file_fields = {
        "save_project_and_verify": ("project_path",),
        "create_geodatabase": ("database_path",),
        "download_osm_data": ("output_file",),
        "download_osm_boundary": ("output_file",),
        "download_osm_roads": ("output_file",),
        "download_osm_features": ("output_file",),
    }
    directory_fields = {
        "clip_vector_layers_to_boundary": ("output_dir",),
        "run_gee_sentinel2_download_workflow": ("output_dir",),
        "run_gee_dem_download_workflow": ("output_dir",),
        "run_osm_acquisition_workflow": ("output_dir",),
    }
    for field in file_fields.get(tool_name, ()):
        rewrite(kwargs, field, False, field)
    for field in directory_fields.get(tool_name, ()):
        rewrite(kwargs, field, True, field)
    if tool_name == "run_processing_algorithm":
        parameters = kwargs.get("parameters") or {}
        if isinstance(parameters, dict):
            for key in list(parameters):
                if str(key).upper().endswith("OUTPUT") or str(key).upper() == "OUTPUT":
                    rewrite(parameters, key, False, f"parameters.{key}")
    if tool_name == "run_qgis_workflow_batch":
        for step in kwargs.get("steps") or []:
            if isinstance(step, dict):
                changes.extend(redirect_external_outputs_to_project(
                    str(step.get("action") or ""),
                    step.setdefault("arguments", {}),
                    project_home,
                ))
    return changes


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
    except (ImportError, AttributeError, RuntimeError) as exc:
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
    except (AttributeError, RuntimeError, TypeError):
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
            path_report = validate_path_within_allowed_roots(value, f"parameters.{key}")
            report.ok = report.ok and path_report.ok
            report.issues.extend(path_report.issues)
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

    from .code_execution_guard import analyze_main_thread_code
    from .validation_rules import (
        PYQGIS_API_VALIDATION_RULES,
        apply_rule_table,
        check_nominatim_ast_calls,
    )
    for finding in analyze_main_thread_code(code):
        message = finding.message
        if finding.line:
            message = f"Line {finding.line}: {message}"
        report.add_error(message, finding.suggestion, "code")

    apply_rule_table(report, code, PYQGIS_API_VALIDATION_RULES)
    check_nominatim_ast_calls(report, code, tree)

    return report


def _add_code_security_findings(report: ValidationReport, code: str) -> None:
    from .validation_rules import (
        CODE_SECURITY_BLOCKING_RULES,
        CODE_SECURITY_WARNING_RULES,
        apply_rule_table,
    )
    apply_rule_table(report, code, CODE_SECURITY_BLOCKING_RULES)
    apply_rule_table(report, code, CODE_SECURITY_WARNING_RULES)


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

    if tool_name == "activate_domain_tools":
        from .request_profile import DOMAIN_TOOL_PACKS

        domains = kwargs.get("domains")
        if not isinstance(domains, list) or not domains:
            report.add_error(
                "domains must contain at least one built-in domain.",
                "Choose one or more supported domains before retrying.",
                "domains",
            )
        else:
            invalid = sorted({str(domain) for domain in domains if str(domain) not in DOMAIN_TOOL_PACKS})
            if invalid:
                report.add_error(
                    "Unsupported domain(s): " + ", ".join(invalid),
                    "Use one of: " + ", ".join(sorted(DOMAIN_TOOL_PACKS)),
                    "domains",
                )
    elif tool_name in {"zoom_to_layer", "set_layer_visibility"}:
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
    elif tool_name in {"read_file", "write_file", "replace_file_content", "load_external_layer"}:
        file_path_report = validate_agent_file_path_argument(kwargs.get("file_path", ""))
        if tool_name == "load_external_layer":
            file_path_report = validate_agent_file_path_argument(kwargs.get("source_path", ""), "source_path")
        report.ok = report.ok and file_path_report.ok
        report.issues.extend(file_path_report.issues)
    elif tool_name == "cleanup_qgis_project":
        for field in ("cleanup_chunk_files_dir", "cleanup_wal_files_dir"):
            value = kwargs.get(field, "")
            if value:
                path_report = validate_path_within_allowed_roots(value, field)
                report.ok = report.ok and path_report.ok
                report.issues.extend(path_report.issues)
    elif tool_name == "remove_qgis_layers_and_data":
        scope = str(kwargs.get("scope") or "")
        if scope == "named_layers":
            names = kwargs.get("layer_names")
            if not isinstance(names, list) or not any(str(name).strip() for name in names):
                report.add_error(
                    "layer_names must contain at least one layer when scope is named_layers.",
                    "Use exact QGIS layer names or IDs, or choose scope=all_layers.",
                    "layer_names",
                )
    elif tool_name in {"run_gee_sentinel2_download_workflow", "run_gee_dem_download_workflow"}:
        output_dir_report = validate_path_within_allowed_roots(kwargs.get("output_dir", ""), "output_dir")
        report.ok = report.ok and output_dir_report.ok
        report.issues.extend(output_dir_report.issues)
        if kwargs.get("user_confirmed_parameters") is not True:
            report.add_error(
                "GEE parameters were not explicitly confirmed by the user.",
                "Call ask_human and set user_confirmed_parameters=true only after the user responds.",
                "user_confirmed_parameters",
            )
        try:
            scale = float(kwargs.get("scale"))
            if not 1 <= scale <= 10000:
                raise ValueError
        except (TypeError, ValueError):
            report.add_error("scale must be between 1 and 10000 meters.", "Ask the user to confirm a valid scale.", "scale")
        crs = str(kwargs.get("crs") or "").strip().upper()
        if not re.fullmatch(r"EPSG:\d{3,6}", crs):
            report.add_error("crs must be an EPSG authority id such as EPSG:4326.", "Ask the user to confirm the output CRS.", "crs")
        try:
            min_valid_percent = float(kwargs.get("min_valid_percent", 0.01))
            if not 0 <= min_valid_percent <= 100:
                raise ValueError
        except (TypeError, ValueError):
            report.add_error("min_valid_percent must be between 0 and 100.", "Use a valid percentage threshold.", "min_valid_percent")
        if tool_name == "run_gee_sentinel2_download_workflow":
            from datetime import datetime
            try:
                start = datetime.strptime(str(kwargs.get("start_date")), "%Y-%m-%d")
                end = datetime.strptime(str(kwargs.get("end_date")), "%Y-%m-%d")
                if start >= end:
                    raise ValueError
            except (TypeError, ValueError):
                report.add_error("Sentinel-2 dates must be valid YYYY-MM-DD values with start_date before end_date.", "Confirm the date range.", "start_date")
            try:
                cloud_pct = float(kwargs.get("cloud_pct"))
                if not 0 <= cloud_pct <= 100:
                    raise ValueError
            except (TypeError, ValueError):
                report.add_error("cloud_pct must be between 0 and 100.", "Confirm the cloud threshold.", "cloud_pct")
    elif tool_name == "compute_raster_index":
        output_path = kwargs.get("output_path", "")
        if output_path:
            path_report = validate_path_within_allowed_roots(output_path, "output_path")
            report.ok = report.ok and path_report.ok
            report.issues.extend(path_report.issues)
        for band_key in ("band_a", "band_b"):
            try:
                if int(kwargs.get(band_key, 0)) < 1:
                    raise ValueError
            except (TypeError, ValueError):
                report.add_error(
                    f"{band_key} must be a 1-based positive integer band number.",
                    "Inspect the raster bands first and pass 1-based band numbers.",
                    band_key,
                )
    elif tool_name == "validate_project_outputs":
        for index, value in enumerate(kwargs.get("expected_files", []) or []):
            path_report = validate_path_within_allowed_roots(value, f"expected_files[{index}]")
            report.ok = report.ok and path_report.ok
            report.issues.extend(path_report.issues)
    elif tool_name == "run_qgis_workflow_batch":
        from .tool_registry import BATCHABLE_TOOLS

        for index, step in enumerate(kwargs.get("steps", []) or []):
            action = (step or {}).get("action", "")
            if action not in BATCHABLE_TOOLS:
                report.add_error(
                    f"Unsupported batch action: {action}",
                    "Use a registered workflow action allowed by run_qgis_workflow_batch.",
                    f"steps[{index}].action",
                )
                continue
            child_report = validate_tool_call(action, (step or {}).get("arguments") or {})
            report.ok = report.ok and child_report.ok
            for issue in child_report.issues:
                issue.field = f"steps[{index}].arguments.{issue.field}" if issue.field else f"steps[{index}].arguments"
                report.issues.append(issue)
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
        except (TypeError, ValueError):
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
            try:
                max_chunk_area = float(kwargs.get("max_chunk_area", 0.25))
                if not 0 < max_chunk_area <= 5.0:
                    raise ValueError
            except (TypeError, ValueError):
                report.add_error(
                    "max_chunk_area must be greater than 0 and no more than 5 square degrees.",
                    "Use a smaller positive OSM chunk area, such as 0.25.",
                    "max_chunk_area",
                )
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
                except (TypeError, ValueError):
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
    elif tool_name == "create_or_update_user_tool":
        from .user_tool_extensions import validate_user_tool_definition

        definition_errors = validate_user_tool_definition(
            kwargs.get("tool_name", ""),
            kwargs.get("description", ""),
            kwargs.get("parameters_schema", {}),
            kwargs.get("source_code", ""),
            kwargs.get("domains") or ["general"],
        )
        for message in definition_errors:
            report.add_error(
                message,
                "Use a user_ name, an object parameter schema, and source defining run(iface, arguments).",
                "user_tool_definition",
            )
    elif tool_name in {"run_user_tool_extension", "register_user_tool_extension"}:
        from .user_tool_extensions import TOOL_NAME_PATTERN

        if not TOOL_NAME_PATTERN.fullmatch(str(kwargs.get("tool_name", ""))):
            report.add_error(
                "tool_name must refer to a user-scoped tool name beginning with user_.",
                "Use the name returned by create_or_update_user_tool or list_user_tool_extensions.",
                "tool_name",
            )
    elif tool_name == "install_python_package":
        from .validation_rules import ALLOWED_INSTALL_PACKAGES

        package_spec = str(kwargs.get("package_name", "")).strip()
        package_name = re.split(r"[<>=!~\[]", package_spec, maxsplit=1)[0].lower().replace("_", "-")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~]{1,2}[A-Za-z0-9*_.+-]+)?", package_spec):
            report.add_error(
                "package_name is not a safe package specification.",
                "Use a package name such as 'pandas' or a pinned version such as 'pandas==2.2.0'.",
                "package_name",
            )
        elif package_name not in ALLOWED_INSTALL_PACKAGES:
            report.add_error(
                f"Package is not in the QGIS Agent dependency allowlist: {package_name}",
                "Install it manually after reviewing its source, or add it to ALLOWED_INSTALL_PACKAGES in validation_rules.py.",
                "package_name",
            )
    elif tool_name in {"read_skill", "save_or_update_dynamic_skill", "save_skill"}:
        name_report = validate_safe_name(kwargs.get("skill_name", ""), "skill_name")
        report.ok = report.ok and name_report.ok
        report.issues.extend(name_report.issues)

    return report
