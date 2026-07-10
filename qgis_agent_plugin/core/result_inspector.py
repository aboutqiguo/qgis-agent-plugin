from typing import Any, Dict


def inspect_qgis_layer(layer: Any) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "valid": False,
        "name": "",
        "type": "unknown",
        "crs": "",
        "feature_count": None,
        "extent": "",
        "warnings": [],
    }
    if layer is None:
        info["warnings"].append("Layer is None.")
        return info

    try:
        info["valid"] = bool(layer.isValid())
    except Exception:
        info["warnings"].append("Could not check layer validity.")

    try:
        info["name"] = layer.name()
    except Exception:
        pass

    try:
        from qgis.core import QgsMapLayerType

        layer_type = layer.type()
        if layer_type == QgsMapLayerType.VectorLayer:
            info["type"] = "vector"
        elif layer_type == QgsMapLayerType.RasterLayer:
            info["type"] = "raster"
    except Exception:
        pass

    try:
        crs = layer.crs()
        info["crs"] = crs.authid() if crs and crs.isValid() else ""
        if not info["crs"]:
            info["warnings"].append("Layer CRS is missing or invalid.")
    except Exception:
        pass

    try:
        if info["type"] == "vector":
            info["feature_count"] = int(layer.featureCount())
            if info["feature_count"] == 0:
                info["warnings"].append("Vector layer has zero features.")
    except Exception:
        pass

    try:
        info["extent"] = layer.extent().toString()
    except Exception:
        pass

    return info


def inspect_processing_result(result: Dict[str, Any]) -> Dict[str, Any]:
    report = {"ok": True, "outputs": {}, "warnings": []}
    if not isinstance(result, dict):
        return {"ok": False, "outputs": {}, "warnings": ["Processing result is not a dictionary."]}

    for key, value in result.items():
        if hasattr(value, "isValid"):
            layer_info = inspect_qgis_layer(value)
            report["outputs"][key] = layer_info
            if not layer_info.get("valid"):
                report["ok"] = False
            report["warnings"].extend(layer_info.get("warnings", []))
        else:
            report["outputs"][key] = {"value": str(value)}
    return report


def inspect_project_layers() -> Dict[str, Any]:
    report = {"ok": True, "layers": [], "warnings": []}
    try:
        from qgis.core import QgsProject
    except Exception as exc:
        return {"ok": False, "layers": [], "warnings": [f"QGIS project inspection unavailable: {exc}"]}

    try:
        layers = list(QgsProject.instance().mapLayers().values())
    except Exception as exc:
        return {"ok": False, "layers": [], "warnings": [f"Could not read QGIS layers: {exc}"]}

    if not layers:
        report["warnings"].append("Project has no loaded map layers.")
        return report

    for layer in layers:
        layer_info = inspect_qgis_layer(layer)
        report["layers"].append(layer_info)
        if not layer_info.get("valid"):
            report["ok"] = False
        report["warnings"].extend(layer_info.get("warnings", []))
    return report


def build_layer_report_markdown() -> str:
    report = inspect_project_layers()
    lines = ["# Layer Report", ""]
    lines.append(f"- Overall status: {'OK' if report.get('ok') else 'Needs attention'}")
    warnings = report.get("warnings", [])
    if warnings:
        lines.append("- Warnings:")
        for warning in warnings:
            lines.append(f"  - {warning}")
    else:
        lines.append("- Warnings: None")

    lines.extend(["", "## Layers", ""])
    layers = report.get("layers", [])
    if not layers:
        lines.append("No layers loaded.")
        return "\n".join(lines) + "\n"

    lines.append("| Name | Type | Valid | CRS | Feature Count | Extent |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for layer in layers:
        name = str(layer.get("name", "")).replace("|", "\\|")
        extent = str(layer.get("extent", "")).replace("|", "\\|")
        lines.append(
            f"| {name} | {layer.get('type', '')} | {layer.get('valid')} | "
            f"{layer.get('crs', '')} | {layer.get('feature_count', '')} | {extent} |"
        )
    return "\n".join(lines) + "\n"
