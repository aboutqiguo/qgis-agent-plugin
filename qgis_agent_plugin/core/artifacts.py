import json
import os
import re
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional


ARTIFACT_SCHEMA_VERSION = "2.0"


def _slugify(text: str, fallback: str = "task") -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text or "").strip("_").lower()
    return text[:40] or fallback


class AgentRunArtifacts:
    def __init__(self, project_home: str, user_request: str = "", started_at: Optional[datetime] = None):
        self.project_home = os.path.abspath(project_home)
        self.user_request = user_request or ""
        self.started_at = started_at or datetime.now()
        timestamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        slug = _slugify(self.user_request)
        self.run_dir = os.path.join(self.project_home, ".qgis_agent_runs", f"{timestamp}_{slug}")
        os.makedirs(self.run_dir, exist_ok=True)
        self._manifest: Dict[str, Any] = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "project_home": self.project_home,
            "user_request": self.user_request,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "run_dir": self.run_dir,
            "artifacts": [],
        }
        self._write_manifest()
        self.write_json(
            "run.json",
            {
                "started_at": self.started_at.isoformat(timespec="seconds"),
                "user_request": self.user_request,
                "run_dir": self.run_dir,
            },
            artifact_type="metadata",
            role="run_metadata",
            description="Run metadata for this QGIS Agent task.",
        )

    @classmethod
    def create(cls, project_home: str, user_request: str = "") -> "AgentRunArtifacts":
        return cls(project_home=project_home, user_request=user_request)

    def path(self, relative_path: str) -> str:
        return os.path.join(self.run_dir, relative_path)

    def write_text(
        self,
        relative_path: str,
        content: str,
        artifact_type: str = "text",
        role: str = "",
        description: str = "",
        source: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        file_path = self.path(relative_path)
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(content or "")
        self.register_artifact(relative_path, artifact_type, role, description, source, metadata)
        return file_path

    def write_json(
        self,
        relative_path: str,
        payload: Dict[str, Any],
        artifact_type: str = "json",
        role: str = "",
        description: str = "",
        source: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        return self.write_text(
            relative_path,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            artifact_type=artifact_type,
            role=role,
            description=description,
            source=source,
            metadata=metadata,
        )

    def append_jsonl(
        self,
        relative_path: str,
        payload: Dict[str, Any],
        artifact_type: str = "jsonl",
        role: str = "",
        description: str = "",
    ) -> str:
        file_path = self.path(relative_path)
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(file_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        self.register_artifact(relative_path, artifact_type, role, description)
        return file_path

    def write_plan(self, plan_markdown: str) -> str:
        self.write_json(
            "plan.json",
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "user_request": self.user_request,
                "plan_markdown": plan_markdown,
            },
            artifact_type="json",
            role="plan_metadata",
            description="Planner approval payload.",
        )
        return self.write_text("task.md", plan_markdown, artifact_type="markdown", role="task_plan", description="Human-readable task plan.")

    def write_task_plan(self, plan_payload: Dict[str, Any]) -> str:
        return self.write_json("task_plan.json", plan_payload, role="planner_state", description="Structured Planner/Verifier state.")

    def append_step_event(self, payload: Dict[str, Any]) -> str:
        event = dict(payload or {})
        event.setdefault("time", datetime.now().isoformat(timespec="seconds"))
        self.append_event("planner_step", event)
        return self.append_jsonl("steps.jsonl", event, role="planner_events", description="Planner/Verifier step event stream.")

    def read_step_events(self):
        return self._read_jsonl("steps.jsonl")

    def _read_jsonl(self, relative_path: str) -> List[Dict[str, Any]]:
        file_path = self.path(relative_path)
        if not os.path.exists(file_path):
            return []
        events = []
        with open(file_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    events.append({"event": "unparseable", "raw": line})
        return events

    def append_tool_call(self, tool_name: str, arguments: Dict[str, Any], result: Any) -> str:
        path = self.append_jsonl(
            "tool_calls.jsonl",
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "tool": tool_name,
                "arguments": arguments or {},
                "result": result,
            },
            role="tool_calls",
            description="Tool call event stream.",
        )
        self.append_event("tool_call", {"tool": tool_name, "arguments": arguments or {}})
        return path

    def copy_file(self, source_path: str, relative_path: str) -> str:
        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError(source_path)
        file_path = self.path(relative_path)
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy2(source_path, file_path)
        self.register_artifact(relative_path, _infer_artifact_type(relative_path), "copied_file", f"Copied from {source_path}.")
        return file_path

    def write_result(self, ok: bool, summary: str, data: Optional[Dict[str, Any]] = None) -> str:
        return self.write_json(
            "result.json",
            {
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "ok": ok,
                "summary": summary,
                "data": data or {},
            },
            role="run_result",
            description="Final structured run result.",
        )

    def write_layer_report(self, report_markdown: str) -> str:
        return self.write_text("layer_report.md", report_markdown, artifact_type="markdown", role="layer_report", description="Layer inspection report.")

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> str:
        event = dict(payload or {})
        event.setdefault("time", datetime.now().isoformat(timespec="seconds"))
        event.setdefault("event", event_type)
        return self.append_jsonl("events.jsonl", event, role="run_events", description="Artifact 2.0 run event stream.")

    def register_artifact(
        self,
        relative_path: str,
        artifact_type: str = "",
        role: str = "",
        description: str = "",
        source: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        relative_path = _normalize_relative_path(relative_path)
        if not relative_path:
            raise ValueError("relative_path is required.")

        file_path = self.path(relative_path)
        now = datetime.now().isoformat(timespec="seconds")
        entry = {
            "id": _slugify(relative_path, "artifact"),
            "path": relative_path,
            "type": artifact_type or _infer_artifact_type(relative_path),
            "role": role or "artifact",
            "description": description,
            "source": source or {},
            "metadata": metadata or {},
            "exists": os.path.exists(file_path),
            "size_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            "updated_at": now,
        }

        artifacts = [item for item in self._manifest.get("artifacts", []) if item.get("path") != relative_path]
        existing = next((item for item in self._manifest.get("artifacts", []) if item.get("path") == relative_path), {})
        if existing.get("created_at"):
            entry["created_at"] = existing["created_at"]
        else:
            entry["created_at"] = now
        artifacts.append(entry)
        artifacts.sort(key=lambda item: item.get("path", ""))
        self._manifest["artifacts"] = artifacts
        self._manifest["updated_at"] = now
        self._write_manifest()
        return entry

    def manifest(self) -> Dict[str, Any]:
        return dict(self._manifest)

    def write_data_source_search(self, search_payload: Dict[str, Any]) -> Dict[str, str]:
        from .data_sources import format_search_results_markdown

        json_path = self.write_json(
            "data_sources/latest_search.json",
            search_payload,
            role="data_source_search",
            description="Latest data source handbook search result.",
        )
        markdown_path = self.write_text(
            "data_sources/latest_search.md",
            format_search_results_markdown(search_payload),
            artifact_type="markdown",
            role="data_source_search_report",
            description="Human-readable data source handbook search result.",
        )
        return {"json": json_path, "markdown": markdown_path}

    def write_data_acquisition_plan(self, plan_payload: Dict[str, Any]) -> Dict[str, str]:
        json_path = self.write_json(
            "data_sources/acquisition_plan.json",
            plan_payload,
            role="data_acquisition_plan",
            description="Structured data acquisition plan.",
        )
        markdown_path = self.write_text(
            "data_sources/acquisition_plan.md",
            plan_payload.get("markdown", ""),
            artifact_type="markdown",
            role="data_acquisition_plan_report",
            description="Human-readable data acquisition plan.",
        )
        return {"json": json_path, "markdown": markdown_path}

    def write_tool_result_artifacts(self, tool_name: str, result: Any) -> Dict[str, Any]:
        payload = _parse_tool_result(result)
        data = payload.get("data") if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            return {}

        try:
            if tool_name == "search_data_sources" and isinstance(data.get("search"), dict):
                paths = self.write_data_source_search(data["search"])
                return {"type": "data_source_search", "paths": paths}
            if tool_name == "create_data_acquisition_plan" and isinstance(data.get("acquisition_plan"), dict):
                paths = self.write_data_acquisition_plan(data["acquisition_plan"])
                return {"type": "data_acquisition_plan", "paths": paths}
        except Exception as exc:
            self.append_event("artifact_write_warning", {"tool": tool_name, "message": str(exc)})
        return {}

    def write_tool_registry_artifacts(self) -> Dict[str, str]:
        from .tool_registry import build_registry_payload, export_registry_markdown

        payload = build_registry_payload()
        json_path = self.write_json(
            "security/tool_registry.json",
            payload,
            role="security_tool_registry",
            description="Tool registry 2.0 structured export.",
        )
        markdown_path = self.write_text(
            "security/tool_registry.md",
            export_registry_markdown(),
            artifact_type="markdown",
            role="security_tool_registry_report",
            description="Human-readable tool registry 2.0 export.",
        )
        health_path = self.write_json(
            "security/tool_registry_health.json",
            payload.get("health", {}),
            role="security_tool_registry_health",
            description="Tool registry health check result.",
        )
        self.write_security_risk_report()
        return {"json": json_path, "markdown": markdown_path, "health": health_path}

    def append_approval_decision(self, payload: Dict[str, Any]) -> str:
        event = dict(payload or {})
        event.setdefault("time", datetime.now().isoformat(timespec="seconds"))
        path = self.append_jsonl(
            "security/approval_decisions.jsonl",
            event,
            role="security_approval_log",
            description="High-risk tool approval decisions.",
        )
        self.append_event("security_approval_decision", event)
        self.write_security_risk_report()
        return path

    def write_security_risk_report(self) -> str:
        approvals = self._read_jsonl("security/approval_decisions.jsonl")
        registry_health = {}
        registry_health_path = self.path("security/tool_registry_health.json")
        if os.path.exists(registry_health_path):
            try:
                with open(registry_health_path, "r", encoding="utf-8") as handle:
                    registry_health = json.load(handle)
            except Exception:
                registry_health = {}

        total = len(approvals)
        required = [item for item in approvals if item.get("requires_approval")]
        approved = [item for item in approvals if item.get("user_approved") is True]
        denied = [item for item in approvals if item.get("user_approved") is False]

        lines = [
            "# Security Risk Report",
            "",
            "## Tool Registry Health",
            "",
            f"- Status: {'OK' if registry_health.get('ok', True) else 'Needs attention'}",
            f"- Tool count: {registry_health.get('tool_count', '-')}",
            f"- Errors: {registry_health.get('error_count', 0)}",
            f"- Warnings: {registry_health.get('warning_count', 0)}",
            "",
            "## Approval Summary",
            "",
            f"- Decisions logged: {total}",
            f"- Required approval: {len(required)}",
            f"- Approved: {len(approved)}",
            f"- Denied: {len(denied)}",
            "",
            "| Time | Tool | Risk | Required | Approved | Reason |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item in approvals:
            reason = str(item.get("reason", "")).replace("|", "\\|")
            approved_value = item.get("user_approved")
            if approved_value is None:
                approved_text = "-"
            else:
                approved_text = "yes" if approved_value else "no"
            lines.append(
                f"| {item.get('time', '')} | `{item.get('tool', '')}` | {item.get('risk_level', '')} | "
                f"{item.get('requires_approval', False)} | {approved_text} | {reason} |"
            )

        issues = registry_health.get("issues") or []
        if issues:
            lines.extend(["", "## Registry Issues", ""])
            for issue in issues:
                lines.append(f"- [{issue.get('level')}] `{issue.get('tool')}`: {issue.get('message')}")

        return self.write_text(
            "security/risk_report.md",
            "\n".join(lines) + "\n",
            artifact_type="markdown",
            role="security_risk_report",
            description="Security approvals and tool registry risk summary.",
        )

    def write_final_report(
        self,
        summary: str,
        ok: bool = True,
        layer_report_path: str = "",
        snapshot_path: str = "",
    ) -> str:
        outcome_markdown, has_attention_signal = self._build_outcome_signal_markdown(summary or "")
        token_summary = self.write_token_usage_summary()
        status = "OK" if ok and not has_attention_signal else "Needs attention"
        lines = [
            "# QGIS Agent Run Report",
            "",
            f"- Status: {status}",
            f"- Started at: {self.started_at.isoformat(timespec='seconds')}",
            f"- Finished at: {datetime.now().isoformat(timespec='seconds')}",
            f"- Run directory: `{self.run_dir}`",
            "",
            "## User Request",
            "",
            self.user_request or "(empty)",
            "",
            "## Summary",
            "",
            summary or "(no summary)",
            "",
            "## Task Outcome Signals",
            "",
            outcome_markdown,
            "",
            "## Planner / Verifier Steps",
            "",
            self._build_step_summary_markdown(),
            "",
            "## Token Usage",
            "",
            self._build_token_usage_summary_markdown(token_summary),
            "",
            "## Data Sources",
            "",
            self._build_data_source_summary_markdown(),
            "",
            "## Security",
            "",
            self._build_security_summary_markdown(),
            "",
            "## Artifacts",
            "",
            "- Manifest: `manifest.json`",
            "- Index: `index.md`",
            "- Events: `events.jsonl`",
            "- Plan: `task.md`",
            "- Structured plan: `plan.json`",
            "- Planner state: `task_plan.json`",
            "- Step events: `steps.jsonl`",
            "- Tool calls: `tool_calls.jsonl`",
            "- Token summary: `token_summary.md`",
            "- Result: `result.json`",
        ]
        if layer_report_path:
            lines.append(f"- Layer report: `{os.path.basename(layer_report_path)}`")
        if snapshot_path:
            lines.append(f"- Map snapshot: `{os.path.basename(snapshot_path)}`")
        return self.write_text("report.md", "\n".join(lines) + "\n", artifact_type="markdown", role="final_report", description="Final run report.")

    def write_token_usage_summary(self) -> Dict[str, Any]:
        summary = self._build_token_usage_summary()
        self.write_json(
            "token_summary.json",
            summary,
            artifact_type="json",
            role="token_summary",
            description="Token usage summary for the current plugin log window.",
        )
        self.write_text(
            "token_summary.md",
            self._build_token_usage_summary_markdown(summary),
            artifact_type="markdown",
            role="token_summary_report",
            description="Human-readable token usage summary.",
        )
        return summary

    def _build_token_usage_summary(self) -> Dict[str, Any]:
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        token_log = os.path.join(plugin_root, "utils", "token_usage.jsonl")
        rows = []
        if os.path.exists(token_log):
            try:
                with open(token_log, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            payload = json.loads(line)
                        except Exception:
                            continue
                        ts = str(payload.get("time") or payload.get("timestamp") or "")
                        if ts and ts < self.started_at.isoformat(timespec="seconds"):
                            continue
                        rows.append(payload)
            except Exception as exc:
                return {
                    "ok": False,
                    "message": f"Could not read token usage log: {exc}",
                    "log_path": token_log,
                    "request_count": 0,
                }

        prompt_total = 0
        completion_total = 0
        total = 0
        peak_total = 0
        model_counts: Dict[str, int] = {}
        for row in rows:
            usage = row.get("usage") if isinstance(row.get("usage"), dict) else row
            prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            row_total = int(usage.get("total_tokens") or (prompt + completion))
            prompt_total += prompt
            completion_total += completion
            total += row_total
            peak_total = max(peak_total, row_total)
            model = str(row.get("model") or usage.get("model") or "unknown")
            model_counts[model] = model_counts.get(model, 0) + 1

        request_count = len(rows)
        return {
            "ok": True,
            "message": "Token usage summary generated." if request_count else "No token usage rows found for this run.",
            "log_path": token_log,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "request_count": request_count,
            "prompt_tokens": prompt_total,
            "completion_tokens": completion_total,
            "total_tokens": total,
            "average_tokens_per_request": round(total / request_count, 2) if request_count else 0,
            "peak_tokens_single_request": peak_total,
            "prompt_token_share": round(prompt_total / total, 4) if total else 0,
            "models": model_counts,
        }

    def _build_token_usage_summary_markdown(self, summary: Dict[str, Any]) -> str:
        if not summary or not summary.get("ok"):
            return (summary or {}).get("message", "Token usage summary unavailable.")
        lines = [
            f"- Requests: {summary.get('request_count', 0)}",
            f"- Total tokens: {summary.get('total_tokens', 0)}",
            f"- Prompt tokens: {summary.get('prompt_tokens', 0)}",
            f"- Completion tokens: {summary.get('completion_tokens', 0)}",
            f"- Average/request: {summary.get('average_tokens_per_request', 0)}",
            f"- Peak request: {summary.get('peak_tokens_single_request', 0)}",
            f"- Prompt share: {summary.get('prompt_token_share', 0)}",
        ]
        models = summary.get("models") or {}
        if models:
            lines.extend(["", "| Model | Requests |", "| --- | --- |"])
            for model, count in sorted(models.items()):
                lines.append(f"| `{model}` | {count} |")
        return "\n".join(lines)

    def _build_outcome_signal_markdown(self, summary: str) -> tuple:
        text = summary or ""
        lowered = text.lower()
        attention_terms = [
            "失败",
            "跳过",
            "skipped",
            "failed",
            "partial",
            "部分成功",
            "bad request",
            "overpass",
            "0 features",
            "空结果",
        ]
        has_attention = any(term in lowered for term in attention_terms) or any(term in text for term in attention_terms)

        rows = []
        osm_terms = ("OSM", "OpenStreetMap", "道路", "建筑", "Overpass")
        if any(term in text for term in osm_terms):
            osm_status = "success"
            osm_note = "Summary mentions OSM/OpenStreetMap outputs."
            if any(term in text for term in ("失败", "跳过", "部分成功", "空结果")) or any(
                term in lowered for term in ("failed", "skipped", "partial", "bad request", "overpass")
            ):
                osm_status = "partial_success_or_skipped"
                osm_note = "OSM-related text includes failure, skipped, partial, or Overpass signals; verify logs/artifacts before treating it as complete."
            rows.append(("OSM / OpenStreetMap", osm_status, osm_note))

        if not rows:
            if has_attention:
                return (
                    "Attention terms were found in the final summary. Review the summary and tool logs before treating the run as fully complete.",
                    True,
                )
            return ("No explicit failure, skip, or partial-success signals detected in the final summary.", False)

        lines = [
            "| Area | Status Signal | Note |",
            "| --- | --- | --- |",
        ]
        for area, status, note in rows:
            safe_note = note.replace("|", "\\|")
            lines.append(f"| {area} | {status} | {safe_note} |")
        return "\n".join(lines), has_attention

    def _build_step_summary_markdown(self) -> str:
        events = self.read_step_events()
        if not events:
            return "No planner/verifier step events recorded."

        verified = [event for event in events if event.get("event") == "step_verified"]
        if not verified:
            started = [event for event in events if event.get("event") == "step_started"]
            if not started:
                return "No verified steps recorded yet."
            return f"{len(started)} step(s) started; no verifier result recorded yet."

        lines = [
            "| Step | Status | Score | Retry | Failure Type | Message | Failed Checks |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for event in verified:
            verification = event.get("verification") or {}
            failed_checks = [
                str(check.get("name", "check"))
                for check in verification.get("checks", [])
                if not check.get("ok")
            ]
            message = str(verification.get("message", "")).replace("|", "\\|")
            failed = ", ".join(failed_checks) if failed_checks else "-"
            retry = "yes" if verification.get("retry_recommended") else "no"
            lines.append(
                f"| {verification.get('step_id', '')} | {verification.get('status', '')} | "
                f"{verification.get('quality_score', '')} | {retry} | "
                f"{verification.get('failure_type', '') or '-'} | "
                f"{message} | {failed} |"
            )
        return "\n".join(lines)

    def _build_security_summary_markdown(self) -> str:
        security_artifacts = [
            item for item in self._manifest.get("artifacts", [])
            if str(item.get("role", "")).startswith("security_")
        ]
        if not security_artifacts:
            return "No security artifacts recorded."

        approvals = self._read_jsonl("security/approval_decisions.jsonl")
        lines = [
            f"- Security artifacts: {len(security_artifacts)}",
            f"- Approval decisions: {len(approvals)}",
            "",
            "| Artifact | Role | Description |",
            "| --- | --- | --- |",
        ]
        for item in security_artifacts:
            description = str(item.get("description", "")).replace("|", "\\|")
            lines.append(f"| `{item.get('path', '')}` | {item.get('role', '')} | {description} |")
        return "\n".join(lines)

    def _build_data_source_summary_markdown(self) -> str:
        artifacts = self._manifest.get("artifacts", [])
        data_artifacts = [
            item for item in artifacts
            if str(item.get("role", "")).startswith("data_")
        ]
        if not data_artifacts:
            return "No data source handbook artifacts recorded."

        lines = [
            "| Artifact | Role | Description |",
            "| --- | --- | --- |",
        ]
        for item in data_artifacts:
            description = str(item.get("description", "")).replace("|", "\\|")
            lines.append(f"| `{item.get('path', '')}` | {item.get('role', '')} | {description} |")
        return "\n".join(lines)

    def _write_manifest(self) -> None:
        self._ensure_system_artifacts()
        self._write_raw_json("manifest.json", self._manifest)
        self._write_index()

    def _write_index(self) -> None:
        lines = [
            "# QGIS Agent Artifact Index",
            "",
            f"- Schema: {ARTIFACT_SCHEMA_VERSION}",
            f"- Run directory: `{self.run_dir}`",
            f"- User request: {self.user_request or '(empty)'}",
            "",
            "| Path | Role | Type | Size | Description |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in self._manifest.get("artifacts", []):
            description = str(item.get("description", "")).replace("|", "\\|")
            lines.append(
                f"| `{item.get('path', '')}` | {item.get('role', '')} | "
                f"{item.get('type', '')} | {item.get('size_bytes', 0)} | {description} |"
            )
        self._write_raw_text("index.md", "\n".join(lines) + "\n")

    def _ensure_system_artifacts(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        system = [
            {
                "path": "manifest.json",
                "type": "json",
                "role": "artifact_manifest",
                "description": "Artifact 2.0 manifest.",
            },
            {
                "path": "index.md",
                "type": "markdown",
                "role": "artifact_index",
                "description": "Human-readable artifact index.",
            },
        ]
        artifacts = self._manifest.setdefault("artifacts", [])
        by_path = {item.get("path"): item for item in artifacts}
        for entry in system:
            file_path = self.path(entry["path"])
            current = dict(by_path.get(entry["path"], {}))
            current.update({
                "id": _slugify(entry["path"], "artifact"),
                "path": entry["path"],
                "type": entry["type"],
                "role": entry["role"],
                "description": entry["description"],
                "source": {},
                "metadata": {},
                "exists": os.path.exists(file_path),
                "size_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                "updated_at": now,
            })
            current.setdefault("created_at", now)
            by_path[entry["path"]] = current
        self._manifest["artifacts"] = sorted(by_path.values(), key=lambda item: item.get("path", ""))

    def _write_raw_text(self, relative_path: str, content: str) -> str:
        file_path = self.path(relative_path)
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(content or "")
        return file_path

    def _write_raw_json(self, relative_path: str, payload: Dict[str, Any]) -> str:
        return self._write_raw_text(relative_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _normalize_relative_path(relative_path: str) -> str:
    value = (relative_path or "").replace("\\", "/").strip("/")
    if not value or value.startswith("../") or "/../" in value:
        raise ValueError(f"Unsafe artifact path: {relative_path}")
    return value


def _infer_artifact_type(relative_path: str) -> str:
    ext = os.path.splitext(relative_path or "")[1].lower()
    if ext == ".md":
        return "markdown"
    if ext == ".json":
        return "json"
    if ext == ".jsonl":
        return "jsonl"
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return "image"
    if ext in {".gpkg", ".geojson", ".shp"}:
        return "geodata"
    return "file"


def _parse_tool_result(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            payload = json.loads(result)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return {}
