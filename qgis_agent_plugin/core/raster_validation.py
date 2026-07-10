import os
from typing import Any, Dict, Iterable, List, Optional


def _extent_from_gt(gt, width: int, height: int) -> Dict[str, float]:
    xs = [gt[0], gt[0] + width * gt[1], gt[0] + height * gt[2], gt[0] + width * gt[1] + height * gt[2]]
    ys = [gt[3], gt[3] + width * gt[4], gt[3] + height * gt[5], gt[3] + width * gt[4] + height * gt[5]]
    return {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _gdal_inspect_raster(file_path: str, force_read: bool = True) -> Dict[str, Any]:
    from osgeo import gdal

    try:
        gdal.UseExceptions()
    except Exception:
        pass

    errors: List[str] = []
    ds = gdal.Open(file_path, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError("GDAL could not open the raster.")

    gt = ds.GetGeoTransform(can_return_null=True)
    info: Dict[str, Any] = {
        "path": file_path,
        "exists": True,
        "size_bytes": os.path.getsize(file_path),
        "driver": ds.GetDriver().ShortName if ds.GetDriver() else "",
        "width": int(ds.RasterXSize),
        "height": int(ds.RasterYSize),
        "band_count": int(ds.RasterCount),
        "projection": ds.GetProjection() or "",
        "geotransform": list(gt) if gt else [],
        "extent": _extent_from_gt(gt, ds.RasterXSize, ds.RasterYSize) if gt else {},
        "bands": [],
    }

    for band_index in range(1, ds.RasterCount + 1):
        band = ds.GetRasterBand(band_index)
        band_info: Dict[str, Any] = {
            "band": band_index,
            "description": band.GetDescription() or "",
            "data_type": gdal.GetDataTypeName(band.DataType),
            "nodata": _to_float(band.GetNoDataValue()),
            "valid_percent": None,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "stddev": None,
            "checksum": None,
            "read_ok": True,
        }
        try:
            stats = band.GetStatistics(False, True)
            if stats:
                band_info["minimum"] = _to_float(stats[0])
                band_info["maximum"] = _to_float(stats[1])
                band_info["mean"] = _to_float(stats[2])
                band_info["stddev"] = _to_float(stats[3])
        except Exception as exc:
            band_info["read_ok"] = False
            errors.append(f"band {band_index} statistics failed: {exc}")

        metadata = band.GetMetadata() or {}
        valid_percent = _to_float(metadata.get("STATISTICS_VALID_PERCENT"))
        if valid_percent is not None:
            band_info["valid_percent"] = valid_percent

        if force_read:
            try:
                band_info["checksum"] = int(band.Checksum())
            except Exception as exc:
                band_info["read_ok"] = False
                errors.append(f"band {band_index} checksum/read failed: {exc}")

        info["bands"].append(band_info)

    info["read_errors"] = errors
    info["read_ok"] = not errors
    return info


def _qgis_inspect_raster(file_path: str, force_read: bool = True) -> Dict[str, Any]:
    from qgis.core import QgsRasterBandStats, QgsRasterLayer

    layer = QgsRasterLayer(file_path, os.path.splitext(os.path.basename(file_path))[0])
    if not layer.isValid():
        raise RuntimeError("QGIS could not load the raster.")
    provider = layer.dataProvider()
    extent = layer.extent()
    info: Dict[str, Any] = {
        "path": file_path,
        "exists": True,
        "size_bytes": os.path.getsize(file_path),
        "driver": "qgis",
        "width": int(layer.width()),
        "height": int(layer.height()),
        "band_count": int(layer.bandCount()),
        "projection": layer.crs().authid(),
        "geotransform": [],
        "extent": {
            "xmin": extent.xMinimum(),
            "ymin": extent.yMinimum(),
            "xmax": extent.xMaximum(),
            "ymax": extent.yMaximum(),
        },
        "bands": [],
        "read_errors": [],
        "read_ok": True,
    }
    for band_index in range(1, layer.bandCount() + 1):
        band_info = {
            "band": band_index,
            "description": provider.generateBandName(band_index),
            "data_type": str(provider.dataType(band_index)),
            "nodata": _to_float(provider.sourceNoDataValue(band_index)),
            "valid_percent": None,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "stddev": None,
            "checksum": None,
            "read_ok": True,
        }
        try:
            stats = provider.bandStatistics(band_index, QgsRasterBandStats.All)
            band_info["minimum"] = _to_float(stats.minimumValue)
            band_info["maximum"] = _to_float(stats.maximumValue)
            band_info["mean"] = _to_float(stats.mean)
            band_info["stddev"] = _to_float(stats.stdDev)
        except Exception as exc:
            band_info["read_ok"] = False
            info["read_ok"] = False
            info["read_errors"].append(f"band {band_index} statistics failed: {exc}")
        info["bands"].append(band_info)
    return info


def inspect_raster_file(file_path: str, force_read: bool = True) -> Dict[str, Any]:
    file_path = os.path.abspath(file_path)
    if not os.path.exists(file_path):
        return {
            "ok": False,
            "message": f"Raster file not found: {file_path}",
            "error_type": "file_path_error",
            "data": {"path": file_path, "exists": False},
        }
    if os.path.getsize(file_path) <= 0:
        return {
            "ok": False,
            "message": f"Raster file is empty: {file_path}",
            "error_type": "raster_integrity_error",
            "data": {"path": file_path, "exists": True, "size_bytes": 0},
        }

    try:
        data = _gdal_inspect_raster(file_path, force_read=force_read)
    except Exception as gdal_exc:
        try:
            data = _qgis_inspect_raster(file_path, force_read=force_read)
            data.setdefault("warnings", []).append(f"GDAL inspection failed, used QGIS provider fallback: {gdal_exc}")
        except Exception as qgis_exc:
            return {
                "ok": False,
                "message": f"Raster integrity inspection failed: {gdal_exc}; QGIS fallback failed: {qgis_exc}",
                "error_type": "raster_integrity_error",
                "data": {"path": file_path, "exists": True, "size_bytes": os.path.getsize(file_path)},
            }

    ok = bool(data.get("read_ok")) and int(data.get("band_count") or 0) > 0
    return {
        "ok": ok,
        "message": "Raster file is readable." if ok else "Raster file has read errors.",
        "error_type": None if ok else "raster_integrity_error",
        "data": data,
        "warnings": data.get("warnings", []),
    }


def validate_raster_has_data(
    file_path: str,
    bands: Optional[Iterable[int]] = None,
    min_valid_percent: float = 0.01,
    force_read: bool = True,
) -> Dict[str, Any]:
    inspection = inspect_raster_file(file_path, force_read=force_read)
    if not inspection.get("ok"):
        return inspection

    data = inspection.get("data") or {}
    band_rows = data.get("bands") or []
    selected = set(int(b) for b in bands or [])
    failures = []
    checked = []

    for row in band_rows:
        band_index = int(row.get("band") or 0)
        if selected and band_index not in selected:
            continue
        checked.append(band_index)
        valid_percent = row.get("valid_percent")
        minimum = row.get("minimum")
        maximum = row.get("maximum")
        nodata = row.get("nodata")
        read_ok = bool(row.get("read_ok", True))

        if not read_ok:
            failures.append({"band": band_index, "reason": "read_failed"})
            continue
        if valid_percent is not None and float(valid_percent) < min_valid_percent:
            failures.append({"band": band_index, "reason": "valid_percent_below_threshold", "valid_percent": valid_percent})
            continue
        if minimum is None or maximum is None:
            failures.append({"band": band_index, "reason": "statistics_missing"})
            continue
        if nodata is not None and float(minimum) == float(nodata) and float(maximum) == float(nodata):
            failures.append({"band": band_index, "reason": "all_values_equal_nodata", "nodata": nodata})

    if not checked:
        failures.append({"band": None, "reason": "no_matching_bands"})

    ok = not failures
    return {
        "ok": ok,
        "message": "Raster contains valid data." if ok else "Raster has no usable data in required bands.",
        "error_type": None if ok else "raster_no_data_error",
        "data": {
            "path": os.path.abspath(file_path),
            "checked_bands": checked,
            "failures": failures,
            "inspection": data,
            "min_valid_percent": min_valid_percent,
        },
        "suggestions": [] if ok else [
            "Do not continue to raster math until this input is fixed.",
            "If this follows a GEE download, re-download the raster and verify file integrity before clipping.",
            "If this follows clipping, verify raster/vector overlap and mask CRS.",
        ],
    }
