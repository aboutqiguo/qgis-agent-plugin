import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


ERROR_SUGGESTIONS = {
    "argument_error": [
        "Check the required tool arguments and retry with a complete parameter set.",
    ],
    "file_path_error": [
        "Check that the path exists, is writable, and is inside an allowed workspace.",
    ],
    "qgis_layer_error": [
        "Use list_layers first, then retry with the exact layer name or layer id.",
    ],
    "crs_error": [
        "Inspect the input CRS and reproject the layer before running spatial analysis.",
    ],
    "processing_error": [
        "Check the processing algorithm id and parameter names against QGIS Processing docs.",
    ],
    "network_error": [
        "Check network connectivity, credentials, and remote service availability.",
    ],
    "overpass_parse_error": [
        "Inspect last_overpass_query.ql, remove duplicated bbox clauses, and use the GDAL-friendly `(._;>;); out body;` pattern.",
    ],
    "overpass_rate_limited": [
        "Retry later or switch to another Overpass endpoint.",
    ],
    "overpass_timeout": [
        "Retry with a smaller bbox, fewer tags, or split the request into smaller regions.",
    ],
    "overpass_empty_result": [
        "Check whether the selected OSM tags exist in the ROI, try a wider bbox, or choose another geometry_type.",
    ],
    "overpass_error": [
        "Review the saved Overpass query and server response before retrying.",
    ],
    "timeout_error": [
        "Retry with a smaller operation, check whether QGIS is busy, or wait for network connectivity to recover.",
    ],
    "permission_error": [
        "Ask the user for confirmation or write inside the current project folder.",
    ],
    "unknown_error": [
        "Review the message and retry with a smaller, validated step.",
    ],
}


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error_type: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "ok": self.ok,
            "message": self.message,
            "data": self.data,
            "artifacts": self.artifacts,
            "warnings": self.warnings,
        }
        if self.error_type:
            payload["error_type"] = self.error_type
        if self.suggestions:
            payload["suggestions"] = self.suggestions
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def success(
        cls,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        artifacts: Optional[List[Dict[str, Any]]] = None,
        warnings: Optional[List[str]] = None,
    ) -> "ToolResult":
        return cls(
            ok=True,
            message=message,
            data=data or {},
            artifacts=artifacts or [],
            warnings=warnings or [],
        )

    @classmethod
    def failure(
        cls,
        message: str,
        error_type: str = "unknown_error",
        data: Optional[Dict[str, Any]] = None,
        suggestions: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ) -> "ToolResult":
        return cls(
            ok=False,
            message=message,
            data=data or {},
            warnings=warnings or [],
            error_type=error_type,
            suggestions=suggestions or ERROR_SUGGESTIONS.get(error_type, ERROR_SUGGESTIONS["unknown_error"]),
        )

    @classmethod
    def from_legacy(cls, tool_name: str, output: Any) -> "ToolResult":
        text = "" if output is None else str(output)
        error_type = classify_error(text)
        if error_type:
            return cls.failure(
                message=text,
                error_type=error_type,
                data={"tool": tool_name, "legacy_text": text},
            )
        return cls.success(
            message=text,
            data={"tool": tool_name, "legacy_text": text},
        )


def classify_error(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    if not lowered:
        return None

    error_markers = (
        "error:",
        "error ",
        "error running",
        "failed",
        "traceback",
        "exception",
        "not found",
        "denied",
        "invalid",
        "refusing",
    )
    if not any(marker in lowered for marker in error_markers):
        return None

    if "overpass" in lowered:
        if "parse error" in lowered or "unknown type" in lowered or "empty query" in lowered:
            return "overpass_parse_error"
        if "too many requests" in lowered or "rate limit" in lowered or "429" in lowered:
            return "overpass_rate_limited"
        if "timeout" in lowered or "timed out" in lowered or "gateway" in lowered:
            return "overpass_timeout"
        if "0 features" in lowered or "empty result" in lowered:
            return "overpass_empty_result"
        return "overpass_error"
    if any(marker in lowered for marker in ("argument", "parameter", "required", "empty", "json decode")):
        return "argument_error"
    if any(marker in lowered for marker in ("path", "file", "directory", "overwrite", "write", "read")):
        return "file_path_error"
    if any(marker in lowered for marker in ("layer", "feature", "field")):
        return "qgis_layer_error"
    if any(marker in lowered for marker in ("crs", "epsg", "projection")):
        return "crs_error"
    if any(marker in lowered for marker in ("algorithm", "processing", "gdal", "native:")):
        return "processing_error"
    if any(marker in lowered for marker in ("http", "network", "timeout", "api", "earth engine")):
        if "timeout" in lowered or "timed out" in lowered:
            return "timeout_error"
        return "network_error"
    if any(marker in lowered for marker in ("permission", "denied", "unsafe", "refusing")):
        return "permission_error"
    return "unknown_error"


def is_tool_result_payload(value: str) -> bool:
    try:
        payload = json.loads(value)
    except Exception:
        return False
    return isinstance(payload, dict) and {"ok", "message", "data", "artifacts", "warnings"}.issubset(payload.keys())


def normalize_tool_output(tool_name: str, output: Any) -> str:
    if isinstance(output, ToolResult):
        return output.to_json()
    if isinstance(output, dict) and {"ok", "message"}.issubset(output.keys()):
        payload = {
            "ok": bool(output.get("ok")),
            "message": str(output.get("message", "")),
            "data": output.get("data") or {},
            "artifacts": output.get("artifacts") or [],
            "warnings": output.get("warnings") or [],
        }
        if output.get("error_type"):
            payload["error_type"] = output["error_type"]
        if output.get("suggestions"):
            payload["suggestions"] = output["suggestions"]
        return json.dumps(payload, ensure_ascii=False, default=str)
    if isinstance(output, str) and is_tool_result_payload(output):
        return output
    return ToolResult.from_legacy(tool_name, output).to_json()
