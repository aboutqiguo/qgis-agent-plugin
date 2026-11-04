"""Privacy-preserving LLM prompt-cache telemetry and aggregation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional


CACHE_METRICS_SCHEMA_VERSION = "1.0"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_BYTES = 10 * 1024 * 1024

# DeepSeek standard pricing in CNY per million tokens. These are estimates only;
# the provider's billing page remains authoritative.
DEEPSEEK_STANDARD_PRICING = {
    "currency": "CNY",
    "unit_tokens": 1_000_000,
    "cache_hit_input": 0.02,
    "cache_miss_input": 1.00,
    "output": 2.00,
    "label": "DeepSeek standard estimate",
}

_APPEND_LOCK = threading.Lock()
_LAST_MAINTENANCE: Dict[str, datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(exclude_none=True)
            return dumped if isinstance(dumped, dict) else {}
        except TypeError:
            dumped = model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except (AttributeError, ValueError, RuntimeError):
            pass
    try:
        return dict(vars(value))
    except TypeError:
        return {}


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def extract_usage(response: Any) -> Dict[str, Any]:
    """Extract standard and provider-specific usage fields without inventing zeros."""
    usage_obj = getattr(response, "usage", None)
    if usage_obj is None and isinstance(response, dict):
        usage_obj = response.get("usage")
    raw = _as_dict(usage_obj)

    prompt = _optional_int(raw.get("prompt_tokens", raw.get("input_tokens")))
    completion = _optional_int(raw.get("completion_tokens", raw.get("output_tokens")))
    total = _optional_int(raw.get("total_tokens"))

    hit = _optional_int(
        raw.get("prompt_cache_hit_tokens", raw.get("cache_hit_tokens"))
    )
    miss = _optional_int(
        raw.get("prompt_cache_miss_tokens", raw.get("cache_miss_tokens"))
    )

    # OpenAI-compatible providers may expose cached input under details instead.
    details = _as_dict(raw.get("prompt_tokens_details") or raw.get("input_tokens_details"))
    if hit is None:
        hit = _optional_int(details.get("cached_tokens"))
    if hit is not None and miss is None and prompt is not None:
        miss = max(0, prompt - hit)

    if prompt is None and hit is not None and miss is not None:
        prompt = hit + miss
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion

    warnings: List[str] = []
    if hit is not None and miss is not None and prompt is not None:
        if hit + miss != prompt:
            warnings.append("cache_tokens_do_not_match_prompt_tokens")

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
        "cache_fields_reported": hit is not None and miss is not None,
        "warnings": warnings,
    }


def canonical_sha256(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_structure_fingerprints(
    messages: Iterable[Dict[str, Any]],
    tools: Iterable[Dict[str, Any]],
    dynamic_context: str = "",
) -> Dict[str, str]:
    message_list = list(messages or [])
    stable_system = []
    for message in message_list:
        if message.get("role") != "system":
            continue
        if dynamic_context and message.get("content") == dynamic_context:
            continue
        stable_system.append(message)
    tool_list = list(tools or [])
    stable_prefix = {"system": stable_system, "tools": tool_list}
    return {
        "stable_system_sha256": canonical_sha256(stable_system),
        "tool_schema_sha256": canonical_sha256(tool_list),
        "stable_prefix_sha256": canonical_sha256(stable_prefix),
        "dynamic_context_sha256": canonical_sha256(dynamic_context or ""),
    }


def _cost_estimate(usage: Dict[str, Any]) -> Dict[str, Any]:
    prompt = _optional_int(usage.get("prompt_tokens")) or 0
    completion = _optional_int(usage.get("completion_tokens")) or 0
    hit = _optional_int(usage.get("prompt_cache_hit_tokens"))
    miss = _optional_int(usage.get("prompt_cache_miss_tokens"))
    unit = float(DEEPSEEK_STANDARD_PRICING["unit_tokens"])
    output_cost = completion * DEEPSEEK_STANDARD_PRICING["output"] / unit
    no_cache = prompt * DEEPSEEK_STANDARD_PRICING["cache_miss_input"] / unit + output_cost
    if hit is None or miss is None:
        actual = no_cache
        cache_known = False
    else:
        actual = (
            hit * DEEPSEEK_STANDARD_PRICING["cache_hit_input"] / unit
            + miss * DEEPSEEK_STANDARD_PRICING["cache_miss_input"] / unit
            + output_cost
        )
        cache_known = True
    return {
        "currency": DEEPSEEK_STANDARD_PRICING["currency"],
        "pricing_label": DEEPSEEK_STANDARD_PRICING["label"],
        "cache_known": cache_known,
        "estimated_actual": round(actual, 8),
        "estimated_without_cache": round(no_cache, 8),
        "estimated_savings": round(max(0.0, no_cache - actual), 8),
    }


def build_metrics_record(
    response: Any,
    model: str,
    messages: Iterable[Dict[str, Any]],
    tools: Iterable[Dict[str, Any]],
    *,
    dynamic_context: str = "",
    context_truncated: bool = False,
    tool_round: Optional[int] = None,
    run_id: str = "",
    project_home: str = "",
    char_metrics: Optional[Dict[str, int]] = None,
    usage_fallback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    message_list = list(messages or [])
    tool_list = list(tools or [])
    usage = extract_usage(response)
    if usage_fallback:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if usage.get(key) is None:
                usage[key] = _optional_int(usage_fallback.get(key))
        usage["estimated"] = bool(usage_fallback.get("estimated", False))
    else:
        usage["estimated"] = False

    hit = usage.get("prompt_cache_hit_tokens")
    miss = usage.get("prompt_cache_miss_tokens")
    cache_total = (hit or 0) + (miss or 0)
    usage["cache_hit_rate"] = round((hit or 0) / cache_total, 6) if cache_total else None

    response_id = getattr(response, "id", None)
    if response_id is None and isinstance(response, dict):
        response_id = response.get("id")

    return {
        "schema_version": CACHE_METRICS_SCHEMA_VERSION,
        "time": _now().isoformat(timespec="seconds"),
        "request_id": str(response_id or ""),
        "run_id": canonical_sha256(run_id)[:16] if run_id else "",
        "project_home": str(project_home or ""),
        "project_name": os.path.basename(project_home) if project_home else "未命名项目",
        "model": model or "unknown",
        "usage": usage,
        "cost_estimate": _cost_estimate(usage),
        "structure": {
            **build_structure_fingerprints(message_list, tool_list, dynamic_context),
            "message_count": len(message_list),
            "active_tool_count": len(tool_list),
            "context_truncated": bool(context_truncated),
            "tool_round": int(tool_round) if tool_round is not None else None,
            **(char_metrics or {}),
        },
    }


def default_telemetry_dir() -> str:
    override = os.environ.get("QGIS_AGENT_TELEMETRY_DIR", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    try:
        from qgis.core import QgsApplication

        base = QgsApplication.qgisSettingsDirPath()
        if isinstance(base, str) and base.strip() and "MagicMock" not in base and not base.startswith("<"):
            return os.path.join(base.strip(), "qgis_agent", "telemetry")
    except (ImportError, AttributeError, TypeError, RuntimeError):
        pass
    return os.path.join(tempfile.gettempdir(), "qgis_agent", "telemetry")


def default_telemetry_path() -> str:
    return os.path.join(default_telemetry_dir(), "cache_usage.jsonl")


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone()
    except (TypeError, ValueError):
        return None


def load_records(
    path: Optional[str] = None,
    days: Optional[float] = None,
    project_home: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if project_home:
        proj_log = os.path.join(project_home, ".qgis_agent_runs", "cache_usage.jsonl")
        if os.path.exists(proj_log):
            log_path = proj_log
        else:
            log_path = path or default_telemetry_path()
    else:
        log_path = path or default_telemetry_path()

    if not os.path.exists(log_path):
        return []
    cutoff = _now() - timedelta(days=float(days)) if days is not None else None
    records = []
    norm_proj = os.path.normcase(os.path.abspath(project_home)) if project_home else None
    try:
        with open(log_path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                if norm_proj:
                    rec_proj = record.get("project_home")
                    if rec_proj:
                        if os.path.normcase(os.path.abspath(rec_proj)) != norm_proj:
                            continue
                    elif log_path != os.path.join(project_home, ".qgis_agent_runs", "cache_usage.jsonl"):
                        continue
                when = _parse_time(record.get("time"))
                if cutoff is not None and (when is None or when < cutoff):
                    continue
                records.append(record)
    except OSError:
        return []
    return records


def _compact_records(records: List[Dict[str, Any]], max_bytes: int) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    size = 0
    target = max(1024, int(max_bytes * 0.85))
    for record in reversed(records):
        row_size = len(json.dumps(record, ensure_ascii=False, default=str).encode("utf-8")) + 1
        if kept and size + row_size > target:
            break
        kept.append(record)
        size += row_size
    kept.reverse()
    return kept


def _maintain_log(path: str, retention_days: int, max_bytes: int) -> None:
    records = load_records(path=path, days=retention_days)
    records = _compact_records(records, max_bytes=max_bytes)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    os.replace(temp_path, path)


def append_record(
    record: Dict[str, Any],
    path: Optional[str] = None,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    log_path = path or default_telemetry_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    now = _now()
    with _APPEND_LOCK:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        
        # Dual-write to project workspace runs directory if available
        project_home = record.get("project_home")
        if project_home and os.path.exists(project_home):
            proj_dir = os.path.join(project_home, ".qgis_agent_runs")
            os.makedirs(proj_dir, exist_ok=True)
            proj_log = os.path.join(proj_dir, "cache_usage.jsonl")
            try:
                with open(proj_log, "a", encoding="utf-8") as proj_handle:
                    proj_handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            except OSError:
                pass

        last = _LAST_MAINTENANCE.get(log_path)
        oversized = os.path.getsize(log_path) > max_bytes
        if oversized or last is None or now - last >= timedelta(days=1):
            _maintain_log(log_path, retention_days, max_bytes)
            _LAST_MAINTENANCE[log_path] = now
    return log_path


def summarize_records(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(records or [])
    prompt = completion = total = hit = miss = 0
    known = estimated = truncated = 0
    actual_cost = no_cache_cost = savings = 0.0
    models: Dict[str, int] = {}
    warning_count = 0
    tool_hash_changes = stable_prefix_changes = dynamic_context_changes = 0
    previous_tool = previous_prefix = previous_dynamic = None

    for row in rows:
        usage = row.get("usage") if isinstance(row.get("usage"), dict) else row
        row_prompt = _optional_int(usage.get("prompt_tokens")) or 0
        row_completion = _optional_int(usage.get("completion_tokens")) or 0
        prompt += row_prompt
        completion += row_completion
        total += _optional_int(usage.get("total_tokens")) or row_prompt + row_completion
        row_hit = _optional_int(usage.get("prompt_cache_hit_tokens"))
        row_miss = _optional_int(usage.get("prompt_cache_miss_tokens"))
        if row_hit is not None and row_miss is not None:
            known += 1
            hit += row_hit
            miss += row_miss
        if usage.get("estimated"):
            estimated += 1
        warning_count += len(usage.get("warnings") or [])

        cost = row.get("cost_estimate") or _cost_estimate(usage)
        actual_cost += float(cost.get("estimated_actual") or 0)
        no_cache_cost += float(cost.get("estimated_without_cache") or 0)
        savings += float(cost.get("estimated_savings") or 0)

        model = str(row.get("model") or "unknown")
        models[model] = models.get(model, 0) + 1
        structure = row.get("structure") or {}
        if structure.get("context_truncated"):
            truncated += 1
        tool_hash = structure.get("tool_schema_sha256")
        prefix_hash = structure.get("stable_prefix_sha256")
        dynamic_hash = structure.get("dynamic_context_sha256")
        if previous_tool is not None and tool_hash and tool_hash != previous_tool:
            tool_hash_changes += 1
        if previous_prefix is not None and prefix_hash and prefix_hash != previous_prefix:
            stable_prefix_changes += 1
        if previous_dynamic is not None and dynamic_hash and dynamic_hash != previous_dynamic:
            dynamic_context_changes += 1
        previous_tool = tool_hash or previous_tool
        previous_prefix = prefix_hash or previous_prefix
        previous_dynamic = dynamic_hash or previous_dynamic

    cache_input = hit + miss
    request_count = len(rows)
    transitions = max(0, request_count - 1)
    hit_rate = hit / cache_input if cache_input else None
    return {
        "request_count": request_count,
        "cache_known_requests": known,
        "cache_coverage": round(known / request_count, 6) if request_count else 0,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
        "cache_hit_rate": round(hit_rate, 6) if hit_rate is not None else None,
        "estimated_request_count": estimated,
        "estimated_actual_cost_cny": round(actual_cost, 6),
        "estimated_without_cache_cost_cny": round(no_cache_cost, 6),
        "estimated_savings_cny": round(savings, 6),
        "estimated_savings_rate": round(savings / no_cache_cost, 6) if no_cache_cost else 0,
        "context_truncated_requests": truncated,
        "tool_schema_changes": tool_hash_changes,
        "tool_schema_change_rate": round(tool_hash_changes / transitions, 6) if transitions else 0,
        "stable_prefix_changes": stable_prefix_changes,
        "dynamic_context_changes": dynamic_context_changes,
        "usage_warning_count": warning_count,
        "models": models,
    }


def get_summary(
    days: Optional[float] = 30,
    path: Optional[str] = None,
    project_home: Optional[str] = None,
) -> Dict[str, Any]:
    records = load_records(path=path, days=days, project_home=project_home)
    summary = summarize_records(records)
    summary["days"] = days
    summary["project_home"] = project_home or ""
    if project_home:
        proj_log = os.path.join(project_home, ".qgis_agent_runs", "cache_usage.jsonl")
        summary["log_path"] = proj_log if os.path.exists(proj_log) else (path or default_telemetry_path())
    else:
        summary["log_path"] = path or default_telemetry_path()
    return summary


def diagnostic_messages(summary: Dict[str, Any]) -> List[str]:
    if not summary.get("request_count"):
        return ["暂无监控数据。完成一次 Agent 对话后刷新即可查看。"]
    messages = []
    coverage = float(summary.get("cache_coverage") or 0)
    hit_rate = summary.get("cache_hit_rate")
    if coverage < 0.8:
        messages.append("部分请求未返回缓存明细，命中率只基于可识别请求计算。")
    if hit_rate is not None and hit_rate < 0.5:
        messages.append("缓存命中率低于 50%，应优先检查系统前缀和工具集合是否频繁变化。")
    if summary.get("tool_schema_changes"):
        messages.append(
            f"相邻请求中工具结构变化 {summary['tool_schema_changes']} 次，可能削弱前缀缓存复用。"
        )
    if summary.get("stable_prefix_changes"):
        messages.append(
            f"稳定前缀变化 {summary['stable_prefix_changes']} 次，请检查系统提示词或工具定义。"
        )
    if summary.get("context_truncated_requests"):
        messages.append(
            f"发生上下文截断 {summary['context_truncated_requests']} 次，长任务的连续缓存可能中断。"
        )
    if summary.get("usage_warning_count"):
        messages.append("供应商返回的缓存 Token 与输入 Token 存在不一致，请以计费后台为准。")
    if not messages:
        messages.append("缓存遥测未发现明显结构异常。")
    return messages
