"""Lazy exports for QGIS helpers.

Importing one workflow should not initialize every GUI, renderer, and processing
module. Symbols are resolved only when a tool actually uses them.
"""

from importlib import import_module


_EXPORTS = {
    "find_existing_layer": ("io_tools", "find_existing_layer"),
    "load_raster_layer": ("io_tools", "load_raster_layer"),
    "load_vector_layer": ("io_tools", "load_vector_layer"),
    "remove_duplicate_layers": ("io_tools", "remove_duplicate_layers"),
    "save_layer": ("io_tools", "save_layer"),
    "buffer": ("geoprocessing_tools", "buffer"),
    "clip": ("geoprocessing_tools", "clip"),
    "clip_raster": ("geoprocessing_tools", "clip_raster"),
    "clip_vector_layers_to_boundary": ("workflow_tools", "clip_vector_layers_to_boundary"),
    "run_osm_acquisition_workflow": ("workflow_tools", "run_osm_acquisition_workflow"),
    "load_external_layer": ("external_data", "load_external_layer"),
    "render_quick_map": ("mapping_tools", "render_quick_map"),
    "open_georeferencer": ("gui_tools", "open_georeferencer"),
    "open_data_source_manager": ("gui_tools", "open_data_source_manager"),
    "open_layout_manager": ("gui_tools", "open_layout_manager"),
    "open_style_manager": ("gui_tools", "open_style_manager"),
    "open_snapping_options": ("gui_tools", "open_snapping_options"),
    "show_attribute_table": ("gui_tools", "show_attribute_table"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, symbol_name = target
    value = getattr(import_module(f"{__name__}.{module_name}"), symbol_name)
    globals()[name] = value
    return value
