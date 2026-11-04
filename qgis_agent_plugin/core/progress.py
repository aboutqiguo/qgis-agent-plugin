"""Structured progress events for long-running data acquisition tools."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


DATA_ACQUISITION_TOOLS = frozenset(
    {
        "download_osm_data",
        "download_osm_boundary",
        "download_osm_roads",
        "download_osm_features",
        "run_osm_acquisition_workflow",
        "run_gee_sentinel2_download_workflow",
        "run_gee_dem_download_workflow",
    }
)


class DataAcquisitionCancelled(Exception):
    """Raised when the user cancels a running acquisition operation."""


@dataclass(frozen=True)
class ProgressEvent:
    tool_name: str
    title: str
    stage: str
    stage_index: int
    stage_count: int
    stage_percent: Optional[float] = None
    detail: str = ""
    state: str = "running"

    def to_dict(self) -> Dict[str, Any]:
        stage_count = max(1, int(self.stage_count or 1))
        stage_index = min(max(1, int(self.stage_index or 1)), stage_count)
        stage_percent = self.stage_percent
        if stage_percent is not None:
            stage_percent = min(100.0, max(0.0, float(stage_percent)))
            overall_percent = (
                ((stage_index - 1) + stage_percent / 100.0) / stage_count * 100.0
            )
        else:
            overall_percent = None
        if self.state == "completed":
            stage_percent = 100.0
            overall_percent = 100.0
        return {
            "tool_name": str(self.tool_name or ""),
            "title": str(self.title or "Data acquisition"),
            "stage": str(self.stage or "Processing"),
            "stage_index": stage_index,
            "stage_count": stage_count,
            "stage_percent": stage_percent,
            "percent": overall_percent,
            "determinate": overall_percent is not None,
            "detail": str(self.detail or ""),
            "state": str(self.state or "running"),
        }


def emit_progress(
    callback: Optional[Callable[[Dict[str, Any]], None]],
    *,
    tool_name: str,
    title: str,
    stage: str,
    stage_index: int,
    stage_count: int,
    stage_percent: Optional[float] = None,
    detail: str = "",
    state: str = "running",
) -> Dict[str, Any]:
    """Build and deliver a progress event without letting UI failures stop work."""
    event = ProgressEvent(
        tool_name=tool_name,
        title=title,
        stage=stage,
        stage_index=stage_index,
        stage_count=stage_count,
        stage_percent=stage_percent,
        detail=detail,
        state=state,
    ).to_dict()
    if callback:
        try:
            callback(event)
        except Exception:
            pass
    return event


def raise_if_cancelled(cancel_callback, message="Data acquisition was cancelled by the user."):
    if not cancel_callback:
        return
    try:
        cancelled = bool(cancel_callback())
    except Exception:
        cancelled = False
    if cancelled:
        raise DataAcquisitionCancelled(message)
