# Path resolution, approval gating, tool validation, result compaction, and planner step helpers.

import os


class HarnessExecutionHelpersMixin:
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
        project_home = self._project_home()
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
        managed_paths = {os.path.abspath(os.path.join(self.plugin_dir, "USER.md"))}
        project_home = self._project_home()
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

        context = dict(context or {})
        if "mode" not in context:
            context["mode"] = self.work_mode
        if "project_home" not in context:
            context["project_home"] = self._project_home()

        decision = ToolApprovalPolicy(self.plugin_dir).evaluate(tool_name, args, context)
        if not decision.requires_approval:
            self._record_approval_decision(tool_name, args, decision, user_approved=None)
            return True, decision

        self.destructive_auth_response = False
        self.destructive_auth_event.clear()
        self.request_destructive_auth_signal.emit(decision.approval_prompt)
        if not self._wait_for_event(self.destructive_auth_event, 300, "approval response"):
            from .run_state import AWAITING_APPROVAL

            decision.warnings.append("approval_timeout")
            self._run_status_override = AWAITING_APPROVAL
            self._run_status_reason = f"Timed out while waiting for approval of {tool_name}."
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
            registry_health_path = artifacts.path("security/tool_registry_health.json")
            if not os.path.exists(registry_health_path):
                artifacts.write_tool_registry_artifacts()
            artifacts.append_approval_decision({
                "tool": tool_name,
                "risk_level": decision.risk_level,
                "requires_approval": decision.requires_approval,
                "reason": decision.reason,
                "warnings": decision.warnings,
                "user_approved": user_approved,
                "arguments_summary": self._summarize_tool_args(args),
            })
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as e:
            self.logger.warning(f"Failed to record approval decision for {tool_name}: {e}", exc_info=True)

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

    def _serialized_chars(self, value) -> int:
        import json

        try:
            return len(json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")))
        except (TypeError, ValueError, OverflowError):
            return len(str(value))

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
        except (json.JSONDecodeError, TypeError, ValueError):
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
            from .validators import (
                external_write_targets,
                redirect_external_outputs_to_project,
                report_has_only_external_path_errors,
                validate_tool_call,
            )
            report = validate_tool_call(tool_name, args)
            if report.ok:
                return True

            targets = external_write_targets(tool_name, args)
            if targets and report_has_only_external_path_errors(report):
                action = self._request_external_path_action(tool_name, targets)
                if action == "allow":
                    from .path_access import grant_write_access

                    for target in targets:
                        root = grant_write_access(
                            target["path"],
                            is_directory=bool(target.get("is_directory")),
                        )
                        if root not in self._external_write_grants:
                            self._external_write_grants.append(root)
                    self.logger.info(
                        "User approved one-task external write access for %s target(s).",
                        len(targets),
                    )
                    report = validate_tool_call(tool_name, args)
                elif action == "copy_to_project":
                    changes = redirect_external_outputs_to_project(
                        tool_name,
                        args,
                        self._project_home(),
                    )
                    if changes:
                        self.logger.info("Redirected %s external output path(s) into the project folder.", len(changes))
                        report = validate_tool_call(tool_name, args)
                    else:
                        from .tool_result import ToolResult

                        result = ToolResult.failure(
                            "Cannot copy output into the project folder because the current project has not been saved.",
                            error_type="file_path_error",
                            data={"tool": tool_name, "external_targets": targets},
                            suggestions=["Save the QGIS project first, or explicitly approve the external output path."],
                        ).to_json()
                        self._append_tool_result(tool_call, tool_name, args, result, planner_complete=False)
                        return False
                else:
                    from .tool_result import ToolResult

                    result = ToolResult.failure(
                        "User did not approve writing outside the project workspace.",
                        error_type="permission_error",
                        data={"tool": tool_name, "external_targets": targets},
                        suggestions=["Approve the one-task external path access or choose to save a copy inside the project folder."],
                    ).to_json()
                    self._append_tool_result(tool_call, tool_name, args, result, planner_complete=False)
                    return False

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
            from .tool_result import ToolResult
            result = ToolResult.failure(
                f"Tool validation failed internally and execution was blocked: {e}",
                error_type="argument_error",
                data={"tool": tool_name},
                suggestions=["Repair the validator or retry with a registered, fully specified tool call."],
            ).to_json()
            self._append_tool_result(tool_call, tool_name, args, result, planner_complete=False)
            return False

    def _append_tool_result(self, tool_call, tool_name, args, result, record_artifact=True, planner_complete=True):
        from .tool_result import normalize_tool_output

        content = normalize_tool_output(tool_name, result)
        try:
            import json
            payload = json.loads(content)
            if isinstance(payload, dict) and "ok" in payload:
                self._last_tool_ok = bool(payload.get("ok"))
                if self._last_tool_ok:
                    self._tool_success_count += 1
                    self._last_failure_type = ""
                else:
                    self._tool_failure_count += 1
                    self._last_failure_type = str(payload.get("error_type") or "unknown_error")
                    self._capture_recovery_context(tool_name, args, payload)
                try:
                    from .tool_registry import get_tool_spec

                    spec = get_tool_spec(tool_name)
                    if spec is not None and spec.mutates_project:
                        self._project_mutation_count += 1
                except (ImportError, KeyError, AttributeError, TypeError):
                    pass
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
        if planner_complete:
            content = self._complete_planner_step(tool_call, tool_name, args, content)
        try:
            import json

            final_payload = json.loads(content)
            if isinstance(final_payload, dict):
                self._current_response_results.append({
                    "tool_name": tool_name,
                    "payload": final_payload,
                })
                substantive_milestone_tools = {
                    "compute_raster_index",
                    "compute_raster_zonal_stats",
                    "run_processing_algorithm",
                    "clip_vector_layers_to_boundary",
                    "run_osm_acquisition_workflow",
                    "download_osm_boundary",
                    "download_osm_features",
                    "download_osm_roads",
                    "run_gee_dem_download_workflow",
                    "run_gee_sentinel2_download_workflow",
                    "save_project_and_verify",
                }
                from ..ui.metro_progress import TOOL_CHINESE_TRANSLATION

                cn_tool_title = TOOL_CHINESE_TRANSLATION.get(tool_name, tool_name)
                if isinstance(args, dict) and args.get("index_name"):
                    cn_tool_title = f"{args.get('index_name')}指数计算"
                elif isinstance(args, dict) and args.get("alg_id"):
                    cn_tool_title = TOOL_CHINESE_TRANSLATION.get(str(args.get("alg_id")).lower(), cn_tool_title)

                if final_payload.get("ok") and tool_name in substantive_milestone_tools:
                    try:
                        if not self.checkpoint_manager:
                            from .checkpoints import CheckpointManager
                            artifacts = self._ensure_run_artifacts()
                            run_dir = artifacts.run_dir if artifacts else ""
                            self.checkpoint_manager = CheckpointManager(self._project_home(), run_dir)
                        if self.checkpoint_manager:
                            step_idx = len(self.checkpoint_manager.checkpoints) + 1
                            cp = self.checkpoint_manager.record_checkpoint(
                                step_number=step_idx,
                                title=cn_tool_title,
                                tool_name=tool_name,
                                inputs=args if isinstance(args, dict) else {},
                                outputs=final_payload.get("data") if isinstance(final_payload.get("data"), dict) else {},
                                status="completed",
                                notes=str(final_payload.get("message") or "执行节点已持久化保存"),
                            )
                            self.append_message_signal.emit("SYSTEM", self.checkpoint_manager.format_checkpoint_card(cp))
                            self._sync_metro_progress(state="running", detail=f"已完成：{cp.title}")
                    except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as cp_err:
                        self.logger.warning(f"Checkpoint auto-record failed: {cp_err}", exc_info=True)
                elif not final_payload.get("ok") and tool_name in substantive_milestone_tools:
                    try:
                        if not self.checkpoint_manager:
                            from .checkpoints import CheckpointManager
                            artifacts = self._ensure_run_artifacts()
                            run_dir = artifacts.run_dir if artifacts else ""
                            self.checkpoint_manager = CheckpointManager(self._project_home(), run_dir)
                        if self.checkpoint_manager:
                            step_idx = len(self.checkpoint_manager.checkpoints) + 1
                            err_msg = str(final_payload.get("message") or "执行未通过")
                            cp = self.checkpoint_manager.record_checkpoint(
                                step_number=step_idx,
                                title=f"{cn_tool_title}遇阻",
                                tool_name=tool_name,
                                inputs=args if isinstance(args, dict) else {},
                                outputs={"error": err_msg, "error_type": final_payload.get("error_type")},
                                status="failed",
                                notes=f"第 {step_idx} 步执行异常：{err_msg}。已保留当前断点现场与前置图层。",
                            )
                            self.append_message_signal.emit("SYSTEM", self.checkpoint_manager.format_checkpoint_card(cp))
                            self._sync_metro_progress(state="running", detail=f"已遇阻：{cp.title}")
                    except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as cp_err:
                        self.logger.warning(f"Checkpoint failure record failed: {cp_err}", exc_info=True)
        except (ValueError, TypeError, KeyError, AttributeError, ImportError):
            pass
        # Track consecutive failures vs healthy progress
        try:
            import json as _j
            _p = _j.loads(content) if isinstance(content, str) and content.strip().startswith("{") else {}
            if isinstance(_p, dict) and not _p.get("ok", True):
                self._consecutive_tool_failures += 1
            else:
                self._consecutive_tool_failures = 0
        except (ValueError, TypeError, AttributeError):
            pass

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

    def _capture_recovery_context(self, tool_name, args, payload):
        """Keep only safe, confirmed GEE arguments for a concise retry acknowledgement."""
        if tool_name not in {
            "run_gee_sentinel2_download_workflow",
            "run_gee_dem_download_workflow",
        }:
            return
        error_type = str(payload.get("error_type") or "")
        message = str(payload.get("message") or "")
        if error_type != "gee_download_error":
            return
        self.recovery_context = {
            "kind": "gee_retry",
            "tool_name": tool_name,
            "arguments": dict(args or {}),
            "failure_message": message[:1000],
        }

    def _project_home(self):
        try:
            from qgis.core import QgsProject
            home = QgsProject.instance().homePath()
            if not isinstance(home, str) or not home.strip() or "MagicMock" in home:
                return ""
            return home
        except (ImportError, AttributeError, RuntimeError, TypeError):
            return ""

    def _register_planner_plan(self, plan_markdown, plan_payload=None):
        try:
            from .planner import build_task_plan_from_markdown, build_task_plan_from_payload
            if isinstance(plan_payload, dict) and plan_payload.get("steps"):
                plan = build_task_plan_from_payload(plan_payload, self.user_input, plan_markdown)
            else:
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
            self._sync_metro_progress("running", f"已规划 {len(plan.steps)} 个步骤")
            return plan
        except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
            self.logger.warning(f"Failed to register planner plan: {e}", exc_info=True)
            return None

    def _begin_planner_response(self):
        self._current_response_results = []
        try:
            self.step_controller.start_response()
        except (AttributeError, RuntimeError, TypeError) as e:
            self.logger.warning(f"Failed to start planner response window: {e}", exc_info=True)

    def _finish_if_locally_verified(self):
        results = list(self._current_response_results or [])
        if not results or any(not item.get("payload", {}).get("ok") for item in results):
            return False
        plan = self.step_controller.plan if self.step_controller else None
        plan_complete = bool(plan and plan.all_passed())
        last = results[-1]
        try:
            from .local_continuation import build_local_completion_summary, should_finalize_locally

            if not should_finalize_locally(
                last.get("tool_name", ""),
                last.get("payload") or {},
                getattr(self, "_frozen_task_domains", set()),
                plan_complete=plan_complete,
                response_result_count=len(results),
                user_text=getattr(self, "user_input", ""),
            ):
                return False
            summary = build_local_completion_summary(
                last.get("tool_name", ""),
                last.get("payload") or {},
            )
            self._last_summary = summary
            self._emit_agent_message(summary)
            self._write_artifact_result(summary)
            self._sync_metro_progress("completed", "所有步骤已顺利完成")
            self.logger.info("Task completed by local verifier without a post-tool LLM request.")
            return True
        except (ImportError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            self.logger.warning(f"Local completion decision failed: {exc}", exc_info=True)
            return False

    def _request_external_path_action(self, tool_name, targets):
        """Ask the user before a tool writes or deletes outside project/temp roots."""
        is_destructive = tool_name == "cleanup_qgis_project"
        lines = [
            "该操作需要在当前工程目录之外写入或修改数据。",
            "以下路径本次尚未授权：",
        ]
        lines.extend(f"- {target['path']}" for target in targets[:8])
        if len(targets) > 8:
            lines.append(f"- 另有 {len(targets) - 8} 个路径")
        lines.extend([
            "",
            "请输入 1、2 或 3：",
            "1：仅本次允许 Agent 在上述外部路径执行该操作。",
        ])
        if not is_destructive and self._project_home():
            lines.append("2：改为在当前工程目录的 agent_external_outputs 中保存副本。")
        else:
            lines.append("2：取消（当前工程尚未保存，或该操作不能安全复制）。")
        lines.append("3：取消本次操作。")
        question = "\n".join(lines)
        self.human_input_response = ""
        self.human_input_event.clear()
        self.request_human_input_signal.emit(question)
        if not self._wait_for_event(self.human_input_event, 300, "external path authorization"):
            return "cancel"
        answer = " ".join(str(self.human_input_response or "").strip().lower().split())
        if answer in {"1", "允许", "同意", "授权", "allow", "approve"} or answer.startswith("1"):
            return "allow"
        if answer in {"2", "复制", "保存到工程", "copy", "project"} or answer.startswith("2"):
            return "copy_to_project"
        return "cancel"

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
            self._sync_metro_progress("running" if verification.ok else "failed", verification.message)
            return json.dumps(payload, ensure_ascii=False, default=str)
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
            self.logger.warning(f"Planner step verification failed internally for {tool_name}: {e}", exc_info=True)
            return content

    def _record_step_event(self, payload):
        try:
            artifacts = self._ensure_run_artifacts()
            if artifacts:
                artifacts.append_step_event(payload)
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as e:
            self.logger.warning(f"Failed to record planner step event: {e}", exc_info=True)

    def _write_planner_state_artifact(self):
        try:
            artifacts = self._ensure_run_artifacts()
            if artifacts and self.step_controller.plan:
                artifacts.write_task_plan(self.step_controller.plan.to_dict())
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as e:
            self.logger.warning(f"Failed to write planner state artifact: {e}", exc_info=True)

