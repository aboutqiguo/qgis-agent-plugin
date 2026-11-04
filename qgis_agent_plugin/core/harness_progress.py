# Milestone metro progress detection, synchronization, and user-facing diagnostic summary helpers.

class HarnessProgressMixin:
    def _get_milestone_business_title(self, tool_name: str, args: dict, ok: bool = True) -> str:
        """Map raw tool executions to human-friendly Chinese milestone titles for metro stations."""
        suffix = "" if ok else " 遇阻"
        if tool_name == "run_processing_algorithm":
            alg = str(args.get("alg_id") or "").lower()
            if "rastercalc" in alg:
                return f"遥感指数栅格计算{suffix}"
            elif "fillsinks" in alg:
                return f"水文填洼与流向计算{suffix}"
            elif "watershed" in alg:
                return f"水文流域与河网分析{suffix}"
            elif "warp" in alg:
                return f"栅格重投影与对齐{suffix}"
            elif "clip" in alg:
                return f"矢量边界裁剪{suffix}"
            short_alg = alg.split(":")[-1]
            return f"{short_alg}计算{suffix}"
        elif tool_name == "save_project_and_verify":
            return f"工程保存与成果校验{suffix}"
        elif tool_name == "remove_qgis_layers_and_data":
            return f"图层数据清理{suffix}"
        elif tool_name == "load_external_layer":
            return f"外部图层加载{suffix}"
        elif tool_name == "summarize_layers":
            return f"图层状态汇总{suffix}"
        elif tool_name == "compute_raster_index":
            return f"遥感指数计算{suffix}"
        elif tool_name == "compute_raster_zonal_stats":
            return f"波段分区统计{suffix}"
        elif tool_name == "execute_pyqgis_script":
            return f"空间数据分析计算{suffix}"
        elif "download" in tool_name or "acquisition" in tool_name:
            return f"空间数据下载入库{suffix}"
        return f"{tool_name}{suffix}"

    def _detect_and_init_long_task_stations(self):
        """Auto-detect multi-step workflow from the CURRENT user request (or approved plan) and emit initial metro progress."""
        try:
            if self.step_controller and self.step_controller.plan and self.step_controller.plan.steps:
                self._sync_metro_progress("running", "长线多步骤任务执行中")
                return
            user_text_raw = str(self.user_input or "")
            user_text_low = user_text_raw.lower()

            # 1. Detect remote sensing index tasks (NDVI, NDWI, EVI, etc.)
            if any(kw in user_text_low for kw in ("ndvi", "ndwi", "mndwi", "mvi", "evi", "ndbi", "水体指数", "植被指数")):
                idx_name = "NDVI" if "ndvi" in user_text_low else "MNDWI" if "mndwi" in user_text_low else "NDWI" if "ndwi" in user_text_low else "遥感指数"
                stations = [
                    {"title": "1. 影像波段准备", "status": "completed"},
                    {"title": f"2. {idx_name}栅格计算", "status": "running"},
                    {"title": "3. 成果入库渲染", "status": "pending"},
                ]
                self.operation_progress_signal.emit({
                    "operation_id": "index_calc_metro",
                    "title": f"{idx_name} 遥感计算工作流",
                    "state": "running",
                    "stations": stations,
                    "detail": f"正在执行：{idx_name} 栅格计算",
                })
                return

            # 2. Detect multi-action layer cleanup + loading tasks from current user request
            has_remove = any(kw in user_text_low for kw in ("删除", "移除", "清理", "remove", "delete"))
            has_load = any(kw in user_text_low for kw in ("加载", "导入", "打开", "load"))
            if has_remove and has_load:
                stations = [
                    {"title": "1. 图层状态汇总", "status": "running"},
                    {"title": "2. 图层数据清理", "status": "pending"},
                    {"title": "3. 外部图层加载", "status": "pending"},
                ]
                self.operation_progress_signal.emit({
                    "operation_id": "long_task_metro",
                    "title": "长线多步骤任务",
                    "state": "running",
                    "stations": stations,
                    "detail": "正在推进：1. 图层状态汇总",
                })
                return

            # 3. Only inspect previous assistant message when user is explicitly approving/resuming a plan
            is_plan_resume = any(
                kw in user_text_low
                for kw in ("approve", "继续", "resume", "按计划", "开始执行", "同意方案", "确认执行")
            )
            if not is_plan_resume:
                return

            import re
            step_pattern = re.compile(r'(?:步骤\s*([0-9一二三四五六七八九十]+)[：:]\s*([^\n\r]+))')
            
            last_agent_text = ""
            for m in reversed(self.messages):
                if m.get("role") == "assistant" and m.get("content"):
                    last_agent_text = m.get("content")
                    break
            
            found_steps = []
            if last_agent_text:
                matches = step_pattern.findall(last_agent_text)
                for m in matches:
                    step_num = m[0]
                    step_title = (m[1] or "").strip()
                    if 2 <= len(step_title) <= 24 and not step_title.startswith("http"):
                        clean_title = re.sub(r'[*_`]', '', step_title)
                        found_steps.append(f"{step_num}. {clean_title}")

            if len(found_steps) >= 2:
                stations = []
                existing_count = len(self.checkpoint_manager.checkpoints) if self.checkpoint_manager else 0
                for idx, title in enumerate(found_steps):
                    if idx < existing_count:
                        st_status = "completed"
                    elif idx == existing_count:
                        st_status = "running"
                    else:
                        st_status = "pending"
                    stations.append({
                        "title": title,
                        "status": st_status,
                    })
                event = {
                    "operation_id": "long_task_metro",
                    "title": "长线多步骤任务",
                    "state": "running",
                    "stations": stations,
                    "detail": f"正在推进：{stations[min(existing_count, len(stations)-1)]['title']}",
                }
                self.operation_progress_signal.emit(event)
        except (AttributeError, TypeError, ValueError, KeyError, IndexError, RuntimeError) as e:
            self.logger.warning(f"Failed to auto-detect long task stations: {e}", exc_info=True)

    def _sync_metro_progress(self, state: str = "running", detail: str = ""):
        try:
            plan = self.step_controller.plan if self.step_controller else None
            stations = []
            title = "多步骤长线任务"
            if plan and plan.steps:
                title = getattr(plan, "title", None) or getattr(plan, "objective", None) or "多步骤长线任务"
                for idx, st in enumerate(plan.steps, start=1):
                    st_status = "pending"
                    if st.status == "passed":
                        st_status = "completed"
                    elif st.status == "running":
                        st_status = "running"
                    elif st.status == "failed":
                        st_status = "failed"
                    elif st.status == "skipped":
                        st_status = "pending"
                    
                    stations.append({
                        "title": f"{idx}. {st.title}",
                        "status": st_status,
                    })
            elif self.checkpoint_manager and self.checkpoint_manager.checkpoints:
                title = "任务里程碑进度"
                stations = self.checkpoint_manager.get_metro_stations()

            if stations:
                event = {
                    "operation_id": "long_task_metro",
                    "title": title,
                    "state": state,
                    "stations": stations,
                    "detail": detail,
                }
                self.operation_progress_signal.emit(event)
        except (AttributeError, TypeError, ValueError, KeyError, RuntimeError) as e:
            self.logger.warning(f"Failed to sync metro progress: {e}", exc_info=True)

    def _build_diagnostic_summary_for_user(self, reason: str = "") -> str:
        # 1. First check if a requested target layer already exists and is valid in current QGIS project!
        try:
            from qgis.core import QgsProject
            user_text_low = str(getattr(self, "user_input", "")).lower()
            all_layers = list(QgsProject.instance().mapLayers().values())
            for ly in all_layers:
                lname = ly.name().lower()
                if (("ndvi" in user_text_low and "ndvi" in lname) or 
                    ("ndwi" in user_text_low and "ndwi" in lname) or
                    ("dem" in user_text_low and "dem" in lname)):
                    if ly.isValid():
                        # Target layer successfully created! Directly report SUCCESS instead of failure!
                        return (
                            f"🎉 **任务已圆满完成：成功生成并加载目标图层**\n\n"
                            f"- **已生成图层**：`{ly.name()}`\n"
                            f"- **数据源路径**：`{ly.source()}`\n"
                            f"- **状态**：图层有效并已在当前画布中渲染显示。\n\n"
                            f"如果您需要对该图层进行色带渲染、阈值分割或出图导出，请告诉我。"
                        )
        except (ImportError, AttributeError, RuntimeError, TypeError):
            pass
        turn_start = getattr(self, "_turn_messages_start_idx", 0)
        current_turn_msgs = self.messages[turn_start:] if turn_start < len(self.messages) else []
        latest_tool_msg = None
        for m in reversed(current_turn_msgs):
            if m.get("role") == "tool":
                latest_tool_msg = m
                break

        latest_content = str(latest_tool_msg.get("content") or "") if latest_tool_msg else ""
        latest_is_err = any(k in latest_content.lower() for k in ["error", "exception", "failed", "traceback", "not found"])

        last_error = ""
        last_tool = ""
        if latest_is_err:
            last_tool = latest_tool_msg.get("name", "工具")
            last_error = latest_content
        elif latest_tool_msg:
            # The latest tool in THIS turn actually succeeded! Do not surface ancient already-resolved errors.
            last_tool = latest_tool_msg.get("name", "任务执行")
            last_error = ""

        if not last_tool:
            lines = [
                "⚠️ **当前任务未能自动完成（已安全暂停）**",
                "",
                "Agent 在当前轮次未能顺利获得大模型完整回复或工具执行计划。为防止产生无效输出，系统已安全暂停，并保留了当前工程状态与已生成的数据图层。",
            ]
            if reason:
                lines.append(f"\n- **暂停原因**：{reason}")
            lines.append("\n💡 **建议操作**：您可以补充更具体的指令或重试；若频繁出现，请检查大模型网络连接或账户额度。")
            return "\n".join(lines)
        
        lines = [
            "⚠️ **当前任务未能自动完成（已安全暂停）**",
            "",
            "Agent 尝试了多次工具调用与验证，但遇到了环境或算法参数障碍。为防止陷入无意义的重试死循环，系统已自动暂停，并保留了当前工程状态与已生成的数据图层。",
        ]
        if last_tool:
            lines.append(f"\n- **受阻步骤/执行的工具**：`{last_tool}`")
        if last_error:
            error_preview = last_error.strip()
            if len(error_preview) > 500:
                error_preview = error_preview[:500] + "... (详细日志见工程运行记录)"
            lines.append(f"- **底层返回的关键信息**：\n```text\n{error_preview}\n```")
            
            if "watershed" in error_preview.lower() or "threshold" in error_preview.lower():
                lines.append(
                    "\n💡 **分析与建议**：GRASS 水文分析 (`grass:r.watershed`) 必须明确提供像元汇流阈值 `threshold`（例如 `threshold=1000`）。"
                    "未指定该参数会导致 GRASS 算法立即退出且不生成 accumulation 栅格。\n"
                    "您可直接回复：*“使用 threshold=1000 重试步骤 2”*。"
                )
            elif "not found" in error_preview.lower() or "missing" in error_preview.lower():
                lines.append("\n💡 **分析与建议**：上一步输出的栅格/矢量未能成功保存或加载。请检查数据目录读写权限或检查前序步骤输出。")
            else:
                lines.append("\n💡 **建议操作**：您可以根据上述报错调整执行参数，或直接告诉我具体调整方案。")
        else:
            lines.append(f"\n- **暂停原因**：{reason or '执行达到单轮上限'}")
            lines.append("\n💡 **建议操作**：您可以补充更具体的执行参数，或指示我分步执行单个子任务。")

        return "\n".join(lines)

