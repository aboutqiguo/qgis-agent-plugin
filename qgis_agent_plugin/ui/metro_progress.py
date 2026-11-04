# -*- coding: utf-8 -*-
"""Metro line / Subway station progress stepper for long-running GIS tasks.

Visualizes multi-step workflow milestones like a train transit map:
- Completed stations: Green filled circle (● / ✔) with solid green track
- In-progress station: Blue pulsing/double-ring circle (◉ / 🚆) with active track
- Failed station: Red error badge (✖ / 🔴) with warning track
- Paused station: Orange pause badge (⏸ / 🟡)
- Pending stations: Gray hollow circle (○) with dotted track
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
try:
    from qgis.PyQt.QtCore import Qt, QRect
    from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPen, QBrush
    from qgis.PyQt.QtWidgets import QWidget, QSizePolicy
except ImportError:
    try:
        from PyQt5.QtCore import Qt, QRect
        from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QBrush
        from PyQt5.QtWidgets import QWidget, QSizePolicy
    except ImportError:
        Qt = None
        QRect = object
        QWidget = object

STATUS_COMPLETED = "completed"
STATUS_RUNNING = "running"
STATUS_FAILED = "failed"
STATUS_PAUSED = "paused"
STATUS_PENDING = "pending"

COLOR_COMPLETED = "#2ea043"  # Metro green
COLOR_RUNNING = "#0969da"    # Metro blue
COLOR_FAILED = "#cf222e"     # Metro red
COLOR_PAUSED = "#d29922"     # Metro orange/amber
COLOR_PENDING = "#8c959f"    # Metro gray
COLOR_TRACK_DONE = "#2ea043"
COLOR_TRACK_TODO = "#d0d7de"

# Global dictionary ensuring every tool/technical name is translated to natural Chinese
TOOL_CHINESE_TRANSLATION = {
    "execute_pyqgis_script": "数据分析计算",
    "compute_raster_index": "遥感指数计算",
    "compute_raster_zonal_stats": "波段分区统计",
    "run_processing_algorithm": "栅格算法处理",
    "save_project_and_verify": "工程保存校验",
    "validate_processing_algorithm_call": "算法参数核对",
    "validate_raster_has_data": "栅格数据校验",
    "validate_project_outputs": "工程成果核验",
    "inspect_raster_file": "栅格文件核验",
    "describe_project_layer": "图层信息检查",
    "describe_processing_algorithm": "算法接口核验",
    "search_project_layers": "工程图层检索",
    "summarize_layers": "图层状态汇总",
    "remove_qgis_layers_and_data": "图层数据清理",
    "cleanup_qgis_project": "工程临时清理",
    "load_external_layer": "外部图层加载",
    "create_geodatabase": "空间库创建",
    "run_osm_acquisition_workflow": "OSM要素获取",
    "run_qgis_workflow_batch": "批处理工作流",
    "read_skill": "规则经验读取",
    "read_file": "文件内容读取",
    "write_file": "成果文件写入",
    "replace_file_content": "文档修改更新",
    "clip_vector_layers_to_boundary": "矢量边界裁剪",
    "download_osm_features": "OSM要素获取",
    "download_osm_boundary": "OSM边界获取",
    "download_osm_roads": "OSM路网获取",
    "run_gee_sentinel2_download_workflow": "Sentinel2数据获取",
    "run_gee_dem_download_workflow": "DEM高程获取",
    "ask_human": "方案确认交互",
    "gdal:rastercalculator": "遥感指数计算",
    "native:rastercalc": "栅格计算器运算",
    "native:fillsinkswangliu": "填洼与流向计算",
    "grass:r.watershed": "水文流域分析",
}


def sanitize_station_title(title: str, default_index: int = 1) -> str:
    """Enforce concise natural Chinese wording and clean step prefix for all station titles.
    
    Guarantees no raw English function identifiers, abbreviations, truncation dots,
    or overly long explanatory sentences leak to the UI.
    """
    if not title:
        return f"{default_index}. 步骤推进"

    clean = str(title).strip()
    
    # Check if there is an explicit numeric prefix (e.g. "1. " or "步骤 1: ")
    prefix_match = re.match(r'^(?:步骤\s*([0-9]+)[：:]\s*|([0-9]+)[\.、\s]+)(.*)$', clean)
    idx_str = f"{default_index}."
    body = clean
    if prefix_match:
        step_num = prefix_match.group(1) or prefix_match.group(2)
        idx_str = f"{step_num}."
        body = (prefix_match.group(3) or "").strip()

    # Detect failure or obstacle indicators
    has_failed = "遇阻" in body or "failed" in body.lower() or "error" in body.lower()

    # Exact or substring match against known tool table
    matched_chinese = None
    lower_body = body.lower()
    for eng, chn in TOOL_CHINESE_TRANSLATION.items():
        if eng in lower_body:
            matched_chinese = chn
            break

    if matched_chinese:
        body = matched_chinese
    else:
        # Heuristic translation for truncated prefixes, partial names, or code identifiers
        if any(token in lower_body for token in ["remove_qgis", "cleanup_qgis", "移除", "删除", "清理"]):
            body = "图层数据清理"
        elif any(token in lower_body for token in ["load_external", "加载", "导入"]):
            body = "外部图层加载"
        elif any(token in lower_body for token in ["exec", "script", "pyqgis"]):
            body = "数据分析计算"
        elif any(token in lower_body for token in ["rastercalc", "raster_calc", "calculator"]):
            body = "遥感指数计算"
        elif any(token in lower_body for token in ["process", "algorithm", "native", "gdal", "grass"]):
            body = "栅格算法处理"
        elif any(token in lower_body for token in ["valid", "check", "inspect", "va."]):
            body = "数据核对校验"
        elif any(token in lower_body for token in ["save", "project", "verify"]):
            body = "工程保存校验"
        elif any(token in lower_body for token in ["read", "skill", "re."]):
            body = "规则数据读取"
        elif any(token in lower_body for token in ["down", "osm", "gee", "fetch"]):
            body = "地理数据获取"
        elif any(token in lower_body for token in ["clip", "mask", "bound"]):
            body = "空间范围裁剪"
        elif any(token in lower_body for token in ["ndvi", "ndwi", "mvi", "index"]):
            body = "遥感指数提取"
        elif any(token in lower_body for token in ["flow", "watershed", "hydro", "basin"]):
            body = "水文水系分析"
        elif re.search(r'^[a-zA-Z_\.\s\d]+$', body):
            # Pure English identifiers with no Chinese
            body = "业务处理推进"

    # Clean residual punctuation, English leftovers, markdown, and trailing dots
    body = re.sub(r'execute_pyqgis_script', '数据分析计算', body, flags=re.I)
    body = re.sub(r'run_processing_algorithm', '空间算法处理', body, flags=re.I)
    body = re.sub(r'validate_processing_algorithm_call', '参数核验', body, flags=re.I)
    body = re.sub(r'save_project_and_verify', '工程保存', body, flags=re.I)
    body = re.sub(r'[（\(][^）\)]*[）\)]', '', body)
    body = re.sub(r'[a-zA-Z0-9_/\.\:\\-]+', ' ', body)
    body = re.sub(r'[_\-\*`\.]+', ' ', body)
    # Keep only the first clause before comma/semicolon/colon if it's a long sentence
    body = re.split(r'[，,；;。：:、]', body)[0].strip()
    body = re.sub(r'\s+', '', body)

    # Cap length to at most 10 Chinese characters so labels never overflow or overlap
    if len(body) > 10:
        body = body[:10]

    if has_failed and "遇阻" not in body:
        body = (body[:8] if len(body) > 8 else body) + "遇阻"

    if len(body) < 2:
        body = "任务推进"

    return f"{idx_str} {body}"


def render_metro_line_html(stations: List[Dict[str, Any]], line_title: str = "任务执行线路图") -> str:
    """HTML fallback renderer for metro station progress, used for previews and testing."""
    if not stations:
        return ""
    
    icons = {
        "completed": "✔",
        "running": "🚆",
        "failed": "✖",
        "paused": "⏸",
        "pending": "○",
    }
    
    parts = []
    parts.append(f'<div style="margin: 8px 0; padding: 8px; background: #f6f8fa; border-radius: 6px;">')
    parts.append(f'<div style="font-weight: bold; margin-bottom: 6px;">🚇 {line_title} ({len(stations)} 站)</div>')
    parts.append('<div style="display: flex; align-items: center; justify-content: space-between;">')
    
    for i, st in enumerate(stations, 1):
        status = str(st.get("status") or "pending").lower()
        icon = icons.get(status, "○")
        title = sanitize_station_title(st.get("title") or f"步骤 {i}", default_index=i)
        parts.append(f'<div style="text-align: center;"><span style="font-size: 14px;">{icon}</span><br/><span style="font-size: 11px;">{title}</span></div>')
        if i < len(stations):
            parts.append('<div style="flex-grow: 1; height: 2px; background: #d0d7de; margin: 0 4px;"></div>')
            
    parts.append('</div></div>')
    return "".join(parts)


class MetroStationWidget(QWidget):
    """Custom graphical widget rendering an interactive metro line stepper with word-wrapped Chinese labels."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.stations: List[Dict[str, Any]] = []
        self.line_title: str = "长线任务进度"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(96)

    def set_stations(self, title: str, stations: List[Dict[str, Any]]) -> None:
        self.line_title = title or "长线任务进度"
        cleaned_stations = []
        for i, st in enumerate(stations or [], start=1):
            raw_title = str(st.get("title") or st.get("name") or "")
            ch_title = sanitize_station_title(raw_title, default_index=i)
            cleaned_stations.append({
                "title": ch_title,
                "status": str(st.get("status") or STATUS_PENDING).lower(),
            })
        self.stations = cleaned_stations
        self.update()

    def paintEvent(self, event) -> None:
        if not self.stations:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        width = self.width()
        height = self.height()
        n = len(self.stations)
        if n == 0:
            return

        # Header Title
        title_font = QFont("Microsoft YaHei", 9, QFont.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor("#374151"))
        painter.drawText(8, 14, f"🚇 {self.line_title} ({n} 站)")

        # Metro track geometry - generous margins to avoid clipping and prevent box overlap
        margin_x = 56
        track_y = 30
        avail_width = max(1, width - margin_x * 2)
        step_x = avail_width / max(1, n - 1) if n > 1 else avail_width / 2

        # 1. Draw track lines
        for i in range(n - 1):
            x1 = margin_x + i * step_x
            x2 = margin_x + (i + 1) * step_x

            st1 = self.stations[i]
            st2 = self.stations[i + 1]
            status1 = st1.get("status", STATUS_PENDING)
            status2 = st2.get("status", STATUS_PENDING)

            if status1 == STATUS_COMPLETED and status2 in (STATUS_COMPLETED, STATUS_RUNNING):
                pen = QPen(QColor(COLOR_TRACK_DONE), 4)
            elif status1 == STATUS_FAILED or status2 == STATUS_FAILED:
                pen = QPen(QColor(COLOR_FAILED), 3, Qt.DashLine)
            else:
                pen = QPen(QColor(COLOR_TRACK_TODO), 3, Qt.DashLine)

            painter.setPen(pen)
            painter.drawLine(int(x1), int(track_y), int(x2), int(track_y))

        # 2. Draw station nodes and labels
        label_font = QFont("Microsoft YaHei", 8)

        for i, st in enumerate(self.stations):
            cx = margin_x + (i * step_x if n > 1 else avail_width / 2)
            cy = track_y
            status = st.get("status", STATUS_PENDING)
            title = st.get("title", f"{i + 1}. 步骤")

            # Station Circle / Badge
            if status in ("completed", "passed", "ok"):
                painter.setBrush(QBrush(QColor(COLOR_COMPLETED)))
                painter.setPen(QPen(QColor("#ffffff"), 2))
                painter.drawEllipse(int(cx - 7), int(cy - 7), 14, 14)
                # Mini checkmark
                painter.setPen(QPen(QColor("#ffffff"), 1.8))
                painter.drawLine(int(cx - 3), int(cy), int(cx - 1), int(cy + 3))
                painter.drawLine(int(cx - 1), int(cy + 3), int(cx + 4), int(cy - 3))
                label_color = QColor(COLOR_COMPLETED)

            elif status in ("running", "in_progress", "active"):
                # Double ring pulsing station + top train icon
                painter.setBrush(QBrush(QColor("#ffffff")))
                painter.setPen(QPen(QColor(COLOR_RUNNING), 3))
                painter.drawEllipse(int(cx - 8), int(cy - 8), 16, 16)
                painter.setBrush(QBrush(QColor(COLOR_RUNNING)))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(int(cx - 4), int(cy - 4), 8, 8)
                label_color = QColor(COLOR_RUNNING)

                # Mini top car badge
                painter.setFont(QFont("Segoe UI Emoji", 8))
                painter.setPen(QColor(COLOR_RUNNING))
                painter.drawText(int(cx - 6), int(cy - 12), "🚆")

            elif status in ("failed", "error"):
                painter.setBrush(QBrush(QColor(COLOR_FAILED)))
                painter.setPen(QPen(QColor("#ffffff"), 2))
                painter.drawEllipse(int(cx - 7), int(cy - 7), 14, 14)
                # Mini X
                painter.setPen(QPen(QColor("#ffffff"), 1.8))
                painter.drawLine(int(cx - 3), int(cy - 3), int(cx + 3), int(cy + 3))
                painter.drawLine(int(cx + 3), int(cy - 3), int(cx - 3), int(cy + 3))
                label_color = QColor(COLOR_FAILED)

            elif status in ("paused", "interrupted"):
                painter.setBrush(QBrush(QColor(COLOR_PAUSED)))
                painter.setPen(QPen(QColor("#ffffff"), 2))
                painter.drawEllipse(int(cx - 7), int(cy - 7), 14, 14)
                # Mini pause bars
                painter.setPen(QPen(QColor("#ffffff"), 1.8))
                painter.drawLine(int(cx - 2), int(cy - 3), int(cx - 2), int(cy + 3))
                painter.drawLine(int(cx + 2), int(cy - 3), int(cx + 2), int(cy + 3))
                label_color = QColor(COLOR_PAUSED)

            else:
                # Pending / Future (gray hollow circle)
                painter.setBrush(QBrush(QColor("#ffffff")))
                painter.setPen(QPen(QColor(COLOR_PENDING), 2))
                painter.drawEllipse(int(cx - 6), int(cy - 6), 12, 12)
                label_color = QColor("#6b7280")

            # Station Name: Multi-line Word-Wrapped Chinese Label
            painter.setFont(label_font)
            painter.setPen(label_color)
            
            # Width allocation for label text with strict upper cap so adjacent stations NEVER overlap
            text_box_w = min(104, max(56, int(step_x - 10))) if n > 1 else 120
            rect_x = int(cx - text_box_w / 2)
            # Bound within widget boundaries to avoid cutting left/right edge
            rect_x = max(2, min(width - text_box_w - 2, rect_x))
            rect_y = int(cy + 12)
            rect_h = 54

            label_rect = QRect(rect_x, rect_y, text_box_w, rect_h)
            wrap_flags = (Qt.TextWrapAnywhere | Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop) if hasattr(Qt, "TextWrapAnywhere") else (Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop)
            painter.drawText(
                label_rect,
                wrap_flags,
                title,
            )
