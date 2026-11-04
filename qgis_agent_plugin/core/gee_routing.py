"""Pure GEE download route estimation helpers."""

import math
from typing import Any, Dict


EE_DIRECT_MAX_BYTES = 32 * 1024 * 1024
EE_DIRECT_MAX_DIMENSION = 10000


def estimate_direct_download_route(
    area_m2: float,
    width_m: float,
    height_m: float,
    band_count: int,
    scale: float,
    bytes_per_sample: int = 4,
) -> Dict[str, Any]:
    scale = max(float(scale or 0), 1e-9)
    bands = max(int(band_count or 0), 1)
    width_px = max(1, int(math.ceil(max(float(width_m or 0), 0.0) / scale)))
    height_px = max(1, int(math.ceil(max(float(height_m or 0), 0.0) / scale)))
    area_pixels = max(1, int(math.ceil(max(float(area_m2 or 0), 0.0) / (scale * scale))))
    grid_pixels = max(area_pixels, width_px * height_px)
    estimated_bytes = grid_pixels * bands * max(int(bytes_per_sample or 0), 1)
    eligible = (
        estimated_bytes < EE_DIRECT_MAX_BYTES
        and width_px <= EE_DIRECT_MAX_DIMENSION
        and height_px <= EE_DIRECT_MAX_DIMENSION
    )
    return {
        "route": "ee_direct" if eligible else "batch_export",
        "eligible": eligible,
        "estimated_bytes": estimated_bytes,
        "estimated_mb": round(estimated_bytes / (1024 * 1024), 3),
        "width_px": width_px,
        "height_px": height_px,
        "band_count": bands,
        "scale": scale,
        "direct_max_bytes": EE_DIRECT_MAX_BYTES,
        "direct_max_dimension": EE_DIRECT_MAX_DIMENSION,
    }
