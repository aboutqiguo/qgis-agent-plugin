from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class TaskStep:
    step_id: str
    title: str
    description: str = ""
    status: str = STATUS_PENDING
    suggested_tools: List[str] = field(default_factory=list)
    expected_layers: List[str] = field(default_factory=list)
    expected_files: List[str] = field(default_factory=list)
    expected_artifacts: List[str] = field(default_factory=list)
    attempts: int = 0
    quality_score: int = 0
    last_tool: str = ""
    last_error: str = ""
    last_failure_type: str = ""
    retry_recommended: bool = False
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "suggested_tools": self.suggested_tools,
            "expected_layers": self.expected_layers,
            "expected_files": self.expected_files,
            "expected_artifacts": self.expected_artifacts,
            "attempts": self.attempts,
            "quality_score": self.quality_score,
            "last_tool": self.last_tool,
            "last_error": self.last_error,
            "last_failure_type": self.last_failure_type,
            "retry_recommended": self.retry_recommended,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TaskStep":
        return cls(
            step_id=str(payload.get("step_id", "")),
            title=str(payload.get("title", "")),
            description=str(payload.get("description", "")),
            status=str(payload.get("status", STATUS_PENDING)),
            suggested_tools=list(payload.get("suggested_tools") or []),
            expected_layers=list(payload.get("expected_layers") or []),
            expected_files=list(payload.get("expected_files") or []),
            expected_artifacts=list(payload.get("expected_artifacts") or []),
            attempts=int(payload.get("attempts") or 0),
            quality_score=int(payload.get("quality_score") or 0),
            last_tool=str(payload.get("last_tool", "")),
            last_error=str(payload.get("last_error", "")),
            last_failure_type=str(payload.get("last_failure_type", "")),
            retry_recommended=bool(payload.get("retry_recommended", False)),
            started_at=str(payload.get("started_at", "")),
            finished_at=str(payload.get("finished_at", "")),
        )


@dataclass
class TaskPlan:
    objective: str
    steps: List[TaskStep] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    source_markdown: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "created_at": self.created_at,
            "source_markdown": self.source_markdown,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TaskPlan":
        return cls(
            objective=str(payload.get("objective", "")),
            created_at=str(payload.get("created_at", "")),
            source_markdown=str(payload.get("source_markdown", "")),
            steps=[TaskStep.from_dict(item) for item in payload.get("steps", [])],
        )

    def active_step(self) -> Optional[TaskStep]:
        for step in self.steps:
            if step.status in (STATUS_RUNNING, STATUS_FAILED):
                return step
        for step in self.steps:
            if step.status == STATUS_PENDING:
                return step
        return None

    def all_passed(self) -> bool:
        return bool(self.steps) and all(step.status == STATUS_PASSED for step in self.steps)


@dataclass
class StepVerification:
    ok: bool
    step_id: str
    status: str
    message: str
    checks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    quality_score: int = 0
    severity: str = "info"
    failure_type: str = ""
    retry_recommended: bool = False
    retry_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "step_id": self.step_id,
            "status": self.status,
            "message": self.message,
            "checks": self.checks,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
            "quality_score": self.quality_score,
            "severity": self.severity,
            "failure_type": self.failure_type,
            "retry_recommended": self.retry_recommended,
            "retry_action": self.retry_action,
        }
