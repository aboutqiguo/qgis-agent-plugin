"""Execution checkpoints for long-running and multi-step GIS tasks.

Allows recording execution states at each milestone, pausing, resuming,
and rolling back without starting long tasks from scratch.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class TaskCheckpoint:
    checkpoint_id: str
    run_id: str
    step_number: int
    title: str
    status: str  # "completed", "paused", "interrupted", "failed"
    timestamp: str
    tool_name: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    can_resume: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskCheckpoint:
        return cls(
            checkpoint_id=str(data.get("checkpoint_id") or ""),
            run_id=str(data.get("run_id") or ""),
            step_number=int(data.get("step_number") or 1),
            title=str(data.get("title") or "Unnamed Milestone"),
            status=str(data.get("status") or "completed"),
            timestamp=str(data.get("timestamp") or datetime.now().isoformat(timespec="seconds")),
            tool_name=str(data.get("tool_name") or ""),
            inputs=dict(data.get("inputs") or {}),
            outputs=dict(data.get("outputs") or {}),
            can_resume=bool(data.get("can_resume", True)),
            notes=str(data.get("notes") or ""),
        )


class CheckpointManager:
    """Manages milestone checkpoints for tasks within a QGIS project."""

    def __init__(self, project_home: str = "", run_dir: str = "", run_id: str = ""):
        self.project_home = project_home or ""
        self.run_dir = run_dir or ""
        self.run_id = run_id or (os.path.basename(run_dir) if run_dir else "")
        self.checkpoints: List[TaskCheckpoint] = []
        self._load_existing_checkpoints()

    def _get_run_checkpoint_file(self) -> str:
        if self.run_dir and os.path.exists(self.run_dir):
            return os.path.join(self.run_dir, "checkpoints.json")
        return ""

    def _get_project_index_file(self) -> str:
        if self.project_home and os.path.exists(self.project_home):
            index_dir = os.path.join(self.project_home, ".qgis_agent_runs")
            try:
                os.makedirs(index_dir, exist_ok=True)
            except OSError:
                pass
            return os.path.join(index_dir, "checkpoints_index.json")
        return ""

    def _load_existing_checkpoints(self) -> None:
        run_file = self._get_run_checkpoint_file()
        if run_file and os.path.exists(run_file):
            try:
                with open(run_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, list):
                        self.checkpoints = [TaskCheckpoint.from_dict(item) for item in raw if isinstance(item, dict)]
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                pass

    def _persist(self) -> None:
        serialized = [cp.to_dict() for cp in self.checkpoints]
        run_file = self._get_run_checkpoint_file()
        if run_file:
            try:
                with open(run_file, "w", encoding="utf-8") as f:
                    json.dump(serialized, f, ensure_ascii=False, indent=2)
            except (OSError, TypeError, ValueError):
                pass

        index_file = self._get_project_index_file()
        if index_file:
            try:
                existing: Dict[str, Any] = {}
                if os.path.exists(index_file):
                    try:
                        with open(index_file, "r", encoding="utf-8") as f:
                            existing = json.load(f) or {}
                    except (OSError, json.JSONDecodeError, ValueError, TypeError):
                        existing = {}
                key = self.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
                existing[key] = {
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "checkpoint_count": len(serialized),
                    "checkpoints": serialized[-10:],
                }
                with open(index_file, "w", encoding="utf-8") as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2)
            except (OSError, TypeError, ValueError):
                pass

    def record_checkpoint(
        self,
        step_number: int,
        title: str,
        tool_name: str = "",
        inputs: Optional[Dict[str, Any]] = None,
        outputs: Optional[Dict[str, Any]] = None,
        status: str = "completed",
        notes: str = "",
    ) -> TaskCheckpoint:
        """Create a new milestone checkpoint."""
        timestamp = datetime.now().isoformat(timespec="seconds")
        cp_id = f"cp_step_{step_number:02d}_{int(datetime.now().timestamp()) % 100000}"
        cp = TaskCheckpoint(
            checkpoint_id=cp_id,
            run_id=self.run_id,
            step_number=step_number,
            title=title,
            status=status,
            timestamp=timestamp,
            tool_name=tool_name,
            inputs=inputs or {},
            outputs=outputs or {},
            can_resume=True,
            notes=notes,
        )
        self.checkpoints.append(cp)
        self._persist()
        return cp

    def mark_interrupted(
        self,
        step_number: Optional[int] = None,
        title: str = "Task interrupted by user",
        reason: str = "User requested stop/pause",
        partial_outputs: Optional[Dict[str, Any]] = None,
    ) -> TaskCheckpoint:
        """Record an interruption checkpoint so the session can be safely resumed."""
        step_num = step_number or (len(self.checkpoints) + 1)
        return self.record_checkpoint(
            step_number=step_num,
            title=title,
            tool_name="user_interrupt",
            inputs={"reason": reason},
            outputs=partial_outputs or {},
            status="paused",
            notes=f"暂停状态：{reason}。已保留当前已产出的图层与数据，可随时输入‘继续’或‘从第{step_num}步继续’。",
        )

    def get_last_checkpoint(self) -> Optional[TaskCheckpoint]:
        """Return the most recent checkpoint."""
        if not self.checkpoints:
            return None
        return self.checkpoints[-1]

    def get_checkpoint(self, checkpoint_id: str) -> Optional[TaskCheckpoint]:
        for cp in reversed(self.checkpoints):
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        return [cp.to_dict() for cp in self.checkpoints]

    def get_metro_stations(self, total_planned: int = 0) -> List[Dict[str, Any]]:
        """Return structured station objects for the bottom metro progress stepper."""
        stations = []
        for c in self.checkpoints:
            stations.append({
                "title": f"{c.step_number}. {c.title}",
                "status": c.status,
            })
        if total_planned > len(stations):
            for i in range(len(stations) + 1, total_planned + 1):
                stations.append({
                    "title": f"步骤 {i}",
                    "status": "pending",
                })
        return stations

    def format_checkpoint_card(self, cp: TaskCheckpoint) -> str:
        """Format a clean, concise markdown summary for display in the chat panel."""
        status_icon = "📍" if cp.status == "completed" else "⏸️" if cp.status == "paused" else "⚠️"
        lines = [
            f"{status_icon} **执行节点已保存 [步骤 {cp.step_number}: {cp.title}]**",
            f"- 状态：`{cp.status}` · 时间：`{cp.timestamp}` · 节点 ID: `{cp.checkpoint_id}`",
        ]
        outputs = cp.outputs or {}
        layers = outputs.get("layers") or []
        files = outputs.get("files") or []
        if layers:
            lines.append(f"- 已生成图层：" + "、".join(f"`{layer}`" for layer in layers))
        if files:
            lines.append(f"- 已持久化文件：" + "；".join(f"`{f}`" for f in files[:4]))
        if cp.notes:
            lines.append(f"- 说明：{cp.notes}")

        return "\n".join(lines)
