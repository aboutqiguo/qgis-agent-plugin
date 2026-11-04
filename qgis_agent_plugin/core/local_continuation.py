"""Local completion decisions that avoid unnecessary post-tool LLM calls."""

from __future__ import annotations

from typing import Any, Dict, Iterable


WORKFLOW_DOMAINS = {
    "run_osm_acquisition_workflow": "osm",
    "run_gee_sentinel2_download_workflow": "gee",
    "run_gee_dem_download_workflow": "gee",
}

SIMPLE_TERMINAL_DOMAINS = {
    "summarize_layers": {"selection"},
    "list_layers": {"selection"},
    "search_project_layers": {"selection"},
    "describe_project_layer": {"selection"},
    "inspect_layer_fields": {"selection"},
    "get_selected_features": {"selection"},
    "validate_project_outputs": set(),
    "inspect_raster_file": {"gee", "processing"},
    "validate_raster_has_data": {"gee", "processing"},
}

CONSULTATIVE_PATTERNS = (
    "哪些", "怎样", "怎么", "如何", "为什么", "建议", "方案", "能完成", "帮我", "请问",
    "能否", "可否", "步骤", "思路", "评价", "分析", "what", "how", "why", "can you",
    "could you", "recommend", "suggest", "which",
)


def is_consultative_query(text: str) -> bool:
    """Detect whether user query is asking for guidance, planning, or consultation."""
    lowered = (text or "").lower()
    return any(p in lowered for p in CONSULTATIVE_PATTERNS)


def should_finalize_locally(
    tool_name: str,
    payload: Dict[str, Any],
    task_domains: Iterable[str],
    *,
    plan_complete: bool = False,
    response_result_count: int = 1,
    user_text: str = "",
) -> bool:
    if not payload or not payload.get("ok"):
        return False
    if plan_complete:
        return True
    if response_result_count != 1:
        return False

    # 1. 如果用户输入属于咨询、开放式提问、长线规划或建议（例如“基于这份数据，你能帮我完成哪些工作呢？”），
    # 探针工具（如 summarize_layers）仅仅是 LLM 获取事实依据的探针，绝不能在此处短路截断，必须交回大模型回答！
    if user_text and is_consultative_query(user_text):
        return False

    domains = set(task_domains or [])
    if tool_name in SIMPLE_TERMINAL_DOMAINS:
        return domains.issubset(SIMPLE_TERMINAL_DOMAINS[tool_name])
    workflow_domain = WORKFLOW_DOMAINS.get(tool_name)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not workflow_domain or not data.get("workflow_complete"):
        return False
    return domains.issubset({workflow_domain, "workflow"})


def build_local_completion_summary(tool_name: str, payload: Dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    lines = [f"本地验证已通过：{payload.get('message') or tool_name}"]
    completed = data.get("completed_components") or []
    if completed:
        lines.append("完成数据项：" + "、".join(str(item) for item in completed))
    paths = data.get("expected_files") or []
    output_path = data.get("output_path")
    if output_path:
        paths = [output_path]
    if paths:
        lines.append("输出文件：" + "；".join(str(path) for path in paths[:8]))
    layers = data.get("layers") or []
    if layers:
        layer_names = [str(item.get("name")) for item in layers[:12] if isinstance(item, dict) and item.get("name")]
        if layer_names:
            lines.append("图层：" + "、".join(layer_names))
    if data.get("layer_count") is not None:
        lines.append(f"图层数量：{data.get('layer_count')}")
    return "\n".join(lines)
