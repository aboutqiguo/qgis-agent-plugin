"""Declarative validation rule tables for PyQGIS code, security checks, and dependency allowlists."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class CodeValidationRule:
    rule_id: str
    severity: str  # "error" or "warning"
    message: str
    suggestion: str
    pattern: Optional[str] = None
    substring: Optional[str] = None
    required_substring: Optional[str] = None
    excluded_substring: Optional[str] = None
    regex_flags: int = 0
    field: str = "code"

    def matches(self, code: str) -> bool:
        if self.required_substring and self.required_substring not in code:
            return False
        if self.excluded_substring and self.excluded_substring in code:
            return False
        if self.substring and self.substring not in code:
            return False
        if self.pattern and not re.search(self.pattern, code, flags=self.regex_flags):
            return False
        return bool(self.substring or self.pattern)


CODE_SECURITY_BLOCKING_RULES: Tuple[CodeValidationRule, ...] = (
    CodeValidationRule(
        rule_id="sec_subprocess",
        severity="error",
        pattern=r"\bsubprocess\.(run|Popen|call|check_call|check_output)\s*\(",
        regex_flags=re.IGNORECASE,
        message="Subprocess calls are blocked in agent PyQGIS scripts.",
        suggestion="Use a registered tool or QGIS/Python API instead of launching external processes.",
    ),
    CodeValidationRule(
        rule_id="sec_os_system",
        severity="error",
        pattern=r"\bos\.system\s*\(",
        regex_flags=re.IGNORECASE,
        message="os.system calls are blocked in agent PyQGIS scripts.",
        suggestion="Use a registered tool or QGIS/Python API instead of shell commands.",
    ),
    CodeValidationRule(
        rule_id="sec_pip_install",
        severity="error",
        pattern=r"\bpip_main\s*\(|\bpip\._internal\b|python\s+-m\s+pip|\bpip\s+install\b",
        regex_flags=re.IGNORECASE,
        message="Package installation inside PyQGIS scripts is blocked.",
        suggestion="Use the install_python_package tool instead.",
    ),
)


CODE_SECURITY_WARNING_RULES: Tuple[CodeValidationRule, ...] = (
    CodeValidationRule(
        rule_id="sec_network_access",
        severity="warning",
        pattern=r"\brequests\.(get|post|put|delete|patch)\s*\(|\burllib\.request\b|\bhttpx\.(get|post|put|delete|patch)\s*\(",
        regex_flags=re.IGNORECASE,
        message="The script performs network access.",
        suggestion="Prefer registered data-source tools and ensure the data source is documented.",
    ),
    CodeValidationRule(
        rule_id="sec_file_write",
        severity="warning",
        pattern=r"\bopen\s*\([^)]*,\s*['\"][wa]\b|\bQgsVectorFileWriter\b|\bQgsRasterFileWriter\b|\bwriteAsVectorFormat",
        regex_flags=re.IGNORECASE,
        message="The script appears to write files.",
        suggestion="Ensure the target path is inside the project or temp folder and approval is requested when needed.",
    ),
    CodeValidationRule(
        rule_id="sec_destructive_delete",
        severity="warning",
        pattern=r"\bos\.(remove|unlink|rmdir)\s*\(|\bshutil\.rmtree\s*\(|\bremoveMapLayer\s*\(",
        regex_flags=re.IGNORECASE,
        message="The script may delete files, layers, or project data.",
        suggestion="This must be explicitly approved before execution.",
    ),
)


PYQGIS_API_VALIDATION_RULES: Tuple[CodeValidationRule, ...] = (
    CodeValidationRule(
        rule_id="qgis_raster_calculator_import",
        severity="error",
        pattern=r"from\s+qgis\.core\s+import[^\n]*\bQgsRasterCalculator\b",
        message="QgsRasterCalculator is not imported from qgis.core in QGIS 3.44.",
        suggestion="Use `from qgis.analysis import QgsRasterCalculator` instead.",
    ),
    CodeValidationRule(
        rule_id="qgis_color_ramp_shader_item",
        severity="error",
        substring="QgsColorRampShaderItem",
        message="QgsColorRampShaderItem is not imported directly from qgis.core in QGIS 3.44.",
        suggestion="Call repair_common_qgis_code_issues, or use `QgsColorRampShader.ColorRampItem(...)`.",
    ),
    CodeValidationRule(
        rule_id="qgis_color_ramp_item_hex_str",
        severity="error",
        pattern=r"QgsColorRampShader\.ColorRampItem\(\s*[^,\n]+,\s*['\"]#[0-9A-Fa-f]{6,8}['\"]\s*,",
        message="QgsColorRampShader.ColorRampItem color argument must be a QColor object.",
        suggestion="Call repair_common_qgis_code_issues, or wrap hex strings as `QColor('#1a9850')`.",
    ),
    CodeValidationRule(
        rule_id="qgis_feature_attributes_dict",
        severity="error",
        pattern=r"\bdict\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\.attributes\(\)\s*\)",
        message="QgsFeature.attributes() returns a list, so dict(feature.attributes()) is invalid.",
        suggestion="Use `field_names = [f.name() for f in layer.fields()]` then `dict(zip(field_names, feature.attributes()))`.",
    ),
    CodeValidationRule(
        rule_id="osm_downloader_download_features",
        severity="error",
        substring="OSMDownloader.download_features",
        message="OSMDownloader.download_features does not exist.",
        suggestion="Use the registered `download_osm_features` tool, or call `OSMDownloader.query_osm()` and `load_osm_layer()`.",
    ),
    CodeValidationRule(
        rule_id="qgis_write_as_vector_format_v3_arity",
        severity="warning",
        pattern=r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*,\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*QgsVectorFileWriter\.writeAsVectorFormatV3\s*\(",
        regex_flags=re.MULTILINE,
        message="writeAsVectorFormatV3 return arity varies across QGIS builds.",
        suggestion="Assign to `result`, then use `err = result[0] if isinstance(result, tuple) else result`.",
    ),
    CodeValidationRule(
        rule_id="qgis_layer_type_to_string",
        severity="error",
        pattern=r"\.type\(\)\.toString\(\)",
        message="LayerType/QgsMapLayerType does not support `.toString()`.",
        suggestion="Call repair_common_qgis_code_issues, or use `str(layer.type())`.",
    ),
    CodeValidationRule(
        rule_id="qgis_geometry_num_points",
        severity="warning",
        pattern=r"\.constGet\(\)\.numPoints\(\)|\.numPoints\(\)",
        message="numPoints() is fragile on QGIS 3.44 geometry internals.",
        suggestion="Call repair_common_qgis_code_issues, or use vertexCount().",
    ),
    CodeValidationRule(
        rule_id="qgis_raster_min_max_methods",
        severity="error",
        pattern=r"\.\s*(maximumValue|minimumValue)\s*\(",
        message="Raster maximumValue()/minimumValue() calls are fragile or unavailable in QGIS 3.44.",
        suggestion=(
            "Use `provider.bandStatistics(1, QgsRasterBandStats.All)` and then read "
            "`stats.maximumValue` or `stats.minimumValue`."
        ),
    ),
    CodeValidationRule(
        rule_id="qgis_provider_band_name",
        severity="error",
        pattern=r"\b(prov|provider|mp|pr|dataProvider\(\))\s*\.\s*bandName\s*\(",
        message="QgsRasterDataProvider does not have a bandName() method in QGIS 3.44.",
        suggestion="Call `raster_layer.bandName(band_no)` on the QgsRasterLayer object, or prefer `compute_raster_zonal_stats`.",
    ),
    CodeValidationRule(
        rule_id="qgis_band_stats_min_max_attr",
        severity="error",
        required_substring="bandStatistics",
        pattern=r"\b(st|stat|stats|ms)\s*\.\s*(minimum|maximum)\b(?!Value)",
        message="QgsRasterBandStats uses `.minimumValue` and `.maximumValue`, not `.minimum` or `.maximum`.",
        suggestion="Read `stats.minimumValue`, `stats.maximumValue`, and `stats.mean` (float attributes), or call `compute_raster_zonal_stats`.",
    ),
    CodeValidationRule(
        rule_id="qgis_band_stats_mean_callable",
        severity="error",
        required_substring="bandStatistics",
        pattern=r"\b(st|stat|stats|ms)\s*\.\s*mean\s*\(\s*\)",
        message="QgsRasterBandStats.mean is a float attribute, not a callable method.",
        suggestion="Use `stats.mean` without parentheses, or call `compute_raster_zonal_stats`.",
    ),
    CodeValidationRule(
        rule_id="qgis_shader_classification_mode",
        severity="error",
        pattern=r"\.setClassificationMode\s*\(\s*(?:QgsColorRampShader\.|_crs_type\.|MODE_)?(?:Discrete|Interpolated|Exact|[012])\b",
        message="QgsColorRampShader.setClassificationMode() does not accept Discrete/Interpolated or raw integers in QGIS 3.44.",
        suggestion="Call `shader.setColorRampType(QgsColorRampShader.Discrete)` (or `QgsColorRampShader.Interpolated`) instead of `setClassificationMode()`.",
    ),
    CodeValidationRule(
        rule_id="qgis_layer_render_settings",
        severity="error",
        pattern=r"\.renderSettings\s*\(",
        message="QgsVectorLayer / QgsRasterLayer has no `.renderSettings()` method in QGIS 3.44.",
        suggestion="Use `layer.setOpacity(1.0)` and `layer.setRenderer(QgsSingleSymbolRenderer(symbol))` directly on the layer.",
    ),
    CodeValidationRule(
        rule_id="gdal_type_to_numpy_type",
        severity="error",
        substring="GDALTypeToNumpyType",
        message="osgeo.gdal_array has no attribute `GDALTypeToNumpyType`.",
        suggestion="Use `gdal_array.GDALTypeCodeToNumericTypeCode(gdt)` or a dict `{gdal.GDT_Float32: np.float32, gdal.GDT_Int16: np.int16}`.",
    ),
    CodeValidationRule(
        rule_id="gdal_gdt_in_numpy_astype_direct",
        severity="error",
        pattern=r"\.astype\s*\(\s*gdal\.GDT_",
        message="GDAL data type constants (e.g. `gdal.GDT_Float32 == 6`) are integer enums and cannot be passed to `numpy.ndarray.astype()`.",
        suggestion="Pass `gdal.GDT_Float32` to `driver.Create(...)`, and pass a NumPy dtype (`np.float32`, `np.int16`) to `.astype(...)`.",
    ),
    CodeValidationRule(
        rule_id="gdal_gdt_in_numpy_astype_var",
        severity="error",
        required_substring="gdal.GDT_",
        excluded_substring="GDALTypeCodeToNumericTypeCode",
        pattern=r"\.astype\s*\(\s*(?:dtype|gdt)\s*\)",
        message="GDAL data type constants (e.g. `gdal.GDT_Float32 == 6`) are integer enums and cannot be passed to `numpy.ndarray.astype()`.",
        suggestion="Pass `gdal.GDT_Float32` to `driver.Create(...)`, and pass a NumPy dtype (`np.float32`, `np.int16`) to `.astype(...)`.",
    ),
    CodeValidationRule(
        rule_id="qgis_direct_add_map_layer",
        severity="warning",
        pattern=r"QgsProject\.instance\(\)\.addMapLayer\s*\(",
        message="Direct addMapLayer() can duplicate file-backed layers after retries.",
        suggestion="Prefer load_vector_layer/load_raster_layer, or call repair_common_qgis_code_issues for guidance.",
    ),
    CodeValidationRule(
        rule_id="qgis_raster_file_writer",
        severity="warning",
        pattern=r"QgsRasterFileWriter|\.writeRaster\s*\(",
        message="QgsRasterFileWriter.writeRaster() is deprecated/noisy in recent QGIS.",
        suggestion="Prefer processing.run('gdal:translate', ...) or a dedicated raster-save helper.",
    ),
    CodeValidationRule(
        rule_id="qgis_pseudo_color_renderer_arg",
        severity="error",
        pattern=r"QgsSingleBandPseudoColorRenderer\s*\(\s*(layer|raster_layer|.*_layer)\s*,",
        message="QgsSingleBandPseudoColorRenderer expects a raster data provider as its first argument.",
        suggestion="Pass `raster_layer.dataProvider()` instead of the layer object.",
    ),
    CodeValidationRule(
        rule_id="qgis_message_level_alias",
        severity="warning",
        pattern=r"level\s*=\s*Qgis\.(Info|Warning|Critical|Success)\b",
        message="Qgis message level aliases are less stable in QGIS 3.44.",
        suggestion="Prefer `Qgis.MessageLevel.Info/Warning/Critical/Success`.",
    ),
)


ALLOWED_INSTALL_PACKAGES = frozenset({
    "earthengine-api",
    "geopandas",
    "networkx",
    "numpy",
    "openai",
    "openpyxl",
    "osmnx",
    "pandas",
    "pyproj",
    "rasterio",
    "requests",
    "scikit-learn",
    "scipy",
    "shapely",
})


def apply_rule_table(report, code: str, rules: Sequence[CodeValidationRule]) -> None:
    seen = {(i.level, i.message, i.field) for i in report.issues}
    for rule in rules:
        if not rule.matches(code):
            continue
        key = (rule.severity, rule.message, rule.field)
        if key in seen:
            continue
        seen.add(key)
        if rule.severity == "error":
            report.add_error(rule.message, rule.suggestion, rule.field)
        else:
            report.add_warning(rule.message, rule.suggestion, rule.field)


def check_nominatim_ast_calls(report, code: str, tree: ast.AST) -> None:
    if "download_boundary_nominatim" not in code:
        return
    allowed_keywords = {"name", "output_file", "layer_name"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_nominatim_call = (
            isinstance(func, ast.Attribute)
            and func.attr == "download_boundary_nominatim"
            and isinstance(func.value, ast.Name)
            and func.value.id == "OSMDownloader"
        )
        if not is_nominatim_call:
            continue
        keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
        unsupported = sorted(keyword_names - allowed_keywords)
        if unsupported:
            report.add_error(
                "OSMDownloader.download_boundary_nominatim was called with unsupported keyword names.",
                "Use `download_boundary_nominatim(name, output_file, layer_name=None)`. "
                f"Unsupported keyword(s): {', '.join(unsupported)}.",
                "code",
            )
        has_output = len(node.args) >= 2 or "output_file" in keyword_names
        if not has_output:
            report.add_error(
                "OSMDownloader.download_boundary_nominatim is missing output_file.",
                "Provide the output path as the second positional argument or as `output_file=...`.",
                "code",
            )
