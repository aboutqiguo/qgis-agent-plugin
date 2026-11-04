"""Run outcome state shared by the harness and artifact reports."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


RUNNING = "running"
AWAITING_INPUT = "awaiting_input"
AWAITING_APPROVAL = "awaiting_approval"
AWAITING_MANUAL_DOWNLOAD = "awaiting_manual_download"
SUCCEEDED = "succeeded"
PARTIAL = "partial"
BLOCKED = "blocked"
CANCELLED = "cancelled"
FAILED = "failed"

FINAL_STATES = {
    AWAITING_INPUT,
    AWAITING_APPROVAL,
    AWAITING_MANUAL_DOWNLOAD,
    SUCCEEDED,
    PARTIAL,
    BLOCKED,
    CANCELLED,
    FAILED,
}


@dataclass
class RunOutcome:
    status: str
    reason: str = ""
    failed_steps: List[str] = field(default_factory=list)
    pending_steps: List[str] = field(default_factory=list)
    pending_actions: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == SUCCEEDED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "reason": self.reason,
            "failed_steps": list(self.failed_steps),
            "pending_steps": list(self.pending_steps),
            "pending_actions": list(self.pending_actions),
        }


def derive_run_outcome(
    plan: Optional[Any] = None,
    tool_success_count: int = 0,
    tool_failure_count: int = 0,
    last_tool_ok: Optional[bool] = None,
    last_failure_type: str = "",
    override_status: str = "",
    override_reason: str = "",
) -> RunOutcome:
    """Derive a conservative run outcome from structured execution evidence."""

    if override_status:
        return RunOutcome(override_status, override_reason)

    if last_failure_type == "manual_download_required":
        return RunOutcome(
            AWAITING_MANUAL_DOWNLOAD,
            "Cloud export completed but local download still requires user action.",
            pending_actions=["Download and load the exported file."],
        )
    if last_failure_type in {"missing_user_parameters", "human_input_required"}:
        return RunOutcome(
            AWAITING_INPUT,
            "Required data acquisition parameters still need user confirmation.",
            pending_actions=["Confirm the missing dataset, time, bands, resolution, CRS, and output parameters."],
        )
    if last_failure_type == "approval_required":
        return RunOutcome(
            AWAITING_APPROVAL,
            "A required plan or high-risk operation still needs user approval.",
            pending_actions=["Review and approve or reject the pending operation."],
        )
    if last_failure_type == "permission_error" and last_tool_ok is False:
        return RunOutcome(CANCELLED, "The latest required operation was not approved.")

    if plan and getattr(plan, "steps", None):
        failed = [step.step_id for step in plan.steps if getattr(step, "status", "") == "failed"]
        pending = [
            step.step_id
            for step in plan.steps
            if getattr(step, "status", "") in {"pending", "running"}
        ]
        passed = [step.step_id for step in plan.steps if getattr(step, "status", "") == "passed"]
        if not failed and not pending and len(passed) == len(plan.steps):
            return RunOutcome(SUCCEEDED, "All required plan steps passed verification.")
        if failed:
            return RunOutcome(
                PARTIAL if passed else FAILED,
                "One or more required plan steps failed verification.",
                failed_steps=failed,
                pending_steps=pending,
            )
        return RunOutcome(
            PARTIAL if passed else BLOCKED,
            "The run ended before all required plan steps were verified.",
            pending_steps=pending,
        )

    if last_tool_ok is False:
        return RunOutcome(FAILED, "The latest tool call failed.")
    if tool_failure_count and not tool_success_count:
        return RunOutcome(FAILED, "No tool call completed successfully.")
    return RunOutcome(SUCCEEDED, "The run completed without unresolved structured failures.")
