"""Permission mode constants and transitions aligned with deepseek-harness sandbox policy."""

import json

# Permission Modes
MODE_READ_ONLY = "READ_ONLY"          # 🛡 仅可查看
MODE_WORKSPACE_WRITE = "WORKSPACE"    # 🛡 工作区内修改（项目内权限）
MODE_FULL_ACCESS = "FULL_ACCESS"      # 🛡 完全权限

MODE_DISPLAY_CONFIG = {
    MODE_READ_ONLY: {
        "text": "仅可查看",
        "icon": "🛡",
        "badge": "只读",
        "desc": "只读模式，禁止修改任何图层或文件，任何改动需计划审批",
    },
    MODE_WORKSPACE_WRITE: {
        "text": "工作区内修改",
        "icon": "🛡",
        "badge": "项目内",
        "desc": "允许在当前工程工作区目录内自由创建和编辑图层/文件，工作区外需审批",
    },
    MODE_FULL_ACCESS: {
        "text": "完全权限",
        "icon": "🛡",
        "badge": "完全",
        "desc": "完全执行权限，自主决策执行所有操作",
    },
}

# Forward and backward compatibility aliases
MODE_ALIASES = {
    "PLAN": MODE_READ_ONLY,
    "WORK": MODE_FULL_ACCESS,
    "READ_ONLY": MODE_READ_ONLY,
    "WORKSPACE": MODE_WORKSPACE_WRITE,
    "WORKSPACE_WRITE": MODE_WORKSPACE_WRITE,
    "FULL_ACCESS": MODE_FULL_ACCESS,
}


def normalize_mode(mode: str) -> str:
    """Normalize any mode string (legacy PLAN/WORK or new dsh modes) to a standard mode constant."""
    m = str(mode or "").strip().upper()
    return MODE_ALIASES.get(m, MODE_WORKSPACE_WRITE)


CONTINUATION_MARKERS = (
    "继续",
    "接着",
    "恢复任务",
    "继续任务",
    "继续执行",
    "按照任务继续",
    "resume",
    "continue",
)


def is_continuation_message(message: str) -> bool:
    text = " ".join(str(message or "").strip().lower().split())
    if not text:
        return False
    return any(marker in text for marker in CONTINUATION_MARKERS)


def should_resume_approved_plan(
    message: str,
    mode: str,
    plan_approved: bool,
    has_active_step: bool,
) -> bool:
    norm = normalize_mode(mode)
    return (
        norm == MODE_READ_ONLY
        and bool(plan_approved)
        and bool(has_active_step)
        and is_continuation_message(message)
    )


GEE_RETRY_CONFIRMATION_MARKERS = (
    "通过了",
    "已通过",
    "启用了",
    "已启用",
    "认证完成",
    "认证好了",
    "可以重试",
    "重新尝试",
    "重试",
)


def is_gee_retry_confirmation(message: str, recovery_context) -> bool:
    """Recognize a short acknowledgement after an actionable GEE configuration error."""
    if not isinstance(recovery_context, dict) or recovery_context.get("kind") != "gee_retry":
        return False
    text = " ".join(str(message or "").strip().lower().split())
    if not text or len(text) > 40:
        return False
    return any(marker in text for marker in GEE_RETRY_CONFIRMATION_MARKERS)


def build_gee_retry_message(message: str, recovery_context) -> str:
    """Carry confirmed, non-secret GEE parameters into a deliberate retry turn."""
    arguments = recovery_context.get("arguments") or {}
    arguments_json = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    return (
        "用户确认已处理上一轮 GEE 配置问题：" + str(message or "").strip() + "\n\n"
        "请直接重试下列已经由用户明确确认的工作流参数；不要再次询问时间、波段、分辨率、处理方法、"
        "输出名或边界。仅当出现新的、不同的错误或参数不再有效时再询问。\n"
        f"原工具：{recovery_context.get('tool_name', '')}\n"
        f"已确认参数：{arguments_json}\n"
        f"上一轮失败摘要：{str(recovery_context.get('failure_message', ''))[:500]}"
    )
