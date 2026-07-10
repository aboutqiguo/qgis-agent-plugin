import os
import threading
from qgis.PyQt.QtCore import QThread, pyqtSignal
from openai import OpenAI

DEFAULT_GLM_VISION_MODEL = "glm-4v-flash"
FREE_GLM_VISION_MODELS = {
    "glm-4v-flash",
    "glm-4.6v-flash",
    "glm-4.1v-thinking-flash",
}

class HarnessThread(QThread):
    append_message_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal()
    
    request_human_input_signal = pyqtSignal(str)
    request_destructive_auth_signal = pyqtSignal(str)
    request_plan_approval_signal = pyqtSignal()
    
    request_code_execution_signal = pyqtSignal(str)
    request_canvas_image_signal = pyqtSignal()
    request_atomic_tool_signal = pyqtSignal(str, dict)
    
    def __init__(self, plugin_dir, existing_messages=None, parent=None):
        super().__init__(parent)
        self.plugin_dir = plugin_dir
        
        from ..utils.logger import get_logger
        self.logger = get_logger()
        self.logger.info("HarnessThread initialized.")
        
        self.user_input = ""
        self.model_name = "DeepSeek-Chat"
        self.effort_level = "High"
        self.work_mode = "PLAN"
        self.messages = existing_messages if existing_messages is not None else []
        self.plan_approved = False
        
        # Events for blocking thread while waiting for GUI
        self.human_input_event = threading.Event()
        self.human_input_response = ""
        
        self.plan_approval_event = threading.Event()
        self.plan_approval_response = ""
        
        self.code_exec_event = threading.Event()
        self.code_exec_response = ""
        
        self.destructive_auth_event = threading.Event()
        self.destructive_auth_response = False
        
        self.canvas_image_event = threading.Event()
        self.canvas_image_path = ""
        
        self.atomic_tool_event = threading.Event()
        self.atomic_tool_response = ""
        
        self.is_killed = False
        self.current_run_artifacts = None
        from .step_runner import StepExecutionController
        self.step_controller = StepExecutionController()
        
        self.client = None
        self._init_client()
        from .tool_registry import build_all_tool_openai_schemas, get_atomic_tool_names
        self.tools = build_all_tool_openai_schemas()
        self.tools_by_name = {tool.get("function", {}).get("name"): tool for tool in self.tools}
        self.atomic_tool_names = set(get_atomic_tool_names())
        self.atomic_tool_names.add("take_qgis_window_snapshot")

    def _select_tools_for_request(self, text: str):
        """Return a compact tool schema subset for the current task."""
        lowered = (text or "").lower()
        selected = {
            "ask_human",
            "execute_pyqgis_script",
            "repair_common_qgis_code_issues",
            "read_file",
            "write_file",
            "replace_file_content",
            "read_skill",
            "summarize_layers",
            "validate_project_outputs",
            "save_project_and_verify",
            "run_qgis_workflow_batch",
            "run_processing_algorithm",
            "search_processing_algorithms",
            "describe_processing_algorithm",
            "validate_processing_algorithm_call",
            "search_project_layers",
            "describe_project_layer",
            "search_layer_fields",
            "search_qgis_expression_functions",
            "describe_qgis_expression_function",
            "validate_qgis_expression",
            "cleanup_qgis_project",
        }

        if any(token in lowered for token in (
            "osm", "openstreetmap", "overpass", "nominatim", "poi", "道路", "路网",
            "建筑", "建筑物", "边界", "行政区", "水系", "水面", "兴趣点",
        )):
            selected.update({
                "download_osm_data",
                "download_osm_boundary",
                "download_osm_roads",
                "download_osm_features",
                "clip_vector_layers_to_boundary",
                "search_data_sources",
                "create_data_acquisition_plan",
            })

        if any(token in lowered for token in (
            "gee", "earth engine", "google earth", "sentinel", "landsat", "copernicus",
            "dem", "ndvi", "遥感", "影像", "哨兵", "云端", "波段", "栅格",
        )):
            selected.update({
                "search_gee_api",
                "search_data_sources",
                "create_data_acquisition_plan",
                "inspect_raster_file",
                "validate_raster_has_data",
                "run_gee_sentinel2_download_workflow",
            })

        if any(token in lowered for token in (
            "出图", "制图", "布局", "layout", "地图", "渲染", "样式", "截图", "视觉",
        )):
            selected.update({
                "take_qgis_window_snapshot",
                "ask_vision_critic",
                "zoom_to_layer",
                "set_layer_visibility",
            })

        if any(token in lowered for token in ("字段", "属性", "选择", "select", "表达式", "查询")):
            selected.update({
                "list_layers",
                "inspect_layer_fields",
                "get_selected_features",
                "select_features_by_expression",
                "clear_selection",
                "zoom_to_selected",
            })

        if any(token in lowered for token in ("数据库", "geodatabase", "gpkg", "包", "安装库", "importerror", "modulenotfounderror")):
            selected.update({"create_geodatabase", "install_python_package"})

        # Short continuation prompts inherit enough tools from recent context by default.
        if len(lowered.strip()) <= 4:
            selected.update({
                "download_osm_features",
                "download_osm_boundary",
                "search_gee_api",
                "inspect_raster_file",
                "validate_raster_has_data",
                "run_gee_sentinel2_download_workflow",
                "clip_vector_layers_to_boundary",
            })

        return [self.tools_by_name[name] for name in sorted(selected) if name in self.tools_by_name]

    def _load_project_memory_context(self, project_home: str) -> str:
        import json
        import os

        memory_md_path = os.path.join(project_home, "MEMORY.md")
        summary_path = os.path.join(project_home, "MEMORY_SUMMARY.md")
        index_path = os.path.join(project_home, "RUN_INDEX.json")
        if not os.path.exists(memory_md_path):
            return (
                f"-- MEMORY.md --\n"
                f"(No project facts recorded yet. You can create this file using `write_file` at its absolute path: `{memory_md_path}`)\n\n"
            )

        try:
            memory_mtime = os.path.getmtime(memory_md_path)
            summary_stale = not os.path.exists(summary_path) or os.path.getmtime(summary_path) < memory_mtime
            if summary_stale:
                with open(memory_md_path, "r", encoding="utf-8", errors="ignore") as handle:
                    memory_text = handle.read()
                summary = self._summarize_memory_text(memory_text, memory_md_path)
                with open(summary_path, "w", encoding="utf-8") as handle:
                    handle.write(summary)
                index_payload = self._build_project_run_index(project_home, memory_md_path, summary_path)
                with open(index_path, "w", encoding="utf-8") as handle:
                    json.dump(index_payload, handle, ensure_ascii=False, indent=2)
            with open(summary_path, "r", encoding="utf-8", errors="ignore") as handle:
                summary_text = handle.read()
            return (
                f"-- MEMORY_SUMMARY.md (Compact Project Memory, Absolute Path: `{summary_path}`) --\n"
                f"{summary_text}\n\n"
                f"-- MEMORY.md --\n"
                f"Full memory is available at `{memory_md_path}`. Use `read_file` with `summary_only=false`, "
                "a `pattern`, or a small line range only when the compact summary is insufficient.\n\n"
                f"-- RUN_INDEX.json --\n"
                f"Project run/file index is available at `{index_path}` for targeted reads.\n\n"
            )
        except Exception as exc:
            self.logger.warning(f"Failed to load compact project memory: {exc}")
            with open(memory_md_path, "r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read(6000)
            return (
                f"-- MEMORY.md (truncated fallback, Absolute Path: `{memory_md_path}`) --\n"
                f"{text}\n\n...[MEMORY.md truncated for token budget. Use read_file for targeted details.]...\n\n"
            )

    def _summarize_memory_text(self, text: str, memory_path: str) -> str:
        import re
        lines = (text or "").splitlines()
        selected = []
        important_patterns = re.compile(
            r"(结论|错误|失败|bug|BUG|split_bbox|removeMapLayer|provider|OSM|要素数|工具|已知正确做法|待修复|P0|P1|P2|token)",
            re.IGNORECASE,
        )
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or important_patterns.search(stripped):
                selected.append(stripped)
            if len("\n".join(selected)) > 5000:
                break
        if not selected:
            selected = [line for line in lines[:80] if line.strip()]
        body = "\n".join(selected)
        if len(body) > 6000:
            body = body[:6000] + "\n...[summary truncated]..."
        return (
            "# MEMORY_SUMMARY\n\n"
            f"Source: `{memory_path}`\n\n"
            "This compact summary is auto-generated to reduce token usage. Update MEMORY.md for durable facts; "
            "the summary refreshes when MEMORY.md changes.\n\n"
            + body
            + "\n"
        )

    def _build_project_run_index(self, project_home: str, memory_path: str, summary_path: str) -> dict:
        import os
        from datetime import datetime

        indexed_files = []
        for root, _dirs, files in os.walk(project_home):
            rel_root = os.path.relpath(root, project_home)
            if rel_root.startswith(".qgis_agent_runs"):
                continue
            for file_name in files:
                path = os.path.join(root, file_name)
                rel = os.path.relpath(path, project_home).replace("\\", "/")
                if file_name.lower().endswith((".md", ".json", ".jsonl", ".qgz", ".qgs", ".gpkg", ".geojson", ".tif", ".shp")):
                    try:
                        indexed_files.append({"path": rel, "size": os.path.getsize(path)})
                    except Exception:
                        indexed_files.append({"path": rel})
        indexed_files.sort(key=lambda item: item.get("path", ""))
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "memory": os.path.relpath(memory_path, project_home).replace("\\", "/"),
            "memory_summary": os.path.relpath(summary_path, project_home).replace("\\", "/"),
            "files": indexed_files[:300],
            "truncated": len(indexed_files) > 300,
        }

    def _prepare_messages(self):
        from qgis.core import QgsSettings, QgsProject
        settings = QgsSettings()
        personality = settings.value("qgis_agent/agent_personality", "")
        project_home = QgsProject.instance().homePath()

        base_prompt = "You are an advanced PyQGIS Agent. You can execute python code directly in the QGIS Python environment.\n"
        
        if personality:
            base_prompt += f"\n### [USER DEFINED PERSONALITY & RULES] ###\n{personality}\n"
        
        # Inject Durable Curated Memory (Hermes Architecture)
        base_prompt += "\n### 🧠 [DURABLE CURATED MEMORY] ###\n"
        base_prompt += "These markdown files represent your long-term memory. You MUST adhere to the rules within them.\n"
        base_prompt += "If you learn new facts, environment quirks, or user preferences, you MUST proactively use the `write_file` or `replace_file_content` tools to update these files so you don't forget!\n\n"
        base_prompt += "\n### TOOL RESULT CONTRACT ###\n"
        base_prompt += "Atomic tools may return JSON with keys: ok, message, data, artifacts, warnings, error_type, suggestions. Always inspect ok first. If ok is false, use error_type and suggestions to plan a smaller repair step. In PLAN mode, tool results may also include data.planner_verifier with per-step verification status, quality_score, failure_type, retry_recommended, and retry_action.\n\n"
        base_prompt += "\n### COMMON QGIS REPAIR TOOL ###\n"
        base_prompt += "When PyQGIS code fails with common QGIS 3.44 mistakes such as OSMDownloader signature errors, QgsColorRampShaderItem, LayerType.toString(), numPoints(), bare addMapLayer duplicates, QgsRasterFileWriter.writeRaster, raster min/max, or pseudo-color renderer provider errors, call `repair_common_qgis_code_issues` with the failed code and traceback before retrying.\n\n"
        base_prompt += "For batch clipping OSM/admin/POI/vector layers to a boundary, prefer `clip_vector_layers_to_boundary` over hand-written processing loops. Provide explicit output file names and output layer names. After any task that changes project layers or outputs, call `save_project_and_verify` before claiming the QGIS project is complete.\n\n"
        base_prompt += "\n### DATA SOURCE HANDBOOK ###\n"
        base_prompt += "Before downloading or generating new GIS data, call `search_data_sources` or `create_data_acquisition_plan` unless the user already provided a concrete local file/source. Prefer sources with clear coverage, license, access method, and QGIS workflow. Record source id, URL, license, CRS, and processing notes in artifacts.\n\n"
        base_prompt += "\n### ARTIFACT SYSTEM 2.0 ###\n"
        base_prompt += "Run artifacts include `manifest.json`, `index.md`, `events.jsonl`, tool calls, planner state, reports, screenshots, and data source handbook outputs. Use these artifacts to explain what happened and how to reproduce data acquisition.\n\n"
        
        import os
        user_md_path = os.path.join(self.plugin_dir, "USER.md")
        legacy_user_md_path = os.path.join(self.plugin_dir, "ui", "USER.md")
        
        if os.path.exists(user_md_path):
            with open(user_md_path, "r", encoding="utf-8") as f:
                base_prompt += f"-- USER.md (Global User Preferences/Facts, Absolute Path: `{user_md_path}`) --\n{f.read()}\n\n"
        elif os.path.exists(legacy_user_md_path):
            with open(legacy_user_md_path, "r", encoding="utf-8") as f:
                base_prompt += f"-- USER.md (Global User Preferences/Facts, Legacy Path: `{legacy_user_md_path}`) --\n{f.read()}\n\n"
        else:
            base_prompt += f"-- USER.md --\n(No global preferences recorded yet. You can create this file using `write_file` at its absolute path: `{user_md_path}`)\n\n"
            
        if project_home:
            base_prompt += self._load_project_memory_context(project_home)
        import os
        base_dir = os.path.dirname(os.path.dirname(__file__))
        
        # 1. Scan and build skill manifest
        skill_manifest = "可用技能目录:\n"
        skills_core_dir = os.path.join(base_dir, "skills", "core")
        skills_dyn_dir = os.path.join(base_dir, "skills", "dynamic")
        
        for d in [skills_core_dir, skills_dyn_dir]:
            if os.path.exists(d):
                for f_name in os.listdir(d):
                    if f_name.endswith('.md'):
                        try:
                            with open(os.path.join(d, f_name), 'r', encoding='utf-8') as sf:
                                content = sf.read()
                                import re
                                name_match = re.search(r'<name>(.*?)</name>', content, re.DOTALL)
                                desc_match = re.search(r'<description>(.*?)</description>', content, re.DOTALL)
                                if name_match and desc_match:
                                    skill_manifest += f"- `{name_match.group(1).strip()}`: {desc_match.group(1).strip()}\n"
                        except Exception:
                            pass
        
        # 2. Load core system prompt
        prompt_path = os.path.join(base_dir, "prompts", "system_prompt.md")
        cheat_sheet = ""
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                cheat_sheet = f.read().replace("{skill_directory}", skill_manifest)
                
        base_prompt += "\n" + cheat_sheet + "\n"
        if self.work_mode == "PLAN":
            base_prompt += """
### ⚠️ CRITICAL WORKFLOW (PLAN MODE & ARTIFACT TRACKING)
1. **PLAN FIRST**: Do NOT call `execute_pyqgis_script` to solve the problem immediately! First, you MUST formulate a detailed plan and a markdown checklist of steps. 
   - ⚠️ FORMAT: Your markdown checklist MUST strictly follow this format, using proper bullet points (`- `) and a main header:
     # 任务执行进度
     
     - [ ] 步骤1：...
     - [ ] 步骤2：...
   - ⚠️ CRITICAL: Your initially proposed plan MUST have ALL steps marked as pending `[ ]`. Do NOT mark any step as completed `[x]` before you have actually executed the code for it!
2. **SUBMIT PLAN**: You MUST call `submit_plan_for_approval` and pass your full markdown plan into the 'plan_markdown' argument. This will automatically save it to `task.md` and pause execution for human review. DO NOT proceed without calling this tool!
3. **EXECUTE & VERIFY (ReAct)**: Once the user approves, execute ONE step at a time using `execute_pyqgis_script`. To save tokens, you don't need to update `task.md` after every single minor tool call. However, you MUST use `replace_file_content` to update the checkboxes (e.g., `[x]`) in `task.md` before you finish your turn (when you are about to stop calling tools and reply to the user).
4. **WALKTHROUGH**: After all steps are completed, create a `walkthrough.md` summarizing what you accomplished.
5. **PLANNER / VERIFIER MVP**: After plan approval, execute only ONE execution tool call per assistant response. Wait for the verifier result in `data.planner_verifier` before moving to the next step. If the verifier fails, inspect `quality_score`, `failure_type`, `retry_recommended`, and `retry_action`; repair the same step or revise the plan, and do not continue to later steps.
6. **DATA SOURCE FIRST**: If the task needs new external data, first use `create_data_acquisition_plan` or `search_data_sources` to choose a source and document license/access notes before calling download tools.
"""
        else:
            base_prompt += """
### 🟢 CRITICAL WORKFLOW (WORK MODE)
You are in auto-execute mode. You DO NOT need to submit plans for approval. You can directly call `execute_pyqgis_script` to fulfill the user's request immediately.
"""
        # Clean existing system prompts to avoid duplicates across restarts
        self.messages[:] = [m for m in self.messages if m.get("role") != "system"]
        
        # Self-heal corrupted memory from huge outputs that crash the LLM API
        for m in self.messages:
            if m.get("role") == "tool" and isinstance(m.get("content"), str):
                m["content"] = self._compact_tool_result(m.get("name", "tool"), {}, m["content"], max_chars=5000)
            if isinstance(m.get("content"), str) and len(m["content"]) > 15000:
                original_len = len(m["content"])
                m["content"] = m["content"][:5000] + f"\n\n...[Output middle truncated! Original length: {original_len} chars. Too long for context.]...\n\n" + m["content"][-5000:]
                
        self.messages.insert(0, {"role": "system", "content": base_prompt})

    def _get_qgis_context(self):
        try:
            from qgis.core import QgsProject
            import os
            context_str = "### CURRENT QGIS ENVIRONMENT CONTEXT ###\n"
            layers = QgsProject.instance().mapLayers()
            if not layers:
                context_str += "- Loaded Map Layers: None\n"
            else:
                context_str += "- Loaded Map Layers:\n"
                for layer_id, layer in layers.items():
                    context_str += f"  * {layer.name()}\n"
                    
            home = QgsProject.instance().homePath()
            if home and os.path.exists(home):
                context_str += f"- Project Home Directory ({home}) contains:\n"
                try:
                    files = os.listdir(home)
                    context_str += f"  {', '.join(files[:30])}\n"
                except:
                    pass
            return context_str
        except Exception:
            return "### CURRENT QGIS ENVIRONMENT CONTEXT ###\n(Context unavailable)"
        
    def _process_mentions(self, text):
        import re
        from qgis.core import QgsProject
        
        mentions = re.findall(r'@([^\s]+)', text)
        if not mentions:
            return ""
            
        context = []
        layers = QgsProject.instance().mapLayers().values()
        
        for mention in mentions:
            mention_lower = mention.lower()
            matched_layer = None
            for layer in layers:
                if mention_lower in layer.name().lower():
                    matched_layer = layer
                    break
                    
            if matched_layer:
                crs = matched_layer.crs()
                crs_info = crs.authid() if crs.isValid() else "Invalid/None"
                bbox = matched_layer.extent().toString()
                source = matched_layer.source()
                context.append(f"- Layer '{matched_layer.name()}': CRS={crs_info}, Extent={bbox}, Path={source}")
                
        return "\n".join(context)

    def _get_auto_rag_context(self, user_text):
        context_parts = []
        try:
            from .sqlite_memory import SqliteMemoryDB
            mem_db = SqliteMemoryDB()
            # Extract basic keywords from prompt for searching (simplistic approach)
            import re
            # Filter out common stop words or very short words
            keywords = [w for w in re.split(r'\W+', user_text) if len(w) > 1][:5]
            if keywords:
                query = " OR ".join(keywords)
                # 1. Search Episodic Memory
                past_conv = mem_db.search_conversations(query, limit=2)
                if past_conv and not past_conv.startswith("Error") and not past_conv.startswith("No past"):
                    context_parts.append(f"--- Similar Past Conversations ---\n{past_conv}")
                
                # 2. Search Skills
                from qgis.core import QgsProject
                import os, json
                prj_home = QgsProject.instance().homePath()
                if prj_home:
                    index_file = os.path.join(prj_home, "agent_skills", "skills_index.json")
                    if os.path.exists(index_file):
                        with open(index_file, "r", encoding="utf-8") as f:
                            index_data = json.load(f)
                        matches = []
                        for s_name, s_info in index_data.items():
                            if any(k.lower() in s_name.lower() or k.lower() in s_info.get("description", "").lower() for k in keywords):
                                code_path = os.path.join(prj_home, "agent_skills", s_info["file"])
                                if os.path.exists(code_path):
                                    with open(code_path, "r", encoding="utf-8") as cf:
                                        matches.append(f"Skill: {s_name}\nCode:\n```python\n{cf.read()}\n```")
                        if matches:
                            context_parts.append("--- Relevant Procedural Skills ---\n" + "\n\n".join(matches[:2]))
        except Exception as e:
            self.logger.warning(f"Auto-RAG failed: {e}")
            
        if context_parts:
            return "[System Auto-RAG (Passive Memory Injection)]\n" + "\n\n".join(context_parts)
        return ""

    def _init_client(self):
        from qgis.core import QgsSettings
        s = QgsSettings()
        api_key = s.value("qgis_agent/deepseek_api_key", "")
        base_url = s.value("qgis_agent/deepseek_base_url", "https://api.deepseek.com")
        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.logger.error("DeepSeek API Key not configured in Settings.")
            self.append_message_signal.emit("SYSTEM", "Error: DeepSeek API Key not configured. Please open Settings (⚙️).")
            self.finished_signal.emit()
            return

    def _get_glm_vision_model(self):
        from qgis.core import QgsSettings
        model = str(QgsSettings().value("qgis_agent/glm_vision_model", DEFAULT_GLM_VISION_MODEL) or DEFAULT_GLM_VISION_MODEL)
        if model not in FREE_GLM_VISION_MODELS:
            self.logger.warning(
                f"Unsupported GLM vision model '{model}' in settings; falling back to {DEFAULT_GLM_VISION_MODEL}."
            )
            return DEFAULT_GLM_VISION_MODEL
        return model

    def _is_path_within(self, path, root):
        path = os.path.abspath(os.path.normcase(path))
        root = os.path.abspath(os.path.normcase(root))
        try:
            return os.path.commonpath([path, root]) == root
        except ValueError:
            return False

    def _resolve_agent_file_path(self, file_path, for_write=False):
        import tempfile
        from qgis.core import QgsProject

        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("file_path is empty.")

        raw_path = file_path.strip().strip('"')
        project_home = QgsProject.instance().homePath()
        user_md_path = os.path.abspath(os.path.join(self.plugin_dir, "USER.md"))

        if raw_path in ("USER.md", "./USER.md"):
            resolved = user_md_path
        elif raw_path in ("MEMORY.md", "./MEMORY.md"):
            if not project_home:
                raise ValueError("MEMORY.md requires a saved QGIS project.")
            resolved = os.path.join(project_home, "MEMORY.md")
        elif not os.path.isabs(raw_path):
            if not project_home:
                raise ValueError("Relative file paths require a saved QGIS project.")
            resolved = os.path.join(project_home, raw_path)
        else:
            resolved = raw_path

        resolved = os.path.abspath(os.path.normpath(resolved))

        allowed_roots = [tempfile.gettempdir()]
        if project_home:
            allowed_roots.append(project_home)

        if resolved != user_md_path and not any(self._is_path_within(resolved, root) for root in allowed_roots):
            action = "Write" if for_write else "Read"
            raise PermissionError(
                f"{action} denied. The agent can only access files inside the current QGIS project folder, "
                "the system temp folder, or USER.md in the plugin folder."
            )

        return resolved

    def _needs_file_write_confirmation(self, file_path):
        return not self._is_agent_managed_file(file_path) and os.path.exists(file_path)

    def _is_agent_managed_file(self, file_path):
        from qgis.core import QgsProject

        managed_paths = {os.path.abspath(os.path.join(self.plugin_dir, "USER.md"))}
        project_home = QgsProject.instance().homePath()
        if project_home:
            for name in ("MEMORY.md", "task.md", "walkthrough.md"):
                managed_paths.add(os.path.abspath(os.path.join(project_home, name)))
            runs_dir = os.path.abspath(os.path.join(project_home, ".qgis_agent_runs"))
            try:
                if os.path.commonpath([os.path.abspath(file_path), runs_dir]) == runs_dir:
                    return True
            except ValueError:
                pass

        return os.path.abspath(file_path) in managed_paths

    def _confirm_file_write(self, action, file_path, preview_text=""):
        tool_name = "replace_file_content" if action.lower().startswith("modify") else "write_file"
        approved, _decision = self._request_tool_approval(
            tool_name,
            {"file_path": file_path, "content": preview_text or ""},
            {
                "resolved_file_path": file_path,
                "file_exists": os.path.exists(file_path),
                "managed_file": self._is_agent_managed_file(file_path),
                "preview": preview_text,
            },
        )
        return approved

    def _request_tool_approval(self, tool_name, args, context=None):
        from .approval_policy import ToolApprovalPolicy

        decision = ToolApprovalPolicy(self.plugin_dir).evaluate(tool_name, args, context)
        if not decision.requires_approval:
            self._record_approval_decision(tool_name, args, decision, user_approved=None)
            return True, decision

        self.destructive_auth_response = False
        self.destructive_auth_event.clear()
        self.request_destructive_auth_signal.emit(decision.approval_prompt)
        if not self._wait_for_event(self.destructive_auth_event, 300, "approval response"):
            self._record_approval_decision(tool_name, args, decision, user_approved=False)
            return False, decision
        if self.is_killed:
            self._record_approval_decision(tool_name, args, decision, user_approved=False)
            return False, decision
        approved = bool(self.destructive_auth_response)
        self._record_approval_decision(tool_name, args, decision, user_approved=approved)
        return approved, decision

    def _wait_for_event(self, event, timeout_seconds, label):
        if event.wait(timeout_seconds):
            return True
        self.logger.warning(f"Timed out waiting for {label} after {timeout_seconds} seconds.")
        self.append_message_signal.emit(
            "SYSTEM",
            f"Timeout while waiting for {label}. The operation was cancelled safely.",
        )
        return False

    def _record_approval_decision(self, tool_name, args, decision, user_approved=None):
        try:
            artifacts = self._ensure_run_artifacts()
            if not artifacts:
                return
            artifacts.append_approval_decision({
                "tool": tool_name,
                "risk_level": decision.risk_level,
                "requires_approval": decision.requires_approval,
                "reason": decision.reason,
                "warnings": decision.warnings,
                "user_approved": user_approved,
                "arguments_summary": self._summarize_tool_args(args),
            })
        except Exception as e:
            self.logger.warning(f"Failed to record approval decision for {tool_name}: {e}")

    def _summarize_tool_args(self, args):
        summary = {}
        for key, value in (args or {}).items():
            text = "" if value is None else str(value)
            if len(text) > 300:
                text = text[:300] + f"...[truncated {len(text) - 300} chars]"
            summary[key] = text
        return summary

    def _estimate_tokens_from_chars(self, chars: int) -> int:
        return max(1, int(chars / 3.2))

    def _compact_value(self, value, max_chars=1200, max_items=20):
        if isinstance(value, dict):
            compact = {}
            for key, item in list(value.items())[:max_items]:
                compact[key] = self._compact_value(item, max_chars=max_chars, max_items=max_items)
            if len(value) > max_items:
                compact["_truncated_keys"] = len(value) - max_items
            return compact
        if isinstance(value, list):
            compact = [self._compact_value(item, max_chars=max_chars, max_items=max_items) for item in value[:max_items]]
            if len(value) > max_items:
                compact.append({"_truncated_items": len(value) - max_items})
            return compact
        text = "" if value is None else str(value)
        if len(text) > max_chars:
            return text[:max_chars] + f"...[truncated {len(text) - max_chars} chars]"
        return value

    def _compact_tool_result(self, tool_name, args, content, max_chars=7000):
        import json

        text = "" if content is None else str(content)
        if len(text) <= max_chars:
            return text
        try:
            payload = json.loads(text)
        except Exception:
            return text[: max_chars // 2] + f"\n\n...[tool output truncated for token budget; original {len(text)} chars]...\n\n" + text[- max_chars // 3:]

        ok = bool(payload.get("ok"))
        compact_data = self._compact_value(payload.get("data") or {}, max_chars=900 if ok else 1800, max_items=14)
        compact_artifacts = self._compact_value(payload.get("artifacts") or [], max_chars=500, max_items=12)
        compact = {
            "ok": ok,
            "message": self._compact_value(payload.get("message", ""), max_chars=1500 if ok else 3000),
            "data": compact_data,
            "artifacts": compact_artifacts,
            "warnings": self._compact_value(payload.get("warnings") or [], max_chars=900, max_items=10),
            "token_optimized": True,
            "full_result_recorded_in": "current run tool_calls.jsonl and tool result artifacts",
        }
        if payload.get("error_type"):
            compact["error_type"] = payload.get("error_type")
        if payload.get("suggestions"):
            compact["suggestions"] = self._compact_value(payload.get("suggestions"), max_chars=900, max_items=8)
        compact_text = json.dumps(compact, ensure_ascii=False, default=str)
        if len(compact_text) > max_chars:
            compact["data"] = {"summary": f"{tool_name} returned a large result. Full result is in artifacts.", "original_chars": len(text)}
            compact_text = json.dumps(compact, ensure_ascii=False, default=str)
        return compact_text

    def _record_llm_usage(self, response, model_name, messages_to_send):
        import json
        import os
        from datetime import datetime

        try:
            prompt_chars = sum(len(str(m.get("content", ""))) for m in messages_to_send or [])
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None
            estimated = False
            if total_tokens is None:
                estimated = True
                prompt_tokens = self._estimate_tokens_from_chars(prompt_chars)
                try:
                    completion_text = response.choices[0].message.content or ""
                except Exception:
                    completion_text = ""
                completion_tokens = self._estimate_tokens_from_chars(len(completion_text))
                total_tokens = prompt_tokens + completion_tokens
            payload = {
                "time": datetime.now().isoformat(timespec="seconds"),
                "model": model_name,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated": estimated,
                "prompt_chars": prompt_chars,
                "message_count": len(messages_to_send or []),
            }
            artifacts = self._ensure_run_artifacts()
            if artifacts:
                artifacts.append_jsonl("token_usage.jsonl", payload, role="token_usage", description="LLM token usage per request.")
            utils_dir = os.path.join(self.plugin_dir, "utils")
            os.makedirs(utils_dir, exist_ok=True)
            with open(os.path.join(utils_dir, "token_usage.jsonl"), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:
            self.logger.warning(f"Failed to record LLM token usage: {exc}")

    def _read_file_for_agent(self, file_path: str, args: dict) -> str:
        import json
        import os
        import re
        from .tool_result import ToolResult

        max_chars = int(args.get("max_chars", 6000) or 6000)
        summary_only = args.get("summary_only", True)
        pattern = args.get("pattern", "")
        start_line = int(args.get("start_line", 0) or 0)
        line_count = int(args.get("line_count", 0) or 0)

        if not os.path.exists(file_path):
            return ToolResult.failure(
                f"File not found at {file_path}",
                error_type="file_path_error",
                data={"file_path": file_path},
            ).to_json()
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
        lines = text.splitlines()
        selected = text
        mode = "full"
        if pattern:
            mode = "pattern"
            regex = re.compile(pattern, re.IGNORECASE)
            matches = []
            for index, line in enumerate(lines, start=1):
                if regex.search(line):
                    lo = max(1, index - 2)
                    hi = min(len(lines), index + 2)
                    for line_no in range(lo, hi + 1):
                        matches.append(f"{line_no}: {lines[line_no - 1]}")
            selected = "\n".join(matches)
        elif start_line or line_count:
            mode = "line_range"
            start = max(1, start_line or 1)
            count = max(1, line_count or 120)
            selected = "\n".join(f"{i}: {line}" for i, line in enumerate(lines[start - 1:start - 1 + count], start=start))
        elif summary_only and len(text) > max_chars:
            mode = "summary"
            head = "\n".join(lines[:80])
            tail = "\n".join(lines[-40:]) if len(lines) > 120 else ""
            selected = head + ("\n\n...[middle omitted for token budget]...\n\n" + tail if tail else "")

        truncated = False
        if len(selected) > max_chars:
            truncated = True
            selected = selected[:max_chars] + f"\n...[truncated {len(selected) - max_chars} chars; use start_line/line_count or pattern for more]..."
        return ToolResult.success(
            f"Read {os.path.basename(file_path)} using {mode} mode.",
            data={
                "file_path": file_path,
                "size": os.path.getsize(file_path),
                "line_count": len(lines),
                "mode": mode,
                "truncated": truncated,
                "content": selected,
            },
        ).to_json()

    def _validate_tool_call(self, tool_call, tool_name, args):
        try:
            from .validators import validate_tool_call
            report = validate_tool_call(tool_name, args)
            if report.ok:
                return True

            from .tool_result import ToolResult
            result = ToolResult.failure(
                "Tool validation failed before execution.",
                error_type="argument_error",
                data={"tool": tool_name, "validation": report.to_dict()},
            ).to_json()
            self._record_artifact_tool_call(tool_name, args, result)
            model_result = self._compact_tool_result(tool_name, args, result)
            self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": model_result,
            })
            return False
        except Exception as e:
            self.logger.warning(f"Tool validation failed internally for {tool_name}: {e}")
            return True

    def _append_tool_result(self, tool_call, tool_name, args, result, record_artifact=True, planner_complete=True):
        from .tool_result import normalize_tool_output

        content = normalize_tool_output(tool_name, result)
        if planner_complete:
            content = self._complete_planner_step(tool_call, tool_name, args, content)
        if record_artifact:
            self._record_artifact_tool_call(tool_name, args, content)
        model_content = self._compact_tool_result(tool_name, args, content)
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_name,
            "content": model_content,
        })
        return model_content

    def _project_home(self):
        try:
            from qgis.core import QgsProject
            return QgsProject.instance().homePath() or ""
        except Exception:
            return ""

    def _register_planner_plan(self, plan_markdown):
        try:
            from .planner import build_task_plan_from_markdown
            plan = build_task_plan_from_markdown(plan_markdown, self.user_input)
            artifacts = self._ensure_run_artifacts()
            artifact_dir = artifacts.run_dir if artifacts else ""
            self.step_controller.load_plan(plan, self._project_home(), artifact_dir)
            if artifacts:
                artifacts.write_task_plan(plan.to_dict())
                artifacts.append_step_event({
                    "event": "plan_registered",
                    "plan": plan.to_dict(),
                })
            self.append_message_signal.emit(
                "SYSTEM",
                f"Planner registered {len(plan.steps)} step(s). Verifier will check each step before continuing.",
            )
            return plan
        except Exception as e:
            self.logger.warning(f"Failed to register planner plan: {e}")
            return None

    def _begin_planner_response(self):
        try:
            self.step_controller.start_response()
        except Exception as e:
            self.logger.warning(f"Failed to start planner response window: {e}")

    def _before_step_tool_call(self, tool_call, tool_name, args):
        try:
            gate = self.step_controller.begin_tool_call(tool_call.id, tool_name, args)
            if gate.allowed:
                if gate.step:
                    self._record_step_event({
                        "event": "step_started",
                        "step": gate.step.to_dict(),
                        "tool": tool_name,
                        "arguments": args,
                    })
                return True

            from .tool_result import ToolResult
            blocked = ToolResult.failure(
                gate.message,
                error_type="argument_error",
                data={"tool": tool_name, "planner": self.step_controller.to_dict()},
                suggestions=["Wait for the current step verification before calling another execution tool."],
            ).to_json()
            self._append_tool_result(
                tool_call,
                tool_name,
                args,
                blocked,
                planner_complete=False,
            )
            return False
        except Exception as e:
            self.logger.warning(f"Planner step gate failed internally for {tool_name}: {e}")
            return True

    def _complete_planner_step(self, tool_call, tool_name, args, content):
        try:
            verification = self.step_controller.complete_tool_call(tool_call.id, tool_name, args, content)
            if not verification:
                return content

            import json
            payload = json.loads(content)
            payload.setdefault("data", {})
            payload.setdefault("warnings", [])
            payload["data"]["planner_verifier"] = verification.to_dict()
            payload["data"]["planner_state"] = self.step_controller.to_dict()
            if not verification.ok:
                payload["warnings"].append(verification.message)

            self._record_step_event({
                "event": "step_verified",
                "tool": tool_name,
                "arguments": args,
                "verification": verification.to_dict(),
                "planner": self.step_controller.to_dict(),
            })
            self._write_planner_state_artifact()
            retry_hint = " retry recommended" if verification.retry_recommended else ""
            self.append_message_signal.emit(
                "SYSTEM",
                f"Verifier: {verification.message} (score={verification.quality_score}, "
                f"severity={verification.severity}{retry_hint})",
            )
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception as e:
            self.logger.warning(f"Planner step verification failed internally for {tool_name}: {e}")
            return content

    def _record_step_event(self, payload):
        try:
            artifacts = self._ensure_run_artifacts()
            if artifacts:
                artifacts.append_step_event(payload)
        except Exception as e:
            self.logger.warning(f"Failed to record planner step event: {e}")

    def _write_planner_state_artifact(self):
        try:
            artifacts = self._ensure_run_artifacts()
            if artifacts and self.step_controller.plan:
                artifacts.write_task_plan(self.step_controller.plan.to_dict())
        except Exception as e:
            self.logger.warning(f"Failed to write planner state artifact: {e}")

    def _ensure_run_artifacts(self):
        if self.current_run_artifacts:
            return self.current_run_artifacts
        try:
            from qgis.core import QgsProject
            home = QgsProject.instance().homePath()
            if not home:
                return None
            from .artifacts import AgentRunArtifacts
            self.current_run_artifacts = AgentRunArtifacts.create(home, self.user_input)
            self.current_run_artifacts.write_tool_registry_artifacts()
            self.logger.info(f"Created agent run artifact directory: {self.current_run_artifacts.run_dir}")
            return self.current_run_artifacts
        except Exception as e:
            self.logger.warning(f"Failed to initialize run artifacts: {e}")
            return None

    def _record_artifact_tool_call(self, tool_name, arguments, result):
        try:
            artifacts = self._ensure_run_artifacts()
            if artifacts:
                artifacts.append_tool_call(tool_name, arguments, result)
                artifacts.write_tool_result_artifacts(tool_name, result)
        except Exception as e:
            self.logger.warning(f"Failed to record tool call artifact for {tool_name}: {e}")

    def _capture_artifact_snapshot(self):
        try:
            artifacts = self._ensure_run_artifacts()
            if not artifacts:
                return ""
            self.canvas_image_path = ""
            self.canvas_image_event.clear()
            self.request_canvas_image_signal.emit()
            if not self.canvas_image_event.wait(15):
                self.logger.warning("Timed out while capturing map canvas artifact snapshot.")
                return ""
            if self.is_killed or not self.canvas_image_path or not os.path.exists(self.canvas_image_path):
                return ""
            return artifacts.copy_file(self.canvas_image_path, "map_snapshot.png")
        except Exception as e:
            self.logger.warning(f"Failed to capture artifact snapshot: {e}")
            return ""

    def _write_layer_report_artifact(self):
        try:
            artifacts = self._ensure_run_artifacts()
            if not artifacts:
                return ""
            from .result_inspector import build_layer_report_markdown
            report_markdown = build_layer_report_markdown()
            return artifacts.write_layer_report(report_markdown)
        except Exception as e:
            self.logger.warning(f"Failed to write layer report artifact: {e}")
            return ""

    def _write_artifact_result(self, summary, ok=True):
        try:
            artifacts = self._ensure_run_artifacts()
            if artifacts:
                snapshot_path = self._capture_artifact_snapshot()
                layer_report_path = self._write_layer_report_artifact()
                report_path = artifacts.write_final_report(
                    summary=summary,
                    ok=ok,
                    layer_report_path=layer_report_path,
                    snapshot_path=snapshot_path,
                )
                artifacts.write_result(
                    ok=ok,
                    summary=summary,
                    data={
                        "map_snapshot": snapshot_path,
                        "layer_report": layer_report_path,
                        "report": report_path,
                    },
                )
        except Exception as e:
            self.logger.warning(f"Failed to write run result artifact: {e}")

    def run(self):
        if not getattr(self, 'client', None):
            self.logger.error("Client not initialized. API Key missing.")
            self.finished_signal.emit()
            return
            
        self.logger.info(f"User Input: {self.user_input}")
        
        # Process Meltdown "Continue" Trigger
        continue_keywords = ["继续尝试", "继续", "再试一次", "再试", "keep trying", "try again", "continue"]
        if any(k in self.user_input.lower() for k in continue_keywords):
            lateral_prompt = "\n\n[System Auto-Trigger]: 之前的方法已经证明彻底失效（已熔断）。由于用户要求继续尝试，你现在【必须】彻底放弃之前的代码架构和使用的类库。请尝试使用完全不同的替代方案（例如：放弃 PyQGIS 接口，改用原生 GDAL/OGR 处理；或者换一个不同的算法处理逻辑）。"
            self.user_input += lateral_prompt
            
        # Process @ mentions
        self.ghost_context = self._process_mentions(self.user_input)
        if self.ghost_context:
            self.logger.info(f"Injected Ghost Context:\n{self.ghost_context}")
            
        # Process IMAGE_ATTACHMENT
        import re
        img_match = re.search(r"\[IMAGE_ATTACHMENT\](.*)", self.user_input)
        if img_match:
            img_path = img_match.group(1).strip()
            self.append_message_signal.emit("SYSTEM", "✨ 正在将附带的截图发给视觉大模型进行预处理...")
            import time; time.sleep(0.1)
            import base64, requests
            try:
                with open(img_path, "rb") as f:
                    base64_image = base64.b64encode(f.read()).decode('utf-8')
                from qgis.core import QgsSettings
                glm_key = QgsSettings().value("qgis_agent/glm_api_key", "")
                glm_base_url = QgsSettings().value("qgis_agent/glm_base_url", "https://open.bigmodel.cn/api/paas/v4")
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {glm_key}"
                }
                user_prompt = self.user_input.replace(img_match.group(0), "")
                glm_vision_model = self._get_glm_vision_model()
                payload = {
                    "model": glm_vision_model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Please provide a detailed description of this image. The user attached it to a QGIS Copilot session with the following prompt:\n'{user_prompt}'"},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                        ]
                    }]
                }
                resp = requests.post(f"{glm_base_url}/chat/completions", headers=headers, json=payload, timeout=30)
                if resp.status_code == 200:
                    vision_desc = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
                    self.user_input = self.user_input.replace(img_match.group(0), f"\n\n[Vision Model Analysis of User's Attached Image]:\n{vision_desc}")
                    self.logger.info("Successfully converted image to text description via GLM.")
                else:
                    self.user_input = self.user_input.replace(img_match.group(0), f"\n\n[Error analyzing image: {resp.status_code}]")
            except Exception as e:
                self.user_input = self.user_input.replace(img_match.group(0), f"\n\n[Exception analyzing image: {str(e)}]")
            
        self._prepare_messages()
        
        # Self-repair: Fix hanging tool_calls from previously interrupted sessions
        # If the user kills the thread during tool execution, the assistant's tool_calls message
        # is saved to memory, but the corresponding 'tool' response is never appended.
        # This causes OpenAI to throw a 400 BadRequest on the next turn.
        if self.messages and self.messages[-1].get("role") == "assistant" and self.messages[-1].get("tool_calls"):
            self.logger.warning("Detected hanging tool_calls from an interrupted session. Injecting repair messages...")
            from .tool_result import ToolResult
            for tc in self.messages[-1]["tool_calls"]:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, 'id', '')
                tc_func = tc.get("function", {}) if isinstance(tc, dict) else getattr(tc, "function", None)
                tc_name = tc_func.get("name", "") if isinstance(tc_func, dict) else getattr(tc_func, "name", "")
                if tc_id:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "name": tc_name,
                        "content": ToolResult.failure(
                            "Tool execution was cancelled by the user in the previous session.",
                            error_type="unknown_error",
                            data={"tool": tc_name},
                        ).to_json(),
                    })
        
        # Process Auto-Reflection Trigger
        completion_keywords = ["完成", "结束", "好了", "done", "finish"]
        if any(k in self.user_input.lower() for k in completion_keywords):
            reflection_prompt = "\n\n[System Auto-Trigger]: The user indicates the current task might be completed. Please take a moment to reflect on any new constraints, project quirks, or user preferences you learned during this session. If there are new insights, you MUST use the `write_file` or `replace_file_content` tool to update MEMORY.md or USER.md before asking the user for their next task."
            self.user_input += reflection_prompt
            
        self.messages.append({"role": "user", "content": self.user_input})
        
        try:
            while True:
                if self.is_killed:
                    self.logger.info("Agent thread was killed by user.")
                    self.append_message_signal.emit("SYSTEM", "🛑 Operation stopped by user.")
                    break
                    
                self.append_message_signal.emit("SYSTEM", "Thinking...")
                
                # Inject dynamic QGIS context into the messages before sending
                # Inject dynamic QGIS context into the messages before sending
                # DYNAMIC SLIDING WINDOW: Keep System Prompt + Recent messages up to ~40000 chars to prevent context overflow
                messages_to_send = []
                system_msgs = [m for m in self.messages if m.get("role") == "system"]
                other_msgs = [m for m in self.messages if m.get("role") != "system"]
                
                messages_to_send.extend(system_msgs)
                
                # Dynamic accumulation from the end
                char_limit = 40000
                current_chars = 0
                dynamic_other_msgs = []
                
                for m in reversed(other_msgs):
                    m_len = len(str(m.get("content", "")))
                    if current_chars + m_len > char_limit and len(dynamic_other_msgs) > 0:
                        break
                    dynamic_other_msgs.insert(0, m)
                    current_chars += m_len
                    
                # Fix API Error 400: Truncation might leave orphaned "tool" messages at the beginning 
                # without their preceding "assistant" tool_calls message.
                while dynamic_other_msgs and dynamic_other_msgs[0].get("role") == "tool":
                    dynamic_other_msgs.pop(0)
                    
                messages_to_send.extend(dynamic_other_msgs)
                
                dynamic_context = self._get_qgis_context()
                if getattr(self, "ghost_context", None):
                    dynamic_context += "\n\n[System Auto-Injected Context based on @ Mentions]:\n" + self.ghost_context
                
                # Inject Auto-RAG
                auto_rag = self._get_auto_rag_context(self.user_input)
                if auto_rag:
                    dynamic_context += "\n\n" + auto_rag
                    
                messages_to_send.append({"role": "system", "content": dynamic_context})
                
                real_model_name = self.model_name.split(" ")[0]
                
                kwargs = {
                    "model": real_model_name,
                    "messages": messages_to_send,
                }
                import json
                recent_tool_context = self.user_input
                try:
                    recent_tool_context += "\n" + "\n".join(
                        str(m.get("content", ""))[:1200] for m in messages_to_send[-6:]
                    )
                except Exception:
                    pass
                active_tools = self._select_tools_for_request(recent_tool_context)
                
                # Apply thinking and reasoning_effort for DeepSeek models
                if "deepseek" in real_model_name:
                    if "Disabled" in self.effort_level:
                        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                    elif "Max" in self.effort_level:
                        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                        kwargs["reasoning_effort"] = "max"
                    else: # High (default)
                        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                        kwargs["reasoning_effort"] = "high"
                
                # In DeepSeek V4 API, both Flash and Pro support native tool calling!
                # Keep the fallback ONLY for the deprecated "deepseek-reasoner" alias if someone forces it.
                if real_model_name != "deepseek-reasoner":
                    kwargs["tools"] = active_tools
                    kwargs["tool_choice"] = "auto"
                else:
                    tools_desc = json.dumps([t['function'] for t in active_tools], indent=2, ensure_ascii=False)
                    reasoner_sys = (
                        "You are currently DeepSeek-Reasoner. The native Tool calling API is disabled. "
                        "However, you MUST use the following tools manually to interact with the QGIS environment:\n\n"
                        f"{tools_desc}\n\n"
                        "To call a tool (like `download_osm_data` or `create_geodatabase`), you MUST output a JSON block like this:\n"
                        "```json\n{\n  \"tool_name\": \"name_of_tool\",\n  \"arguments\": {\n    \"arg1\": \"value1\"\n  }\n}\n```\n"
                        "For writing arbitrary Python scripts, you can simply output a ```python ... ``` block, which will automatically trigger the `execute_pyqgis_script` tool."
                    )
                    messages_to_send.append({"role": "system", "content": reasoner_sys})
                    
                try:
                    response = self.client.chat.completions.create(timeout=120, **kwargs)
                except Exception as e:
                    message = f"LLM request failed: {str(e)}"
                    self.logger.error(message, exc_info=True)
                    self.append_message_signal.emit(
                        "SYSTEM",
                        message + "\nThe agent stopped this turn without executing additional tools.",
                    )
                    self._write_artifact_result(message, ok=False)
                    break
                self._record_llm_usage(response, real_model_name, messages_to_send)
                
                msg = response.choices[0].message
                msg_dict = msg.model_dump(exclude_none=True)
                
                # Check for reasoning_content (R1)
                reasoning_content = getattr(msg, "reasoning_content", None)
                if reasoning_content:
                    formatted_reasoning = f'<div style="color: #666; background-color: #f8f9fa; padding: 10px; border-left: 3px solid #007bff; margin: 5px 0; font-size: 12px;"><b>🧠 思考过程:</b><br/><pre style="white-space: pre-wrap; margin: 0; font-family: monospace;">{reasoning_content}</pre></div>'
                    self.append_message_signal.emit("SYSTEM", formatted_reasoning)
                    msg_dict["reasoning_content"] = reasoning_content
                
                # Manual tool parsing for reasoner
                if self.model_name == "deepseek-reasoner" and msg.content:
                    import re, uuid
                    
                    mock_tool_calls = []
                    
                    # 1. Parse JSON tool calls
                    json_blocks = re.findall(r'```json\n(.*?)\n```', msg.content, re.DOTALL)
                    for j_block in json_blocks:
                        try:
                            parsed_j = json.loads(j_block)
                            if "tool_name" in parsed_j and "arguments" in parsed_j:
                                mock_tool_calls.append({
                                    "id": f"call_{uuid.uuid4().hex[:10]}",
                                    "type": "function",
                                    "function": {
                                        "name": parsed_j["tool_name"],
                                        "arguments": json.dumps(parsed_j["arguments"])
                                    }
                                })
                        except Exception as e:
                            self.logger.warning(f"Failed to parse JSON tool block: {e}")
                            
                    # 2. Parse Python blocks only when execution is allowed.
                    # In PLAN mode before approval, code blocks are usually explanatory plan text.
                    if not (self.work_mode == "PLAN" and not self.plan_approved):
                        py_blocks = re.findall(r'```python\n(.*?)\n```', msg.content, re.DOTALL)
                        for code in py_blocks:
                            mock_tool_calls.append({
                                "id": f"call_{uuid.uuid4().hex[:10]}",
                                "type": "function",
                                "function": {
                                    "name": "execute_pyqgis_script",
                                    "arguments": json.dumps({"code": code, "is_destructive": False})
                                }
                            })
                        
                    if mock_tool_calls:
                        msg_dict["tool_calls"] = mock_tool_calls
                        self.logger.info(f"Auto-parsed {len(mock_tool_calls)} tool_calls for deepseek-reasoner.")
                
                self.messages.append(msg_dict)
                
                if msg.content:
                    self.logger.info(f"Agent text response: {msg.content}")
                    self.append_message_signal.emit("AGENT", msg.content)
                
                # Use msg_dict for tool_calls check
                # Re-wrap msg_dict to an object-like wrapper for the rest of the loop
                class MsgWrapper:
                    def __init__(self, d):
                        self.content = d.get("content")
                        self.tool_calls = d.get("tool_calls")
                        
                msg_wrapped = MsgWrapper(msg_dict)
                
                if not getattr(msg_wrapped, "tool_calls", None):
                    # Fallback: if the model forgot to use the tool API but output a python block anyway
                    import re, uuid
                    py_blocks = []
                    if not (self.work_mode == "PLAN" and not self.plan_approved):
                        py_blocks = re.findall(r'```python\n(.*?)\n```', msg.content or "", re.DOTALL)
                    if py_blocks:
                        code = py_blocks[0]
                        mock_tc = {
                            "id": f"call_{uuid.uuid4().hex[:10]}",
                            "type": "function",
                            "function": {
                                "name": "execute_pyqgis_script",
                                "arguments": json.dumps({"code": code, "is_destructive": False})
                            }
                        }
                        msg_dict["tool_calls"] = [mock_tc]
                        msg_wrapped.tool_calls = [mock_tc]
                        self.logger.info("Auto-parsed python block into tool_calls for model that forgot tool API.")

                    else:
                        self.logger.info("Agent stopped without tool calls. Yielding turn to user.")
                        self._write_artifact_result(msg.content or "", ok=True)
                        break
                
                # We do not use else because if the fallback triggered, we want to execute the tool
                self._consecutive_no_tool = 0
                self._begin_planner_response()
                    
                for tc_dict in msg_wrapped.tool_calls:
                    # Create a mock tool_call object for the inner loop
                    class ToolCallWrapper:
                        def __init__(self, t):
                            self.id = t["id"]
                            self.function = lambda: None
                            self.function.name = t["function"]["name"]
                            self.function.arguments = t["function"]["arguments"]
                    tool_call = ToolCallWrapper(tc_dict)
                    name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        self.logger.error(f"JSON decode error for tool {name}: {e}")
                        self._append_tool_result(
                            tool_call,
                            name,
                            {},
                            f"JSON decode error in arguments: {e}. Please ensure you output valid JSON.",
                        )
                        continue
                    if not self._validate_tool_call(tool_call, name, args):
                        continue
                    if not self._before_step_tool_call(tool_call, name, args):
                        continue
                    
                    if name == "ask_human":
                        question = args.get("question", "")
                        self.logger.info(f"Agent asking human: {question}")
                        self.human_input_event.clear()
                        self.request_human_input_signal.emit(question)
                        # Block thread until GUI signals back
                        if not self._wait_for_event(self.human_input_event, 1800, "human input"):
                            from .tool_result import ToolResult
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                ToolResult.failure(
                                    "Timed out waiting for human input.",
                                    error_type="timeout_error",
                                    data={"tool": name},
                                    suggestions=["Ask a shorter question or retry when the user is available."],
                                ).to_json(),
                            )
                            continue
                        
                        answer = self.human_input_response
                        self.logger.info(f"Human answered: {answer}")
                        self._append_tool_result(tool_call, name, args, answer)
                        
                    elif name == "ask_vision_critic":
                        question = args.get("question", "")
                        self.logger.info(f"Asking vision critic: {question}")
                        self.canvas_image_event.clear()
                        self.request_canvas_image_signal.emit()
                        if not self._wait_for_event(self.canvas_image_event, 60, "canvas capture"):
                            from .tool_result import ToolResult
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                ToolResult.failure(
                                    "Timed out while capturing the QGIS canvas.",
                                    error_type="timeout_error",
                                    data={"tool": name},
                                    suggestions=["Retry after the QGIS UI is responsive."],
                                ).to_json(),
                            )
                            continue
                        
                        img_path = self.canvas_image_path
                        result = ""
                        if not img_path or not os.path.exists(img_path):
                            result = "Error: Could not capture map canvas."
                        else:
                            import base64
                            import requests
                            try:
                                with open(img_path, "rb") as f:
                                    base64_image = base64.b64encode(f.read()).decode('utf-8')
                                
                                from qgis.core import QgsSettings
                                glm_key = QgsSettings().value("qgis_agent/glm_api_key", "")
                                glm_base_url = QgsSettings().value("qgis_agent/glm_base_url", "https://open.bigmodel.cn/api/paas/v4")
                                headers = {
                                    "Content-Type": "application/json",
                                    "Authorization": f"Bearer {glm_key}"
                                }
                                glm_vision_model = self._get_glm_vision_model()
                                payload = {
                                    "model": glm_vision_model,
                                    "messages": [{
                                        "role": "user",
                                        "content": [
                                            {"type": "text", "text": question},
                                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                                        ]
                                    }]
                                }
                                self.append_message_signal.emit("SYSTEM", "👀 正在呼叫 GLM-4V 视觉排版顾问...")
                                import time; time.sleep(0.1)
                                resp = requests.post(f"{glm_base_url}/chat/completions", headers=headers, json=payload, timeout=30)
                                if resp.status_code == 200:
                                    result = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
                                    self.append_message_signal.emit("SYSTEM", f"GLM 顾问反馈: {result}")
                                else:
                                    result = f"Vision API Error: {resp.status_code} - {resp.text}"
                            except Exception as e:
                                result = f"Vision API Exception: {str(e)}"
                        
                        self._append_tool_result(tool_call, name, args, result)

                    elif name in self.atomic_tool_names:
                        self.logger.info(f"Executing atomic tool: {name}")
                        approved, approval_decision = self._request_tool_approval(name, args)
                        if not approved:
                            from .tool_result import ToolResult
                            result = ToolResult.failure(
                                "User denied the high-risk tool call.",
                                error_type="permission_error",
                                data={"approval": approval_decision.to_dict()},
                            ).to_json()
                            self._append_tool_result(tool_call, name, args, result)
                            continue
                        self.atomic_tool_event.clear()
                        self.request_atomic_tool_signal.emit(name, args)
                        if not self._wait_for_event(self.atomic_tool_event, 600, f"atomic tool {name}"):
                            from .tool_result import ToolResult
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                ToolResult.failure(
                                    f"Timed out waiting for atomic tool: {name}.",
                                    error_type="timeout_error",
                                    data={"tool": name},
                                    suggestions=["Retry with a smaller tool call or check whether QGIS is busy."],
                                ).to_json(),
                            )
                            continue
                        result = self.atomic_tool_response
                        
                        if result.startswith("[IMAGE_PATH]"):
                            img_path = result.replace("[IMAGE_PATH]", "")
                            import base64, requests
                            try:
                                with open(img_path, "rb") as f:
                                    base64_image = base64.b64encode(f.read()).decode('utf-8')
                                from qgis.core import QgsSettings
                                glm_key = QgsSettings().value("qgis_agent/glm_api_key", "")
                                glm_base_url = QgsSettings().value("qgis_agent/glm_base_url", "https://open.bigmodel.cn/api/paas/v4")
                                headers = {
                                    "Content-Type": "application/json",
                                    "Authorization": f"Bearer {glm_key}"
                                }
                                glm_vision_model = self._get_glm_vision_model()
                                payload = {
                                    "model": glm_vision_model,
                                    "messages": [{
                                        "role": "user",
                                        "content": [
                                            {"type": "text", "text": "Please analyze this QGIS screenshot in detail. Describe the layers, the canvas, and any open panels/dialogs."},
                                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                                        ]
                                    }]
                                }
                                self.append_message_signal.emit("SYSTEM", "✨ 正在将附带的截图发给视觉大模型进行预处理...")
                                import time; time.sleep(0.1)
                                resp = requests.post(f"{glm_base_url}/chat/completions", headers=headers, json=payload, timeout=30)
                                if resp.status_code == 200:
                                    result = "Screenshot analysis from Vision Model:\n" + resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
                                else:
                                    result = f"Vision API Error: {resp.status_code} - {resp.text}"
                            except Exception as e:
                                result = f"Vision API Exception: {str(e)}"
                                
                        self._append_tool_result(tool_call, name, args, result)
                        
                    elif name == "read_file":
                        file_path = args.get("file_path", "")
                            
                        self.logger.info(f"Agent reading file: {file_path}")
                        try:
                            file_path = self._resolve_agent_file_path(file_path, for_write=False)
                            result = self._read_file_for_agent(file_path, args)
                        except Exception as e:
                            result = f"Error reading file: {str(e)}"
                        
                        self._append_tool_result(tool_call, name, args, result)
                        
                    elif name == "write_file":
                        file_path = args.get("file_path", "")
                        content = args.get("content", "")
                            
                        self.logger.info(f"Agent writing file: {file_path}")
                        try:
                            file_path = self._resolve_agent_file_path(file_path, for_write=True)
                            approved, approval_decision = self._request_tool_approval(
                                name,
                                {"file_path": file_path, "content": content},
                                {
                                    "resolved_file_path": file_path,
                                    "file_exists": os.path.exists(file_path),
                                    "managed_file": self._is_agent_managed_file(file_path),
                                    "preview": content,
                                },
                            )
                            if not approved:
                                result = f"Error: User denied overwriting {file_path}"
                            else:
                                parent_dir = os.path.dirname(file_path)
                                if parent_dir:
                                    os.makedirs(parent_dir, exist_ok=True)
                                with open(file_path, "w", encoding="utf-8") as f:
                                    f.write(content)
                                result = f"Successfully wrote to {file_path}"
                                if file_path.endswith(".md"):
                                    self.append_message_signal.emit("AGENT", f"📝 **[Artifact Created: {os.path.basename(file_path)}]**\n\n{content}")
                        except Exception as e:
                            result = f"Error writing file: {str(e)}"
                            
                        self._append_tool_result(tool_call, name, args, result)
                        
                    elif name == "replace_file_content":
                        file_path = args.get("file_path", "")
                            
                        target_content = args.get("target_content", "")
                        replacement_content = args.get("replacement_content", "")
                        self.logger.info(f"Agent replacing content in: {file_path}")
                        try:
                            file_path = self._resolve_agent_file_path(file_path, for_write=True)
                            if not os.path.exists(file_path):
                                result = f"Error: File not found at {file_path}"
                            else:
                                with open(file_path, "r", encoding="utf-8") as f:
                                    file_data = f.read()
                                
                                if target_content not in file_data:
                                    result = "Error: target_content not found in file."
                                else:
                                    preview = f"- {target_content.strip()}\n+ {replacement_content.strip()}"
                                    approved, approval_decision = self._request_tool_approval(
                                        name,
                                        {
                                            "file_path": file_path,
                                            "target_content": target_content,
                                            "replacement_content": replacement_content,
                                        },
                                        {
                                            "resolved_file_path": file_path,
                                            "file_exists": os.path.exists(file_path),
                                            "managed_file": self._is_agent_managed_file(file_path),
                                            "preview": preview,
                                        },
                                    )
                                    if not approved:
                                        result = f"Error: User denied modifying {file_path}"
                                    else:
                                        file_data = file_data.replace(target_content, replacement_content)
                                        with open(file_path, "w", encoding="utf-8") as f:
                                            f.write(file_data)
                                        result = f"Successfully replaced content in {file_path}"
                                        if file_path.endswith(".md"):
                                            self.append_message_signal.emit("AGENT", f"📝 **[Artifact Updated: {os.path.basename(file_path)}]**\n\n```diff\n- {target_content.strip()}\n+ {replacement_content.strip()}\n```")
                        except Exception as e:
                            result = f"Error replacing content: {str(e)}"
                            
                        self._append_tool_result(tool_call, name, args, result)

                    elif name == "save_skill":
                        skill_name = args.get("skill_name", "")
                        description = args.get("description", "")
                        python_code = args.get("python_code", "")
                        self.logger.info(f"Agent saving skill: {skill_name}")
                        try:
                            from .validators import validate_safe_name
                            name_report = validate_safe_name(skill_name, "skill_name")
                            if not name_report.ok:
                                from .tool_result import ToolResult
                                result = ToolResult.failure(
                                    "Invalid skill_name.",
                                    error_type="argument_error",
                                    data={"validation": name_report.to_dict()},
                                    suggestions=["Use only letters, numbers, underscore, and hyphen in skill_name."],
                                ).to_json()
                                self._append_tool_result(tool_call, name, args, result)
                                continue
                            from qgis.core import QgsProject
                            import json
                            prj_home = QgsProject.instance().homePath()
                            if not prj_home:
                                result = "Error: QGIS Project is not saved. Cannot save skills without a project directory."
                            else:
                                skills_dir = os.path.join(prj_home, "agent_skills")
                                os.makedirs(skills_dir, exist_ok=True)
                                
                                skill_file = os.path.join(skills_dir, f"{skill_name}.py")
                                with open(skill_file, "w", encoding="utf-8") as f:
                                    f.write(python_code)
                                    
                                index_file = os.path.join(skills_dir, "skills_index.json")
                                index_data = {}
                                if os.path.exists(index_file):
                                    with open(index_file, "r", encoding="utf-8") as f:
                                        index_data = json.load(f)
                                        
                                index_data[skill_name] = {"description": description, "file": f"{skill_name}.py"}
                                with open(index_file, "w", encoding="utf-8") as f:
                                    json.dump(index_data, f, ensure_ascii=False, indent=2)
                                    
                                result = f"Successfully saved skill '{skill_name}' to {skills_dir}"
                        except Exception as e:
                            result = f"Error saving skill: {str(e)}"
                            
                        self._append_tool_result(tool_call, name, args, result)
                        
                    elif name == "search_skills":
                        query = args.get("query", "").lower()
                        self.logger.info(f"Agent searching skills for: {query}")
                        try:
                            from qgis.core import QgsProject
                            import json
                            prj_home = QgsProject.instance().homePath()
                            if not prj_home:
                                result = "Error: QGIS Project is not saved."
                            else:
                                index_file = os.path.join(prj_home, "agent_skills", "skills_index.json")
                                if not os.path.exists(index_file):
                                    result = "No skills library found in this project."
                                else:
                                    with open(index_file, "r", encoding="utf-8") as f:
                                        index_data = json.load(f)
                                        
                                    matches = []
                                    for s_name, s_info in index_data.items():
                                        if query in s_name.lower() or query in s_info.get("description", "").lower():
                                            code_path = os.path.join(prj_home, "agent_skills", s_info["file"])
                                            if os.path.exists(code_path):
                                                with open(code_path, "r", encoding="utf-8") as cf:
                                                    code = cf.read()
                                                matches.append(f"--- Skill: {s_name} ---\nDescription: {s_info['description']}\nCode:\n```python\n{code}\n```")
                                                
                                    if matches:
                                        result = "Found the following skills:\n\n" + "\n\n".join(matches)
                                    else:
                                        result = f"No skills found matching '{query}'."
                        except Exception as e:
                            result = f"Error searching skills: {str(e)}"
                            
                        self._append_tool_result(tool_call, name, args, result)
                        
                    elif name == "search_past_conversations":
                        query = args.get("query", "")
                        self.logger.info(f"Agent searching episodic memory for: {query}")
                        try:
                            from .sqlite_memory import SqliteMemoryDB
                            db = SqliteMemoryDB()
                            result = db.search_conversations(query)
                        except Exception as e:
                            result = f"Error searching memory: {str(e)}"
                            
                        self._append_tool_result(tool_call, name, args, result)

                    elif name == "submit_plan_for_approval":
                        plan_markdown = args.get("plan_markdown", "")
                        if not plan_markdown:
                            self.logger.warning("Agent attempted to submit plan without providing plan_markdown")
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                "Error: You MUST provide your full markdown checklist in the 'plan_markdown' argument.",
                            )
                            continue
                            
                        from qgis.core import QgsProject
                        home = QgsProject.instance().homePath()
                        if home:
                            task_path = os.path.join(home, "task.md")
                            try:
                                with open(task_path, "w", encoding="utf-8") as f:
                                    f.write(plan_markdown)
                                self.logger.info(f"Automatically wrote plan_markdown to {task_path}")
                                self.append_message_signal.emit("SYSTEM", "📝 **[Artifact Created: task.md]**\n\n(系统已根据您的计划自动生成任务文件)")
                            except Exception as e:
                                self.logger.error(f"Failed to write task.md: {e}")
                            try:
                                artifacts = self._ensure_run_artifacts()
                                if artifacts:
                                    artifacts.write_plan(plan_markdown)
                            except Exception as e:
                                self.logger.warning(f"Failed to write plan artifact: {e}")
                            
                        self.logger.info("Agent requesting plan approval.")
                        self.plan_approval_event.clear()
                        self.request_plan_approval_signal.emit()
                        # Block thread
                        if not self._wait_for_event(self.plan_approval_event, 1800, "plan approval"):
                            from .tool_result import ToolResult
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                ToolResult.failure(
                                    "Timed out waiting for plan approval.",
                                    error_type="timeout_error",
                                    data={"tool": name},
                                    suggestions=["Submit the plan again when the user is ready to approve it."],
                                ).to_json(),
                            )
                            continue
                        if self.is_killed: break
                        
                        action = self.plan_approval_response
                        self.logger.info(f"User plan action: {action}")
                        
                        if action == "REJECT":
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                "Plan rejected by user. Please revise the plan or ask for clarification.",
                            )
                            continue
                        elif action.startswith("REVISE:"):
                            feedback = action.replace("REVISE:", "").strip()
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                f"User provided modification feedback for your plan: '{feedback}'. Please update your plan immediately incorporating this feedback, while STRICTLY RETAINING the original overarching goal.",
                            )
                            continue
                        else:
                            self.plan_approved = True
                            self._register_planner_plan(plan_markdown)
                            self._append_tool_result(tool_call, name, args, "Plan approved. Proceed to execute.")
                            
                    elif name == "execute_pyqgis_script":
                        if self.work_mode == "PLAN" and not self.plan_approved:
                            error_msg = "Error: You are in PLAN mode. You MUST call submit_plan_for_approval and wait for human approval BEFORE executing any code."
                            self.logger.warning("Agent violated PLAN mode constraints.")
                            self._append_tool_result(tool_call, name, args, error_msg)
                            continue
                            
                        code = args.get("code", "")
                        is_destructive = args.get("is_destructive", False)
                        
                        self.logger.debug(f"Agent attempting to execute code (Destructive: {is_destructive}):\n{code}")
                        
                        approved, approval_decision = self._request_tool_approval(
                            name,
                            {"code": code, "is_destructive": is_destructive},
                            {"code": code},
                        )
                        if not approved:
                            self.logger.warning("User denied high-risk operation.")
                            from .tool_result import ToolResult
                            denied_result = ToolResult.failure(
                                "User denied the high-risk operation.",
                                error_type="permission_error",
                                data={"approval": approval_decision.to_dict()},
                            ).to_json()
                            self._append_tool_result(
                                tool_call,
                                name,
                                {"code": code, "is_destructive": is_destructive},
                                denied_result,
                            )
                            continue
                                
                        self.append_message_signal.emit("SYSTEM", f"Agent generated and is executing the following code:\n<pre>{code}</pre>")
                        
                        # Request execution on the main thread to ensure GUI safety
                        self.code_exec_event.clear()
                        self.request_code_execution_signal.emit(code)
                        if not self._wait_for_event(self.code_exec_event, 1800, "PyQGIS code execution"):
                            from .tool_result import ToolResult
                            self._append_tool_result(
                                tool_call,
                                name,
                                {"code": code, "is_destructive": is_destructive},
                                ToolResult.failure(
                                    "Timed out waiting for PyQGIS code execution.",
                                    error_type="timeout_error",
                                    data={"tool": name},
                                    suggestions=["Retry with a smaller script or a registered atomic tool."],
                                ).to_json(),
                            )
                            continue
                        if self.is_killed: break
                        
                        output = self.code_exec_response
                        self.logger.info(f"Execution Result:\n{output}")
                        self.append_message_signal.emit("SYSTEM", f"Execution Result:\n{output}")
                        
                        # Phase 17: Self-Healing
                        break_outer_loop = False
                        if "[EXECUTION_FAILED_TRACEBACK]" in output:
                            self._error_retries = getattr(self, "_error_retries", 0) + 1
                            if self._error_retries >= 4:
                                meltdown_msg = "🛑 **Agent 遇到死胡同已暂停**\n我已经连续 3 次局部修复以及 1 次全局反思均告失败。为了保护运行环境，我已主动熔断。\n你可以这样帮我：\n1. 如果你有相关的 QGIS 3.44 文档代码或 API 变化信息，请直接发给我。\n2. 授权我使用搜索工具（如 search_web）去网上查一下这个报错。\n3. 或者回复 **“继续尝试”**，我将彻底放弃当前思路，换一种全新的逻辑或算法。"
                                self.append_message_signal.emit("SYSTEM", meltdown_msg)
                                self._append_tool_result(
                                    tool_call,
                                    name,
                                    {"code": code, "is_destructive": is_destructive},
                                    output + "\n\n[SYSTEM] Max error retries reached. Agent execution halted. Waiting for human intervention.",
                                )
                                self._error_retries = 0
                                break_outer_loop = True
                                break
                            elif self._error_retries == 3:
                                task_content = ""
                                try:
                                    from qgis.core import QgsProject
                                    proj_path = QgsProject.instance().fileName()
                                    proj_dir = os.path.dirname(proj_path) if proj_path else os.path.expanduser("~")
                                    task_file = os.path.join(proj_dir, "task.md")
                                    if os.path.exists(task_file):
                                        with open(task_file, "r", encoding="utf-8") as f:
                                            task_content = f.read()
                                except Exception:
                                    pass
                                critic_analysis = self._run_critic_agent(output, code, task_content)
                                output = f"[SYSTEM CRITIC]: 局部修复已连续失效！启动全局反思：\n\n{critic_analysis}\n\n[SYSTEM DIRECTIVE] 请仔细阅读以上 Critic 的建议！如果错误是由上一步的脏数据引起的，请使用 `replace_file_content` 修改 `task.md` 倒退进度，并重新执行之前的步骤。"
                            else:
                                debugger_analysis = self._run_debugger_agent(output, code)
                                output = f"[SYSTEM Debugger Analysis]:\n{debugger_analysis}\n\n[SYSTEM] Execution failed. You have {3 - self._error_retries} local retries left before Critic intervention. Please apply the Debugger's suggested fix."
                        else:
                            self._error_retries = 0
                        
                        self._append_tool_result(
                            tool_call,
                            name,
                            {"code": code, "is_destructive": is_destructive},
                            output,
                        )
                    else:
                        # Fallback to atomic tools
                        from ..tools.tools import execute_atomic_tool_structured
                        self.logger.debug(f"Delegating tool execution to atomic tools: {name}")
                        try:
                            approved, approval_decision = self._request_tool_approval(name, args)
                            if not approved:
                                from .tool_result import ToolResult
                                output = ToolResult.failure(
                                    "User denied the high-risk tool call.",
                                    error_type="permission_error",
                                    data={"approval": approval_decision.to_dict()},
                                ).to_json()
                                self._append_tool_result(tool_call, name, args, output)
                                continue
                            from qgis.utils import iface
                            output = execute_atomic_tool_structured(iface, name, args)
                        except Exception as e:
                            output = f"Error executing {name}: {str(e)}"
                        self._append_tool_result(tool_call, name, args, output)
                        
                if locals().get("break_outer_loop", False):
                    break
                        
        except Exception as e:
            self.logger.error(f"Exception during Agent execution: {str(e)}", exc_info=True)
            self.append_message_signal.emit("SYSTEM", f"Exception during Agent execution: {str(e)}")
            
        self.finished_signal.emit()

    # Callbacks from main thread
    def provide_human_input(self, answer):
        self.human_input_response = answer
        self.human_input_event.set()
        
    def provide_destructive_auth(self, is_approved):
        self.destructive_auth_response = is_approved
        self.destructive_auth_event.set()

    def _run_debugger_agent(self, traceback_str, code_str):
        self.append_message_signal.emit("SYSTEM", "🔍 正在调用后台 Debugger Agent 分析报错原因...")
        prompt = f"""You are an expert QGIS Python Debugger. 
The main agent wrote the following script which failed with an error.
Your task is to analyze the traceback and provide a very concise explanation of what went wrong, and the corrected code.

[Faulty Code]:
{code_str}

[Traceback]:
{traceback_str}

Respond in the following format:
**Error Analysis**: (brief explanation)
**Suggested Fix**: (how to fix it)
**Corrected Code**: 
```python
(the full corrected code)
```
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "system", "content": prompt}],
                temperature=0.2,
                timeout=90,
            )
            self._record_llm_usage(response, self.model_name, [{"role": "system", "content": prompt}])
            return response.choices[0].message.content
        except Exception as e:
            return f"Debugger Agent failed to run: {str(e)}\nRaw Traceback:\n{traceback_str}"

    def _run_critic_agent(self, traceback_str, code_str, task_content):
        self.append_message_signal.emit("SYSTEM", "🧠 局部修复失效，正在调用 Critic Agent 进行全局反思...")
        prompt = f"""You are a Senior GIS Architect and Critic.
The main agent has been stuck in an error loop attempting to execute a PyQGIS script. 
The local debugger failed to fix it 2 times. Your job is to look at the bigger picture.

[Task Progress (task.md)]:
{task_content}

[Current Failing Code]:
{code_str}

[Traceback]:
{traceback_str}

Analyze the situation. Is the error caused by a fundamental flaw in the input data (e.g., wrong geometry type like MultiPoint instead of Point, wrong CRS, missing fields) that was generated by a PREVIOUS step? 
If so, instruct the main agent to STOP fixing the current code, and instead ROLLBACK to the previous step to regenerate the data correctly (e.g., by adding native:centroids or reprojecting).

Respond concisely with:
**Root Cause Analysis**: (Why is this failing repeatedly?)
**Rollback & Fix Strategy**: (What exact steps/tools should the agent use to regenerate the previous data correctly?)
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "system", "content": prompt}],
                temperature=0.3,
                timeout=90,
            )
            self._record_llm_usage(response, self.model_name, [{"role": "system", "content": prompt}])
            return response.choices[0].message.content
        except Exception as e:
            return f"Critic Agent failed to run: {str(e)}\nRaw Traceback:\n{traceback_str}"
