from qgis.utils import iface
from qgis.PyQt.QtWidgets import QAction

def _trigger_action_by_name(action_name):
    """Helper to find and trigger a QAction by its objectName."""
    try:
        for action in iface.mainWindow().findChildren(QAction):
            if action.objectName() == action_name:
                action.trigger()
                return True
    except Exception as e:
        print(f"Failed to trigger action {action_name}: {e}")
    return False

def open_georeferencer():
    """
    Opens the QGIS Georeferencer window.
    Use this when the user needs to visually pick GCPs for a raster.
    """
    if _trigger_action_by_name('mActionShowGeoreferencer') or _trigger_action_by_name('mActionGeoreferencer'):
        return True
    # Fallback
    try:
        for action in iface.mainWindow().findChildren(QAction):
            if 'Georeferencer' in action.text() or '地理配准' in action.text():
                action.trigger()
                return True
    except:
        pass
    print("Failed to open Georeferencer automatically.")
    return False

def open_data_source_manager():
    """
    Opens the Data Source Manager window.
    Use this when the user needs to manually configure complex connections (WFS, WMS, PostGIS) that cannot be easily done via code.
    """
    if not _trigger_action_by_name('mActionDataSourceManager'):
        print("Failed to open Data Source Manager.")
        return False
    return True

def open_layout_manager():
    """
    Opens the Layout Manager window.
    Use this if the user wants to manually design or manage print layouts interactively.
    (Note: Simple map exports should be done via code instead).
    """
    if not _trigger_action_by_name('mActionShowLayoutManager'):
        print("Failed to open Layout Manager.")
        return False
    return True

def open_style_manager():
    """
    Opens the Style Manager window.
    Use this if the user needs to manually create or edit complex SVG symbols or color ramps.
    """
    if not _trigger_action_by_name('mActionStyleManager'):
        print("Failed to open Style Manager.")
        return False
    return True

def open_snapping_options():
    """
    Opens the Snapping Options panel.
    Use this when the user is about to manually digitize or edit vector geometries and needs snapping.
    """
    if not _trigger_action_by_name('mActionSnappingOptions'):
        print("Failed to open Snapping Options.")
        return False
    return True

def show_attribute_table(layer):
    """
    Opens the Attribute Table UI for a given layer.
    Use this ONLY when the user explicitly wants to *see* or *inspect* the table in the UI.
    If you just need to read attributes for computation, use PyQGIS features directly.
    """
    try:
        if layer is None or not layer.isValid():
            print("Invalid layer provided to show_attribute_table.")
            return False
        iface.showAttributeTable(layer)
        return True
    except Exception as e:
        print(f"Error opening attribute table: {e}")
        return False
