import os
import threading
import time
from qgis.PyQt.QtCore import QThread, pyqtSignal

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

MAX_TOOL_ROUNDS = 45
MAX_CONSECUTIVE_FAILURES = 4
MAX_TOOL_PACK_EXPANSIONS = 2

from .harness_progress import HarnessProgressMixin
from .harness_memory_and_artifacts import HarnessMemoryArtifactsMixin


from .harness_execution_helpers import HarnessExecutionHelpersMixin


class HarnessThread(HarnessProgressMixin, HarnessMemoryArtifactsMixin, HarnessExecutionHelpersMixin, QThread):
    append_message_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal()
    metrics_signal = pyqtSignal(dict)
    operation_progress_signal = pyqtSignal(dict)
    
    request_human_input_signal = pyqtSignal(str)
    request_destructive_auth_signal = pyqtSignal(str)
    request_plan_approval_signal = pyqtSignal()
    
    request_code_execution_signal = pyqtSignal(str)
    request_canvas_image_signal = pyqtSignal()
    request_atomic_tool_signal = pyqtSignal(str, dict)
    
    def __init__(self, plugin_dir, existing_messages=None, parent=None):
        if parent is not None:
            super().__init__(parent)
        else:
            super().__init__()
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
        self.waiting_for_plan_approval = False
        
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
        self.checkpoint_manager = None
        self._tool_success_count = 0
        self._tool_failure_count = 0
        self._project_mutation_count = 0
        self._last_tool_ok = None
        self._last_failure_type = ""
        self._run_status_override = ""
        self._run_status_reason = ""
        self._result_written = False
        self._last_summary = ""
        self._current_response_results = []
        self._external_write_grants = []
        self._frozen_task_domains = set()
        self._pending_tool_domains = set()
        self._tool_pack_expansion_count = 0
        self.recovery_context = None
        self._agent_message_emitted = False
        self._consecutive_tool_failures = 0
        from .step_runner import StepExecutionController
        self.step_controller = StepExecutionController()
        
        self.client = None
        from .request_profile import canonicalize_tool_schemas
        from .tool_registry import build_all_tool_openai_schemas, get_atomic_tool_names
        self.tools = canonicalize_tool_schemas(build_all_tool_openai_schemas())
        self.tools_by_name = {tool.get("function", {}).get("name"): tool for tool in self.tools}
        self.atomic_tool_names = set(get_atomic_tool_names())
        self.atomic_tool_names.add("take_qgis_window_snapshot")


    def _emit_agent_message(self, content: str):
        if not content:
            return
        self._agent_message_emitted = True
        self._last_summary = content
        self.append_message_signal.emit("AGENT", content)



    def _select_tools_for_request(self, text: str):
        """Build a deterministic task-level tool pack; callers freeze the result."""
        from .request_profile import frozen_tool_names
        from .user_tool_extensions import get_registered_user_tool_domains

        names = frozen_tool_names(
            text,
            self.tools_by_name.keys(),
            work_mode=self.work_mode,
            user_tool_domains=get_registered_user_tool_domains(),
        )
        return [self.tools_by_name[name] for name in names]

    def _queue_domain_tool_expansion(self, domains, source: str = ""):
        from .request_profile import DOMAIN_TOOL_PACKS

        valid = {
            str(domain)
            for domain in (domains or [])
            if str(domain) in DOMAIN_TOOL_PACKS
        }
        new_domains = valid - set(self._frozen_task_domains) - set(self._pending_tool_domains)
        if new_domains:
            self._pending_tool_domains.update(new_domains)
            self.logger.info(
                "Scheduled additive tool-pack expansion: domains=%s source=%s",
                sorted(new_domains),
                source or "runtime",
            )
        return sorted(new_domains)

    def _apply_pending_tool_pack_expansion(self, active_tools):
        if not self._pending_tool_domains:
            return active_tools, []
        requested_domains = sorted(self._pending_tool_domains)
        self._pending_tool_domains.clear()
        if self._tool_pack_expansion_count >= MAX_TOOL_PACK_EXPANSIONS:
            self.logger.warning(
                "Ignored tool-pack expansion after reaching the per-task limit: %s",
                requested_domains,
            )
            return active_tools, []

        from .request_profile import expand_tool_names
        from .user_tool_extensions import get_registered_user_tool_domains

        current_names = {
            tool.get("function", {}).get("name", "")
            for tool in (active_tools or [])
        }
        merged_domains = set(self._frozen_task_domains).union(requested_domains)
        expanded_names = expand_tool_names(
            current_names,
            merged_domains,
            self.tools_by_name.keys(),
            work_mode=self.work_mode,
            user_tool_domains=get_registered_user_tool_domains(),
        )
        added_names = sorted(set(expanded_names) - current_names)
        self._frozen_task_domains = merged_domains
        if not added_names:
            self.logger.info(
                "Tool-pack expansion added no schemas: domains=%s",
                requested_domains,
            )
            return active_tools, []

        self._tool_pack_expansion_count += 1
        expanded_tools = [self.tools_by_name[name] for name in expanded_names]
        self.logger.info(
            "Expanded request profile additively: expansion=%s/%s domains=%s added_tools=%s total_tools=%s",
            self._tool_pack_expansion_count,
            MAX_TOOL_PACK_EXPANSIONS,
            requested_domains,
            added_names,
            len(expanded_tools),
        )
        try:
            artifacts = self._ensure_run_artifacts()
            if artifacts:
                artifacts.append_event("tool_pack_expanded", {
                    "expansion_index": self._tool_pack_expansion_count,
                    "domains": requested_domains,
                    "added_tools": added_names,
                    "total_tools": len(expanded_tools),
                })
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            self.logger.warning(f"Failed to record tool-pack expansion artifact: {exc}", exc_info=True)
        return expanded_tools, added_names

    def _create_chat_completion_with_retry(self, kwargs):
        """Retry only transport failures that occurred before a provider response existed."""
        retry_markers = (
            "apiconnectionerror",
            "apitimeouterror",
            "connection",
            "timeout",
            "timed out",
            "unexpected_eof",
            "ssl",
            "server disconnected",
            "temporarily unavailable",
            " 502",
            " 503",
            " 504",
        )
        for attempt in range(3):
            try:
                return self.client.chat.completions.create(timeout=120, **kwargs)
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}".lower()
                retryable = any(marker in detail for marker in retry_markers)
                if not retryable or attempt >= 2:
                    raise
                delay_seconds = attempt + 1
                self.logger.warning(
                    "LLM transport request failed before a response; retrying in %ss (%s/2): %s",
                    delay_seconds,
                    attempt + 1,
                    exc,
                )
                self.append_message_signal.emit(
                    "SYSTEM",
                    f"网络连接短暂中断，正在自动重试（{attempt + 1}/2）…",
                )
                time.sleep(delay_seconds)

    def _prepare_messages(self):
        from qgis.core import QgsSettings, QgsProject
        settings = QgsSettings()
        personality = settings.value("qgis_agent/agent_personality", "")
        project_home = self._project_home()

        base_prompt = "You are a QGIS execution agent. Follow the registered tool contracts and verify outputs before reporting success.\n"
        
        if personality:
            base_prompt += f"\n### [USER DEFINED PERSONALITY & RULES] ###\n{personality}\n"
        
        import os
        user_md_path = os.path.join(self.plugin_dir, "USER.md")
        legacy_user_md_path = os.path.join(self.plugin_dir, "ui", "USER.md")
        
        if os.path.exists(user_md_path):
            with open(user_md_path, "r", encoding="utf-8") as f:
                base_prompt += f"-- USER.md (Global User Preferences/Facts, Absolute Path: `{user_md_path}`) --\n{f.read()}\n\n"
        elif os.path.exists(legacy_user_md_path):
            with open(legacy_user_md_path, "r", encoding="utf-8") as f:
                base_prompt += f"-- USER.md (Global User Preferences/Facts, Legacy Path: `{legacy_user_md_path}`) --\n{f.read()}\n\n"
            
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
                for f_name in sorted(os.listdir(d), key=str.lower):
                    if f_name.endswith('.md'):
                        try:
                            with open(os.path.join(d, f_name), 'r', encoding='utf-8') as sf:
                                content = sf.read()
                                import re
                                name_match = re.search(r'<name>(.*?)</name>', content, re.DOTALL)
                                desc_match = re.search(r'<description>(.*?)</description>', content, re.DOTALL)
                                if name_match and desc_match:
                                    skill_manifest += f"- `{name_match.group(1).strip()}`: {desc_match.group(1).strip()}\n"
                        except (OSError, UnicodeDecodeError) as e:
                            self.logger.debug("Failed to read skill manifest %s: %s", f_name, e)
        
        # 2. Load core system prompt
        prompt_path = os.path.join(base_dir, "prompts", "system_prompt.md")
        cheat_sheet = ""
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                cheat_sheet = f.read().replace("{skill_directory}", skill_manifest)
                
        base_prompt += "\n" + cheat_sheet + "\n"
        from .mode_state import normalize_mode, MODE_READ_ONLY, MODE_WORKSPACE_WRITE, MODE_FULL_ACCESS
        norm_mode = normalize_mode(self.work_mode)
        if norm_mode == MODE_READ_ONLY and self.plan_approved:
            base_prompt += """
### READ-ONLY MODE - APPROVED PLAN IN PROGRESS
当前计划已经获得批准。继续执行结构化计划中的当前未完成步骤，不要重新提交计划；每个步骤只在 verifier 通过后完成。
"""
        elif norm_mode == MODE_READ_ONLY:
            base_prompt += """
### READ-ONLY MODE (仅可查看)
严禁未经审批直接修改工程或执行破坏性脚本。请先提交全部为 pending 的步骤，并在 `plan_json` 中写明可验证的 expected_outputs。调用 `submit_plan_for_approval` 后等待批准。
"""
        elif norm_mode == MODE_WORKSPACE_WRITE:
            base_prompt += """
### WORKSPACE-WRITE MODE (工作区内修改 / 项目内权限)
您拥有当前 QGIS 工程工作区内的自主修改权限。可以在当前工程目录内自由创建、编辑图层、执行 PyQGIS 分析与生成输出。修改工作区之外的文件或执行系统级危险命令需单独审批。
"""
        else:
            base_prompt += """
### FULL-ACCESS MODE (完全权限)
拥有完全自主执行权限，可直接调度注册工具完成任务。请自主核验每步产物。
"""

        # Self-heal corrupted memory from huge outputs that crash the LLM API
        for m in self.messages:
            if m.get("role") == "tool" and isinstance(m.get("content"), str):
                m["content"] = self._compact_tool_result(m.get("name", "tool"), {}, m["content"], max_chars=5000)
            if isinstance(m.get("content"), str) and len(m["content"]) > 15000:
                original_len = len(m["content"])
                m["content"] = m["content"][:5000] + f"\n\n...[Output middle truncated! Original length: {original_len} chars. Too long for context.]...\n\n" + m["content"][-5000:]

        # DeepSeek Prompt Cache Optimization:
        # Keep messages[0] as a stable immutable system prefix throughout the session.
        # Overwriting messages[0] in subsequent turns would invalidate the provider's Longest Common Prefix KV cache.
        if not self.messages or self.messages[0].get("role") != "system":
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
                for layer_id, layer in sorted(
                    layers.items(),
                    key=lambda item: (item[1].name().lower(), item[0]),
                ):
                    context_str += f"  * {layer.name()}\n"
                    
            home = self._project_home()
            if home and os.path.exists(home):
                context_str += f"- Project Home Directory ({home}) contains:\n"
                try:
                    files = sorted(os.listdir(home), key=str.lower)
                    context_str += f"  {', '.join(files[:30])}\n"
                except OSError as e:
                    self.logger.debug("Failed to list project home directory %s: %s", home, e)
            return context_str
        except (ImportError, OSError, AttributeError, RuntimeError, TypeError) as e:
            self.logger.warning("Failed to build QGIS environment context: %s", e, exc_info=True)
            return "### CURRENT QGIS ENVIRONMENT CONTEXT ###\n(Context unavailable)"
        
    def _task_routing_text(self):
        """Route a new task from its own text; retain prior intent only for explicit continuation."""
        from .mode_state import is_continuation_message

        current_text = str(self.user_input or "")
        if not is_continuation_message(current_text):
            return current_text

        from .vision_manager import extract_text_content

        recent_user_messages = []
        for message in reversed(self.messages):
            if message.get("role") == "user":
                recent_user_messages.insert(0, extract_text_content(message.get("content", ""))[:4000])
            if len(recent_user_messages) >= 4:
                break
        recent_user_messages.append(current_text)
        return "\n".join(recent_user_messages)

    def _build_frozen_request_prefix(self, cancelled_content, char_limit=24000):
        """Create the initial protocol-valid window once; later requests only append."""
        from .message_protocol import reconcile_tool_messages

        system_msgs = [m for m in self.messages if m.get("role") == "system"]
        other_msgs = [m for m in self.messages if m.get("role") != "system"]
        current_chars = 0
        context_truncated = False
        dynamic_other_msgs = []
        for idx, message in enumerate(reversed(other_msgs)):
            message_length = self._serialized_chars(message)
            # Do not drop the latest turn simply because it contains a multimodal payload
            if idx > 0 and current_chars + message_length > char_limit and dynamic_other_msgs:
                context_truncated = True
                break
            dynamic_other_msgs.insert(0, message)
            current_chars += message_length

        while dynamic_other_msgs and dynamic_other_msgs[0].get("role") == "tool":
            context_truncated = True
            dynamic_other_msgs.pop(0)
        dynamic_other_msgs, repairs = reconcile_tool_messages(
            dynamic_other_msgs,
            cancelled_content,
        )
        if repairs:
            context_truncated = True
            self.logger.warning(
                f"Repaired {len(repairs)} tool message issue(s) while freezing the request prefix."
            )
        return list(system_msgs) + dynamic_other_msgs, context_truncated

    def _init_client(self):
        global OpenAI
        if OpenAI is None:
            try:
                from openai import OpenAI as _OpenAI
                OpenAI = _OpenAI
            except ImportError:
                self.logger.error("openai module is not installed.")
                self.append_message_signal.emit(
                    "SYSTEM",
                    "❌ <b>缺少核心依赖库 'openai'</b><br>"
                    "请打开插件【设置 (⚙️)】点击【安装/检查依赖】，或在终端运行：<br>"
                    "<code>pip install openai</code>",
                )
                return False

        from qgis.core import QgsSettings
        s = QgsSettings()
        api_key = s.value("qgis_agent/deepseek_api_key", "")
        base_url = s.value("qgis_agent/deepseek_base_url", "https://api.deepseek.com")
        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
            return True
        else:
            self.logger.error("DeepSeek API Key not configured in Settings.")
            self.append_message_signal.emit("SYSTEM", "Error: DeepSeek API Key not configured. Please open Settings (⚙️).")
            return False

    def _record_llm_usage(
        self,
        response,
        model_name,
        messages_to_send,
        active_tools=None,
        *,
        dynamic_context="",
        context_truncated=False,
        tool_round=None,
    ):
        import json
        import os

        try:
            from .cache_metrics import append_record, build_metrics_record, extract_usage

            message_chars = self._serialized_chars(messages_to_send or [])
            tool_schema_chars = self._serialized_chars(active_tools or [])
            prompt_chars = message_chars + tool_schema_chars
            extracted = extract_usage(response)
            prompt_tokens = extracted.get("prompt_tokens")
            completion_tokens = extracted.get("completion_tokens")
            total_tokens = extracted.get("total_tokens")
            estimated = False
            if total_tokens is None:
                estimated = True
                prompt_tokens = self._estimate_tokens_from_chars(prompt_chars)
                try:
                    completion_payload = response.choices[0].message.model_dump(exclude_none=True)
                except (AttributeError, IndexError, TypeError, ValueError):
                    completion_payload = ""
                completion_tokens = self._estimate_tokens_from_chars(self._serialized_chars(completion_payload))
                total_tokens = prompt_tokens + completion_tokens
            artifacts = self._ensure_run_artifacts()
            run_id = os.path.basename(artifacts.run_dir) if artifacts else ""
            proj_home = self._project_home()
            payload = build_metrics_record(
                response,
                model_name,
                messages_to_send or [],
                active_tools or [],
                dynamic_context=dynamic_context,
                context_truncated=context_truncated,
                tool_round=tool_round,
                run_id=run_id,
                project_home=proj_home,
                char_metrics={
                    "prompt_chars": prompt_chars,
                    "message_chars": message_chars,
                    "tool_schema_chars": tool_schema_chars,
                },
                usage_fallback={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "estimated": estimated,
                },
            )
            # Keep the historical top-level counters readable by older reports.
            payload.update({
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated": estimated,
                "prompt_chars": prompt_chars,
                "message_chars": message_chars,
                "tool_schema_chars": tool_schema_chars,
                "message_count": len(messages_to_send or []),
                "active_tool_count": len(active_tools or []),
                "prompt_cache_hit_tokens": payload["usage"].get("prompt_cache_hit_tokens"),
                "prompt_cache_miss_tokens": payload["usage"].get("prompt_cache_miss_tokens"),
            })
            if artifacts:
                artifacts.append_jsonl(
                    "token_usage.jsonl",
                    payload,
                    role="token_usage",
                    description="LLM token and prompt-cache usage per request.",
                )
            append_record(payload)

            try:
                dur = getattr(self, "_last_request_duration", 0.5)
                comp_tok = completion_tokens or 0
                if comp_tok > 0:
                    self._current_speed_tok_s = int(comp_tok / dur)

                hit = payload.get("prompt_cache_hit_tokens") or 0
                miss = payload.get("prompt_cache_miss_tokens") or 0
                hit_pct = int(round(hit / max(1, hit + miss) * 100)) if (hit + miss) > 0 else 99
                ctx_pct = min(100, int(round((total_tokens or prompt_tokens or 0) / 64000 * 100)))

                self.metrics_signal.emit({
                    "speed": getattr(self, "_current_speed_tok_s", 185),
                    "total_tokens": total_tokens or 0,
                    "cache_hit_rate": hit_pct,
                    "ctx_percent": ctx_pct,
                    "step": tool_round,
                })
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass

            # Retain the legacy location for compatibility with existing run reports.
            utils_dir = os.path.join(self.plugin_dir, "utils")
            os.makedirs(utils_dir, exist_ok=True)
            with open(os.path.join(utils_dir, "token_usage.jsonl"), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            self.logger.warning(f"Failed to record LLM token usage: {exc}", exc_info=True)

    def _enforce_mode_gate(self, tool_call, tool_name, args):
        if self.work_mode != "PLAN" or self.plan_approved:
            return True
        from .step_runner import is_execution_tool
        if not is_execution_tool(tool_name):
            return True
        from .tool_result import ToolResult
        blocked = ToolResult.failure(
            "PLAN mode requires an approved plan before executing a mutating tool.",
            error_type="approval_required",
            data={"tool": tool_name, "work_mode": self.work_mode},
            suggestions=["Call submit_plan_for_approval and wait for approval before retrying."],
        ).to_json()
        self.logger.warning(f"Blocked {tool_name} before PLAN approval.")
        self._append_tool_result(
            tool_call,
            tool_name,
            args,
            blocked,
            planner_complete=False,
        )
        return False

    def _cancel_pending_tool_calls(self, tool_calls, start_index, reason):
        from .message_protocol import build_cancelled_tool_results
        from .tool_result import ToolResult

        pending = list(tool_calls or [])[start_index:]
        if not pending:
            return
        content = ToolResult.failure(
            reason,
            error_type="operation_cancelled",
            suggestions=["Start a new turn to resume the remaining operations."],
        ).to_json()
        cancelled_messages = build_cancelled_tool_results(pending, content)
        self.messages.extend(cancelled_messages)
        self.logger.info(f"Cancelled {len(cancelled_messages)} pending tool call(s) in the current response.")

    def _has_project_mutations(self) -> bool:
        if self._project_mutation_count > 0:
            return True
        return False

    def run(self):
        if not getattr(self, "client", None) and not self._init_client():
            self.logger.error("Client not initialized. API Key missing.")
            self.finished_signal.emit()
            return
            
        self.logger.info(f"User Input: {self.user_input}")
        
        # Process @ mentions
        self.ghost_context = self._process_mentions(self.user_input)
        if self.ghost_context:
            self.logger.info(f"Injected Ghost Context:\n{self.ghost_context}")
            
        # Process IMAGE_ATTACHMENT via native DeepSeek vision
        from .vision_manager import (
            build_multimodal_message,
            extract_image_attachment_and_text,
        )
        clean_user_input, attached_image_path = extract_image_attachment_and_text(self.user_input)
        if attached_image_path and os.path.exists(attached_image_path):
            self.append_message_signal.emit("SYSTEM", "📸 已附加图像，将直接通过 DeepSeek 原生多模态视觉通道处理...")
            user_message = build_multimodal_message(clean_user_input, attached_image_path)
            effective_user_text = clean_user_input
        else:
            effective_user_text = clean_user_input or self.user_input
            user_message = {"role": "user", "content": effective_user_text}
            
        # Turn-scoped system messages (frozen QGIS context, resume notes, reasoner
        # tool descriptions) from earlier turns are stale and would otherwise pile
        # up in the shared history. Keep only the stable messages[0] system prefix
        # (prompt-cache friendly) plus the real user/assistant/tool conversation.
        # IMPORTANT: mutate in place - self.messages is the plugin's shared
        # global_messages list, and rebinding it silently drops conversation memory.
        if self.messages:
            head = [self.messages[0]] if self.messages[0].get("role") == "system" else []
            body = [m for m in self.messages[len(head):] if m.get("role") != "system"]
            self.messages[:] = head + body

        # Checkpoint Resume Detection
        try:
            from .checkpoints import CheckpointManager
            existing_mgr = CheckpointManager(project_home=self._project_home())
            last_cp = existing_mgr.get_last_checkpoint()
            if last_cp and any(w in str(effective_user_text).lower() for w in ["继续", "resume", "从上一步", "恢复", "接着", "纠错", "重试"]):
                import json
                resume_note = (
                    f"### EXECUTION CHECKPOINT RESUME CONTEXT ###\n"
                    f"检测到最近已保存的执行节点：[步骤 {last_cp.step_number}: {last_cp.title}] (状态: {last_cp.status})\n"
                    f"- 节点 ID: {last_cp.checkpoint_id}\n"
                    f"- 节点产出数据: {json.dumps(last_cp.outputs, ensure_ascii=False)}\n"
                    f"请基于该节点的现有图层与产物继续推进后续步骤，或根据用户的纠错要求仅针对该节点做定向调整，严禁从头推倒重来。\n"
                )
                self.messages.append({"role": "system", "content": resume_note})
                self.logger.info(f"Injected checkpoint resume context for checkpoint: {last_cp.checkpoint_id}")
        except (ImportError, OSError, ValueError, TypeError, AttributeError, RuntimeError) as cp_err:
            self.logger.warning(f"Failed to check previous checkpoints: {cp_err}", exc_info=True)

        self._prepare_messages()
        
        # Repair the complete retained sequence, including partially completed
        # multi-tool responses and orphan results left by an interrupted session.
        from .message_protocol import reconcile_tool_messages
        from .tool_result import ToolResult
        cancelled_content = ToolResult.failure(
            "Tool execution was cancelled before a result was recorded.",
            error_type="cancelled_error",
        ).to_json()
        # In-place update keeps the shared history object (plugin.global_messages)
        # in sync. Rebinding here was the root cause of "agent forgets the previous
        # turn" and of the same interrupted call being re-repaired on every turn.
        repaired_messages, repairs = reconcile_tool_messages(self.messages, cancelled_content)
        self.messages[:] = repaired_messages
        if repairs:
            self.logger.warning(f"Repaired {len(repairs)} interrupted tool message issue(s): {repairs}")
        
        # Freeze all prefix-sensitive inputs once for this user task. QGIS state
        # changes after this point are represented by structured tool results.
        routing_text = self._task_routing_text()
        frozen_context = self._get_qgis_context()
        if getattr(self, "ghost_context", None):
            frozen_context += "\n\n[System Auto-Injected Context based on @ Mentions]:\n" + self.ghost_context
        auto_rag = self._get_auto_rag_context(effective_user_text)
        if auto_rag:
            frozen_context += "\n\n" + auto_rag
        self.messages.append({"role": "system", "content": frozen_context})
        self.messages.append(user_message)

        active_tools = self._select_tools_for_request(routing_text)
        real_model_name = self.model_name.split(" ")[0]
        if real_model_name == "deepseek-reasoner":
            import json

            tools_desc = json.dumps(
                [tool["function"] for tool in active_tools],
                indent=2,
                ensure_ascii=False,
            )
            self.messages.append({
                "role": "system",
                "content": (
                    "You are currently DeepSeek-Reasoner. Native tool calling is disabled. "
                    "Use only the currently active tools below and return a JSON tool block with tool_name and arguments. "
                    "If a built-in domain is missing, call activate_domain_tools; newly activated tools will be described "
                    "on the next round.\n\n"
                    f"{tools_desc}\n\n"
                    "A raw python block may be used only when execute_pyqgis_script is available and approved."
                ),
            })
        frozen_request_prefix, context_truncated = self._build_frozen_request_prefix(
            cancelled_content,
        )
        request_growth_start = len(self.messages)
        try:
            from .request_profile import detect_task_domains

            self._frozen_task_domains = set(detect_task_domains(routing_text))
        except (ImportError, ValueError, TypeError):
            self._frozen_task_domains = set()
        self.logger.info(
            "Frozen request profile: domains=%s tools=%s initial_messages=%s truncated=%s",
            sorted(self._frozen_task_domains),
            len(active_tools),
            len(frozen_request_prefix),
            context_truncated,
        )
        
        try:
            tool_round = 0
            self._detect_and_init_long_task_stations()
            while True:
                if self._run_status_override in {"awaiting_input", "awaiting_approval"}:
                    break
                if self.is_killed:
                    self.logger.info("Agent thread was killed by user.")
                    self.append_message_signal.emit("SYSTEM", "🛑 Operation stopped by user.")
                    try:
                        if not self.checkpoint_manager:
                            from .checkpoints import CheckpointManager
                            artifacts = self._ensure_run_artifacts()
                            run_dir = artifacts.run_dir if artifacts else ""
                            self.checkpoint_manager = CheckpointManager(self._project_home(), run_dir)
                        if self.checkpoint_manager:
                            cp = self.checkpoint_manager.mark_interrupted(
                                title="任务执行已被用户手动暂停/中止",
                                reason="用户点击了暂停/停止按钮",
                            )
                            self.append_message_signal.emit("SYSTEM", self.checkpoint_manager.format_checkpoint_card(cp))
                    except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as kill_cp_err:
                        self.logger.warning(f"Failed to mark checkpoint interrupted: {kill_cp_err}", exc_info=True)
                    from .run_state import CANCELLED
                    self._run_status_override = CANCELLED
                    self._run_status_reason = "The user stopped the operation."
                    break
                active_tools, added_tool_names = self._apply_pending_tool_pack_expansion(active_tools)
                if added_tool_names and real_model_name == "deepseek-reasoner":
                    import json

                    activated = [self.tools_by_name[name]["function"] for name in added_tool_names]
                    self.messages.append({
                        "role": "system",
                        "content": (
                            "Runtime activated these additional registered tools after a domain clarification. "
                            "They are available from this round onward:\n"
                            + json.dumps(activated, ensure_ascii=False, sort_keys=True)
                        ),
                    })
                tool_round += 1
                # Check consecutive failures circuit breaker (true infinite retry loop)
                if self._consecutive_tool_failures >= MAX_CONSECUTIVE_FAILURES:
                    from .run_state import BLOCKED
                    self._run_status_override = BLOCKED
                    self._run_status_reason = f"Consecutive tool failure limit ({MAX_CONSECUTIVE_FAILURES}) reached."
                    self.append_message_signal.emit(
                        "SYSTEM",
                        f"Agent stopped after {MAX_CONSECUTIVE_FAILURES} consecutive tool errors to prevent unyielding retry.",
                    )
                    self._sync_metro_progress("failed", "连续多次工具执行遇到阻碍")
                    diagnostic_card = self._build_diagnostic_summary_for_user("连续多次工具执行失败，为防死循环已安全挂起")
                    self._emit_agent_message(diagnostic_card)
                    break

                # Global safety cap for total task rounds
                if tool_round > MAX_TOOL_ROUNDS:
                    from .run_state import BLOCKED
                    self._run_status_override = BLOCKED
                    self._run_status_reason = f"Maximum tool loop count ({MAX_TOOL_ROUNDS}) reached."
                    self.append_message_signal.emit(
                        "SYSTEM",
                        f"Agent stopped after {MAX_TOOL_ROUNDS} total tool rounds.",
                    )
                    self._sync_metro_progress("failed", f"达到单任务最大轮数 ({MAX_TOOL_ROUNDS})")
                    diagnostic_card = self._build_diagnostic_summary_for_user(
                        f"达到单次任务安全轮数上限 ({MAX_TOOL_ROUNDS})"
                    )
                    self._emit_agent_message(diagnostic_card)
                    break
                    
                self.append_message_signal.emit("SYSTEM", "Thinking...")
                
                # The initial prefix is immutable. Assistant/tool messages from
                # this task are appended in protocol order without re-windowing.
                messages_to_send = list(frozen_request_prefix)
                messages_to_send.extend(self.messages[request_growth_start:])
                
                kwargs = {
                    "model": real_model_name,
                    "messages": messages_to_send,
                }
                import json
                
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
                    # DeepSeek Prompt Cache Optimization: Ensure deterministic dictionary order for tool definitions
                    sorted_tools = sorted(active_tools, key=lambda t: t.get("function", {}).get("name", ""))
                    kwargs["tools"] = sorted_tools
                    kwargs["tool_choice"] = "auto"
                    
                t_req_start = time.time()
                try:
                    response = self._create_chat_completion_with_retry(kwargs)
                    self._last_request_duration = max(0.05, time.time() - t_req_start)
                except Exception as e:
                    message = f"LLM request failed: {str(e)}"
                    self.logger.error(message, exc_info=True)
                    self.append_message_signal.emit(
                        "SYSTEM",
                        message + "\nThe agent stopped this turn without executing additional tools.",
                    )
                    self._write_artifact_result(message, ok=False)
                    break
                self._record_llm_usage(
                    response,
                    real_model_name,
                    messages_to_send,
                    active_tools,
                    dynamic_context=frozen_context,
                    context_truncated=context_truncated,
                    tool_round=tool_round,
                )
                
                msg = response.choices[0].message
                msg_dict = msg.model_dump(exclude_none=True)
                
                # Check for reasoning_content (R1)
                reasoning_content = getattr(msg, "reasoning_content", None)
                if reasoning_content:
                    import html as _html
                    escaped_reasoning = _html.escape(str(reasoning_content))
                    formatted_reasoning = f'<div style="color: #666; background-color: #f8f9fa; padding: 10px; border-left: 3px solid #007bff; margin: 5px 0; font-size: 12px;"><b>🧠 思考过程:</b><br/><pre style="white-space: pre-wrap; margin: 0; font-family: monospace;">{escaped_reasoning}</pre></div>'
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
                        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
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
                    self._emit_agent_message(msg.content)
                    self._last_summary = msg.content
                
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
                        self._write_artifact_result(msg.content or "")
                        break
                
                # We do not use else because if the fallback triggered, we want to execute the tool
                self._consecutive_no_tool = 0
                self._begin_planner_response()
                    
                break_outer_loop = False
                tool_calls_in_response = list(msg_wrapped.tool_calls)
                for tool_index, tc_dict in enumerate(tool_calls_in_response):
                    if self.is_killed:
                        self._cancel_pending_tool_calls(
                            tool_calls_in_response,
                            tool_index,
                            "Tool execution was skipped because the user stopped the operation.",
                        )
                        from .run_state import CANCELLED
                        self._run_status_override = CANCELLED
                        self._run_status_reason = "The user stopped the operation."
                        break_outer_loop = True
                        break
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
                    if not self._enforce_mode_gate(tool_call, name, args):
                        continue
                    if not self._before_step_tool_call(tool_call, name, args):
                        continue
                    
                    if name == "activate_domain_tools":
                        requested_domains = sorted({str(domain) for domain in (args.get("domains") or [])})
                        scheduled_domains = self._queue_domain_tool_expansion(
                            requested_domains,
                            source="activate_domain_tools",
                        )
                        from .tool_result import ToolResult
                        result = ToolResult.success(
                            "Registered domain tools are scheduled for additive activation on the next model round.",
                            data={
                                "requested_domains": requested_domains,
                                "scheduled_domains": scheduled_domains,
                                "currently_active_domains": sorted(self._frozen_task_domains),
                                "max_expansions": MAX_TOOL_PACK_EXPANSIONS,
                            },
                        ).to_json()
                        self._append_tool_result(
                            tool_call,
                            name,
                            args,
                            result,
                            planner_complete=False,
                        )

                    elif name == "ask_human":
                        question = args.get("question", "")
                        self.logger.info(f"Agent asking human: {question}")
                        self.human_input_event.clear()
                        self.request_human_input_signal.emit(question)
                        # Block thread until GUI signals back
                        if not self._wait_for_event(self.human_input_event, 1800, "human input"):
                            from .tool_result import ToolResult
                            from .run_state import AWAITING_INPUT
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                ToolResult.failure(
                                    "Timed out waiting for human input.",
                                    error_type="human_input_required",
                                    data={"tool": name},
                                    suggestions=["Ask a shorter question or retry when the user is available."],
                                ).to_json(),
                            )
                            self._run_status_override = AWAITING_INPUT
                            self._run_status_reason = "Timed out while waiting for required user input."
                            break_outer_loop = True
                            break
                        
                        answer = self.human_input_response
                        self.logger.info(f"Human answered: {answer}")
                        from .request_profile import detect_task_domains
                        clarification_domains = detect_task_domains(f"{question}\n{answer}")
                        self._queue_domain_tool_expansion(
                            clarification_domains,
                            source="ask_human clarification",
                        )
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
                            from .vision_manager import call_deepseek_vision
                            self.append_message_signal.emit("SYSTEM", "👀 正在呼叫 DeepSeek 视觉排版顾问...")
                            time.sleep(0.1)
                            try:
                                vision_feedback = call_deepseek_vision(
                                    client=self.client,
                                    model=self.model_name,
                                    prompt=question,
                                    image_path_or_url=img_path,
                                    system_prompt="你是一位专业的 GIS 地图制图与视觉设计专家，擅长从色彩搭配、图面构图、文字标注、图例布局及可读性等多维度对地图进行深入专业的评估并给出改进建议。",
                                    max_tokens=1024,
                                )
                                self.append_message_signal.emit("SYSTEM", f"DeepSeek 视觉顾问反馈: {vision_feedback}")
                                result = vision_feedback
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
                        from .tool_registry import get_tool_spec
                        tool_spec = get_tool_spec(name)
                        if tool_spec is not None and not tool_spec.requires_qgis_main_thread:
                            from ..tools.tools import execute_atomic_tool_structured
                            from qgis.utils import iface
                            result = execute_atomic_tool_structured(
                                iface,
                                name,
                                args,
                                cancel_callback=lambda: bool(self.is_killed),
                            )
                            if self.is_killed:
                                from .tool_result import ToolResult
                                result = ToolResult.failure(
                                    "Tool execution was cancelled by user.",
                                    error_type="operation_cancelled",
                                    data={"tool": name},
                                ).to_json()
                                self._append_tool_result(tool_call, name, args, result)
                                break_outer_loop = True
                                break
                        else:
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
                        
                        if isinstance(result, str) and result.startswith("[IMAGE_PATH]"):
                            img_path = result.replace("[IMAGE_PATH]", "").strip()
                            if os.path.exists(img_path):
                                from .vision_manager import call_deepseek_vision
                                self.append_message_signal.emit("SYSTEM", "📸 正在通过 DeepSeek 原生视觉解析窗口截图...")
                                time.sleep(0.1)
                                try:
                                    vision_desc = call_deepseek_vision(
                                        client=self.client,
                                        model=self.model_name,
                                        prompt="Please analyze this QGIS screenshot in detail. Describe the layers, the canvas, and any open panels/dialogs.",
                                        image_path_or_url=img_path,
                                        max_tokens=1024,
                                    )
                                    result = "Screenshot analysis from DeepSeek Vision:\n" + vision_desc
                                except Exception as e:
                                    result = f"Vision API Exception: {str(e)}"
                            else:
                                result = f"Error: Screenshot file not found: {img_path}"
                                
                        self._append_tool_result(tool_call, name, args, result)
                        from .tool_result import parse_tool_result_payload
                        result_payload = parse_tool_result_payload(result) or {}
                        if self.is_killed or result_payload.get("error_type") == "operation_cancelled":
                            self._cancel_pending_tool_calls(
                                tool_calls_in_response,
                                tool_index + 1,
                                "Tool execution was skipped because the current operation was cancelled.",
                            )
                            from .run_state import CANCELLED
                            self._run_status_override = CANCELLED
                            self._run_status_reason = str(
                                result_payload.get("message") or "The current operation was cancelled."
                            )
                            break_outer_loop = True
                            break
                        
                    elif name == "read_file":
                        file_path = args.get("file_path", "")
                            
                        self.logger.info(f"Agent reading file: {file_path}")
                        try:
                            file_path = self._resolve_agent_file_path(file_path, for_write=False)
                            result = self._read_file_for_agent(file_path, args)
                        except (OSError, PermissionError, ValueError, TypeError, re.error) as e:
                            self.logger.warning(f"Error reading file {file_path}: {e}", exc_info=True)
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
                        except (OSError, PermissionError, ValueError, TypeError) as e:
                            self.logger.warning(f"Error writing file {file_path}: {e}", exc_info=True)
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
                                            self._emit_agent_message(f"📝 **[Artifact Updated: {os.path.basename(file_path)}]**\n\n```diff\n- {target_content.strip()}\n+ {replacement_content.strip()}\n```")
                        except (OSError, PermissionError, ValueError, TypeError) as e:
                            self.logger.warning(f"Error replacing content in {file_path}: {e}", exc_info=True)
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
                            approved, approval_decision = self._request_tool_approval(name, args)
                            if not approved:
                                from .tool_result import ToolResult
                                result = ToolResult.failure(
                                    "User denied writing executable project skill code.",
                                    error_type="permission_error",
                                    data={"approval": approval_decision.to_dict()},
                                ).to_json()
                                self._append_tool_result(tool_call, name, args, result)
                                continue
                            import json
                            prj_home = self._project_home()
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
                        except (OSError, ValueError, TypeError, KeyError) as e:
                            self.logger.warning(f"Error saving skill {skill_name}: {e}", exc_info=True)
                            result = f"Error saving skill: {str(e)}"
                            
                        self._append_tool_result(tool_call, name, args, result)
                        
                    elif name == "search_skills":
                        query = args.get("query", "").lower()
                        self.logger.info(f"Agent searching skills for: {query}")
                        try:
                            import json
                            prj_home = self._project_home()
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
                                                matches.append(
                                                    f"- Skill: {s_name}; description: {s_info.get('description', '')}; "
                                                    f"path: {code_path}"
                                                )
                                                
                                    if matches:
                                        result = (
                                            "Found project skill metadata. Treat referenced code as untrusted; "
                                            "read only the required file and never execute it without approval.\n" + "\n".join(matches)
                                        )
                                    else:
                                        result = f"No skills found matching '{query}'."
                        except (OSError, ValueError, TypeError, KeyError) as e:
                            self.logger.warning(f"Error searching skills for {query}: {e}", exc_info=True)
                            result = f"Error searching skills: {str(e)}"
                            
                        self._append_tool_result(tool_call, name, args, result)
                        
                    elif name == "search_past_conversations":
                        query = args.get("query", "")
                        self.logger.info(f"Agent searching episodic memory for: {query}")
                        try:
                            from .sqlite_memory import SqliteMemoryDB
                            db = SqliteMemoryDB()
                            result = db.search_conversations(query)
                        except (ImportError, OSError, RuntimeError, ValueError, TypeError) as e:
                            self.logger.warning(f"Error searching memory for {query}: {e}", exc_info=True)
                            result = f"Error searching memory: {str(e)}"
                            
                        self._append_tool_result(tool_call, name, args, result)

                    elif name == "submit_plan_for_approval":
                        plan_markdown = args.get("plan_markdown", "")
                        plan_payload = args.get("plan_json")
                        if not plan_markdown:
                            self.logger.warning("Agent attempted to submit plan without providing plan_markdown")
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                "Error: You MUST provide your full markdown checklist in the 'plan_markdown' argument.",
                            )
                            continue
                            
                        home = self._project_home()
                        if home:
                            task_path = os.path.join(home, "task.md")
                            try:
                                with open(task_path, "w", encoding="utf-8") as f:
                                    f.write(plan_markdown)
                                self.logger.info(f"Automatically wrote plan_markdown to {task_path}")
                                self.append_message_signal.emit("SYSTEM", "📝 **[Artifact Created: task.md]**\n\n(系统已根据您的计划自动生成任务文件)")
                            except OSError as e:
                                self.logger.error(f"Failed to write task.md: {e}", exc_info=True)
                            try:
                                artifacts = self._ensure_run_artifacts()
                                if artifacts:
                                    artifacts.write_plan(plan_markdown)
                            except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as e:
                                self.logger.warning(f"Failed to write plan artifact: {e}", exc_info=True)
                            
                        self.logger.info("Agent requesting plan approval.")
                        self.plan_approval_event.clear()
                        self.waiting_for_plan_approval = True
                        self.request_plan_approval_signal.emit()
                        # Block thread
                        approval_received = self._wait_for_event(self.plan_approval_event, 1800, "plan approval")
                        self.waiting_for_plan_approval = False
                        if not approval_received:
                            from .tool_result import ToolResult
                            from .run_state import AWAITING_APPROVAL
                            self._append_tool_result(
                                tool_call,
                                name,
                                args,
                                ToolResult.failure(
                                    "Timed out waiting for plan approval.",
                                    error_type="approval_required",
                                    data={"tool": name},
                                    suggestions=["Submit the plan again when the user is ready to approve it."],
                                ).to_json(),
                            )
                            self._run_status_override = AWAITING_APPROVAL
                            self._run_status_reason = "Timed out while waiting for plan approval."
                            break_outer_loop = True
                            break
                        if self.is_killed:
                            self._cancel_pending_tool_calls(
                                tool_calls_in_response,
                                tool_index,
                                "Tool execution was skipped because the user stopped the operation.",
                            )
                            break_outer_loop = True
                            break
                        
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
                            self._register_planner_plan(plan_markdown, plan_payload)
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
                                    proj_dir = os.path.dirname(proj_path) if isinstance(proj_path, str) and proj_path else os.path.expanduser("~")
                                    task_file = os.path.join(proj_dir, "task.md")
                                    if os.path.exists(task_file):
                                        with open(task_file, "r", encoding="utf-8") as f:
                                            task_content = f.read()
                                except (ImportError, OSError, AttributeError, RuntimeError, TypeError):
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
                            from .tool_registry import get_tool_spec
                            tool_spec = get_tool_spec(name)
                            if tool_spec is not None and not tool_spec.requires_qgis_main_thread:
                                from ..tools.tools import execute_atomic_tool_structured
                                from qgis.utils import iface
                                output = execute_atomic_tool_structured(iface, name, args)
                            else:
                                self.atomic_tool_event.clear()
                                self.request_atomic_tool_signal.emit(name, args)
                                if not self._wait_for_event(self.atomic_tool_event, 600, f"atomic tool {name}"):
                                    from .tool_result import ToolResult
                                    output = ToolResult.failure(
                                        f"Timed out waiting for atomic tool: {name}.",
                                        error_type="timeout_error",
                                        data={"tool": name},
                                        suggestions=["Retry with a smaller tool call or check whether QGIS is busy."],
                                    ).to_json()
                                    self._append_tool_result(tool_call, name, args, output)
                                    continue
                                output = self.atomic_tool_response
                        except Exception as e:
                            output = f"Error executing {name}: {str(e)}"
                        self._append_tool_result(tool_call, name, args, output)
                        
                if locals().get("break_outer_loop", False):
                    break
                if self._finish_if_locally_verified():
                    break
                        
        except Exception as e:
            self.logger.error(f"Exception during Agent execution: {str(e)}", exc_info=True)
            self.append_message_signal.emit("SYSTEM", f"Exception during Agent execution: {str(e)}")
            from .run_state import FAILED
            self._run_status_override = FAILED
            self._run_status_reason = str(e)
            self._sync_metro_progress("failed", str(e))
            self._emit_agent_message(f"❌ **执行过程遇到异常**：\n\n```text\n{str(e)}\n```\n\n已保留当前状态与图层。您可以尝试补充说明以继续。")

        if not self._result_written:
            self._write_artifact_result(
                self._last_summary or self._run_status_reason or "The agent run ended without a final model summary."
            )
        if not self._agent_message_emitted and not self.is_killed:
            fallback_msg = self._build_diagnostic_summary_for_user("运行结束但未生成最终回复")
            self._emit_agent_message(fallback_msg)

        if self._external_write_grants:
            try:
                from .path_access import revoke_write_access

                revoke_write_access(self._external_write_grants)
                self.logger.info("Revoked %s one-task external write grant(s).", len(self._external_write_grants))
            except (ImportError, OSError, ValueError, TypeError, RuntimeError) as exc:
                self.logger.warning(f"Failed to revoke external write grants: {exc}", exc_info=True)
            self._external_write_grants = []
            
        self.finished_signal.emit()

    # Callbacks from main thread
    def provide_human_input(self, answer):
        self.human_input_response = answer
        self.human_input_event.set()
        
    def provide_destructive_auth(self, is_approved):
        self.destructive_auth_response = is_approved
        self.destructive_auth_event.set()

