import ast
import re
from typing import Any, Dict, List, Tuple


def _issue(
    issue_id: str,
    severity: str,
    message: str,
    suggestion: str,
    evidence: str = "",
    auto_applied: bool = False,
) -> Dict[str, Any]:
    return {
        "id": issue_id,
        "severity": severity,
        "message": message,
        "suggestion": suggestion,
        "evidence": evidence,
        "auto_applied": auto_applied,
    }


def _replace_import_symbol(code: str, module: str, bad_symbol: str, replacement_symbol: str = "") -> Tuple[str, bool]:
    changed = False
    import_pattern = re.compile(rf"^from\s+{re.escape(module)}\s+import\s+(.+)$", re.MULTILINE)

    def repl(match):
        nonlocal changed
        symbols = [part.strip() for part in match.group(1).split(",") if part.strip()]
        if bad_symbol not in symbols:
            return match.group(0)
        changed = True
        symbols = [symbol for symbol in symbols if symbol != bad_symbol]
        if replacement_symbol and replacement_symbol not in symbols:
            symbols.append(replacement_symbol)
        if not symbols:
            return ""
        return f"from {module} import {', '.join(symbols)}"

    return import_pattern.sub(repl, code), changed


def _ensure_import(code: str, import_line: str) -> Tuple[str, bool]:
    if import_line in code:
        return code, False
    return f"{import_line}\n{code}", True


def _replace_pattern(
    code: str,
    pattern: str,
    replacement: str,
    issues: List[Dict[str, Any]],
    issue_id: str,
    message: str,
    suggestion: str,
    severity: str = "error",
    flags: int = 0,
) -> Tuple[str, bool]:
    new_code, count = re.subn(pattern, replacement, code, flags=flags)
    if count:
        issues.append(_issue(issue_id, severity, message, suggestion, evidence=f"{count} occurrence(s)", auto_applied=True))
        return new_code, True
    return code, False


def _detect_missing_nominatim_output(code: str, issues: List[Dict[str, Any]]) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not _is_nominatim_call(node):
            continue
        keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
        if len(node.args) < 2 and "output_file" not in keyword_names:
            issues.append(
                _issue(
                    "osm_nominatim_missing_output_file",
                    "error",
                    "OSMDownloader.download_boundary_nominatim requires an output_file argument.",
                    "Use OSMDownloader.download_boundary_nominatim(name, output_file, layer_name=None).",
                    evidence=ast.get_source_segment(code, node) or "download_boundary_nominatim(...)",
                    auto_applied=False,
                )
            )


def _is_nominatim_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "download_boundary_nominatim"
        and isinstance(func.value, ast.Name)
        and func.value.id == "OSMDownloader"
    )


def _line_offsets(code: str) -> List[int]:
    offsets = [0]
    total = 0
    for line in code.splitlines(True):
        total += len(line)
        offsets.append(total)
    return offsets


def _byte_col_to_char_col(line: str, byte_col: int) -> int:
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def _node_span(code: str, node: ast.AST) -> Tuple[int, int]:
    lines = code.splitlines(True)
    char_offsets = _line_offsets(code)
    start_line = lines[node.lineno - 1]
    end_line = lines[node.end_lineno - 1]
    start_col = _byte_col_to_char_col(start_line, node.col_offset)
    end_col = _byte_col_to_char_col(end_line, node.end_col_offset)
    start = char_offsets[node.lineno - 1] + start_col
    end = char_offsets[node.end_lineno - 1] + end_col
    return start, end


def _repair_nominatim_call_keywords(code: str) -> Tuple[str, bool]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, False

    edits: List[Tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not _is_nominatim_call(node):
            continue
        segment = ast.get_source_segment(code, node)
        if not segment:
            continue
        repaired = re.sub(r"\bplace_name\s*=", "name=", segment)
        repaired = re.sub(r"\boutput_path\s*=", "output_file=", repaired)
        if repaired != segment:
            start, end = _node_span(code, node)
            edits.append((start, end, repaired))

    if not edits:
        return code, False
    repaired_code = code
    for start, end, replacement in sorted(edits, reverse=True):
        repaired_code = repaired_code[:start] + replacement + repaired_code[end:]
    return repaired_code, True


def repair_common_qgis_code_issues(code: str = "", error_message: str = "", context: str = "") -> Dict[str, Any]:
    """Diagnose and repair high-frequency PyQGIS mistakes seen in agent logs."""
    original_code = code or ""
    fixed_code = original_code
    error_text = error_message or ""
    combined = "\n".join([original_code, error_text, context or ""])
    issues: List[Dict[str, Any]] = []
    warnings: List[str] = []
    replacements: List[Dict[str, str]] = []

    def record_replacement(rule_id: str, before: str, after: str) -> None:
        replacements.append({"rule_id": rule_id, "before": before, "after": after})

    if "QgsColorRampShaderItem" in combined:
        before = fixed_code
        fixed_code = fixed_code.replace("QgsColorRampShaderItem(", "QgsColorRampShader.ColorRampItem(")
        fixed_code, _ = _replace_import_symbol(fixed_code, "qgis.core", "QgsColorRampShaderItem", "QgsColorRampShader")
        if fixed_code != before:
            record_replacement(
                "qgis_color_ramp_item",
                "QgsColorRampShaderItem",
                "QgsColorRampShader.ColorRampItem",
            )
            issues.append(
                _issue(
                    "qgis_color_ramp_item",
                    "error",
                    "QgsColorRampShaderItem is not imported directly from qgis.core in QGIS 3.44.",
                    "Use QgsColorRampShader.ColorRampItem(...) instead.",
                    evidence="QgsColorRampShaderItem",
                    auto_applied=True,
                )
            )

    color_item_hex_pattern = r"(QgsColorRampShader\.ColorRampItem\(\s*[^,\n]+,\s*)(['\"]#[0-9A-Fa-f]{6,8}['\"])(\s*,)"
    if re.search(color_item_hex_pattern, fixed_code):
        before = fixed_code
        fixed_code = re.sub(color_item_hex_pattern, r"\1QColor(\2)\3", fixed_code)
        fixed_code, _ = _ensure_import(fixed_code, "from qgis.PyQt.QtGui import QColor")
        if fixed_code != before:
            record_replacement(
                "qgis_color_ramp_item_qcolor",
                "QgsColorRampShader.ColorRampItem(value, '#hex', label)",
                "QgsColorRampShader.ColorRampItem(value, QColor('#hex'), label)",
            )
            issues.append(
                _issue(
                    "qgis_color_ramp_item_qcolor",
                    "error",
                    "QgsColorRampShader.ColorRampItem expects a QColor object for the color argument.",
                    "Wrap hex color strings with QColor(...).",
                    evidence="ColorRampItem(..., '#hex', ...)",
                    auto_applied=True,
                )
            )

    if re.search(r"\bdict\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\.attributes\(\)\s*\)", combined):
        issues.append(
            _issue(
                "qgis_attributes_dict",
                "error",
                "QgsFeature.attributes() returns a list, not key/value pairs.",
                "Build field names first, then use dict(zip(field_names, feature.attributes())).",
                evidence="dict(feature.attributes())",
                auto_applied=False,
            )
        )

    if "OSMDownloader.download_features" in combined:
        issues.append(
            _issue(
                "osm_downloader_download_features_missing",
                "error",
                "OSMDownloader has no download_features method.",
                "Use the download_osm_features tool, or call OSMDownloader.query_osm() plus load_osm_layer().",
                evidence="OSMDownloader.download_features",
                auto_applied=False,
            )
        )

    if "qgis.agent_plugin" in combined:
        before = fixed_code
        fixed_code = fixed_code.replace("qgis.agent_plugin", "qgis_agent_plugin")
        if fixed_code != before:
            record_replacement("plugin_import_path", "qgis.agent_plugin", "qgis_agent_plugin")
            issues.append(
                _issue(
                    "plugin_import_path",
                    "error",
                    "The plugin package is qgis_agent_plugin, not qgis.agent_plugin.",
                    "Use imports such as `from qgis_agent_plugin.bridges.gee_bridge import init_gee, GEEDownloader`.",
                    evidence="qgis.agent_plugin",
                    auto_applied=True,
                )
            )

    if "COPERNICUS/DEM/GLO30" in combined and re.search(r"ee\.Image\s*\(\s*['\"]COPERNICUS/DEM/GLO30['\"]\s*\)", fixed_code):
        before = fixed_code
        fixed_code = re.sub(
            r"ee\.Image\s*\(\s*(['\"])COPERNICUS/DEM/GLO30\1\s*\)",
            r"ee.ImageCollection('COPERNICUS/DEM/GLO30').mosaic().select('DEM')",
            fixed_code,
        )
        if fixed_code != before:
            record_replacement(
                "gee_copernicus_dem_collection",
                "ee.Image('COPERNICUS/DEM/GLO30')",
                "ee.ImageCollection('COPERNICUS/DEM/GLO30').mosaic().select('DEM')",
            )
            issues.append(
                _issue(
                    "gee_copernicus_dem_collection",
                    "error",
                    "COPERNICUS/DEM/GLO30 is an Earth Engine ImageCollection, not an Image.",
                    "Use run_gee_dem_download_workflow, or mosaic the ImageCollection and select band DEM.",
                    evidence="COPERNICUS/DEM/GLO30",
                    auto_applied=True,
                )
            )

    if any(name in combined for name in ("simple_feature_collection_to_ee_geom", "feature_collection_to_ee_geom")):
        issues.append(
            _issue(
                "gee_boundary_helper_missing",
                "error",
                "The attempted boundary-to-ee.Geometry helper is not exported from qgis_tools.",
                "Prefer run_gee_dem_download_workflow/run_gee_sentinel2_download_workflow, or use the internal _boundary_layer_to_ee_geometry helper inside tools.py.",
                evidence="feature_collection_to_ee_geom",
                auto_applied=False,
            )
        )

    if re.search(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*,\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*QgsVectorFileWriter\.writeAsVectorFormatV3\s*\(", combined, flags=re.MULTILINE):
        issues.append(
            _issue(
                "qgs_vector_writer_v3_unpack",
                "warning",
                "writeAsVectorFormatV3 return arity varies across QGIS builds.",
                "Assign the result to one variable and read result[0] when it is a tuple.",
                evidence="err, msg = QgsVectorFileWriter.writeAsVectorFormatV3(...)",
                auto_applied=False,
            )
        )

    if "QgsRasterCalculator" in combined and re.search(r"from\s+qgis\.core\s+import[^\n]*\bQgsRasterCalculator\b", fixed_code):
        before = fixed_code
        fixed_code, _ = _replace_import_symbol(fixed_code, "qgis.core", "QgsRasterCalculator", "")
        fixed_code, _ = _ensure_import(fixed_code, "from qgis.analysis import QgsRasterCalculator")
        if fixed_code != before:
            record_replacement(
                "qgis_raster_calculator_import",
                "from qgis.core import QgsRasterCalculator",
                "from qgis.analysis import QgsRasterCalculator",
            )
            issues.append(
                _issue(
                    "qgis_raster_calculator_import",
                    "error",
                    "QgsRasterCalculator must be imported from qgis.analysis.",
                    "Use `from qgis.analysis import QgsRasterCalculator`.",
                    evidence="QgsRasterCalculator",
                    auto_applied=True,
                )
            )

    fixed_code, changed = _replace_pattern(
        fixed_code,
        r"([A-Za-z_][A-Za-z0-9_\.]*)\.type\(\)\.toString\(\)",
        r"str(\1.type())",
        issues,
        "layer_type_to_string",
        "QgsMapLayerType/LayerType does not provide .toString().",
        "Use str(layer.type()) or compare against QgsMapLayerType enum values.",
    )
    if changed:
        record_replacement("layer_type_to_string", "layer.type().toString()", "str(layer.type())")

    if "numPoints" in combined:
        before = fixed_code
        fixed_code = re.sub(r"\.constGet\(\)\.numPoints\(\)", ".constGet().vertexCount()", fixed_code)
        if "object has no attribute 'numPoints'" in combined:
            fixed_code = re.sub(r"\.numPoints\(\)", ".vertexCount()", fixed_code)
        if fixed_code != before:
            record_replacement("geometry_num_points", "numPoints()", "vertexCount()")
            issues.append(
                _issue(
                    "geometry_num_points",
                    "error",
                    "QgsPolygon/QgsGeometry internals do not expose numPoints() in this context.",
                    "Use vertexCount() for QGIS 3.44 geometry vertex counting.",
                    evidence="numPoints()",
                    auto_applied=True,
                )
            )

    if "download_boundary_nominatim" in combined:
        before = fixed_code
        fixed_code, changed = _repair_nominatim_call_keywords(fixed_code)
        if changed:
            record_replacement(
                "osm_nominatim_signature",
                "place_name=/output_path=",
                "name=/output_file=",
            )
            issues.append(
                _issue(
                    "osm_nominatim_signature",
                    "error",
                    "OSMDownloader.download_boundary_nominatim was called with unsupported keyword names.",
                    "Use signature: OSMDownloader.download_boundary_nominatim(name, output_file, layer_name=None).",
                    evidence="download_boundary_nominatim",
                    auto_applied=True,
                )
            )
        _detect_missing_nominatim_output(fixed_code, issues)

    if re.search(r"QgsProject\.instance\(\)\.addMapLayer\s*\(", combined):
        issues.append(
            _issue(
                "bare_add_map_layer",
                "warning",
                "The code directly calls QgsProject.instance().addMapLayer().",
                (
                    "For file-backed layers, prefer load_vector_layer/load_raster_layer so retries reuse existing "
                    "layers and avoid duplicates."
                ),
                evidence="addMapLayer(",
                auto_applied=False,
            )
        )
        warnings.append("Direct addMapLayer calls are not auto-rewritten because the layer source/type must be inspected.")

    if re.search(r"QgsRasterFileWriter|\.writeRaster\s*\(", combined):
        issues.append(
            _issue(
                "deprecated_raster_writer",
                "warning",
                "QgsRasterFileWriter.writeRaster() is deprecated/noisy in recent QGIS.",
                "Prefer processing.run('gdal:translate', ...) or a dedicated save_raster_layer helper.",
                evidence="QgsRasterFileWriter.writeRaster",
                auto_applied=False,
            )
        )
        warnings.append("Raster writer deprecation is reported but not auto-rewritten because output options vary by task.")

    if "SaveVectorFormatOptions" in combined:
        before = fixed_code
        fixed_code = fixed_code.replace("QgsVectorFileWriter.SaveVectorFormatOptions", "QgsVectorFileWriter.SaveVectorOptions")
        if fixed_code != before:
            record_replacement(
                "qgs_vector_writer_options_class",
                "QgsVectorFileWriter.SaveVectorFormatOptions",
                "QgsVectorFileWriter.SaveVectorOptions",
            )
            issues.append(
                _issue(
                    "qgs_vector_writer_options_class",
                    "error",
                    "QgsVectorFileWriter.SaveVectorFormatOptions is not available in QGIS 3.44.",
                    "Use QgsVectorFileWriter.SaveVectorOptions() and set driverName/layerName on the options object.",
                    evidence="SaveVectorFormatOptions",
                    auto_applied=True,
                )
            )

    if "driverName' is an unknown keyword argument" in combined or re.search(r"SaveVectorOptions\s*\([^)]*driverName\s*=", combined):
        issues.append(
            _issue(
                "qgs_vector_writer_driver_keyword",
                "error",
                "QgsVectorFileWriter.SaveVectorOptions does not accept driverName as a constructor keyword.",
                "Create options = QgsVectorFileWriter.SaveVectorOptions(); then set options.driverName = 'GPKG' or 'ESRI Shapefile'.",
                evidence="driverName keyword",
                auto_applied=False,
            )
        )

    if "writeRasterFile" in combined:
        before = fixed_code
        fixed_code = fixed_code.replace(".writeRasterFile(", ".writeRaster(")
        if fixed_code != before:
            record_replacement("qgs_raster_writer_method", "writeRasterFile(", "writeRaster(")
            issues.append(
                _issue(
                    "qgs_raster_writer_method",
                    "error",
                    "QgsRasterFileWriter.writeRasterFile does not exist in QGIS 3.44.",
                    "Use writeRaster(...) with the QGIS 3.44 signature, or prefer processing.run('gdal:translate', ...).",
                    evidence="writeRasterFile",
                    auto_applied=True,
                )
            )

    if "QgsRasterFileWriter.writeRaster(): arguments did not match" in combined:
        issues.append(
            _issue(
                "qgs_raster_writer_signature",
                "error",
                "QgsRasterFileWriter.writeRaster was called with an incompatible signature.",
                "Prefer processing.run('gdal:translate', {'INPUT': source, 'OUTPUT': output_path}) for raster export.",
                evidence="writeRaster signature mismatch",
                auto_applied=False,
            )
        )

    if any(token in combined for token in ("Normalized/laundered field name", "Field name of width", "Shapefile")):
        issues.append(
            _issue(
                "shapefile_field_limit",
                "warning",
                "Shapefile field names and text widths are being truncated by format limits.",
                "Prefer GeoPackage or GeoJSON when preserving full field names matters; export Shapefile only as a compatibility copy.",
                evidence="Shapefile field warning",
                auto_applied=False,
            )
        )

    if re.search(r"\.\s*(maximumValue|minimumValue)\s*\(", combined):
        issues.append(
            _issue(
                "raster_minmax_methods",
                "error",
                "Raster maximumValue()/minimumValue() calls are fragile or unavailable in QGIS 3.44.",
                "Use provider.bandStatistics(1, QgsRasterBandStats.All), then stats.maximumValue/stats.minimumValue.",
                evidence="maximumValue()/minimumValue()",
                auto_applied=False,
            )
        )

    if re.search(r"QgsSingleBandPseudoColorRenderer\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,", combined):
        issues.append(
            _issue(
                "pseudo_color_renderer_provider",
                "error",
                "QgsSingleBandPseudoColorRenderer expects a raster data provider as the first argument.",
                "Pass raster_layer.dataProvider(), not the raster layer object.",
                evidence="QgsSingleBandPseudoColorRenderer(layer, ...)",
                auto_applied=False,
            )
        )

    changed = fixed_code != original_code
    applied_count = sum(1 for issue in issues if issue.get("auto_applied"))
    return {
        "ok": True,
        "message": f"Detected {len(issues)} common issue(s); applied {applied_count} automatic repair(s).",
        "data": {
            "changed": changed,
            "fixed_code": fixed_code,
            "issues": issues,
            "replacements": replacements,
            "applied_repair_count": applied_count,
            "issue_count": len(issues),
            "needs_review": any(not issue.get("auto_applied") for issue in issues),
            "known_signatures": {
                "OSMDownloader.download_boundary_nominatim": "download_boundary_nominatim(name: str, output_file: str, layer_name: str = None)",
                "QgsColorRampShader item": "QgsColorRampShader.ColorRampItem(value, color, label='')",
                "Layer type display": "str(layer.type()) or compare layer.type() to QgsMapLayerType",
                "Copernicus DEM GLO30": "ee.ImageCollection('COPERNICUS/DEM/GLO30').mosaic().select('DEM')",
            },
        },
        "artifacts": [],
        "warnings": warnings,
    }
