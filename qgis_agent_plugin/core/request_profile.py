"""Deterministic, task-scoped tool packs for stable LLM request prefixes."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set


BASE_TOOL_PACK = {
    "activate_domain_tools",
    "ask_human",
    "execute_pyqgis_script",
    "create_or_update_user_tool",
    "run_user_tool_extension",
    "register_user_tool_extension",
    "list_user_tool_extensions",
    "summarize_layers",
    "validate_project_outputs",
    "save_project_and_verify",
    "search_project_layers",
    "describe_project_layer",
}

DOMAIN_TOOL_PACKS = {
    "osm": {
        "run_osm_acquisition_workflow",
        "download_osm_boundary",
        "download_osm_roads",
        "download_osm_features",
        "clip_vector_layers_to_boundary",
    },
    "gee": {
        "run_gee_sentinel2_download_workflow",
        "run_gee_dem_download_workflow",
        "search_gee_api",
        "inspect_raster_file",
        "validate_raster_has_data",
    },
    "processing": {
        "run_processing_algorithm",
        "search_processing_algorithms",
        "describe_processing_algorithm",
        "validate_processing_algorithm_call",
        "clip_vector_layers_to_boundary",
        "inspect_raster_file",
        "validate_raster_has_data",
        "compute_raster_zonal_stats",
        "compute_raster_index",
    },
    "mapping": {
        "take_qgis_window_snapshot",
        "ask_vision_critic",
        "zoom_to_layer",
        "set_layer_visibility",
    },
    "selection": {
        "list_layers",
        "inspect_layer_fields",
        "get_selected_features",
        "select_features_by_expression",
        "clear_selection",
        "zoom_to_selected",
        "search_layer_fields",
    },
    "code": {
        "execute_pyqgis_script",
        "repair_common_qgis_code_issues",
        "query_pyqgis_doc",
    },
    "files": {"read_file", "write_file", "replace_file_content", "load_external_layer"},
    "skills": {"read_skill", "read_file", "search_skills", "save_or_update_dynamic_skill"},
    "workflow": {"run_qgis_workflow_batch", "cleanup_qgis_project", "remove_qgis_layers_and_data"},
    "database": {"create_geodatabase", "install_python_package"},
}

DOMAIN_KEYWORDS = {
    "osm": (
        "osm", "openstreetmap", "overpass", "nominatim", "poi", "道路", "路网",
        "建筑", "建筑物", "边界", "行政区", "水系", "水面", "兴趣点",
        "学校", "大学", "学院", "高校",
    ),
    # GEE is a *download* channel. Generic remote-sensing words such as 遥感/影像/
    # 波段 describe local raster analysis just as often, so they route to the
    # raster/processing pack instead (a mask-statistics request was misrouted to
    # GEE in production logs).
    "gee": (
        "gee", "earth engine", "google earth", "sentinel", "landsat", "copernicus",
        "哨兵", "云端", "下载影像", "下载dem", "获取影像", "获取dem",
    ),
    "processing": (
        "处理", "分析", "裁剪", "缓冲", "叠加", "相交", "合并", "融合", "重投影",
        "坡度", "坡向", "等高线", "波段计算", "栅格计算", "邻域", "视域", "距离",
        "processing", "buffer", "clip", "intersect", "dissolve", "reproject", "算法",
        "slope", "aspect", "contour", "raster calculator", "band calculator", "viewshed",
        "dem", "遥感", "影像", "波段", "栅格", "指数", "掩膜", "mask", "统计", "均值", "标准差",
        "ndvi", "ndwi", "mndwi", "ndmi", "ndbi", "ndre", "savi", "evi", "nbr", "水体", "植被",
        "填洼", "流向", "汇流", "河网", "水文", "重分类", "分区统计", "zonal",
    ),
    "mapping": ("出图", "制图", "布局", "layout", "地图", "渲染", "样式", "截图", "视觉"),
    "selection": ("字段", "属性", "选择", "select", "表达式", "查询"),
    "code": ("python", "pyqgis", "代码", "脚本", "api", "报错", "traceback"),
    "files": ("文件", "markdown", ".md", "读取", "写入", "替换", "外部数据", "工程外", "导入数据", "加载文件"),
    "skills": ("skill", "技能", "经验"),
    "workflow": ("批量", "工作流", "workflow", "清理", "cleanup", "清空", "删除", "移除图层", "删除图层", "删除数据", "清理图层"),
    "database": ("数据库", "geodatabase", "gpkg", "安装库", "importerror", "modulenotfounderror"),
}


_NEGATION_PATTERN = re.compile(
    r"(?:跳过|不要|不需要|无需|不用|排除|除了|除去|忽略|别用|不涉及|未涉及|skip|without|exclude|except|no)"
    r"\s*(?:使用|调用|下载|获取)?\s*[a-z0-9_\u4e00-\u9fa5]{1,12}",
    re.IGNORECASE,
)


def strip_negated_phrases(text: str) -> str:
    """Remove explicitly negated targets ("跳过 osm数据", "skip gee") before routing."""
    return _NEGATION_PATTERN.sub(" ", text or "")


def detect_task_domains(text: str) -> List[str]:
    lowered = strip_negated_phrases((text or "").lower())
    return sorted(
        domain
        for domain, keywords in DOMAIN_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    )


def frozen_tool_names(
    text: str,
    available_names: Iterable[str],
    *,
    work_mode: str = "WORK",
    user_tool_domains: Optional[Dict[str, Iterable[str]]] = None,
) -> List[str]:
    """Select one deterministic tool bundle for the full user task."""
    return tool_names_for_domains(
        detect_task_domains(text),
        available_names,
        work_mode=work_mode,
        user_tool_domains=user_tool_domains,
    )


def tool_names_for_domains(
    domains: Iterable[str],
    available_names: Iterable[str],
    *,
    work_mode: str = "WORK",
    user_tool_domains: Optional[Dict[str, Iterable[str]]] = None,
) -> List[str]:
    """Select a deterministic tool bundle from already-classified domains."""
    selected: Set[str] = set(BASE_TOOL_PACK)
    normalized_domains = sorted({str(domain) for domain in (domains or []) if domain in DOMAIN_TOOL_PACKS})
    for domain in normalized_domains:
        selected.update(DOMAIN_TOOL_PACKS.get(domain, set()))
    if str(work_mode or "").upper() == "PLAN":
        # Execution remains protected by the local mode/approval gate. Including
        # it here avoids changing the provider schema immediately after approval.
        selected.add("submit_plan_for_approval")
    available = set(available_names or [])
    selected_domains = set(normalized_domains)
    for tool_name, tool_domains in sorted((user_tool_domains or {}).items()):
        normalized_domains = {str(domain) for domain in (tool_domains or [])}
        if tool_name not in available:
            continue
        if "general" in normalized_domains or selected_domains.intersection(normalized_domains):
            selected.add(tool_name)
    return sorted(name for name in selected if name in available)


def expand_tool_names(
    current_names: Iterable[str],
    domains: Iterable[str],
    available_names: Iterable[str],
    *,
    work_mode: str = "WORK",
    user_tool_domains: Optional[Dict[str, Iterable[str]]] = None,
) -> List[str]:
    """Monotonically add deterministic domain tools without removing the current task tools."""
    selected = set(current_names or [])
    selected.update(tool_names_for_domains(
        domains,
        available_names,
        work_mode=work_mode,
        user_tool_domains=user_tool_domains,
    ))
    available = set(available_names or [])
    return sorted(name for name in selected if name in available)


def canonicalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: canonicalize_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [canonicalize_json(item) for item in value]
    return value


def canonicalize_tool_schemas(tools: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = [canonicalize_json(tool) for tool in (tools or [])]
    return sorted(normalized, key=lambda item: item.get("function", {}).get("name", ""))
