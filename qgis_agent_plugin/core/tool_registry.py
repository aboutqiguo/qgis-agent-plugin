from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


REGISTRY_SCHEMA_VERSION = "2.3"


READ_ONLY_TOOLS = {
    "activate_domain_tools",
    "ask_human",
    "ask_vision_critic",
    "repair_common_qgis_code_issues",
    "read_file",
    "search_past_conversations",
    "search_data_sources",
    "create_data_acquisition_plan",
    "search_gee_api",
    "search_gee_python_api",
    "search_skills",
    "list_layers",
    "inspect_layer_fields",
    "get_selected_features",
    "query_pyqgis_doc",
    "rebuild_qgis_catalog",
    "search_processing_algorithms",
    "describe_processing_algorithm",
    "validate_processing_algorithm_call",
    "search_qgis_expression_functions",
    "describe_qgis_expression_function",
    "validate_qgis_expression",
    "search_project_layers",
    "describe_project_layer",
    "search_layer_fields",
    "read_skill",
    "summarize_layers",
    "validate_project_outputs",
    "inspect_raster_file",
    "validate_raster_has_data",
    "compute_raster_zonal_stats",
    "take_qgis_window_snapshot",
    "list_user_tool_extensions",
}

MEDIUM_RISK_TOOLS = {
    "load_external_layer",
    "compute_raster_index",
    "run_processing_algorithm",
    "clip_vector_layers_to_boundary",
    "save_project_and_verify",
    "cleanup_qgis_project",
    "run_qgis_workflow_batch",
    "run_gee_sentinel2_download_workflow",
    "run_gee_dem_download_workflow",
    "run_osm_acquisition_workflow",
    "create_geodatabase",
    "download_osm_data",
    "download_osm_boundary",
    "download_osm_roads",
    "download_osm_features",
    "submit_plan_for_approval",
}

HIGH_RISK_TOOLS = {
    "remove_qgis_layers_and_data",
    "execute_pyqgis_script",
    "install_python_package",
    "replace_file_content",
    "write_file",
    "save_skill",
    "save_or_update_dynamic_skill",
    "create_or_update_user_tool",
    "run_user_tool_extension",
    "register_user_tool_extension",
}

CONTROL_TOOLS = {
    "activate_domain_tools",
    "ask_human",
    "submit_plan_for_approval",
}

BATCHABLE_TOOLS = {
    "summarize_layers",
    "cleanup_qgis_project",
    "validate_project_outputs",
    "inspect_raster_file",
    "validate_raster_has_data",
    "compute_raster_zonal_stats",
    "compute_raster_index",
    "save_project_and_verify",
    "download_osm_features",
    "clip_vector_layers_to_boundary",
    "run_gee_sentinel2_download_workflow",
    "run_gee_dem_download_workflow",
    "run_processing_algorithm",
}

OUTPUT_TYPES = {
    "activate_domain_tools": "tool_pack_status",
    "remove_qgis_layers_and_data": "project_cleanup",
    "load_external_layer": "layer_or_file",
    "ask_human": "text",
    "ask_vision_critic": "text",
    "execute_pyqgis_script": "execution_log",
    "list_layers": "table",
    "inspect_layer_fields": "table",
    "get_selected_features": "table",
    "run_processing_algorithm": "layer_or_file",
    "rebuild_qgis_catalog": "catalog_status",
    "search_processing_algorithms": "processing_algorithm_list",
    "describe_processing_algorithm": "processing_algorithm_signature",
    "validate_processing_algorithm_call": "validation_report",
    "search_qgis_expression_functions": "expression_function_list",
    "describe_qgis_expression_function": "expression_function_signature",
    "validate_qgis_expression": "validation_report",
    "search_project_layers": "layer_list",
    "describe_project_layer": "layer_details",
    "search_layer_fields": "field_list",
    "clip_vector_layers_to_boundary": "layer_or_file",
    "save_project_and_verify": "project_file",
    "summarize_layers": "table",
    "cleanup_qgis_project": "project_cleanup",
    "validate_project_outputs": "validation_report",
    "inspect_raster_file": "raster_inspection",
    "validate_raster_has_data": "validation_report",
    "compute_raster_zonal_stats": "raster_statistics",
    "compute_raster_index": "layer_or_file",
    "run_qgis_workflow_batch": "workflow_report",
    "run_gee_sentinel2_download_workflow": "layer_or_file",
    "run_gee_dem_download_workflow": "layer_or_file",
    "run_osm_acquisition_workflow": "layer_or_file",
    "create_geodatabase": "file",
    "download_osm_data": "layer",
    "download_osm_boundary": "layer",
    "download_osm_roads": "layer",
    "download_osm_features": "layer_or_file",
    "query_pyqgis_doc": "text",
    "read_skill": "text",
    "save_or_update_dynamic_skill": "file",
    "install_python_package": "environment",
    "repair_common_qgis_code_issues": "code_repair",
    "search_gee_api": "text",
    "search_gee_python_api": "text",
    "read_file": "text",
    "write_file": "file",
    "replace_file_content": "file",
    "save_skill": "file",
    "search_skills": "text",
    "search_past_conversations": "text",
    "search_data_sources": "data_source_list",
    "create_data_acquisition_plan": "data_acquisition_plan",
    "submit_plan_for_approval": "plan",
    "take_qgis_window_snapshot": "image",
    "create_or_update_user_tool": "user_tool_definition",
    "run_user_tool_extension": "user_tool_result",
    "register_user_tool_extension": "user_tool_registry",
    "list_user_tool_extensions": "user_tool_list",
}

TOOL_CATEGORIES = {
    "activate_domain_tools": "interaction",
    "remove_qgis_layers_and_data": "project_cleanup",
    "load_external_layer": "filesystem",
    "ask_human": "interaction",
    "ask_vision_critic": "vision",
    "execute_pyqgis_script": "execution",
    "repair_common_qgis_code_issues": "code_repair",
    "install_python_package": "environment",
    "list_layers": "project_inspection",
    "inspect_layer_fields": "project_inspection",
    "get_selected_features": "project_inspection",
    "zoom_to_layer": "map_navigation",
    "set_layer_visibility": "map_navigation",
    "select_features_by_expression": "selection",
    "clear_selection": "selection",
    "zoom_to_selected": "map_navigation",
    "run_processing_algorithm": "geoprocessing",
    "rebuild_qgis_catalog": "documentation",
    "search_processing_algorithms": "documentation",
    "describe_processing_algorithm": "documentation",
    "validate_processing_algorithm_call": "geoprocessing",
    "search_qgis_expression_functions": "documentation",
    "describe_qgis_expression_function": "documentation",
    "validate_qgis_expression": "selection",
    "search_project_layers": "project_inspection",
    "describe_project_layer": "project_inspection",
    "search_layer_fields": "project_inspection",
    "clip_vector_layers_to_boundary": "geoprocessing",
    "save_project_and_verify": "project_persistence",
    "summarize_layers": "project_inspection",
    "cleanup_qgis_project": "project_cleanup",
    "validate_project_outputs": "project_inspection",
    "inspect_raster_file": "raster_validation",
    "validate_raster_has_data": "raster_validation",
    "compute_raster_zonal_stats": "geoprocessing",
    "compute_raster_index": "geoprocessing",
    "run_qgis_workflow_batch": "workflow",
    "run_gee_sentinel2_download_workflow": "data_acquisition",
    "run_gee_dem_download_workflow": "data_acquisition",
    "run_osm_acquisition_workflow": "data_acquisition",
    "create_geodatabase": "data_management",
    "download_osm_data": "data_acquisition",
    "download_osm_boundary": "data_acquisition",
    "download_osm_roads": "data_acquisition",
    "download_osm_features": "data_acquisition",
    "search_data_sources": "data_acquisition",
    "create_data_acquisition_plan": "data_acquisition",
    "query_pyqgis_doc": "documentation",
    "read_skill": "skills",
    "save_or_update_dynamic_skill": "skills",
    "search_gee_api": "documentation",
    "search_gee_python_api": "documentation",
    "read_file": "filesystem",
    "write_file": "filesystem",
    "replace_file_content": "filesystem",
    "save_skill": "skills",
    "search_skills": "skills",
    "search_past_conversations": "memory",
    "submit_plan_for_approval": "planning",
    "take_qgis_window_snapshot": "vision",
    "create_or_update_user_tool": "user_extensions",
    "run_user_tool_extension": "user_extensions",
    "register_user_tool_extension": "user_extensions",
    "list_user_tool_extensions": "user_extensions",
}

NETWORK_TOOLS = {
    "ask_vision_critic",
    "install_python_package",
    "search_gee_api",
    "search_gee_python_api",
    "download_osm_data",
    "download_osm_boundary",
    "download_osm_roads",
    "download_osm_features",
    "run_gee_sentinel2_download_workflow",
    "run_gee_dem_download_workflow",
    "run_osm_acquisition_workflow",
}

AUTH_TOOLS = {
    "ask_vision_critic",
    "search_gee_api",
    "search_gee_python_api",
    "run_gee_sentinel2_download_workflow",
    "run_gee_dem_download_workflow",
}

PROJECT_MUTATION_TOOLS = {
    "remove_qgis_layers_and_data",
    "load_external_layer",
    "compute_raster_index",
    "execute_pyqgis_script",
    "run_processing_algorithm",
    "clip_vector_layers_to_boundary",
    "save_project_and_verify",
    "create_geodatabase",
    "download_osm_data",
    "download_osm_boundary",
    "download_osm_roads",
    "download_osm_features",
    "run_gee_sentinel2_download_workflow",
    "run_gee_dem_download_workflow",
    "run_osm_acquisition_workflow",
    "zoom_to_layer",
    "set_layer_visibility",
    "select_features_by_expression",
    "clear_selection",
    "zoom_to_selected",
    "cleanup_qgis_project",
    "run_qgis_workflow_batch",
    "run_user_tool_extension",
}

LAYER_CONSUMING_TOOLS = {
    "zoom_to_layer",
    "set_layer_visibility",
    "inspect_layer_fields",
    "get_selected_features",
    "select_features_by_expression",
    "clear_selection",
    "zoom_to_selected",
    "compute_raster_zonal_stats",
    "compute_raster_index",
    "run_processing_algorithm",
    "clip_vector_layers_to_boundary",
    "run_gee_sentinel2_download_workflow",
    "run_gee_dem_download_workflow",
}

ARTIFACT_PRODUCING_TOOLS = {
    "remove_qgis_layers_and_data",
    "load_external_layer",
    "compute_raster_index",
    "submit_plan_for_approval",
    "take_qgis_window_snapshot",
    "write_file",
    "replace_file_content",
    "save_skill",
    "save_or_update_dynamic_skill",
    "create_or_update_user_tool",
    "register_user_tool_extension",
    "create_data_acquisition_plan",
    "search_data_sources",
    "create_geodatabase",
    "download_osm_data",
    "download_osm_boundary",
    "download_osm_roads",
    "download_osm_features",
    "run_processing_algorithm",
    "clip_vector_layers_to_boundary",
    "run_gee_sentinel2_download_workflow",
    "run_gee_dem_download_workflow",
    "run_osm_acquisition_workflow",
    "save_project_and_verify",
}

APPROVAL_COVERED_TOOLS = {
    "remove_qgis_layers_and_data",
    "execute_pyqgis_script",
    "install_python_package",
    "write_file",
    "replace_file_content",
    "save_skill",
    "save_or_update_dynamic_skill",
    "create_or_update_user_tool",
    "run_user_tool_extension",
    "register_user_tool_extension",
    "clip_vector_layers_to_boundary",
    "save_project_and_verify",
    "create_geodatabase",
    "download_osm_data",
    "download_osm_boundary",
    "download_osm_roads",
    "download_osm_features",
    "run_gee_sentinel2_download_workflow",
    "run_gee_dem_download_workflow",
    "run_osm_acquisition_workflow",
}


@dataclass
class ToolSpec:
    name: str
    description: str
    args_schema: Dict[str, Any]
    version: str = "1.0"
    risk_level: str = "low"
    requires_qgis_main_thread: bool = True
    output_type: str = "text"
    category: str = ""
    side_effects: List[str] = field(default_factory=list)
    path_scope: str = ""
    requires_network: Optional[bool] = None
    requires_auth: Optional[bool] = None
    produces_artifacts: Optional[bool] = None
    consumes_layers: Optional[bool] = None
    mutates_project: Optional[bool] = None
    read_only: Optional[bool] = None
    batchable: Optional[bool] = None
    capability_group: str = ""
    examples: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.category:
            self.category = _infer_category(self.name)
        if not self.side_effects:
            self.side_effects = _infer_side_effects(self.name)
        if not self.path_scope:
            self.path_scope = _infer_path_scope(self.name)
        if self.requires_network is None:
            self.requires_network = _infer_requires_network(self.name)
        if self.requires_auth is None:
            self.requires_auth = _infer_requires_auth(self.name)
        if self.produces_artifacts is None:
            self.produces_artifacts = self.name in ARTIFACT_PRODUCING_TOOLS
        if self.consumes_layers is None:
            self.consumes_layers = self.name in LAYER_CONSUMING_TOOLS
        if self.mutates_project is None:
            self.mutates_project = self.name in PROJECT_MUTATION_TOOLS
        if self.read_only is None:
            self.read_only = self.name in READ_ONLY_TOOLS
        if self.batchable is None:
            self.batchable = self.name in BATCHABLE_TOOLS
        if not self.capability_group:
            self.capability_group = _infer_capability_group(self.name)

    def to_openai_tool(self) -> Dict[str, Any]:
        # Keep provider-facing schemas strict. Risk metadata is for the local registry only.
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema,
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "args_schema": self.args_schema,
            "version": self.version,
            "risk_level": self.risk_level,
            "requires_qgis_main_thread": self.requires_qgis_main_thread,
            "output_type": self.output_type,
            "category": self.category,
            "side_effects": self.side_effects,
            "path_scope": self.path_scope,
            "requires_network": bool(self.requires_network),
            "requires_auth": bool(self.requires_auth),
            "produces_artifacts": bool(self.produces_artifacts),
            "consumes_layers": bool(self.consumes_layers),
            "mutates_project": bool(self.mutates_project),
            "read_only": bool(self.read_only),
            "batchable": bool(self.batchable),
            "capability_group": self.capability_group,
            "examples": self.examples,
            "metadata": self.metadata,
        }


def _infer_risk_level(name: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    metadata = metadata or {}
    if metadata.get("destructive") or metadata.get("requires_confirmation"):
        return "high"
    if name in HIGH_RISK_TOOLS:
        return "high"
    if name in MEDIUM_RISK_TOOLS:
        return "medium"
    return "low"


def _infer_requires_main_thread(name: str) -> bool:
    return name not in {
        "ask_human",
        "read_file",
        "replace_file_content",
        "search_gee_api",
        "search_gee_python_api",
        "query_pyqgis_doc",
        "repair_common_qgis_code_issues",
        "inspect_raster_file",
        "validate_raster_has_data",
        "compute_raster_zonal_stats",
        "read_skill",
        "save_skill",
        "search_skills",
        "search_past_conversations",
        "search_data_sources",
        "create_data_acquisition_plan",
        "write_file",
        "create_or_update_user_tool",
        "register_user_tool_extension",
    }


def _infer_output_type(name: str) -> str:
    return OUTPUT_TYPES.get(name, "text")


def _infer_category(name: str) -> str:
    return TOOL_CATEGORIES.get(name, "general")


def _infer_capability_group(name: str) -> str:
    category = _infer_category(name)
    if category in {"data_acquisition"}:
        if "gee" in name:
            return "gee"
        if "osm" in name:
            return "osm"
        return "data"
    if category in {"geoprocessing", "selection"}:
        return "processing"
    if category in {"raster_validation"}:
        return "raster"
    if category in {"map_navigation", "vision"}:
        return "mapping"
    if category in {"documentation", "code_repair"}:
        return "diagnostics"
    if category in {"filesystem", "environment", "skills"}:
        return "security"
    return "project"


def _infer_side_effects(name: str) -> List[str]:
    effects: List[str] = []
    if name in {"execute_pyqgis_script", "run_user_tool_extension"}:
        effects.append("code_execution")
    if name in {"install_python_package"}:
        effects.extend(["environment_mutation", "network_request"])
    if name in NETWORK_TOOLS:
        effects.append("network_request")
    if name in {
        "write_file",
        "replace_file_content",
        "save_skill",
        "save_or_update_dynamic_skill",
        "create_or_update_user_tool",
        "register_user_tool_extension",
        "create_geodatabase",
        "clip_vector_layers_to_boundary",
        "save_project_and_verify",
        "download_osm_boundary",
        "download_osm_roads",
        "download_osm_features",
        "run_gee_sentinel2_download_workflow",
        "run_gee_dem_download_workflow",
        "run_osm_acquisition_workflow",
    }:
        effects.append("file_write")
    if name in {
        "load_external_layer",
        "run_processing_algorithm",
        "download_osm_data",
        "download_osm_boundary",
        "download_osm_roads",
        "download_osm_features",
        "create_geodatabase",
        "clip_vector_layers_to_boundary",
        "save_project_and_verify",
        "run_gee_sentinel2_download_workflow",
        "run_gee_dem_download_workflow",
        "run_osm_acquisition_workflow",
    }:
        effects.extend(["project_mutation", "layer_creation"])
    if name in {"zoom_to_layer", "set_layer_visibility", "select_features_by_expression", "clear_selection", "zoom_to_selected"}:
        effects.append("project_state_change")
    if name in {"submit_plan_for_approval", "ask_human"}:
        effects.append("user_interaction")
    if name in {"take_qgis_window_snapshot", "ask_vision_critic"}:
        effects.append("screenshot_capture")
    if not effects:
        effects.append("read_only")
    return sorted(set(effects))


def _infer_path_scope(name: str) -> str:
    if name in {"write_file", "replace_file_content", "read_file"}:
        return "agent_resolved_path"
    if name in {
        "create_or_update_user_tool",
        "run_user_tool_extension",
        "register_user_tool_extension",
        "list_user_tool_extensions",
    }:
        return "user_extension"
    if name in {"save_skill", "save_or_update_dynamic_skill"}:
        return "project_or_plugin_skills"
    if name in {
        "load_external_layer",
        "create_geodatabase",
        "run_processing_algorithm",
        "download_osm_data",
        "download_osm_boundary",
        "download_osm_roads",
        "download_osm_features",
        "clip_vector_layers_to_boundary",
        "save_project_and_verify",
        "run_gee_sentinel2_download_workflow",
        "run_gee_dem_download_workflow",
        "run_osm_acquisition_workflow",
    }:
        return "project_or_temp_output"
    if name in NETWORK_TOOLS:
        return "network"
    return "none"


def _infer_requires_network(name: str) -> bool:
    return name in NETWORK_TOOLS


def _infer_requires_auth(name: str) -> bool:
    return name in AUTH_TOOLS


def spec_from_openai_tool(schema: Dict[str, Any]) -> ToolSpec:
    function = schema.get("function", {})
    name = function.get("name", "")
    metadata = schema.get("metadata", {})
    return ToolSpec(
        name=name,
        description=function.get("description", ""),
        args_schema=function.get("parameters", {"type": "object", "properties": {}, "required": []}),
        risk_level=_infer_risk_level(name, metadata),
        requires_qgis_main_thread=metadata.get(
            "requires_qgis_main_thread",
            _infer_requires_main_thread(name),
        ),
        output_type=_infer_output_type(name),
        category=_infer_category(name),
        side_effects=list(metadata.get("side_effects") or []),
        path_scope=str(metadata.get("path_scope", "")),
        requires_network=metadata.get("requires_network", None),
        requires_auth=metadata.get("requires_auth", None),
        produces_artifacts=metadata.get("produces_artifacts", None),
        consumes_layers=metadata.get("consumes_layers", None),
        mutates_project=metadata.get("mutates_project", None),
        metadata=metadata,
    )


def build_atomic_tool_specs() -> List[ToolSpec]:
    from ..tools.tools import ATOMIC_TOOLS_SCHEMA

    specs = [spec_from_openai_tool(schema) for schema in ATOMIC_TOOLS_SCHEMA]
    names = {spec.name for spec in specs}
    if "search_gee_api" in names and "search_gee_python_api" not in names:
        source = next(spec for spec in specs if spec.name == "search_gee_api")
        specs.append(
            ToolSpec(
                name="search_gee_python_api",
                description="Compatibility alias for search_gee_api.",
                args_schema=source.args_schema,
                risk_level=source.risk_level,
                requires_qgis_main_thread=source.requires_qgis_main_thread,
                output_type=source.output_type,
                metadata={"alias_for": "search_gee_api"},
            )
        )
    return specs


def build_registered_user_tool_specs() -> List[ToolSpec]:
    """Load only previously verified user tools for the next task's frozen tool set."""

    try:
        from .user_tool_extensions import get_registered_user_tools

        definitions = get_registered_user_tools()
    except Exception:
        return []

    specs: List[ToolSpec] = []
    for definition in definitions:
        name = str(definition.get("tool_name", ""))
        description = str(definition.get("description", ""))
        args_schema = definition.get("parameters_schema")
        if not name or not description or not isinstance(args_schema, dict):
            continue
        specs.append(
            ToolSpec(
                name=name,
                description=description,
                args_schema=args_schema,
                version="user",
                risk_level="high",
                requires_qgis_main_thread=True,
                output_type="user_tool_result",
                category="user_extensions",
                side_effects=["code_execution", "file_write", "project_mutation"],
                path_scope="user_extension",
                produces_artifacts=True,
                mutates_project=True,
                metadata={
                    "user_extension": True,
                    "requires_confirmation": True,
                    "domains": definition.get("domains", []),
                    "source_file": definition.get("source_file", ""),
                    "registered_at": definition.get("registered_at", ""),
                },
            )
        )
    return sorted(specs, key=lambda spec: spec.name)


def _object_schema(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }


def build_builtin_tool_specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="activate_domain_tools",
            description=(
                "Activate one or more built-in domain tool packs when the initial request was ambiguous and "
                "the required registered tools are not currently visible. Use this before claiming a capability "
                "gap or creating a user tool. Activation is deterministic, additive, and applies from the next "
                "model round."
            ),
            args_schema=_object_schema(
                {
                    "domains": {
                        "type": "array",
                        "description": "Built-in domains to activate.",
                        "items": {
                            "type": "string",
                            "enum": [
                                "code", "database", "files", "gee", "mapping", "osm",
                                "processing", "selection", "skills", "workflow",
                            ],
                        },
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short explanation of why the initial task routing was insufficient.",
                    },
                },
                ["domains", "reason"],
            ),
            risk_level="low",
            requires_qgis_main_thread=False,
            output_type="tool_pack_status",
        ),
        ToolSpec(
            name="execute_pyqgis_script",
            description=(
                "Execute a Python script in the QGIS environment. Provide complete, executable raw code "
                "without markdown formatting. This main-thread fallback is limited to short QGIS project/UI "
                "operations; synchronous network, Processing, waits, unbounded loops, and dynamic execution "
                "are rejected and execution is time-bounded."
            ),
            args_schema=_object_schema(
                {
                    "code": {
                        "type": "string",
                        "description": "The raw Python code to execute.",
                    },
                    "is_destructive": {
                        "type": "boolean",
                        "description": (
                            "True if the code deletes, overwrites, or modifies existing user files on disk."
                        ),
                    },
                },
                ["code", "is_destructive"],
            ),
            risk_level="high",
            requires_qgis_main_thread=True,
            output_type="execution_log",
        ),
        ToolSpec(
            name="submit_plan_for_approval",
            description=(
                "Submit a proposed plan for human approval. Pass detailed markdown and checklist into "
                "plan_markdown."
            ),
            args_schema=_object_schema(
                {
                    "plan_markdown": {
                        "type": "string",
                        "description": "Full markdown plan and checklist. Use [ ], [/], [x].",
                    },
                    "plan_json": {
                        "type": "object",
                        "description": "Optional typed plan. Each step should declare suggested_tools and expected_outputs.",
                        "properties": {
                            "objective": {"type": "string"},
                            "steps": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "step_id": {"type": "string"},
                                        "title": {"type": "string"},
                                        "description": {"type": "string"},
                                        "suggested_tools": {"type": "array", "items": {"type": "string"}},
                                        "expected_outputs": {"type": "array", "items": {"type": "object"}},
                                    },
                                    "required": ["title"],
                                },
                            },
                        },
                    },
                },
                ["plan_markdown"],
            ),
            risk_level="medium",
            requires_qgis_main_thread=False,
            output_type="plan",
        ),
        ToolSpec(
            name="ask_human",
            description="Ask the human a clarifying question and wait for their response.",
            args_schema=_object_schema(
                {"question": {"type": "string", "description": "The question to ask the user."}},
                ["question"],
            ),
            risk_level="low",
            requires_qgis_main_thread=True,
            output_type="text",
        ),
        ToolSpec(
            name="ask_vision_critic",
            description=(
                "Capture the current QGIS map canvas and ask the configured vision model for cartographic advice."
            ),
            args_schema=_object_schema(
                {
                    "question": {
                        "type": "string",
                        "description": "Specific question about the current map canvas.",
                    }
                },
                ["question"],
            ),
            risk_level="low",
            requires_qgis_main_thread=True,
            output_type="text",
        ),
        ToolSpec(
            name="take_qgis_window_snapshot",
            description="Capture the entire QGIS window to diagnose the UI state.",
            args_schema=_object_schema({}),
            risk_level="low",
            requires_qgis_main_thread=True,
            output_type="image",
        ),
        ToolSpec(
            name="read_file",
            description="Read the contents of a local file.",
            args_schema=_object_schema(
                {
                    "file_path": {"type": "string", "description": "Absolute or agent-resolved file path."},
                    "summary_only": {"type": "boolean", "description": "Return compact head/tail summary for large files. Default true."},
                    "max_chars": {"type": "integer", "description": "Maximum content characters returned to the model. Default 6000."},
                    "pattern": {"type": "string", "description": "Optional regex/keyword pattern. Returns matching lines with context."},
                    "start_line": {"type": "integer", "description": "Optional 1-based start line for targeted reads."},
                    "line_count": {"type": "integer", "description": "Optional number of lines to read with start_line."},
                },
                ["file_path"],
            ),
            risk_level="low",
            requires_qgis_main_thread=False,
            output_type="text",
        ),
        ToolSpec(
            name="write_file",
            description="Write text content to a local file, overwriting existing content when approved.",
            args_schema=_object_schema(
                {
                    "file_path": {"type": "string", "description": "Absolute or agent-resolved file path."},
                    "content": {"type": "string", "description": "Text content to write."},
                },
                ["file_path", "content"],
            ),
            risk_level="high",
            requires_qgis_main_thread=False,
            output_type="file",
        ),
        ToolSpec(
            name="replace_file_content",
            description="Replace a specific substring in a local file.",
            args_schema=_object_schema(
                {
                    "file_path": {"type": "string", "description": "Absolute or agent-resolved file path."},
                    "target_content": {"type": "string", "description": "Exact string to replace."},
                    "replacement_content": {"type": "string", "description": "Replacement string."},
                },
                ["file_path", "target_content", "replacement_content"],
            ),
            risk_level="high",
            requires_qgis_main_thread=False,
            output_type="file",
        ),
        ToolSpec(
            name="save_skill",
            description="Save a reusable PyQGIS snippet to the current project's procedural skill library.",
            args_schema=_object_schema(
                {
                    "skill_name": {"type": "string", "description": "Short unique skill filename."},
                    "description": {"type": "string", "description": "What the skill does and expects."},
                    "python_code": {"type": "string", "description": "Complete working PyQGIS Python code."},
                },
                ["skill_name", "description", "python_code"],
            ),
            risk_level="high",
            requires_qgis_main_thread=False,
            output_type="file",
        ),
        ToolSpec(
            name="search_skills",
            description="Search the current project's procedural skill library.",
            args_schema=_object_schema(
                {"query": {"type": "string", "description": "Search keywords."}},
                ["query"],
            ),
            risk_level="low",
            requires_qgis_main_thread=False,
            output_type="text",
        ),
        ToolSpec(
            name="search_past_conversations",
            description="Search past conversation history from the SQLite episodic memory database.",
            args_schema=_object_schema(
                {"query": {"type": "string", "description": "Keywords to search in previous chats."}},
                ["query"],
            ),
            risk_level="low",
            requires_qgis_main_thread=False,
            output_type="text",
        ),
    ]


def build_all_tool_specs() -> List[ToolSpec]:
    seen = set()
    specs: List[ToolSpec] = []
    for spec in build_builtin_tool_specs() + build_atomic_tool_specs() + build_registered_user_tool_specs():
        if spec.name in seen:
            continue
        seen.add(spec.name)
        specs.append(spec)
    return specs


def build_registry_payload(specs: Optional[Iterable[ToolSpec]] = None) -> Dict[str, Any]:
    rows = [spec.to_dict() for spec in specs or build_all_tool_specs()]
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "tool_count": len(rows),
        "tools": rows,
        "health": validate_registry_health(rows),
    }


def build_atomic_tool_openai_schemas() -> List[Dict[str, Any]]:
    return [spec.to_openai_tool() for spec in build_atomic_tool_specs()]


def build_all_tool_openai_schemas() -> List[Dict[str, Any]]:
    return [spec.to_openai_tool() for spec in build_all_tool_specs()]


def get_atomic_tool_names(include_aliases: bool = True) -> List[str]:
    names = [spec.name for spec in build_atomic_tool_specs()]
    names.extend(spec.name for spec in build_registered_user_tool_specs())
    if not include_aliases:
        names = [name for name in names if name != "search_gee_python_api"]
    return sorted(set(names))


def get_tool_names() -> List[str]:
    return sorted({spec.name for spec in build_all_tool_specs()})


def get_tool_spec(name: str) -> Optional[ToolSpec]:
    for spec in build_all_tool_specs():
        if spec.name == name:
            return spec
    return None


def iter_registry_rows(specs: Optional[Iterable[ToolSpec]] = None) -> Iterable[Dict[str, Any]]:
    for spec in specs or build_all_tool_specs():
        yield spec.to_dict()


def validate_registry_health(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    rows = rows or [spec.to_dict() for spec in build_all_tool_specs()]
    names = [row.get("name", "") for row in rows]
    duplicate_names = sorted({name for name in names if names.count(name) > 1 and name})
    issues: List[Dict[str, Any]] = []

    required_fields = {
        "name",
        "description",
        "args_schema",
        "version",
        "risk_level",
        "category",
        "output_type",
        "side_effects",
        "path_scope",
        "requires_network",
        "requires_auth",
        "produces_artifacts",
        "consumes_layers",
        "mutates_project",
        "read_only",
        "batchable",
        "capability_group",
    }
    allowed_risks = {"low", "medium", "high"}
    allowed_path_scopes = {
        "none",
        "agent_resolved_path",
        "external_read_or_project_copy",
        "project_or_plugin_skills",
        "project_or_temp_output",
        "network",
        "user_extension",
    }

    for row in rows:
        name = row.get("name", "")
        missing = sorted(field for field in required_fields if field not in row)
        if missing:
            issues.append({"level": "error", "tool": name, "message": f"Missing registry fields: {', '.join(missing)}"})
        if row.get("risk_level") not in allowed_risks:
            issues.append({"level": "error", "tool": name, "message": f"Invalid risk level: {row.get('risk_level')}"})
        if row.get("path_scope") not in allowed_path_scopes:
            issues.append({"level": "warning", "tool": name, "message": f"Unexpected path scope: {row.get('path_scope')}"})
        is_user_extension = bool((row.get("metadata") or {}).get("user_extension"))
        if row.get("risk_level") == "high" and name not in APPROVAL_COVERED_TOOLS and not is_user_extension:
            issues.append({"level": "error", "tool": name, "message": "High-risk tool is not explicitly covered by approval policy."})
        if row.get("requires_network") and "network_request" not in row.get("side_effects", []):
            issues.append({"level": "warning", "tool": name, "message": "Network tool should declare network_request side effect."})

    for name in duplicate_names:
        issues.append({"level": "error", "tool": name, "message": "Duplicate tool registration."})

    errors = [issue for issue in issues if issue.get("level") == "error"]
    warnings = [issue for issue in issues if issue.get("level") == "warning"]
    risk_counts = {"low": 0, "medium": 0, "high": 0}
    for row in rows:
        risk = row.get("risk_level")
        if risk in risk_counts:
            risk_counts[risk] += 1

    return {
        "ok": not errors,
        "tool_count": len(rows),
        "risk_counts": risk_counts,
        "duplicate_names": duplicate_names,
        "issue_count": len(issues),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": issues,
    }


def export_registry_markdown(specs: Optional[Iterable[ToolSpec]] = None) -> str:
    spec_list = list(specs or build_all_tool_specs())
    payload = build_registry_payload(spec_list)
    lines = [
        "# QGIS Agent Tool Registry",
        "",
        f"- Schema version: {REGISTRY_SCHEMA_VERSION}",
        f"- Tool count: {payload['tool_count']}",
        f"- Health: {'OK' if payload['health']['ok'] else 'Needs attention'}",
        "",
        "| Tool | Category | Risk | Main Thread | Network | Auth | Mutates Project | Output | Path Scope | Description |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for spec in spec_list:
        description = (spec.description or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{spec.name}` | {spec.category} | {spec.risk_level} | {spec.requires_qgis_main_thread} | "
            f"{bool(spec.requires_network)} | {bool(spec.requires_auth)} | {bool(spec.mutates_project)} | "
            f"{spec.output_type} | {spec.path_scope} | {description} |"
        )
    if payload["health"]["issues"]:
        lines.extend(["", "## Health Issues", ""])
        for issue in payload["health"]["issues"]:
            lines.append(f"- [{issue.get('level')}] `{issue.get('tool')}`: {issue.get('message')}")
    return "\n".join(lines) + "\n"
