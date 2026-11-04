import os
import math
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
    except (TypeError, ValueError):
        return None


def _gdal_inspect_raster(file_path: str, force_read: bool = True) -> Dict[str, Any]:
    from osgeo import gdal

    try:
        gdal.UseExceptions()
    except (AttributeError, RuntimeError):
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
        except (RuntimeError, ValueError, TypeError, IndexError) as exc:
            band_info["read_ok"] = False
            errors.append(f"band {band_index} statistics failed: {exc}")

        metadata = band.GetMetadata() or {}
        valid_percent = _to_float(metadata.get("STATISTICS_VALID_PERCENT"))
        if valid_percent is None and force_read:
            try:
                mask_stats = band.GetMaskBand().GetStatistics(False, True)
                if mask_stats:
                    valid_percent = max(0.0, min(100.0, float(mask_stats[2]) / 255.0 * 100.0))
            except (RuntimeError, ValueError, TypeError, IndexError, AttributeError):
                pass
        if valid_percent is not None:
            band_info["valid_percent"] = valid_percent

        if force_read:
            try:
                band_info["checksum"] = int(band.Checksum())
            except (RuntimeError, ValueError, TypeError) as exc:
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
        except (AttributeError, RuntimeError, ValueError, TypeError) as exc:
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
    extent = data.get("extent") or {}
    dimensions_ok = int(data.get("width") or 0) > 0 and int(data.get("height") or 0) > 0
    extent_values = [extent.get(key) for key in ("xmin", "ymin", "xmax", "ymax")]
    extent_ok = all(value is not None and math.isfinite(float(value)) for value in extent_values)
    if extent_ok:
        extent_ok = float(extent["xmin"]) < float(extent["xmax"]) and float(extent["ymin"]) < float(extent["ymax"])
    ok = ok and dimensions_ok and extent_ok
    if not dimensions_ok:
        data.setdefault("read_errors", []).append("Raster dimensions are zero or invalid.")
    if not extent_ok:
        data.setdefault("read_errors", []).append("Raster georeferenced extent is missing or invalid.")
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
            continue
        if float(minimum) == float(maximum) and float(minimum) in {-9999.0, -32768.0, 65535.0, 255.0}:
            failures.append({"band": band_index, "reason": "all_values_equal_common_nodata", "value": minimum})

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


def _resolve_raster_path(layer_or_path: str) -> str:
    """Resolve either an existing file path or a loaded QGIS raster layer name/id."""
    raw = str(layer_or_path or "").strip()
    if not raw:
        return ""
    if os.path.exists(raw):
        return os.path.abspath(raw)
    try:
        from qgis.core import QgsProject

        proj = QgsProject.instance()
        by_id = proj.mapLayer(raw)
        if by_id is not None and hasattr(by_id, "source"):
            src = str(by_id.source() or "").split("|")[0]
            if os.path.exists(src):
                return os.path.abspath(src)
        matches = proj.mapLayersByName(raw)
        if matches:
            src = str(matches[0].source() or "").split("|")[0]
            if os.path.exists(src):
                return os.path.abspath(src)
        for lyr in proj.mapLayers().values():
            if raw.lower() in str(lyr.name() or "").lower():
                src = str(lyr.source() or "").split("|")[0]
                if os.path.exists(src):
                    return os.path.abspath(src)
    except (ImportError, AttributeError, RuntimeError, TypeError):
        pass
    return os.path.abspath(raw)


def _release_qgis_layers_locking_path(target_path: str, layer_name: str = "") -> List[str]:
    """Unload any QGIS project layers holding an open handle to target_path on Windows."""
    removed_names: List[str] = []
    if not target_path:
        return removed_names
    norm_target = os.path.normcase(os.path.abspath(target_path))
    try:
        import gc
        from qgis.core import QgsProject

        proj = QgsProject.instance()
        for lid, lyr in list(proj.mapLayers().items()):
            try:
                src = str(lyr.source() or "").split("|")[0]
                norm_src = os.path.normcase(os.path.abspath(src)) if src else ""
                name_match = bool(layer_name and str(lyr.name() or "") == layer_name)
                if norm_src == norm_target or name_match:
                    removed_names.append(str(lyr.name() or lid))
                    proj.removeMapLayer(lid)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        if removed_names:
            gc.collect()
    except (ImportError, AttributeError, RuntimeError, TypeError):
        pass
    return removed_names


def compute_raster_zonal_stats(
    source_layer_or_path: str,
    mask_layer_or_path: str = "",
    mask_valid_value: float = 1.0,
    rank_band_pairs: bool = True,
) -> Dict[str, Any]:
    """Compute per-band statistics and optional mask target/background separability.

    Avoids SWIG GDAL temporary-Dataset GC crashes and ranks normalized-difference
    band pairs ``(Bi - Bj) / (Bi + Bj)`` by |Cohen's d| and AUC in a single call.
    """
    src_path = _resolve_raster_path(source_layer_or_path)
    if not src_path or not os.path.exists(src_path):
        return {
            "ok": False,
            "message": f"Source raster not found: {source_layer_or_path}",
            "error_type": "file_path_error",
            "data": {"source": source_layer_or_path, "resolved_path": src_path},
        }

    mask_path = _resolve_raster_path(mask_layer_or_path) if mask_layer_or_path else ""
    if mask_layer_or_path and not os.path.exists(mask_path):
        return {
            "ok": False,
            "message": f"Mask raster not found: {mask_layer_or_path}",
            "error_type": "file_path_error",
            "data": {"mask": mask_layer_or_path, "resolved_path": mask_path},
        }

    try:
        import itertools
        import numpy as np
        from osgeo import gdal

        gdal.UseExceptions()
        src_ds = gdal.Open(src_path)
        if src_ds is None:
            raise RuntimeError(f"GDAL could not open source raster: {src_path}")

        mask_ds = None
        try:
            width = int(src_ds.RasterXSize)
            height = int(src_ds.RasterYSize)
            band_count = int(src_ds.RasterCount)
            arrays = []
            band_meta = []
            for idx in range(1, band_count + 1):
                band = src_ds.GetRasterBand(idx)
                arr = band.ReadAsArray().astype(np.float32)
                nodata = band.GetNoDataValue()
                desc = band.GetDescription() or f"Band_{idx}"
                arrays.append(arr)
                band_meta.append({
                    "band": idx,
                    "description": desc,
                    "dtype": gdal.GetDataTypeName(band.DataType),
                    "nodata": nodata,
                })

            stack = np.stack(arrays, axis=0)
            all_zero = np.all(stack == 0, axis=0)
            finite_mask = np.all(np.isfinite(stack), axis=0) & (~all_zero)

            if mask_path:
                mask_ds = gdal.Open(mask_path)
                if mask_ds is None:
                    raise RuntimeError(f"GDAL could not open mask raster: {mask_path}")
                if mask_ds.RasterXSize != width or mask_ds.RasterYSize != height:
                    mask_ds = gdal.Warp(
                        "",
                        mask_ds,
                        format="MEM",
                        width=width,
                        height=height,
                        resampleAlg="near",
                    )
                mask_band = mask_ds.GetRasterBand(1)
                mask_arr = mask_band.ReadAsArray()
                tgt = (mask_arr == mask_valid_value) & finite_mask
                bkg = (mask_arr != mask_valid_value) & finite_mask
                n_target = int(tgt.sum())
                n_background = int(bkg.sum())

                band_stats = []
                for idx in range(band_count):
                    b_arr = arrays[idx]
                    t_vals = b_arr[tgt]
                    k_vals = b_arr[bkg]
                    mt = float(t_vals.mean()) if t_vals.size else float("nan")
                    st = float(t_vals.std()) if t_vals.size else float("nan")
                    mk = float(k_vals.mean()) if k_vals.size else float("nan")
                    sk = float(k_vals.std()) if k_vals.size else float("nan")
                    pooled = math.sqrt((st * st + sk * sk) / 2.0) if (t_vals.size and k_vals.size) else 0.0
                    cohen_d = abs(mt - mk) / pooled if pooled > 1e-9 else 0.0
                    row = dict(band_meta[idx])
                    row.update({
                        "target_mean": round(mt, 4),
                        "target_std": round(st, 4),
                        "background_mean": round(mk, 4),
                        "background_std": round(sk, 4),
                        "mean_diff": round(mt - mk, 4),
                        "cohen_d": round(cohen_d, 4),
                        "min": round(float(b_arr.min()), 4),
                        "max": round(float(b_arr.max()), 4),
                    })
                    band_stats.append(row)

                top_pairs = []
                if rank_band_pairs and band_count >= 2 and n_target > 0 and n_background > 0:
                    rng = np.random.RandomState(0)
                    for i, j in itertools.combinations(range(band_count), 2):
                        a_arr, c_arr = arrays[i], arrays[j]
                        den = a_arr + c_arr
                        valid = (np.abs(den) > 1e-6) & finite_mask
                        idx_arr = np.zeros_like(a_arr)
                        np.divide(a_arr - c_arr, den, out=idx_arr, where=valid)
                        t_idx = idx_arr[tgt & valid]
                        k_idx = idx_arr[bkg & valid]
                        if t_idx.size < 10 or k_idx.size < 10:
                            continue
                        mt, st = float(t_idx.mean()), float(t_idx.std())
                        mk, sk = float(k_idx.mean()), float(k_idx.std())
                        pooled = math.sqrt((st * st + sk * sk) / 2.0)
                        d_val = abs(mt - mk) / pooled if pooled > 1e-9 else 0.0
                        a_sub = t_idx if t_idx.size <= 30000 else t_idx[rng.choice(t_idx.size, 30000, replace=False)]
                        b_sub = k_idx if k_idx.size <= 30000 else k_idx[rng.choice(k_idx.size, 30000, replace=False)]
                        comb = np.concatenate([a_sub, b_sub])
                        order = comb.argsort()
                        ranks = np.empty(comb.size, dtype=np.float64)
                        ranks[order] = np.arange(1, comb.size + 1)
                        rt = ranks[: a_sub.size].sum()
                        auc = (rt - a_sub.size * (a_sub.size + 1) / 2.0) / (a_sub.size * b_sub.size)
                        auc = float(max(auc, 1.0 - auc))
                        top_pairs.append({
                            "pair": f"B{i + 1}&B{j + 1}",
                            "band_a": i + 1,
                            "band_b": j + 1,
                            "formula": f"(B{i + 1} - B{j + 1}) / (B{i + 1} + B{j + 1})",
                            "target_mean": round(mt, 4),
                            "target_std": round(st, 4),
                            "background_mean": round(mk, 4),
                            "background_std": round(sk, 4),
                            "cohen_d": round(d_val, 4),
                            "auc": round(auc, 4),
                            "suggested_threshold": round((mt + mk) / 2.0, 4),
                        })
                    top_pairs.sort(key=lambda item: (-item["cohen_d"], -item["auc"]))

                return {
                    "ok": True,
                    "message": (
                        f"Computed zonal statistics across {band_count} band(s): "
                        f"target={n_target} px, background={n_background} px."
                    ),
                    "data": {
                        "source_path": src_path,
                        "mask_path": mask_path,
                        "width": width,
                        "height": height,
                        "band_count": band_count,
                        "target_pixels": n_target,
                        "background_pixels": n_background,
                        "band_statistics": band_stats,
                        "top_normalized_difference_pairs": top_pairs[:12],
                    },
                    "artifacts": [],
                    "warnings": [],
                }

            band_stats = []
            for idx in range(band_count):
                b_arr = arrays[idx]
                valid_vals = b_arr[finite_mask]
                row = dict(band_meta[idx])
                row.update({
                    "min": round(float(valid_vals.min()), 4) if valid_vals.size else float("nan"),
                    "max": round(float(valid_vals.max()), 4) if valid_vals.size else float("nan"),
                    "mean": round(float(valid_vals.mean()), 4) if valid_vals.size else float("nan"),
                    "std": round(float(valid_vals.std()), 4) if valid_vals.size else float("nan"),
                    "valid_pixels": int(valid_vals.size),
                    "valid_percent": round(100.0 * valid_vals.size / max(1, b_arr.size), 2),
                })
                band_stats.append(row)

            return {
                "ok": True,
                "message": f"Computed statistics for {band_count} band(s) of {os.path.basename(src_path)}.",
                "data": {
                    "source_path": src_path,
                    "width": width,
                    "height": height,
                    "band_count": band_count,
                    "band_statistics": band_stats,
                },
                "artifacts": [],
                "warnings": [],
            }
        finally:
            mask_ds = None
            src_ds = None
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Failed to compute raster zonal statistics: {exc}",
            "error_type": "processing_error",
            "data": {"source": src_path, "mask": mask_path},
        }


def compute_raster_index(
    source_layer_or_path: str,
    output_path: str,
    band_a: int,
    band_b: int,
    index_name: str = "INDEX",
    mask_layer_or_path: str = "",
    mask_valid_value: float = 1.0,
    clip_range: bool = True,
    load_layer: bool = True,
    layer_name: str = "",
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Safely compute a normalized difference index ``(Band_A - Band_B) / (Band_A + Band_B)`` in float32.

    Prevents UInt16 underflow in ``gdal:rastercalculator``, releases Windows file
    locks on existing QGIS layers before writing, and validates output integrity.
    """
    src_path = _resolve_raster_path(source_layer_or_path)
    if not src_path or not os.path.exists(src_path):
        return {
            "ok": False,
            "message": f"Source raster not found: {source_layer_or_path}",
            "error_type": "file_path_error",
            "data": {"source": source_layer_or_path, "resolved_path": src_path},
        }

    out_abs = os.path.abspath(output_path)
    if os.path.exists(out_abs) and not overwrite:
        return {
            "ok": False,
            "message": f"Output raster already exists and overwrite=False: {out_abs}",
            "error_type": "file_path_error",
            "data": {"output_path": out_abs},
        }

    mask_path = _resolve_raster_path(mask_layer_or_path) if mask_layer_or_path else ""
    if mask_layer_or_path and not os.path.exists(mask_path):
        return {
            "ok": False,
            "message": f"Mask raster not found: {mask_layer_or_path}",
            "error_type": "file_path_error",
            "data": {"mask": mask_layer_or_path, "resolved_path": mask_path},
        }

    target_layer_name = str(layer_name or os.path.splitext(os.path.basename(out_abs))[0]).strip()
    unloaded = _release_qgis_layers_locking_path(out_abs, target_layer_name)

    try:
        import gc
        import numpy as np
        from osgeo import gdal

        gdal.UseExceptions()
        src_ds = gdal.Open(src_path)
        if src_ds is None:
            raise RuntimeError(f"GDAL could not open source raster: {src_path}")

        mask_ds = None
        dst_ds = None
        try:
            band_count = int(src_ds.RasterCount)
            if not (1 <= int(band_a) <= band_count and 1 <= int(band_b) <= band_count):
                return {
                    "ok": False,
                    "message": f"Band numbers band_a={band_a}, band_b={band_b} out of range (1..{band_count}).",
                    "error_type": "argument_error",
                    "data": {"band_a": band_a, "band_b": band_b, "band_count": band_count},
                }

            width = int(src_ds.RasterXSize)
            height = int(src_ds.RasterYSize)
            gt = src_ds.GetGeoTransform()
            proj = src_ds.GetProjection()

            rb_a = src_ds.GetRasterBand(int(band_a))
            rb_b = src_ds.GetRasterBand(int(band_b))
            arr_a = rb_a.ReadAsArray().astype(np.float32)
            arr_b = rb_b.ReadAsArray().astype(np.float32)
            nodata_a = rb_a.GetNoDataValue()
            nodata_b = rb_b.GetNoDataValue()

            valid = np.isfinite(arr_a) & np.isfinite(arr_b)
            if nodata_a is not None and not math.isnan(float(nodata_a)):
                valid &= arr_a != float(nodata_a)
            if nodata_b is not None and not math.isnan(float(nodata_b)):
                valid &= arr_b != float(nodata_b)

            if mask_path:
                mask_ds = gdal.Open(mask_path)
                if mask_ds is None:
                    raise RuntimeError(f"GDAL could not open mask raster: {mask_path}")
                if mask_ds.RasterXSize != width or mask_ds.RasterYSize != height:
                    mask_ds = gdal.Warp(
                        "",
                        mask_ds,
                        format="MEM",
                        width=width,
                        height=height,
                        resampleAlg="near",
                    )
                mask_arr = mask_ds.GetRasterBand(1).ReadAsArray()
                valid &= mask_arr == mask_valid_value

            den = arr_a + arr_b
            valid &= np.abs(den) > 1e-6

            nodata_out = -9999.0
            out_arr = np.full((height, width), nodata_out, dtype=np.float32)
            np.divide(arr_a - arr_b, den, out=out_arr, where=valid)

            if clip_range:
                out_of_bounds = valid & ((out_arr < -1.0) | (out_arr > 1.0))
                out_arr[out_of_bounds] = nodata_out
                valid &= ~out_of_bounds

        finally:
            mask_ds = None
            src_ds = None
        gc.collect()

        os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
        tmp_path = out_abs + ".tmp.tif"
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        drv = gdal.GetDriverByName("GTiff")
        dst_ds = drv.Create(
            tmp_path,
            width,
            height,
            1,
            gdal.GDT_Float32,
            options=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"],
        )
        dst_ds.SetGeoTransform(gt)
        dst_ds.SetProjection(proj)
        out_band = dst_ds.GetRasterBand(1)
        out_band.SetNoDataValue(nodata_out)
        out_band.SetDescription(str(index_name or f"ND_B{band_a}_B{band_b}"))
        out_band.WriteArray(out_arr)
        out_band.FlushCache()
        dst_ds.FlushCache()
        out_band = None
        dst_ds = None
        gc.collect()

        try:
            os.replace(tmp_path, out_abs)
        except PermissionError:
            _release_qgis_layers_locking_path(out_abs, target_layer_name)
            os.replace(tmp_path, out_abs)

        valid_vals = out_arr[valid]
        stats = {
            "min": round(float(valid_vals.min()), 4) if valid_vals.size else None,
            "max": round(float(valid_vals.max()), 4) if valid_vals.size else None,
            "mean": round(float(valid_vals.mean()), 4) if valid_vals.size else None,
            "std": round(float(valid_vals.std()), 4) if valid_vals.size else None,
            "valid_pixels": int(valid_vals.size),
            "total_pixels": int(out_arr.size),
            "valid_percent": round(100.0 * valid_vals.size / max(1, out_arr.size), 2),
            "positive_pixels": int((valid_vals > 0).sum()) if valid_vals.size else 0,
        }

        loaded_layer_id = ""
        if load_layer:
            try:
                from qgis.core import QgsProject, QgsRasterLayer

                rl = QgsRasterLayer(out_abs, target_layer_name, "gdal")
                if rl.isValid():
                    QgsProject.instance().addMapLayer(rl)
                    loaded_layer_id = str(rl.id() or "")
            except (ImportError, AttributeError, RuntimeError, TypeError):
                pass

        validation = validate_raster_has_data(out_abs, bands=[1], min_valid_percent=0.01, force_read=True)
        return {
            "ok": bool(validation.get("ok")),
            "message": (
                f"Computed {index_name} ((B{band_a}-B{band_b})/(B{band_a}+B{band_b})) -> {out_abs} "
                f"(min={stats['min']}, mean={stats['mean']}, max={stats['max']}, valid={stats['valid_percent']}%)."
            ),
            "error_type": validation.get("error_type"),
            "data": {
                "output_path": out_abs,
                "layer_name": target_layer_name,
                "layer_id": loaded_layer_id,
                "band_a": int(band_a),
                "band_b": int(band_b),
                "index_name": index_name,
                "mask_path": mask_path,
                "unloaded_locked_layers": unloaded,
                "statistics": stats,
                "validation": validation.get("data"),
            },
            "artifacts": [
                {
                    "path": out_abs,
                    "type": "raster",
                    "description": f"{index_name} float32 raster ((B{band_a}-B{band_b})/(B{band_a}+B{band_b})).",
                }
            ],
            "warnings": [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Failed to compute raster index: {exc}",
            "error_type": "processing_error",
            "data": {
                "source": src_path,
                "output_path": out_abs,
                "band_a": band_a,
                "band_b": band_b,
            },
        }
