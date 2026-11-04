"""User-scoped executable tool extensions.

Extensions are intentionally kept outside the plugin installation directory.  They are
created only after a high-risk approval, tested as candidates in the current task, and
registered for future tasks only after a separate verified-registration approval.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .code_execution_guard import (
    DEFAULT_MAIN_THREAD_TIMEOUT_SECONDS,
    analyze_main_thread_code,
    build_restricted_builtins,
    execution_deadline,
)


REGISTRY_FILE_NAME = "registry.json"
REGISTRY_SCHEMA_VERSION = 1
TOOL_NAME_PATTERN = re.compile(r"^user_[A-Za-z][A-Za-z0-9_]{2,63}$")
ALLOWED_DOMAINS = {
    "osm",
    "gee",
    "processing",
    "mapping",
    "selection",
    "files",
    "workflow",
    "database",
    "general",
}


class UserToolDefinitionError(ValueError):
    """Raised when an extension definition cannot be safely stored or run."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def get_user_tool_root(create: bool = False) -> Path:
    """Return the active QGIS profile's user-tool directory.

    An environment override keeps the module deterministic in tests and is also useful
    for managed deployments.  Normal QGIS installations use qgisSettingsDirPath(), so
    the location follows the active profile rather than the QGIS installation drive.
    """

    override = os.environ.get("QGIS_AGENT_USER_TOOL_ROOT", "").strip()
    if override:
        root = Path(override).expanduser()
    else:
        try:
            from qgis.core import QgsApplication

            raw_root = QgsApplication.qgisSettingsDirPath()
            settings_root = raw_root.strip() if isinstance(raw_root, str) else ""
            if "MagicMock" in settings_root or settings_root.startswith("<"):
                settings_root = ""
        except Exception:
            settings_root = ""
        if settings_root:
            root = Path(settings_root) / "qgis_agent" / "user_tools"
        else:
            root = Path(tempfile.gettempdir()) / "qgis_agent" / "user_tools"

    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _registry_path() -> Path:
    return get_user_tool_root(create=True) / REGISTRY_FILE_NAME


def _empty_registry() -> Dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "tools": {},
    }


def _read_registry() -> Dict[str, Any]:
    path = _registry_path()
    if not path.exists():
        return _empty_registry()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _empty_registry()
    if not isinstance(value, dict) or not isinstance(value.get("tools"), dict):
        return _empty_registry()
    value.setdefault("schema_version", REGISTRY_SCHEMA_VERSION)
    return value


def _write_registry(registry: Dict[str, Any]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True))


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    temp_path = ""
    try:
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temp_path = handle.name
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temp_path, path)
    finally:
        if handle is not None:
            handle.close()
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _source_path(tool_name: str) -> Path:
    return get_user_tool_root(create=True) / f"{tool_name}.py"


def _is_json_schema_object(schema: Any) -> bool:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        return False
    if any(not isinstance(name, str) or not name for name in properties):
        return False
    if any(item not in properties for item in required):
        return False
    for property_schema in properties.values():
        if not isinstance(property_schema, dict):
            return False
        property_type = property_schema.get("type")
        if property_type not in {"string", "number", "integer", "boolean", "array", "object"}:
            return False
        if property_type == "array" and "items" in property_schema and not isinstance(property_schema["items"], dict):
            return False
    return True


def _validate_source_contract(source_code: str) -> List[str]:
    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        return [f"Python syntax error: {exc.msg}"]

    errors: List[str] = []
    run_functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    ]
    if len(run_functions) != 1:
        errors.append("Source code must define exactly one run(iface, arguments) function.")
    else:
        function = run_functions[0]
        positional = list(function.args.posonlyargs) + list(function.args.args)
        if len(positional) != 2 or [argument.arg for argument in positional] != ["iface", "arguments"]:
            errors.append("The extension entry point must be exactly run(iface, arguments).")
        if function.args.vararg or function.args.kwarg or function.args.kwonlyargs:
            errors.append("run(iface, arguments) must not use variadic or keyword-only parameters.")

    allowed_top_level = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if not isinstance(node, allowed_top_level):
            errors.append(
                "Only imports, class declarations, function declarations, and a module docstring are allowed at module level."
            )
            break

    blocked_patterns = (
        (r"\bsubprocess\b", "subprocess is not allowed in user tools."),
        (r"\bos\.system\s*\(", "os.system is not allowed in user tools."),
        (r"\bpip\._internal\b|\bpip_main\s*\(", "Package installation is not allowed in user tools."),
        (r"\bexec\s*\(|\beval\s*\(|\bcompile\s*\(", "Dynamic code evaluation is not allowed in user tools."),
        (r"\b__import__\s*\(", "Dynamic imports are not allowed in user tools."),
    )
    for pattern, message in blocked_patterns:
        if re.search(pattern, source_code, flags=re.IGNORECASE):
            errors.append(message)

    guard_findings = analyze_main_thread_code(source_code)
    for finding in guard_findings:
        prefix = f"line {finding.line}: " if finding.line else ""
        msg = f"{prefix}{finding.message}"
        if msg not in errors:
            errors.append(msg)
    return errors


def validate_user_tool_definition(
    tool_name: Any,
    description: Any,
    parameters_schema: Any,
    source_code: Any,
    domains: Optional[Iterable[Any]] = None,
) -> List[str]:
    """Return definition errors without writing any user-controlled content."""

    errors: List[str] = []
    if not isinstance(tool_name, str) or not TOOL_NAME_PATTERN.fullmatch(tool_name):
        errors.append("tool_name must start with user_ and contain 4-64 letters, digits, or underscores.")
    if not isinstance(description, str) or not (8 <= len(description.strip()) <= 500):
        errors.append("description must contain 8-500 characters.")
    if not _is_json_schema_object(parameters_schema):
        errors.append("parameters_schema must be a JSON Schema object with properties and required fields.")
    if not isinstance(source_code, str) or len(source_code.strip()) > 50000:
        errors.append("source_code must be non-empty and no longer than 50,000 characters.")
    elif source_code:
        errors.extend(_validate_source_contract(source_code))

    normalized_domains = list(domains or ["general"])
    if not normalized_domains or any(not isinstance(domain, str) or domain not in ALLOWED_DOMAINS for domain in normalized_domains):
        errors.append("domains must use supported domains: " + ", ".join(sorted(ALLOWED_DOMAINS)) + ".")
    return errors


def _sanitize_definition(definition: Dict[str, Any], include_source: bool = False) -> Dict[str, Any]:
    safe_keys = {
        "tool_name",
        "description",
        "parameters_schema",
        "domains",
        "status",
        "created_at",
        "updated_at",
        "registered_at",
        "execution_count",
        "success_count",
        "last_execution_at",
        "last_error",
        "verification_summary",
        "source_file",
        "source_sha256",
    }
    if include_source:
        safe_keys.add("source_code")
    return {key: definition[key] for key in sorted(safe_keys) if key in definition}


def list_user_tools(include_candidates: bool = True) -> List[Dict[str, Any]]:
    registry = _read_registry()
    rows = []
    for name, definition in registry.get("tools", {}).items():
        if not isinstance(definition, dict):
            continue
        if definition.get("tool_name") != name:
            continue
        if not include_candidates and definition.get("status") != "registered":
            continue
        rows.append(_sanitize_definition(definition))
    return sorted(rows, key=lambda row: row.get("tool_name", ""))


def get_user_tool(tool_name: str, include_candidates: bool = True) -> Optional[Dict[str, Any]]:
    registry = _read_registry()
    definition = registry.get("tools", {}).get(tool_name)
    if not isinstance(definition, dict):
        return None
    if definition.get("tool_name") != tool_name:
        return None
    if not include_candidates and definition.get("status") != "registered":
        return None
    return dict(definition)


def get_registered_user_tools() -> List[Dict[str, Any]]:
    return list_user_tools(include_candidates=False)


def get_registered_user_tool_domains() -> Dict[str, List[str]]:
    return {
        row["tool_name"]: sorted(set(row.get("domains") or ["general"]))
        for row in get_registered_user_tools()
    }


def create_or_update_user_tool(
    tool_name: str,
    description: str,
    parameters_schema: Dict[str, Any],
    source_code: str,
    domains: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    errors = validate_user_tool_definition(
        tool_name,
        description,
        parameters_schema,
        source_code,
        domains,
    )
    if errors:
        return {
            "ok": False,
            "message": "User tool definition is invalid.",
            "data": {"errors": errors},
            "artifacts": [],
            "warnings": [],
            "error_type": "validation_error",
            "suggestions": ["Fix the reported definition errors and submit the candidate again."],
        }

    tool_name = tool_name.strip()
    normalized_domains = sorted(set(domains or ["general"]))
    registry = _read_registry()
    existing = registry["tools"].get(tool_name, {})
    created_at = existing.get("created_at") or _utc_now()
    definition = {
        "tool_name": tool_name,
        "description": description.strip(),
        "parameters_schema": parameters_schema,
        "domains": normalized_domains,
        "status": "candidate",
        "created_at": created_at,
        "updated_at": _utc_now(),
        # A source or contract update invalidates previous verification evidence.
        "execution_count": 0,
        "success_count": 0,
        "last_execution_at": "",
        "last_error": "",
        "verification_summary": "",
        "source_file": f"{tool_name}.py",
        "source_sha256": _sha256_text(source_code),
    }
    _atomic_write_text(_source_path(tool_name), source_code)
    registry["tools"][tool_name] = definition
    _write_registry(registry)
    return {
        "ok": True,
        "message": f"Saved candidate user tool '{tool_name}'. Test it with run_user_tool_extension before registration.",
        "data": {"tool": _sanitize_definition(definition)},
        "artifacts": [
            {
                "type": "user_tool_candidate",
                "path": str(_source_path(tool_name)),
                "description": "User-scoped candidate tool source.",
            }
        ],
        "warnings": [],
    }


def _record_execution(tool_name: str, success: bool, error: str = "") -> None:
    registry = _read_registry()
    definition = registry.get("tools", {}).get(tool_name)
    if not isinstance(definition, dict):
        return
    definition["execution_count"] = int(definition.get("execution_count", 0) or 0) + 1
    if success:
        definition["success_count"] = int(definition.get("success_count", 0) or 0) + 1
        definition["last_error"] = ""
    else:
        definition["last_error"] = str(error)[:1200]
    definition["last_execution_at"] = _utc_now()
    registry["tools"][tool_name] = definition
    _write_registry(registry)


def execute_user_tool(tool_name: str, iface: Any, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    definition = get_user_tool(tool_name, include_candidates=True)
    if definition is None:
        return {
            "ok": False,
            "message": f"User tool '{tool_name}' is not available.",
            "data": {},
            "artifacts": [],
            "warnings": [],
            "error_type": "not_found",
            "suggestions": ["Create the tool first or choose a registered user tool."],
        }

    source_path = _source_path(tool_name)
    try:
        source_code = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        _record_execution(tool_name, False, str(exc))
        return {
            "ok": False,
            "message": f"User tool source cannot be read: {exc}",
            "data": {},
            "artifacts": [],
            "warnings": [],
            "error_type": "file_error",
            "suggestions": ["Recreate the candidate tool before running it."],
        }

    expected_sha256 = str(definition.get("source_sha256") or "").strip()
    actual_sha256 = _sha256_text(source_code)
    if expected_sha256 and actual_sha256 != expected_sha256:
        _record_execution(tool_name, False, "Source SHA-256 mismatch with registry")
        return {
            "ok": False,
            "message": f"User tool '{tool_name}' source file failed integrity check (SHA-256 mismatch).",
            "data": {"expected_sha256": expected_sha256, "actual_sha256": actual_sha256},
            "artifacts": [],
            "warnings": [],
            "error_type": "integrity_error",
            "suggestions": ["Recreate or re-verify the user tool through create_user_tool_extension."],
        }

    validation_errors = _validate_source_contract(source_code)
    if validation_errors:
        _record_execution(tool_name, False, "; ".join(validation_errors))
        return {
            "ok": False,
            "message": "User tool source no longer passes the execution contract.",
            "data": {"errors": validation_errors},
            "artifacts": [],
            "warnings": [],
            "error_type": "validation_error",
            "suggestions": ["Recreate the candidate tool with a valid run(iface, arguments) entry point."],
        }

    try:
        namespace: Dict[str, Any] = {
            "__builtins__": build_restricted_builtins(),
            "__name__": f"qgis_agent_user_tool_{tool_name}",
            "__file__": str(source_path),
        }
        with execution_deadline(DEFAULT_MAIN_THREAD_TIMEOUT_SECONDS):
            exec(compile(source_code, str(source_path), "exec"), namespace, namespace)
            runner = namespace["run"]
            result = runner(iface, dict(arguments or {}))
    except Exception as exc:
        _record_execution(tool_name, False, str(exc))
        return {
            "ok": False,
            "message": f"User tool '{tool_name}' failed: {exc}",
            "data": {},
            "artifacts": [],
            "warnings": [],
            "error_type": "execution_error",
            "suggestions": ["Inspect the error, update the candidate, and test it again."],
        }

    if isinstance(result, dict):
        payload = dict(result)
        payload.setdefault("ok", True)
        payload.setdefault("message", f"User tool '{tool_name}' completed.")
        payload.setdefault("data", {})
        payload.setdefault("artifacts", [])
        payload.setdefault("warnings", [])
    else:
        payload = {
            "ok": True,
            "message": f"User tool '{tool_name}' completed.",
            "data": {"result": result},
            "artifacts": [],
            "warnings": [],
        }
    _record_execution(tool_name, bool(payload.get("ok")), "" if payload.get("ok") else payload.get("message", ""))
    return payload


def register_user_tool(tool_name: str, verification_summary: str) -> Dict[str, Any]:
    registry = _read_registry()
    definition = registry.get("tools", {}).get(tool_name)
    if not isinstance(definition, dict):
        return {
            "ok": False,
            "message": f"User tool '{tool_name}' does not exist.",
            "data": {},
            "artifacts": [],
            "warnings": [],
            "error_type": "not_found",
            "suggestions": ["Create and test a candidate tool before registration."],
        }
    if int(definition.get("success_count", 0) or 0) < 1:
        return {
            "ok": False,
            "message": "A user tool must complete at least one successful candidate test before registration.",
            "data": {"tool": _sanitize_definition(definition)},
            "artifacts": [],
            "warnings": [],
            "error_type": "verification_required",
            "suggestions": ["Run the candidate with representative arguments, verify the result, then retry registration."],
        }

    definition["status"] = "registered"
    definition["registered_at"] = _utc_now()
    definition["verification_summary"] = str(verification_summary or "")[:2000]
    definition["updated_at"] = _utc_now()
    registry["tools"][tool_name] = definition
    _write_registry(registry)
    return {
        "ok": True,
        "message": f"Registered user tool '{tool_name}'. It becomes available as a named tool when the next task starts.",
        "data": {"tool": _sanitize_definition(definition)},
        "artifacts": [
            {
                "type": "user_tool_registry",
                "path": str(_registry_path()),
                "description": "User-scoped executable tool registry.",
            }
        ],
        "warnings": [],
    }
