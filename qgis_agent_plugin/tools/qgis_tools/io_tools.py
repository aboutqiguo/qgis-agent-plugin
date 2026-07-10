import os

from qgis.core import QgsVectorLayer, QgsRasterLayer, QgsProject, QgsVectorFileWriter

_DUPLICATE_POLICIES = {"reuse", "replace", "allow", "rename"}


def _canonical_source(source: str) -> str:
    if not source:
        return ""

    source = str(source).strip().strip('"')
    head, sep, tail = source.partition("|")
    normalized_head = head.replace("\\", "/")
    try:
        if os.path.isabs(head) or os.path.exists(head):
            normalized_head = os.path.normcase(os.path.abspath(head)).replace("\\", "/")
    except Exception:
        pass
    return f"{normalized_head}{sep}{tail}"


def _layer_source(layer) -> str:
    try:
        return _canonical_source(layer.source())
    except Exception:
        return ""


def _layer_name(layer) -> str:
    try:
        return layer.name()
    except Exception:
        return ""


def _layer_id(layer) -> str:
    try:
        return layer.id()
    except Exception:
        return ""


def _layer_is_usable(layer) -> bool:
    try:
        _layer_id(layer)
        if hasattr(layer, "isValid") and not layer.isValid():
            return False
        _layer_source(layer)
        _layer_name(layer)
        return True
    except RuntimeError:
        return False
    except Exception:
        return False


def _is_layer_type(layer, layer_type: str = None) -> bool:
    if not layer_type:
        return True
    if layer_type == "vector":
        return isinstance(layer, QgsVectorLayer)
    if layer_type == "raster":
        return isinstance(layer, QgsRasterLayer)
    return True


def find_existing_layer(path: str = None, name: str = None, layer_type: str = None):
    """Find an existing layer by canonical source path and optional name/type."""
    target_source = _canonical_source(path) if path else ""
    project = QgsProject.instance()
    for layer in project.mapLayers().values():
        if not _layer_is_usable(layer) or not _is_layer_type(layer, layer_type):
            continue
        if target_source and _layer_source(layer) == target_source:
            return layer
        if name and _layer_name(layer) == name:
            return layer
    return None


def _matching_layers(path: str = None, name: str = None, layer_type: str = None):
    target_source = _canonical_source(path) if path else ""
    project = QgsProject.instance()
    matches = []
    for layer in project.mapLayers().values():
        if not _layer_is_usable(layer) or not _is_layer_type(layer, layer_type):
            continue
        source_matches = target_source and _layer_source(layer) == target_source
        name_matches = name and _layer_name(layer) == name
        if source_matches or name_matches:
            matches.append(layer)
    return matches


def _unique_layer_name(base_name: str) -> str:
    project = QgsProject.instance()
    existing_names = {_layer_name(layer) for layer in project.mapLayers().values() if _layer_is_usable(layer)}
    if base_name not in existing_names:
        return base_name
    index = 2
    while f"{base_name} ({index})" in existing_names:
        index += 1
    return f"{base_name} ({index})"


def remove_duplicate_layers(path: str = None, name: str = None, layer_type: str = None, keep_first: bool = True) -> int:
    """Remove duplicate layers matching a path/name. Returns the number of removed layers."""
    matches = _matching_layers(path=path, name=name, layer_type=layer_type)
    if keep_first:
        matches = matches[1:]
    removed = 0
    project = QgsProject.instance()
    for layer in matches:
        layer_id = _layer_id(layer)
        if not layer_id:
            continue
        try:
            project.removeMapLayer(layer_id)
            removed += 1
        except Exception:
            pass
    return removed


def _prepare_duplicate_policy(path: str, name: str, layer_type: str, duplicate_policy: str):
    policy = (duplicate_policy or "reuse").lower()
    if policy not in _DUPLICATE_POLICIES:
        raise ValueError(f"Invalid duplicate_policy '{duplicate_policy}'. Expected one of: {sorted(_DUPLICATE_POLICIES)}")

    existing = find_existing_layer(path=path, layer_type=layer_type)
    if existing and policy == "reuse":
        print(f"[Layer Loader] Reusing existing {layer_type} layer: {_layer_name(existing)}")
        return existing, name

    if existing and policy == "replace":
        removed = remove_duplicate_layers(path=path, layer_type=layer_type, keep_first=False)
        print(f"[Layer Loader] Removed {removed} existing {layer_type} layer(s) before loading: {path}")
        return None, name

    if policy == "rename":
        return None, _unique_layer_name(name)

    return None, name

def load_vector_layer(path: str, layer_name: str = None, duplicate_policy: str = "reuse") -> QgsVectorLayer:
    """Loads a vector layer from a file path and adds it to the current QGIS project."""
    name = layer_name or path.replace('\\', '/').split('/')[-1]
    existing, name = _prepare_duplicate_policy(path, name, "vector", duplicate_policy)
    if existing:
        return existing
    layer = QgsVectorLayer(path, name, "ogr")
    if not layer.isValid():
        raise ValueError(f"Failed to load vector layer from {path}")
    QgsProject.instance().addMapLayer(layer)
    return layer

def load_raster_layer(path: str, layer_name: str = None, duplicate_policy: str = "reuse") -> QgsRasterLayer:
    """Loads a raster layer from a file path and adds it to the current QGIS project."""
    name = layer_name or path.replace('\\', '/').split('/')[-1]
    existing, name = _prepare_duplicate_policy(path, name, "raster", duplicate_policy)
    if existing:
        return existing
    layer = QgsRasterLayer(path, name)
    if not layer.isValid():
        raise ValueError(f"Failed to load raster layer from {path}")
    QgsProject.instance().addMapLayer(layer)
    return layer

def save_layer(layer: QgsVectorLayer, output_path: str):
    """Saves a vector layer to a specified file path."""
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "ESRI Shapefile" if output_path.endswith('.shp') else "GeoJSON"
    error = QgsVectorFileWriter.writeAsVectorFormatV3(layer, output_path, QgsProject.instance().transformContext(), options)
    if error[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Failed to save layer to {output_path}. Error code: {error[0]}")
    return output_path

def open_georeferencer():
    """
    Opens the QGIS Georeferencer window.
    Note: PyQGIS does not currently allow auto-loading a raster into the Georeferencer via Python.
    The user must manually click 'Open Raster' once the window opens.
    """
    try:
        from qgis.utils import iface
        from qgis.PyQt.QtWidgets import QAction
        
        for action in iface.mainWindow().findChildren(QAction):
            if action.objectName() in ['mActionShowGeoreferencer', 'mActionGeoreferencer']:
                action.trigger()
                return True
                
        for action in iface.mainWindow().findChildren(QAction):
            if 'Georeferencer' in action.text() or '地理配准' in action.text() or 'georeferencer' in action.objectName().lower():
                action.trigger()
                return True
                
        print("Failed to open Georeferencer automatically. Menu item not found.")
        return False
    except Exception as e:
        print(f"Error opening Georeferencer: {e}")
        return False
