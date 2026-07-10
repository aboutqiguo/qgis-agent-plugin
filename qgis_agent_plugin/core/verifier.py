import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .task_state import STATUS_FAILED, STATUS_PASSED, StepVerification, TaskStep
from .tool_result import classify_error, is_tool_result_payload


MAX_RETRY_ATTEMPTS = 3

RETRY_ACTIONS = {
    "argument_error": "Retry the same step with a smaller tool call and complete the required arguments.",
    "file_path_error": "Check the target path, keep it inside the project folder, then retry the same step.",
    "qgis_layer_error": "Use list_layers first, then retry with the exact layer name or layer id.",
    "crs_error": "Inspect the input CRS, reproject if needed, then retry the same operation.",
    "processing_error": "Check the QGIS Processing algorithm id and parameter names, then retry with validated parameters.",
    "network_error": "Retry only after checking network connectivity, credentials, and remote service availability.",
    "timeout_error": "Retry with a smaller operation, wait until QGIS is responsive, or split the task into smaller steps.",
    "permission_error": "Ask the user for approval or choose a safer path before retrying.",
    "artifact_error": "Regenerate the missing artifact or repair the artifact writer before continuing.",
    "screenshot_error": "Retake the screenshot and verify that the image path exists before continuing.",
    "style_error": "Inspect the target layer renderer, then reapply the style in a smaller script.",
    "verification_error": "Retry this step with a smaller, validated action.",
    "unknown_error": "Review the tool message and retry with a smaller, validated step.",
}


def parse_tool_result_payload(content: Any) -> Dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, str) and is_tool_result_payload(content):
        return json.loads(content)
    return {
        "ok": False if _looks_like_error(str(content)) else True,
        "message": "" if content is None else str(content),
        "data": {},
        "artifacts": [],
        "warnings": [],
    }


def verify_step(
    step: TaskStep,
    tool_name: str,
    tool_result_content: Any,
    project_home: str = "",
    artifact_dir: str = "",
) -> StepVerification:
    payload = parse_tool_result_payload(tool_result_content)
    checks: List[Dict[str, Any]] = []
    warnings: List[str] = list(payload.get("warnings") or [])
    suggestions: List[str] = []

    tool_ok = bool(payload.get("ok"))
    checks.append({"name": "tool_result_ok", "ok": tool_ok, "message": payload.get("message", "")})
    if not tool_ok:
        suggestions.extend(payload.get("suggestions") or ["Fix this step before moving to the next step."])

    for expected_file in step.expected_files:
        file_path = _resolve_project_path(expected_file, project_home)
        exists = os.path.exists(file_path)
        checks.append({"name": "expected_file_exists", "target": file_path, "ok": exists})
        if not exists:
            suggestions.append(f"Create or correct expected output file: {expected_file}")

    for expected_artifact in step.expected_artifacts:
        artifact_path = _resolve_artifact_path(expected_artifact, artifact_dir, project_home)
        exists = os.path.exists(artifact_path)
        checks.append({"name": "expected_artifact_exists", "target": artifact_path, "ok": exists})
        if not exists:
            suggestions.append(f"Create or correct expected artifact: {expected_artifact}")

    for expected_layer in step.expected_layers:
        exists = _qgis_layer_exists(expected_layer)
        checks.append({"name": "expected_layer_exists", "target": expected_layer, "ok": exists})
        if not exists:
            suggestions.append(f"Create or load expected layer: {expected_layer}")

    if artifact_dir:
        checks.extend(_artifact_integrity_checks(artifact_dir))

    if _is_screenshot_step(step, tool_name):
        checks.append(_screenshot_check(payload, artifact_dir))

    if _is_style_step(step, tool_name):
        style_checks, style_warnings = _style_checks(step.expected_layers)
        checks.extend(style_checks)
        warnings.extend(style_warnings)

    ok = all(check.get("ok") for check in checks)
    quality_score = _quality_score(checks, warnings, tool_ok)
    failure_type = _failure_type(payload, checks)
    severity = _severity(ok, quality_score, failure_type, step.attempts)
    retry_recommended, retry_action = _retry_strategy(step, failure_type, checks)
    if retry_action and retry_action not in suggestions:
        suggestions.append(retry_action)

    if ok:
        return StepVerification(
            ok=True,
            step_id=step.step_id,
            status=STATUS_PASSED,
            message=f"Verifier passed step {step.step_id}: {step.title}",
            checks=checks,
            warnings=warnings,
            suggestions=[],
            quality_score=quality_score,
            severity=severity,
            failure_type="",
            retry_recommended=False,
            retry_action="",
        )

    return StepVerification(
        ok=False,
        step_id=step.step_id,
        status=STATUS_FAILED,
        message=f"Verifier failed step {step.step_id}: {step.title}",
        checks=checks,
        warnings=warnings,
        suggestions=suggestions or ["Retry this step with a smaller, validated action."],
        quality_score=quality_score,
        severity=severity,
        failure_type=failure_type,
        retry_recommended=retry_recommended,
        retry_action=retry_action,
    )


def _looks_like_error(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in ("error:", "failed", "traceback", "exception", "denied"))


def _resolve_project_path(file_path: str, project_home: str = "") -> str:
    if not file_path:
        return ""
    if os.path.isabs(file_path):
        return os.path.abspath(os.path.normpath(file_path))
    if project_home:
        return os.path.abspath(os.path.normpath(os.path.join(project_home, file_path)))
    return os.path.abspath(os.path.normpath(file_path))


def _resolve_artifact_path(relative_path: str, artifact_dir: str = "", project_home: str = "") -> str:
    if not relative_path:
        return ""
    if os.path.isabs(relative_path):
        return os.path.abspath(os.path.normpath(relative_path))
    if artifact_dir:
        return os.path.abspath(os.path.normpath(os.path.join(artifact_dir, relative_path)))
    return _resolve_project_path(relative_path, project_home)


def _qgis_layer_exists(layer_name: str) -> bool:
    if not layer_name:
        return False
    try:
        from qgis.core import QgsProject

        return bool(QgsProject.instance().mapLayersByName(layer_name))
    except Exception:
        return True


def _artifact_integrity_checks(artifact_dir: str) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    for name in ("run.json",):
        path = os.path.join(artifact_dir, name)
        checks.append({"name": "artifact_integrity", "target": path, "ok": os.path.exists(path)})
    return checks


def _is_screenshot_step(step: TaskStep, tool_name: str) -> bool:
    text = f"{step.title} {step.description}".lower()
    return tool_name == "take_qgis_window_snapshot" or any(
        token in text for token in ("screenshot", "snapshot", "截图", "截屏")
    )


def _screenshot_check(payload: Dict[str, Any], artifact_dir: str = "") -> Dict[str, Any]:
    message = str(payload.get("message", ""))
    data = payload.get("data") or {}
    candidate_paths = []
    if isinstance(data, dict):
        for key in ("path", "image_path", "snapshot_path", "map_snapshot"):
            if data.get(key):
                candidate_paths.append(str(data[key]))
    for artifact_name in ("map_snapshot.png", "qgis_window_snapshot.png"):
        if artifact_dir:
            candidate_paths.append(os.path.join(artifact_dir, artifact_name))

    existing = [path for path in candidate_paths if path and os.path.exists(path)]
    if existing:
        return {"name": "screenshot_exists", "target": existing[0], "ok": True}
    return {
        "name": "screenshot_completed",
        "ok": bool(payload.get("ok")) and "screenshot" in message.lower(),
        "message": message,
    }


def _is_style_step(step: TaskStep, tool_name: str) -> bool:
    text = f"{step.title} {step.description}".lower()
    return tool_name == "execute_pyqgis_script" and any(
        token in text for token in ("symbol", "style", "color", "renderer", "符号", "颜色", "样式", "渲染")
    )


def _style_checks(expected_layers: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    checks: List[Dict[str, Any]] = []
    warnings: List[str] = []
    try:
        from qgis.core import QgsProject

        project_layers = list(QgsProject.instance().mapLayers().values())
        if expected_layers:
            layers = []
            for layer_name in expected_layers:
                matches = QgsProject.instance().mapLayersByName(layer_name)
                if matches:
                    layers.extend(matches)
                else:
                    checks.append({"name": "style_layer_exists", "target": layer_name, "ok": False})
        else:
            layers = project_layers

        if not layers:
            checks.append({"name": "style_layers_available", "ok": False, "message": "No layers available for style verification."})
            return checks, warnings

        for layer in layers:
            try:
                renderer = layer.renderer()
                ok = renderer is not None
                checks.append({
                    "name": "layer_renderer_exists",
                    "target": layer.name(),
                    "ok": ok,
                    "renderer": renderer.__class__.__name__ if renderer else "",
                })
            except Exception as exc:
                checks.append({
                    "name": "layer_renderer_exists",
                    "target": getattr(layer, "name", lambda: "unknown")(),
                    "ok": False,
                    "message": str(exc),
                })
    except Exception as exc:
        warnings.append(f"QGIS style verification skipped: {exc}")
        checks.append({"name": "style_verification_available", "ok": True, "skipped": True})
    return checks, warnings


def _failed_checks(checks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [check for check in checks if not check.get("ok") and not check.get("skipped")]


def _quality_score(checks: List[Dict[str, Any]], warnings: List[str], tool_ok: bool) -> int:
    score = 100
    failed = _failed_checks(checks)
    for check in failed:
        score -= _check_penalty(str(check.get("name", "")))
    score -= min(20, len(warnings) * 5)

    if not tool_ok:
        score = min(score, 40)
    if failed:
        score = min(score, 80)
    return max(0, min(100, int(score)))


def _check_penalty(check_name: str) -> int:
    if check_name == "tool_result_ok":
        return 60
    if check_name in ("expected_file_exists", "expected_artifact_exists", "expected_layer_exists"):
        return 35
    if check_name == "artifact_integrity":
        return 25
    if check_name in ("screenshot_exists", "screenshot_completed"):
        return 25
    if check_name in ("style_layer_exists", "style_layers_available", "layer_renderer_exists"):
        return 25
    if check_name == "style_verification_available":
        return 10
    return 15


def _failure_type(payload: Dict[str, Any], checks: List[Dict[str, Any]]) -> str:
    failed = _failed_checks(checks)
    if not failed:
        return ""

    payload_error_type = payload.get("error_type")
    if payload_error_type:
        return str(payload_error_type)

    classified = classify_error(str(payload.get("message", "")))
    if classified:
        return classified

    for check in failed:
        name = str(check.get("name", ""))
        if "layer" in name:
            return "qgis_layer_error"
        if "file" in name:
            return "file_path_error"
        if "artifact" in name:
            return "artifact_error"
        if "screenshot" in name:
            return "screenshot_error"
        if "style" in name or "renderer" in name:
            return "style_error"
    return "verification_error"


def _severity(ok: bool, quality_score: int, failure_type: str, attempts: int) -> str:
    if ok:
        return "warning" if quality_score < 100 else "info"
    if failure_type == "permission_error" or attempts >= MAX_RETRY_ATTEMPTS:
        return "blocked"
    if quality_score < 40:
        return "error"
    return "warning"


def _retry_strategy(step: TaskStep, failure_type: str, checks: List[Dict[str, Any]]) -> Tuple[bool, str]:
    if not _failed_checks(checks):
        return False, ""

    if step.attempts >= MAX_RETRY_ATTEMPTS:
        return (
            False,
            f"Stop retrying this exact step after {step.attempts} attempt(s); revise the plan or ask the user.",
        )

    action = RETRY_ACTIONS.get(failure_type) or RETRY_ACTIONS["unknown_error"]
    if failure_type == "permission_error":
        return False, action
    return True, action
