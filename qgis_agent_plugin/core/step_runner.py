from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from .task_state import STATUS_FAILED, STATUS_PASSED, STATUS_RUNNING, StepVerification, TaskPlan, TaskStep
from .verifier import verify_step


NON_EXECUTION_TOOLS = {
    "ask_human",
    "submit_plan_for_approval",
    "search_past_conversations",
    "search_data_sources",
    "create_data_acquisition_plan",
    "search_skills",
    "read_skill",
    "query_pyqgis_doc",
    "search_gee_api",
    "search_gee_python_api",
}


@dataclass
class StepGate:
    allowed: bool
    message: str = ""
    step: Optional[TaskStep] = None


class StepExecutionController:
    def __init__(self, plan: Optional[TaskPlan] = None, project_home: str = "", artifact_dir: str = ""):
        self.plan = plan
        self.project_home = project_home
        self.artifact_dir = artifact_dir
        self.active_tool_call_id = ""
        self.active_step_id = ""
        self.executed_tool_this_response = False

    def load_plan(self, plan: TaskPlan, project_home: str = "", artifact_dir: str = "") -> None:
        self.plan = plan
        self.project_home = project_home
        self.artifact_dir = artifact_dir
        self.active_tool_call_id = ""
        self.active_step_id = ""
        self.executed_tool_this_response = False

    def has_plan(self) -> bool:
        return bool(self.plan and self.plan.steps)

    def start_response(self) -> None:
        self.executed_tool_this_response = False

    def begin_tool_call(self, tool_call_id: str, tool_name: str, args: Dict[str, Any]) -> StepGate:
        if not self.has_plan() or not is_execution_tool(tool_name):
            return StepGate(True)
        if self.executed_tool_this_response:
            return StepGate(
                False,
                "Planner/Verifier allows only one execution tool call per assistant response. Wait for verification before continuing.",
            )

        step = self.plan.active_step()
        if not step:
            return StepGate(True)

        step.status = STATUS_RUNNING
        step.attempts += 1
        step.last_tool = tool_name
        step.started_at = datetime.now().isoformat(timespec="seconds")
        self.active_tool_call_id = tool_call_id
        self.active_step_id = step.step_id
        self.executed_tool_this_response = True
        return StepGate(True, step=step)

    def complete_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        args: Dict[str, Any],
        tool_result_content: Any,
    ) -> Optional[StepVerification]:
        if not self.has_plan() or tool_call_id != self.active_tool_call_id:
            return None

        step = self._find_step(self.active_step_id)
        if not step:
            return None

        verification = verify_step(step, tool_name, tool_result_content, self.project_home, self.artifact_dir)
        step.status = STATUS_PASSED if verification.ok else STATUS_FAILED
        step.quality_score = verification.quality_score
        step.finished_at = datetime.now().isoformat(timespec="seconds")
        step.last_error = "" if verification.ok else verification.message
        step.last_failure_type = verification.failure_type
        step.retry_recommended = verification.retry_recommended
        self.active_tool_call_id = ""
        self.active_step_id = ""
        return verification

    def _find_step(self, step_id: str) -> Optional[TaskStep]:
        if not self.plan:
            return None
        for step in self.plan.steps:
            if step.step_id == step_id:
                return step
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_home": self.project_home,
            "artifact_dir": self.artifact_dir,
            "active_tool_call_id": self.active_tool_call_id,
            "active_step_id": self.active_step_id,
            "executed_tool_this_response": self.executed_tool_this_response,
            "plan": self.plan.to_dict() if self.plan else None,
        }


def is_execution_tool(tool_name: str) -> bool:
    return bool(tool_name and tool_name not in NON_EXECUTION_TOOLS)
