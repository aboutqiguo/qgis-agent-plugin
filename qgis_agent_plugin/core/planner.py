import re
from typing import Any, Dict, List

from .task_state import STATUS_PASSED, STATUS_PENDING, STATUS_RUNNING, TaskPlan, TaskStep


CHECKLIST_RE = re.compile(r"^\s*[-*]\s+\[(?P<mark>[ xX/-])\]\s+(?P<title>.+?)\s*$")
FILE_RE = re.compile(r"(?P<path>[\w./\\:-]+\.(?:gpkg|geojson|json|csv|tif|tiff|shp|png|jpg|md))", re.IGNORECASE)
BACKTICK_RE = re.compile(r"`([^`]+)`")
MENTION_RE = re.compile(r"@([^\s,，。；;]+)")


def build_task_plan_from_markdown(plan_markdown: str, objective: str = "") -> TaskPlan:
    text = plan_markdown or ""
    steps: List[TaskStep] = []
    for line in text.splitlines():
        match = CHECKLIST_RE.match(line)
        if not match:
            continue
        mark = match.group("mark")
        title = _clean_title(match.group("title"))
        status = _status_from_mark(mark)
        step = TaskStep(
            step_id=f"step_{len(steps) + 1:03d}",
            title=title,
            status=status,
            suggested_tools=_infer_tools(title),
            expected_layers=_infer_expected_layers(title),
            expected_files=_infer_expected_files(title),
            expected_artifacts=_infer_expected_artifacts(title),
            expected_outputs=_infer_expected_outputs(title),
        )
        steps.append(step)

    if not steps:
        fallback_title = _first_nonempty_line(text) or objective or "Complete the requested GIS task"
        steps.append(
            TaskStep(
                step_id="step_001",
                title=_clean_title(fallback_title),
                status=STATUS_PENDING,
                suggested_tools=_infer_tools(fallback_title),
                expected_layers=_infer_expected_layers(fallback_title),
                expected_files=_infer_expected_files(fallback_title),
                expected_artifacts=_infer_expected_artifacts(fallback_title),
                expected_outputs=_infer_expected_outputs(fallback_title),
            )
        )

    return TaskPlan(
        objective=objective or _infer_objective(text),
        steps=steps,
        source_markdown=text,
    )


def build_task_plan_from_payload(payload: Dict[str, Any], objective: str = "", source_markdown: str = "") -> TaskPlan:
    """Build a typed plan supplied by the model without trusting status fields."""

    steps: List[TaskStep] = []
    for index, item in enumerate((payload or {}).get("steps") or [], start=1):
        if not isinstance(item, dict):
            continue
        title = _clean_title(str(item.get("title") or item.get("description") or f"Step {index}"))
        expected_outputs = [output for output in (item.get("expected_outputs") or []) if isinstance(output, dict)]
        expected_files = list(item.get("expected_files") or _infer_expected_files(title))
        expected_layers = list(item.get("expected_layers") or _infer_expected_layers(title))
        for output in expected_outputs:
            output_type = str(output.get("type") or "")
            if output_type.endswith("file") and output.get("path") and output["path"] not in expected_files:
                expected_files.append(str(output["path"]))
            if output_type.endswith("layer") and output.get("name") and output["name"] not in expected_layers:
                expected_layers.append(str(output["name"]))
        steps.append(TaskStep(
            step_id=str(item.get("step_id") or f"step_{index:03d}"),
            title=title,
            description=str(item.get("description") or ""),
            status=STATUS_PENDING,
            suggested_tools=list(item.get("suggested_tools") or _infer_tools(title)),
            expected_layers=expected_layers,
            expected_files=expected_files,
            expected_artifacts=list(item.get("expected_artifacts") or []),
            expected_outputs=expected_outputs,
        ))
    if not steps:
        return build_task_plan_from_markdown(source_markdown, objective)
    return TaskPlan(
        objective=str((payload or {}).get("objective") or objective or "QGIS Agent Task"),
        steps=steps,
        source_markdown=source_markdown,
    )


def plan_to_markdown(plan: TaskPlan) -> str:
    lines = [f"# {plan.objective or 'Task Plan'}", ""]
    for step in plan.steps:
        mark = "x" if step.status == STATUS_PASSED else "/" if step.status == STATUS_RUNNING else " "
        lines.append(f"- [{mark}] {step.title}")
    return "\n".join(lines) + "\n"


def _status_from_mark(mark: str) -> str:
    if mark in ("x", "X"):
        return STATUS_PASSED
    if mark in ("/", "-"):
        return STATUS_RUNNING
    return STATUS_PENDING


def _clean_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value[:240] or "Untitled step"


def _first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line
    return ""


def _infer_objective(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return "QGIS Agent Task"


def _infer_tools(title: str) -> List[str]:
    lowered = (title or "").lower()
    tools: List[str] = []
    if any(token in lowered for token in ("list", "inspect", "字段", "查看", "检查")):
        tools.append("list_layers")
    if any(token in lowered for token in ("processing", "buffer", "clip", "叠加", "缓冲", "裁剪")):
        tools.append("run_processing_algorithm")
    if any(token in lowered for token in ("symbol", "style", "color", "符号", "颜色", "渲染")):
        tools.append("execute_pyqgis_script")
    if any(token in lowered for token in ("screenshot", "snapshot", "截图")):
        tools.append("take_qgis_window_snapshot")
    if any(token in lowered for token in ("report", "artifact", "报告", "结果")):
        tools.append("write_file")
    return tools


def _infer_expected_files(title: str) -> List[str]:
    seen = []
    for match in FILE_RE.finditer(title or ""):
        path = match.group("path")
        if path not in seen:
            seen.append(path)
    return seen


def _infer_expected_layers(title: str) -> List[str]:
    seen = []
    for pattern in (BACKTICK_RE, MENTION_RE):
        for match in pattern.finditer(title or ""):
            value = match.group(1).strip()
            if not value or "." in value:
                continue
            if value not in seen:
                seen.append(value)
    return seen


def _infer_expected_artifacts(title: str) -> List[str]:
    # Final reports and snapshots are generated by the artifact system at task end.
    # Step-level verifier should not fail a normal execution step while waiting for final artifacts.
    return []


def _infer_expected_outputs(title: str) -> List[Dict[str, Any]]:
    outputs: List[Dict[str, Any]] = []
    for path in _infer_expected_files(title):
        lower = path.lower()
        output_type = "raster_file" if lower.endswith((".tif", ".tiff")) else "file"
        outputs.append({"type": output_type, "path": path, "min_size_bytes": 1})
    for name in _infer_expected_layers(title):
        outputs.append({"type": "layer", "name": name})
    return outputs
