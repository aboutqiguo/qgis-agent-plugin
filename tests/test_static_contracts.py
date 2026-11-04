from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "qgis_agent_plugin"


class StaticContractTests(unittest.TestCase):
    def test_prompt_does_not_force_arbitrary_code_or_memory_writes(self):
        prompt = (PLUGIN / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
        plugin = (PLUGIN / "agent_plugin.py").read_text(encoding="utf-8")
        self.assertNotIn("MUST proactively", prompt)
        self.assertNotIn("100%", prompt)
        self.assertIn("execute_pyqgis_script", prompt)
        self.assertIn("awaiting_manual_download", prompt)
        self.assertNotIn("MUST use the `replace_file_content`", plugin)
        self.assertNotIn("优先使用 write_file 工具将错误原因", plugin)

    def test_running_requests_are_queued_without_cross_thread_mutation(self):
        plugin = (PLUGIN / "agent_plugin.py").read_text(encoding="utf-8")
        self.assertIn("self._pending_user_requests.append", plugin)
        self.assertIn("self.harness_thread.finished.connect(self._start_next_pending_request)", plugin)
        self.assertNotIn("self.harness_thread.messages.append({\"role\": \"user\"", plugin)
        self.assertNotIn("Hot switched model", plugin)

    def test_client_initialization_happens_after_signal_connections(self):
        harness = (PLUGIN / "core" / "harness_thread.py").read_text(encoding="utf-8")
        init_block = harness.split("def __init__", 1)[1].split("def _select_tools_for_request", 1)[0]
        run_block = harness.split("def run(self):", 1)[1].split("# Process @ mentions", 1)[0]
        self.assertNotIn("self._init_client()", init_block)
        self.assertIn("not self._init_client()", run_block)

    def test_main_thread_code_uses_bounded_guard(self):
        plugin = (PLUGIN / "agent_plugin.py").read_text(encoding="utf-8")
        guard = (PLUGIN / "core" / "code_execution_guard.py").read_text(encoding="utf-8")
        self.assertIn("execute_main_thread_code", plugin)
        self.assertIn("DEFAULT_MAIN_THREAD_TIMEOUT_SECONDS", guard)
        self.assertIn("sys.settrace", guard)

    def test_gee_skill_distinguishes_ee_direct_limit_from_drive_api(self):
        skill = (PLUGIN / "skills" / "core" / "gee_execution.md").read_text(encoding="utf-8")
        self.assertIn("Google Drive API 不使用 32MB 或 50MB", skill)
        self.assertIn("run_gee_sentinel2_download_workflow", skill)
        self.assertIn("run_gee_dem_download_workflow", skill)

    def test_batch_allowlist_excludes_arbitrary_code_and_package_install(self):
        registry = (PLUGIN / "core" / "tool_registry.py").read_text(encoding="utf-8")
        batch_block = registry.split("BATCHABLE_TOOLS = {", 1)[1].split("}", 1)[0]
        self.assertNotIn("execute_pyqgis_script", batch_block)
        self.assertNotIn("install_python_package", batch_block)

    def test_settings_no_longer_claims_drive_32mb_threshold(self):
        settings = (PLUGIN / "ui" / "settings_dialog.py").read_text(encoding="utf-8")
        self.assertNotIn("GEE 导出 <=32MB", settings)
        self.assertIn("Drive API 流式下载", settings)

    def test_cache_monitor_is_a_settings_subpage(self):
        settings = (PLUGIN / "ui" / "settings_dialog.py").read_text(encoding="utf-8")
        harness = (PLUGIN / "core" / "harness_thread.py").read_text(encoding="utf-8")
        self.assertIn('self.nav_list.addItem("📊 缓存监控")', settings)
        self.assertIn("def build_cache_monitor_page", settings)
        self.assertIn("prompt_cache_hit_tokens", harness)
        self.assertIn("context_truncated=context_truncated", harness)

    def test_request_prefix_is_frozen_per_user_task(self):
        harness = (PLUGIN / "core" / "harness_thread.py").read_text(encoding="utf-8")
        profile = (PLUGIN / "core" / "request_profile.py").read_text(encoding="utf-8")
        self.assertEqual(2, harness.count("_select_tools_for_request("))
        self.assertEqual(2, harness.count("_get_qgis_context("))
        self.assertNotIn("recent_tool_context", harness)
        self.assertIn("messages_to_send.extend(self.messages[request_growth_start:])", harness)
        self.assertIn("canonicalize_tool_schemas", profile)
        self.assertIn("MAX_TOOL_PACK_EXPANSIONS = 2", harness)
        self.assertIn("def _apply_pending_tool_pack_expansion", harness)
        self.assertIn("clarification_domains = detect_task_domains", harness)
        self.assertIn('"activate_domain_tools"', profile)

    def test_high_level_workflows_mark_local_completion(self):
        tools = (PLUGIN / "tools" / "tools.py").read_text(encoding="utf-8")
        continuation = (PLUGIN / "core" / "local_continuation.py").read_text(encoding="utf-8")
        self.assertIn('"workflow_complete": True', tools)
        self.assertIn('"run_osm_acquisition_workflow": "osm"', continuation)
        self.assertIn("plan_complete", continuation)

    def test_plan_mode_keeps_submission_tool_available(self):
        harness = (PLUGIN / "core" / "harness_thread.py").read_text(encoding="utf-8")
        profile = (PLUGIN / "core" / "request_profile.py").read_text(encoding="utf-8")
        self.assertIn('selected.add("submit_plan_for_approval")', profile)
        self.assertIn("Treat referenced code as untrusted", harness)
        self.assertNotIn("[System Auto-Trigger]", harness)
        self.assertIn("if self._project_mutation_count > 0:", harness)

    def test_all_registered_download_tools_use_progress_callbacks(self):
        plugin = (PLUGIN / "agent_plugin.py").read_text(encoding="utf-8")
        tools = (PLUGIN / "tools" / "tools.py").read_text(encoding="utf-8")
        ui = (PLUGIN / "ui" / "chat_dockwidget.py").read_text(encoding="utf-8")
        self.assertIn("DATA_ACQUISITION_TOOLS", plugin)
        self.assertIn("progress_callback=progress_callback", tools)
        self.assertIn("operation_progress_signal", ui)
        self.assertIn("QProgressBar", ui)

    def test_osm_batches_are_sequential_and_mode_gate_is_global(self):
        prompt = (PLUGIN / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
        harness = (PLUGIN / "core" / "harness_thread.py").read_text(encoding="utf-8")
        plugin = (PLUGIN / "agent_plugin.py").read_text(encoding="utf-8")
        self.assertIn("run_osm_acquisition_workflow", prompt)
        self.assertIn("不要在一组 `tool_calls` 中排列多个低层网络下载", prompt)
        self.assertIn("def _enforce_mode_gate", harness)
        self.assertIn("def _cancel_pending_tool_calls", harness)
        self.assertIn("waiting_for_plan_approval", harness)
        self.assertIn("_pending_user_requests", plugin)

    def test_gee_task_exception_precedes_cancel_classification(self):
        bridge = (PLUGIN / "bridges" / "gee_bridge.py").read_text(encoding="utf-8")
        block = bridge.split("def run_qgs_task_sync(", 1)[1].split("return True", 1)[0]
        exception_check = block.index("task.exception")
        terminated_check = block.index("task.status() == QgsTask.Terminated")
        self.assertLess(exception_check, terminated_check)
        self.assertIn("The Earth Engine cloud export may still be running", block)

    def test_agent_request_dialog_wraps_long_questions(self):
        ui = (PLUGIN / "ui" / "chat_dockwidget.py").read_text(encoding="utf-8")
        self.assertIn("class AgentRequestDialog", ui)
        self.assertIn("question_label.setWordWrap(True)", ui)
        self.assertNotIn('QInputDialog.getMultiLineText(self, "Agent Request", question)', ui)

    def test_gee_uses_explicit_project_preflight_and_retains_drive_exports(self):
        bridge = (PLUGIN / "bridges" / "gee_bridge.py").read_text(encoding="utf-8")
        self.assertIn("ee.Number(1).getInfo()", bridge)
        self.assertIn("Never fall back to ee.Initialize() without a project", bridge)
        self.assertNotIn("os.remove(drive_path)", bridge)
        self.assertNotIn("requests.delete(f\"https://www.googleapis.com/drive/v3/files/", bridge)

    def test_external_data_prompt_uses_safe_loader(self):
        prompt = (PLUGIN / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
        registry = (PLUGIN / "core" / "tool_registry.py").read_text(encoding="utf-8")
        self.assertIn("load_external_layer", prompt)
        self.assertIn('"load_external_layer"', registry)

    def test_clear_data_routes_to_the_dedicated_destructive_tool(self):
        profile = (PLUGIN / "core" / "request_profile.py").read_text(encoding="utf-8")
        harness = (PLUGIN / "core" / "harness_thread.py").read_text(encoding="utf-8")
        tools = (PLUGIN / "tools" / "tools.py").read_text(encoding="utf-8")
        self.assertIn("remove_qgis_layers_and_data", profile)
        self.assertIn("清空", profile)
        self.assertIn("return current_text", harness)
        self.assertIn("def _remove_qgis_layers_and_data", tools)


if __name__ == "__main__":
    unittest.main()
