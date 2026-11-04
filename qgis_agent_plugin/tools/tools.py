from qgis.core import QgsProject, QgsMapLayerType, QgsVectorLayer, QgsRasterLayer, QgsExpression, Qgis
import processing

ATOMIC_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "repair_common_qgis_code_issues",
            "description": (
                "Diagnose and repair high-frequency PyQGIS mistakes seen in QGIS Agent logs. "
                "Use this before retrying failed code when errors mention QGIS API signatures, "
                "QgsColorRampShaderItem, LayerType.toString, numPoints, addMapLayer duplicates, "
                "QgsRasterFileWriter.writeRaster, or OSMDownloader.download_boundary_nominatim."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The PyQGIS code to diagnose and repair. Optional but strongly recommended."
                    },
                    "error_message": {
                        "type": "string",
                        "description": "The traceback, exception message, or failed tool result."
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional task context, logs, or notes that may help choose a repair."
                    }
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"],
            "requires_qgis_main_thread": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clip_vector_layers_to_boundary",
            "description": (
                "P0 workflow tool for clipping multiple vector layers to one boundary layer with explicit "
                "output names. Prefer this over hand-written PyQGIS for OSM/admin/POI batch clipping. "
                "It removes/replaces old output layers safely, loads results with the OGR provider, "
                "optionally creates spatial indexes, and can save/verify the QGIS project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "boundary_layer_name": {
                        "type": "string",
                        "description": "Boundary layer name or layer id used as the clip overlay."
                    },
                    "clip_tasks": {
                        "type": "array",
                        "description": "One task per input layer. Each task needs input_layer_name, output_name, and output_layer_name.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "input_layer_name": {"type": "string"},
                                "output_name": {"type": "string", "description": "File name only, e.g. tianxin_roads_clipped.gpkg."},
                                "output_layer_name": {"type": "string", "description": "Layer name to show in QGIS."}
                            },
                            "required": ["input_layer_name", "output_name", "output_layer_name"]
                        }
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Absolute output directory for clipped files."
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Whether to remove old matching layers/files before clipping. Default true."
                    },
                    "create_spatial_index": {
                        "type": "boolean",
                        "description": "Whether to create spatial indexes for outputs. Default true."
                    },
                    "save_project": {
                        "type": "boolean",
                        "description": "Whether to save and verify the QGIS project after clipping."
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Optional .qgz/.qgs path when save_project is true."
                    }
                },
                "required": ["boundary_layer_name", "clip_tasks", "output_dir"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["file_write", "layer_creation", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_project_and_verify",
            "description": (
                "Save the current QGIS project and verify the saved .qgz/.qgs contains expected layers. "
                "Use at the end of data acquisition, clipping, styling, or analysis tasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Optional .qgz/.qgs path. If empty, uses the current project file path."
                    },
                    "expected_layers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Layer names expected to be persisted in the project file."
                    },
                    "min_layer_count": {
                        "type": "integer",
                        "description": "Minimum number of saved map layers expected. Default 1."
                    }
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["file_write", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_layers",
            "description": "Return a compact summary of current QGIS layers. Prefer this over custom PyQGIS code for layer counts, CRS, geometry type, and sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_sources": {"type": "boolean", "description": "Include layer data sources. Default false."},
                    "max_layers": {"type": "integer", "description": "Maximum layers to return. Default 50."}
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"],
            "requires_qgis_main_thread": True
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cleanup_qgis_project",
            "description": "Clean common QGIS Agent temporary residue: memory output layers, duplicate temp layers, _chunk_*.osm files, and empty WAL files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "remove_memory_output_layers": {"type": "boolean", "description": "Remove memory layers named output or TEMPORARY_OUTPUT. Default true."},
                    "cleanup_chunk_files_dir": {"type": "string", "description": "Optional directory containing _chunk_*.osm files to delete."},
                    "cleanup_wal_files_dir": {"type": "string", "description": "Optional directory to scan for empty .gpkg-wal/.gpkg-shm files."}
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["file_delete", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_project_outputs",
            "description": "Validate expected QGIS layers and output files in one compact call. Use this instead of repeated read_file/list_layers/PyQGIS checks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expected_layers": {"type": "array", "items": {"type": "string"}, "description": "Layer names expected in the project."},
                    "expected_files": {"type": "array", "items": {"type": "string"}, "description": "Absolute file paths expected on disk."},
                    "include_layer_details": {"type": "boolean", "description": "Include compact per-layer CRS/type/count details. Default true."}
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"],
            "requires_qgis_main_thread": True
        }
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_raster_file",
            "description": "Inspect a raster file with GDAL/QGIS and force a real read to catch corrupt GeoTIFF blocks before clipping or raster math.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the raster file."},
                    "force_read": {"type": "boolean", "description": "Force checksum/statistics reads to catch block-level corruption. Default true."}
                },
                "required": ["file_path"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"],
            "requires_qgis_main_thread": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_raster_has_data",
            "description": "Validate that a raster has readable bands and usable non-NoData pixels. Use before NDVI, band math, clipping results, or map styling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the raster file."},
                    "bands": {"type": "array", "items": {"type": "integer"}, "description": "Optional 1-based band numbers to validate."},
                    "min_valid_percent": {"type": "number", "description": "Minimum valid pixel percent required per checked band. Default 0.01."},
                    "force_read": {"type": "boolean", "description": "Force checksum/statistics reads. Default true."}
                },
                "required": ["file_path"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"],
            "requires_qgis_main_thread": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compute_raster_zonal_stats",
            "description": (
                "Compute per-band statistics (min, max, mean, std) for a multi-band raster layer or file, "
                "with optional binary mask target/background separability (Cohen's d, AUC) and automatic "
                "ranking of the best normalized-difference index band pairs (Bi-Bj)/(Bi+Bj). Prefer this "
                "over writing raw GDAL/NumPy scripts for band/mask statistics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_layer_or_path": {
                        "type": "string",
                        "description": "Loaded QGIS raster layer name/id or absolute path to the raster file."
                    },
                    "mask_layer_or_path": {
                        "type": "string",
                        "description": "Optional binary mask layer name/id or raster file path."
                    },
                    "mask_valid_value": {
                        "type": "number",
                        "description": "Mask pixel value representing the target zone. Default 1."
                    },
                    "rank_band_pairs": {
                        "type": "boolean",
                        "description": "Rank all normalized-difference band pairs by |Cohen's d| and AUC when a mask is provided. Default true."
                    }
                },
                "required": ["source_layer_or_path"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"],
            "requires_qgis_main_thread": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compute_raster_index",
            "description": (
                "Safely compute a normalized-difference spectral index (Band_A - Band_B) / (Band_A + Band_B) "
                "such as NDVI, NDWI, MNDWI, NDMI, NDBI, or NBR in float32. Automatically prevents UInt16 "
                "integer underflow in gdal:rastercalculator, applies an optional binary mask, safely releases "
                "Windows file locks if the output path is already loaded in QGIS, writes an LZW GeoTIFF, and "
                "loads/validates the output layer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_layer_or_path": {
                        "type": "string",
                        "description": "Loaded QGIS raster layer name/id or absolute path to the multi-band raster."
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Absolute output GeoTIFF (.tif) path."
                    },
                    "band_a": {
                        "type": "integer",
                        "description": "1-based band index for A in (A - B) / (A + B), e.g. NIR band for NDVI or Green band for NDWI."
                    },
                    "band_b": {
                        "type": "integer",
                        "description": "1-based band index for B in (A - B) / (A + B), e.g. Red band for NDVI or NIR/SWIR band for NDWI."
                    },
                    "index_name": {
                        "type": "string",
                        "description": "Band description / index label such as 'NDVI', 'NDWI', or 'NDMI'. Default 'INDEX'."
                    },
                    "mask_layer_or_path": {
                        "type": "string",
                        "description": "Optional binary mask layer name/id or file path; pixels != mask_valid_value become NoData (-9999)."
                    },
                    "mask_valid_value": {
                        "type": "number",
                        "description": "Mask pixel value treated as valid area. Default 1."
                    },
                    "clip_range": {
                        "type": "boolean",
                        "description": "Mask out-of-range values outside [-1, 1] as NoData. Default true."
                    },
                    "load_layer": {
                        "type": "boolean",
                        "description": "Load the resulting GeoTIFF into the active QGIS project. Default true."
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Optional QGIS layer name for the loaded output."
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Allow replacing an existing output file (safely unloading locked QGIS layers first). Default true."
                    }
                },
                "required": ["source_layer_or_path", "output_path", "band_a", "band_b"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["file_write", "layer_creation", "project_mutation"],
            "path_scope": "project_or_temp_output",
            "requires_qgis_main_thread": True
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_gee_sentinel2_download_workflow",
            "description": (
                "Download user-specified Sentinel-2 bands from Google Earth Engine after the user has explicitly confirmed "
                "dataset, date range, bands, cloud filter, scale, and processing method. Do not use this tool with guessed defaults."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "boundary_layer_name": {"type": "string", "description": "QGIS boundary layer name or id used as the study area."},
                    "output_dir": {"type": "string", "description": "Absolute output directory."},
                    "output_name": {"type": "string", "description": "Output GeoTIFF filename, e.g. yuhua_sentinel2_b4328.tif."},
                    "collection_id": {
                        "type": "string",
                        "enum": ["COPERNICUS/S2_SR_HARMONIZED", "COPERNICUS/S2_HARMONIZED"],
                        "description": "Confirmed supported Sentinel-2 ImageCollection id."
                    },
                    "start_date": {"type": "string", "description": "Confirmed start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "Confirmed end date YYYY-MM-DD."},
                    "bands": {"type": "array", "items": {"type": "string"}, "description": "Confirmed Sentinel-2 band names to export, e.g. B2,B3,B4,B8 or B4,B3,B2."},
                    "cloud_pct": {"type": "number", "description": "Confirmed maximum CLOUDY_PIXEL_PERCENTAGE."},
                    "scale": {"type": "number", "description": "Confirmed export scale in meters."},
                    "crs": {"type": "string", "description": "Confirmed output CRS, e.g. EPSG:4326 or a local projected CRS."},
                    "processing_method": {"type": "string", "enum": ["median", "cloud_masked_median", "mosaic", "least_cloudy"], "description": "Confirmed processing method. Use cloud_masked_median only when user asks for cloud masking."},
                    "user_confirmed_parameters": {"type": "boolean", "description": "Must be true only after the user explicitly provided or confirmed all Sentinel-2 download parameters."},
                    "min_valid_percent": {"type": "number", "description": "Minimum valid pixel percent after download. Default 0.01."},
                    "load_layer": {"type": "boolean", "description": "Load the output layer into QGIS. Default true."},
                    "apply_renderer": {"type": "boolean", "description": "Reserved for future generic renderers. Default false."}
                },
                "required": ["boundary_layer_name", "output_dir", "output_name", "collection_id", "start_date", "end_date", "bands", "cloud_pct", "scale", "crs", "processing_method", "user_confirmed_parameters", "load_layer"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["network_request", "file_write", "layer_creation", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_gee_dem_download_workflow",
            "description": (
                "Download a user-confirmed DEM from Google Earth Engine with the plugin's smart Drive routing, "
                "validate the GeoTIFF, and optionally load it into QGIS. Prefer this over hand-written GEE DEM code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "boundary_layer_name": {"type": "string", "description": "QGIS boundary layer name or id used as the study area."},
                    "output_dir": {"type": "string", "description": "Absolute output directory."},
                    "output_name": {"type": "string", "description": "Output GeoTIFF filename, e.g. lasa_dem.tif."},
                    "dataset_id": {"type": "string", "description": "Confirmed DEM dataset id. Supported: COPERNICUS/DEM/GLO30, NASA/NASADEM_HGT/001, USGS/SRTMGL1_003."},
                    "scale": {"type": "number", "description": "Confirmed export scale in meters. Default 30."},
                    "crs": {"type": "string", "description": "Confirmed output CRS. Default EPSG:4326."},
                    "simplify_tolerance": {"type": "number", "description": "Optional user-confirmed boundary simplification tolerance in degrees. Default 0 (no simplification)."},
                    "user_confirmed_parameters": {"type": "boolean", "description": "Must be true only after the user explicitly provided or approved DEM dataset, scale, CRS, and output name."},
                    "min_valid_percent": {"type": "number", "description": "Minimum valid pixel percent after download. Default 0.01."},
                    "load_layer": {"type": "boolean", "description": "Load the output DEM layer into QGIS. Default true."}
                },
                "required": ["boundary_layer_name", "output_dir", "output_name", "dataset_id", "scale", "crs", "user_confirmed_parameters", "load_layer"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["network_request", "file_write", "layer_creation", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_qgis_workflow_batch",
            "description": "Run a small batch of registered low/medium-risk workflow tools in sequence to reduce LLM round trips. Each step has action and arguments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "description": "Allowed: summarize_layers, cleanup_qgis_project, validate_project_outputs, inspect_raster_file, validate_raster_has_data, save_project_and_verify, download_osm_features, clip_vector_layers_to_boundary, run_gee_sentinel2_download_workflow, run_gee_dem_download_workflow, run_processing_algorithm."},
                                "arguments": {"type": "object", "description": "Arguments passed to the selected action."}
                            },
                            "required": ["action"]
                        }
                    },
                    "stop_on_error": {"type": "boolean", "description": "Stop at first failed step. Default true."}
                },
                "required": ["steps"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["file_write", "layer_creation", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "install_python_package",
            "description": "当你在执行代码时遇到 ImportError 或 ModuleNotFoundError 时，调用此工具安全地安装缺失的 Python 库（如 openpyxl, pandas）。请勿在代码里自行调用 subprocess 运行 pip。",
            "parameters": {
                "type": "object",
                "properties": {
                    "package_name": {
                        "type": "string",
                        "description": "The name of the package to install."
                    }
                },
                "required": ["package_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_gee_api",
            "description": "Search the internal Google Earth Engine Python API knowledge base by keyword. Returns the official Python signatures, arguments, and descriptions for matching APIs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The API name or keyword to search for, e.g. 'randomForest', 'reduceRegion', 'ImageCollection.filter'"
                    }
                },
                "required": ["query"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_data_sources",
            "description": "Search the built-in GIS data source handbook. Use this before downloading data to choose reliable sources, access methods, licenses, and limitations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language data need, e.g. 'roads for a city', 'Sentinel-2 imagery', 'population raster'."
                    },
                    "theme": {
                        "type": "string",
                        "description": "Optional theme filter such as roads, boundary, imagery, dem, population, land cover."
                    },
                    "geometry_type": {
                        "type": "string",
                        "description": "Optional geometry filter: vector, raster, point, line, polygon, table."
                    },
                    "region": {
                        "type": "string",
                        "description": "Optional region or place name for ranking and notes."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of sources to return, default 5."
                    },
                    "allow_auth": {
                        "type": "boolean",
                        "description": "False excludes sources that require authentication."
                    },
                    "allow_network": {
                        "type": "boolean",
                        "description": "False excludes online sources and returns offline/project sources only."
                    }
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_data_acquisition_plan",
            "description": "Create a source-aware data acquisition plan from the handbook, including recommended sources, QGIS workflow steps, licensing notes, and storage guidance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The GIS task or test objective that needs data."
                    },
                    "region": {
                        "type": "string",
                        "description": "Optional place name or study area."
                    },
                    "data_type": {
                        "type": "string",
                        "description": "Optional data type/theme such as roads, boundary, imagery, dem, population, land cover."
                    },
                    "bbox": {
                        "type": "string",
                        "description": "Optional EPSG:4326 bbox 'min_lon,min_lat,max_lon,max_lat'."
                    },
                    "preferred_source_id": {
                        "type": "string",
                        "description": "Optional handbook source id to force as the primary source."
                    },
                    "output_folder": {
                        "type": "string",
                        "description": "Project-relative folder for downloaded/generated data, default data."
                    }
                },
                "required": ["task"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_layers",
            "description": "List all vector and raster layers in the current QGIS project.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "zoom_to_layer",
            "description": "Zoom the map canvas to the extent of a specific layer by its exact name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "The exact name of the layer to zoom to."
                    }
                },
                "required": ["layer_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_layer_visibility",
            "description": "Turn the visibility of a specific layer on or off.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "The exact name of the layer."
                    },
                    "visible": {
                        "type": "boolean",
                        "description": "True to show, False to hide."
                    }
                },
                "required": ["layer_name", "visible"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_layer_fields",
            "description": "Get a list of fields and their data types for a vector layer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "The exact name of the vector layer."
                    }
                },
                "required": ["layer_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_selected_features",
            "description": "Get a summary of the currently selected features in a vector layer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "The exact name of the vector layer."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of features to return (default 10)."
                    }
                },
                "required": ["layer_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "select_features_by_expression",
            "description": "Select features in a vector layer using a QGIS expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "The exact name of the vector layer."
                    },
                    "expression": {
                        "type": "string",
                        "description": "A valid QGIS expression (e.g. \"type\" = 'road' or \"area\" > 1000)."
                    }
                },
                "required": ["layer_name", "expression"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_selection",
            "description": "Clear the selection of a specific layer or all layers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "The name of the layer to clear selection from. If omitted, clears all selections across all layers."
                    }
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "zoom_to_selected",
            "description": "Zoom the map canvas to the bounding box of the currently selected features of a layer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "The name of the layer with selected features."
                    }
                },
                "required": ["layer_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_processing_algorithm",
            "description": "Run a QGIS processing algorithm safely. It automatically handles 'TEMPORARY_OUTPUT' strings for output parameters. Returns the log and generated layer IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alg_id": {
                        "type": "string",
                        "description": "The processing algorithm ID (e.g. 'native:buffer', 'gdal:slope', 'gdal:contour')."
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Dictionary of algorithm parameters. For inputs, use layer IDs or names. For memory outputs, use the string 'TEMPORARY_OUTPUT'."
                    }
                },
                "required": ["alg_id", "parameters"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_processing_algorithms",
            "description": "Search the local QGIS Processing Toolbox catalog built from the current QgsApplication.processingRegistry(). Use this before choosing an unfamiliar processing alg_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language or keyword query, e.g. '缓冲区 buffer', 'raster slope', '按位置选择'."
                    },
                    "provider": {
                        "type": "string",
                        "description": "Optional provider id filter such as native, gdal, grass, qgis."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of candidates to return. Default 8."
                    }
                },
                "required": ["query"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "describe_processing_algorithm",
            "description": "Return the exact signature of a QGIS Processing algorithm, including parameter names, parameter types, required flags, outputs, and example parameters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alg_id": {
                        "type": "string",
                        "description": "The exact processing algorithm id, e.g. native:buffer."
                    }
                },
                "required": ["alg_id"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_processing_algorithm_call",
            "description": "Validate a QGIS Processing algorithm id and parameters against the live Processing registry without executing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alg_id": {
                        "type": "string",
                        "description": "The processing algorithm id to validate."
                    },
                    "parameters": {
                        "type": "object",
                        "description": "The parameter dictionary intended for run_processing_algorithm."
                    }
                },
                "required": ["alg_id", "parameters"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_qgis_expression_functions",
            "description": "Search the local catalog of QGIS expression functions. Use before writing unfamiliar selection, labeling, or field calculator expressions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Function name or task keyword, e.g. 'area', 'geometry', '字符串', 'attribute'."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of functions to return. Default 8."
                    }
                },
                "required": ["query"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "describe_qgis_expression_function",
            "description": "Return exact help, group, tags, and parameters for one QGIS expression function.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The exact QGIS expression function name."
                    }
                },
                "required": ["name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_qgis_expression",
            "description": "Validate a QGIS expression and optionally check that referenced fields exist in a specific vector layer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The QGIS expression to validate."
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Optional vector layer name or id for field validation."
                    }
                },
                "required": ["expression"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_project_layers",
            "description": "Search currently loaded QGIS project layers by name, id, type, geometry, or field names. Use before referring to layer names.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search text. Leave empty to list layers compactly."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of layers to return. Default 20."
                    }
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "describe_project_layer",
            "description": "Describe a loaded QGIS layer by exact name or id, including source, CRS, geometry, feature count, and fields.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer name or id."
                    }
                },
                "required": ["layer_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_layer_fields",
            "description": "Search fields in a loaded vector layer by field name or type. Use before writing expressions that reference attributes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer name or id."
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional field search text."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of fields to return. Default 20."
                    }
                },
                "required": ["layer_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rebuild_qgis_catalog",
            "description": "Rebuild the local QGIS Agent catalog for Processing algorithms, parameter types, and expression functions after providers or plugins change.",
            "parameters": {
                "type": "object",
                "properties": {
                    "force": {
                        "type": "boolean",
                        "description": "Force rebuilding even if the cached signature appears current. Default true."
                    }
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only"]
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_geodatabase",
            "description": "Create a new GeoPackage database (the QGIS native equivalent of a file geodatabase) and optionally create a new empty vector layer in it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "database_path": {
                        "type": "string",
                        "description": "Absolute path to the new .gpkg file (e.g. 'D:/project/data/mydb.gpkg')."
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Optional name of an initial empty vector layer to create inside the database."
                    },
                    "geometry_type": {
                        "type": "string",
                        "description": "Geometry type for the initial layer (e.g. 'Point', 'LineString', 'Polygon'). Required if layer_name is provided."
                    },
                    "crs": {
                        "type": "string",
                        "description": "EPSG code for the layer (e.g. 'EPSG:4326'). Required if layer_name is provided."
                    }
                },
                "required": ["database_path"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_pyqgis_doc",
            "description": "Perform Native RAG by introspecting a PyQGIS module or class to get its exact methods, properties, and docstrings. Use this if you are unsure about the PyQGIS API before writing scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_name": {
                        "type": "string",
                        "description": "The exact name of the QGIS class or module to inspect (e.g., 'QgsVectorLayer', 'QgsFeatureRequest', 'QgsGeometry')."
                    }
                },
                "required": ["target_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "download_osm_data",
            "description": "Download OpenStreetMap data using the Overpass API based on a bounding box and OSM tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bbox": {
                        "type": "string",
                        "description": "Bounding box string 'min_lon,min_lat,max_lon,max_lat' (e.g. '116.3,39.9,116.4,40.0'). Must be in WGS84 (EPSG:4326)."
                    },
                    "tags": {
                        "type": "string",
                        "description": "OSM tags in Overpass QL format, e.g. 'node[\"amenity\"=\"hospital\"]' or 'way[\"highway\"]'."
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the imported QGIS layer."
                    },
                    "geometry_type": {
                        "type": "string",
                        "description": "OSM GDAL sublayer to load: points, lines, multilinestrings, multipolygons, or other_relations. Default lines."
                    }
                },
                "required": ["bbox", "tags", "layer_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "download_osm_boundary",
            "description": "Download a named place boundary from OSM Nominatim as GeoJSON and load it into QGIS. Prefer this for campuses, districts, cities, and administrative boundaries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Place name to search, e.g. 成都理工大学 or 北京市."},
                    "output_file": {"type": "string", "description": "Absolute output GeoJSON path inside the project folder."},
                    "layer_name": {"type": "string", "description": "Optional QGIS layer name."},
                    "overwrite": {"type": "boolean", "description": "Whether to overwrite an existing output file. Default false."}
                },
                "required": ["name", "output_file"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["network_request", "file_write", "layer_creation", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "download_osm_roads",
            "description": "Download and topologically clean an OSM road or water network from an existing boundary layer using OSMnx, then save it as .gpkg/.geojson/.shp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "boundary_layer_name": {"type": "string", "description": "Existing polygon boundary layer name."},
                    "output_file": {"type": "string", "description": "Absolute output path, preferably .gpkg."},
                    "network_type": {"type": "string", "enum": ["roads", "water"], "description": "Network type. Default roads."},
                    "overwrite": {"type": "boolean", "description": "Whether to overwrite an existing output file. Default false."}
                },
                "required": ["boundary_layer_name", "output_file"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["network_request", "file_write", "layer_creation", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "download_osm_features",
            "description": "Download templated OSM features such as buildings, POI, waterways, water, or landuse by bbox or boundary layer. Supports bbox splitting and saves final output as .gpkg/.geojson/.shp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "boundary_layer_name": {"type": "string", "description": "Optional existing boundary layer name. Used to derive bbox if bbox is omitted."},
                    "bbox": {"type": "string", "description": "Optional bbox 'min_lon,min_lat,max_lon,max_lat' in EPSG:4326."},
                    "preset": {"type": "string", "enum": ["buildings", "roads", "waterways", "water", "poi", "landuse"], "description": "Feature template. Default buildings."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional explicit OSM tag expressions such as way[\"building\"]. Overrides preset."},
                    "geometry_type": {"type": "string", "description": "OSM GDAL sublayer: points, lines, multilinestrings, multipolygons, or other_relations."},
                    "output_file": {"type": "string", "description": "Absolute output path, preferably .gpkg."},
                    "layer_name": {"type": "string", "description": "QGIS layer name for the final output."},
                    "split_large_bbox": {"type": "boolean", "description": "Split large bbox into smaller Overpass requests. Default true."},
                    "max_chunk_area": {"type": "number", "description": "Maximum chunk area in square degrees. Default 0.25."},
                    "overwrite": {"type": "boolean", "description": "Whether to overwrite an existing output file. Default false."}
                },
                "required": ["output_file", "layer_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["network_request", "file_write", "layer_creation", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_external_layer",
            "description": (
                "Load a vector or raster file located outside the current QGIS project folder. "
                "Reading the external source never modifies it. Set copy_to_project=true only when the user asks "
                "to make a project-local streamed copy before loading."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "Absolute path to an existing external data file."},
                    "layer_name": {"type": "string", "description": "Optional QGIS layer name."},
                    "layer_type": {"type": "string", "enum": ["auto", "vector", "raster"], "description": "Expected layer type. Default auto."},
                    "copy_to_project": {"type": "boolean", "description": "Copy into the saved project folder before loading. Default false."},
                    "target_file_name": {"type": "string", "description": "Optional destination file name when copy_to_project is true."},
                    "overwrite": {"type": "boolean", "description": "Allow replacing an existing project-local copy. Default false."}
                },
                "required": ["source_path"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["read_only", "file_write", "layer_creation", "project_mutation"],
            "path_scope": "external_read_or_project_copy"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_osm_acquisition_workflow",
            "description": (
                "Continuously download and verify a named area's OSM boundary plus requested roads, buildings, POI, "
                "waterways, and water polygons in one tool call. Prefer this when the user requests multiple OSM datasets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "place_name": {"type": "string", "description": "Named place for Nominatim boundary lookup."},
                    "output_dir": {"type": "string", "description": "Absolute output directory inside the project workspace."},
                    "output_prefix": {"type": "string", "description": "Safe prefix for output files and QGIS layers."},
                    "components": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["roads", "buildings", "poi", "waterways", "water"]},
                        "description": "Requested components. Default includes all five components. Boundary is always downloaded first."
                    },
                    "max_chunk_area": {"type": "number", "description": "Maximum Overpass chunk area in square degrees. Default 0.25."},
                    "overwrite": {"type": "boolean", "description": "Replace existing workflow outputs. Default false."},
                    "continue_on_error": {"type": "boolean", "description": "Continue with independent components after one component fails. Default true."},
                    "save_project": {"type": "boolean", "description": "Save and verify the QGIS project after successful acquisition. Default false."},
                    "project_path": {"type": "string", "description": "Optional .qgz path used when save_project is true."}
                },
                "required": ["place_name", "output_dir", "output_prefix"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "side_effects": ["network_request", "file_write", "layer_creation", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_qgis_layers_and_data",
            "description": (
                "Remove selected QGIS layers or every layer in the current project, and optionally delete their "
                "file-backed source datasets. This is a destructive operation. Use it only after the user has "
                "explicitly confirmed the scope. It never deletes the QGIS project file itself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["all_layers", "named_layers"],
                        "description": "all_layers removes every currently loaded map layer. named_layers removes only layer_names."
                    },
                    "layer_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact layer names or layer IDs when scope is named_layers."
                    },
                    "delete_source_files": {
                        "type": "boolean",
                        "description": "Also delete local source datasets after removing layers. Remote, memory, and shared unselected sources are retained."
                    },
                    "delete_sidecars": {
                        "type": "boolean",
                        "description": "Delete recognised sidecar files (.shx/.dbf/.prj, world files, GPKG WAL/SHM) with a deleted source. Default true."
                    },
                    "save_project": {
                        "type": "boolean",
                        "description": "Persist removed layers to the current QGIS project. Default true."
                    }
                },
                "required": ["scope", "delete_source_files"]
            }
        },
        "metadata": {
            "destructive": True,
            "requires_confirmation": True,
            "side_effects": ["file_delete", "project_mutation"],
            "path_scope": "project_or_temp_output"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": "Read the full contents of a skill card. Use this to understand specific business rules or API quirks before writing code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "The exact name of the skill (e.g. 'gee_execution')."
                    }
                },
                "required": ["skill_name"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_or_update_dynamic_skill",
            "description": "Save a new dynamic skill or update an existing one. Use this ONLY after you have successfully fixed a complex bug or learned a new user preference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "The name of the skill (e.g. 'default_symbology')."
                    },
                    "description": {
                        "type": "string",
                        "description": "A short summary of what this skill is about (Required if action is 'create')."
                    },
                    "rules": {
                        "type": "string",
                        "description": "The precise rules, gotchas, or code templates to remember."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["create", "update"],
                        "description": "Whether to create a new skill or update/append to an existing one."
                    }
                },
                "required": ["skill_name", "rules", "action"]
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_or_update_user_tool",
            "description": (
                "Create or update a user-scoped executable tool candidate after the user explicitly approves "
                "the requested capability. The source must define run(iface, arguments). This never edits "
                "the plugin's core code and the candidate is not registered for future tasks until it passes "
                "a test and register_user_tool_extension is approved."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "A unique user tool name beginning with user_, for example user_clear_cache_usage_log."
                    },
                    "description": {
                        "type": "string",
                        "description": "Concise capability, scope, expected output, and important side effects."
                    },
                    "parameters_schema": {
                        "type": "object",
                        "description": "JSON Schema object for the tool arguments. It must contain type=object, properties, and required."
                    },
                    "source_code": {
                        "type": "string",
                        "description": "Python source defining exactly run(iface, arguments). No markdown fences, subprocesses, package installation, or dynamic eval/exec."
                    },
                    "domains": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["osm", "gee", "processing", "mapping", "selection", "files", "workflow", "database", "general"]
                        },
                        "description": "Domains that should expose the registered tool in future task tool packs. Default general."
                    }
                },
                "required": ["tool_name", "description", "parameters_schema", "source_code"]
            }
        },
        "metadata": {
            "destructive": True,
            "requires_confirmation": True,
            "requires_qgis_main_thread": False,
            "side_effects": ["file_write", "code_execution"],
            "path_scope": "user_extension"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_user_tool_extension",
            "description": (
                "Run a user-scoped candidate or registered tool after approval. Use this to test a candidate "
                "in the current task; only a successful and verified candidate can later be registered."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "The saved user_ tool name."},
                    "arguments": {"type": "object", "description": "Arguments matching the candidate tool's parameters_schema."}
                },
                "required": ["tool_name"]
            }
        },
        "metadata": {
            "destructive": True,
            "requires_confirmation": True,
            "side_effects": ["code_execution"],
            "path_scope": "user_extension"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "register_user_tool_extension",
            "description": (
                "Register a successfully tested user tool for future tasks. Requires at least one successful "
                "candidate execution and explicit approval. Registration takes effect only when a later task starts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "The tested candidate tool name."},
                    "verification_summary": {"type": "string", "description": "What was tested and which concrete result was verified."}
                },
                "required": ["tool_name", "verification_summary"]
            }
        },
        "metadata": {
            "destructive": True,
            "requires_confirmation": True,
            "requires_qgis_main_thread": False,
            "side_effects": ["file_write"],
            "path_scope": "user_extension"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_user_tool_extensions",
            "description": "List registered and candidate user-scoped executable tools without exposing their source code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_candidates": {"type": "boolean", "description": "Include unregistered candidate tools. Default true."}
                },
                "required": []
            }
        },
        "metadata": {
            "destructive": False,
            "requires_confirmation": False,
            "requires_qgis_main_thread": False,
            "side_effects": ["read_only"],
            "path_scope": "user_extension"
        }
    }
]

def execute_atomic_tool_structured(
    iface,
    tool_name,
    kwargs,
    progress_callback=None,
    cancel_callback=None,
):
    result = execute_atomic_tool(
        iface,
        tool_name,
        kwargs,
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )
    try:
        from ..core.tool_result import normalize_tool_output
        return normalize_tool_output(tool_name, result)
    except Exception:
        return result


def _emit_acquisition_progress(
    callback,
    tool_name,
    title,
    stage,
    stage_index,
    stage_count,
    stage_percent=None,
    detail="",
    state="running",
):
    from ..core.progress import emit_progress

    return emit_progress(
        callback,
        tool_name=tool_name,
        title=title,
        stage=stage,
        stage_index=stage_index,
        stage_count=stage_count,
        stage_percent=stage_percent,
        detail=detail,
        state=state,
    )


def _artifact_entry(path: str, artifact_type: str, description: str):
    return {"type": artifact_type, "path": path, "description": description}


def _find_project_layer(layer_name: str):
    for layer in QgsProject.instance().mapLayers().values():
        if layer.name() == layer_name or layer.id() == layer_name:
            return layer
    return None


def _remove_existing_output(output_file: str) -> None:
    import os
    from pathlib import Path

    if not os.path.exists(output_file):
        return
    path = Path(output_file)
    if path.is_dir():
        raise ValueError(f"Refusing to overwrite directory output: {output_file}")
    try:
        from .qgis_tools.io_tools import _canonical_source
        from qgis.core import QgsProject

        target = _canonical_source(output_file).split("|", 1)[0]
        project = QgsProject.instance()
        remove_ids = []
        for layer_id, layer in project.mapLayers().items():
            try:
                source = _canonical_source(layer.source()).split("|", 1)[0]
                if source == target:
                    remove_ids.append(layer_id)
            except Exception:
                continue
        for layer_id in remove_ids:
            project.removeMapLayer(layer_id)
    except Exception:
        pass
    # GeoPackage is overwritten by QgsVectorFileWriter after loaded layers have
    # been released. Other formats still require sidecar cleanup.
    if path.suffix.lower() != ".gpkg":
        os.remove(output_file)
    if path.suffix.lower() == ".shp":
        for suffix in (".dbf", ".shx", ".prj", ".cpg", ".qix"):
            sidecar = path.with_suffix(suffix)
            if sidecar.exists():
                sidecar.unlink()


def _ensure_output_available(output_file: str, overwrite: bool) -> None:
    import os

    if os.path.exists(output_file):
        if not overwrite:
            raise FileExistsError(f"Output already exists: {output_file}. Set overwrite=true to replace it.")
        _remove_existing_output(output_file)


def _vector_driver_for_path(output_file: str):
    from pathlib import Path

    suffix = Path(output_file).suffix.lower()
    if suffix == ".gpkg":
        return "GPKG", output_file
    if suffix in {".geojson", ".json"}:
        return "GeoJSON", output_file
    if suffix == ".shp":
        return "ESRI Shapefile", output_file
    raise ValueError("Unsupported output format. Use .gpkg, .geojson, or .shp.")


def _save_vector_layer(layer, output_file: str, layer_name: str):
    from qgis.core import QgsVectorFileWriter
    import os

    driver, load_uri = _vector_driver_for_path(output_file)
    parent = os.path.dirname(output_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    if driver == "GPKG":
        options.layerName = layer_name
        if os.path.exists(output_file):
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
    result = QgsVectorFileWriter.writeAsVectorFormatV2(
        layer,
        output_file,
        QgsProject.instance().transformContext(),
        options,
    )
    error = result[0] if isinstance(result, tuple) else result
    if error != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Failed to save vector layer to {output_file}: {result}")
    if driver == "GPKG":
        return f"{output_file}|layername={layer_name}"
    return load_uri


def _bbox_from_layer(layer):
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

    extent = layer.extent()
    if layer.crs().isValid() and layer.crs().authid() != "EPSG:4326":
        transform = QgsCoordinateTransform(
            layer.crs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance(),
        )
        extent = transform.transformBoundingBox(extent)
    return (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())


def _deduplicate_vector_layer(layer, layer_name: str):
    """Return an in-memory layer deduplicated by OSM id or exact geometry."""
    from qgis.core import QgsFeature, QgsVectorLayer, QgsWkbTypes

    crs = layer.crs().authid() if layer.crs().isValid() else "EPSG:4326"
    geometry_name = QgsWkbTypes.displayString(layer.wkbType())
    output = QgsVectorLayer(f"{geometry_name}?crs={crs}", layer_name, "memory")
    provider = output.dataProvider()
    provider.addAttributes(layer.fields())
    output.updateFields()
    field_names = [field.name() for field in layer.fields()]
    osm_id_index = field_names.index("osm_id") if "osm_id" in field_names else -1
    seen = set()
    features = []
    for source_feature in layer.getFeatures():
        osm_id = source_feature.attribute(osm_id_index) if osm_id_index >= 0 else None
        if osm_id not in (None, "", "NULL"):
            key = ("osm_id", str(osm_id))
        else:
            geometry_key = bytes(source_feature.geometry().asWkb()) if source_feature.hasGeometry() else b""
            key = ("geometry", geometry_key, tuple(str(value) for value in source_feature.attributes()))
        if key in seen:
            continue
        seen.add(key)
        feature = QgsFeature(output.fields())
        feature.setAttributes(source_feature.attributes())
        if source_feature.hasGeometry():
            feature.setGeometry(source_feature.geometry())
        features.append(feature)
    provider.addFeatures(features)
    output.updateExtents()
    return output


def _execute_osm_feature_download(kwargs, progress_callback=None, cancel_callback=None):
    import os
    import shutil
    import tempfile
    from ..bridges.osm_bridge import (
        OSMDownloader,
        classify_overpass_error,
        build_bbox_query,
        parse_bbox,
        resolve_tag_template,
        safe_feature_count,
        split_bbox,
        bbox_area,
    )
    from ..core.tool_result import ToolResult
    from ..core.validators import sanitize_file_stem

    output_file = kwargs.get("output_file")
    layer_name = kwargs.get("layer_name") or sanitize_file_stem(os.path.splitext(os.path.basename(output_file))[0], "osm_features")
    overwrite = bool(kwargs.get("overwrite", False))
    split_large_bbox = kwargs.get("split_large_bbox", True)
    max_chunk_area = float(kwargs.get("max_chunk_area", 0.25) or 0.25)
    tmp_dir = ""
    tool_name = "download_osm_features"
    title = "OSM 要素下载"

    try:
        from ..core.progress import raise_if_cancelled
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "准备查询", 1, 5, 0,
            "正在验证范围、标签和输出路径。",
        )
        raise_if_cancelled(cancel_callback, "OSM feature download was cancelled by the user.")
        _ensure_output_available(output_file, overwrite)
        tags, geometry_type = resolve_tag_template(
            preset=kwargs.get("preset", "buildings"),
            tags=kwargs.get("tags"),
            geometry_type=kwargs.get("geometry_type", ""),
        )
        bbox_value = kwargs.get("bbox")
        if bbox_value:
            bbox = parse_bbox(bbox_value)
        else:
            boundary_layer_name = kwargs.get("boundary_layer_name")
            boundary_layer = _find_project_layer(boundary_layer_name)
            if boundary_layer is None:
                return ToolResult.failure(
                    "boundary_layer_name was not found and bbox was not provided.",
                    error_type="qgis_layer_error",
                    data={"boundary_layer_name": boundary_layer_name},
                ).to_dict()
            bbox = parse_bbox(_bbox_from_layer(boundary_layer))

        chunks = split_bbox(bbox, max_area=max_chunk_area) if split_large_bbox else [bbox]
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "准备查询", 1, 5, 100,
            f"已生成 {len(chunks)} 个初始下载分块。",
        )
        tmp_dir = tempfile.mkdtemp(prefix="qgis_agent_osm_")
        loaded_layers = []
        chunk_records = []

        queue = list(chunks)
        index = 0
        while queue:
            raise_if_cancelled(cancel_callback, "OSM feature download was cancelled by the user.")
            chunk = queue.pop(0)
            index += 1
            completed_chunks = len(loaded_layers)
            current_total = max(1, completed_chunks + len(queue) + 1)
            _emit_acquisition_progress(
                progress_callback,
                tool_name,
                title,
                "下载 Overpass 分块",
                2,
                5,
                completed_chunks / current_total * 100.0,
                f"正在请求分块 {completed_chunks + 1}/{current_total}。",
            )
            query = build_bbox_query(tags, chunk, geometry_type=geometry_type, timeout_seconds=180)
            chunk_osm = os.path.join(tmp_dir, f"{sanitize_file_stem(layer_name, 'osm')}_{index:03d}.osm")

            def _chunk_transfer(received, total, endpoint):
                pending_total = max(1, len(loaded_layers) + len(queue) + 1)
                if total > 0:
                    current_ratio = min(1.0, max(0.0, received / total))
                    stage_percent = (len(loaded_layers) + current_ratio) / pending_total * 100.0
                    size_detail = f"{received / (1024 * 1024):.1f}/{total / (1024 * 1024):.1f} MB"
                else:
                    stage_percent = None
                    size_detail = f"已接收 {received / (1024 * 1024):.1f} MB"
                _emit_acquisition_progress(
                    progress_callback,
                    tool_name,
                    title,
                    "下载 Overpass 分块",
                    2,
                    5,
                    stage_percent,
                    f"分块 {len(loaded_layers) + 1}/{pending_total} · {size_detail} · {endpoint}",
                )

            try:
                OSMDownloader.query_osm(
                    query,
                    chunk_osm,
                    timeout_seconds=180,
                    transfer_progress_callback=_chunk_transfer,
                    cancel_callback=cancel_callback,
                )
            except Exception as chunk_exc:
                error_type = getattr(chunk_exc, "error_type", "") or classify_overpass_error(str(chunk_exc))
                area = bbox_area(chunk)
                if split_large_bbox and error_type in {"overpass_timeout", "overpass_rate_limited"} and area > 0.0004 and len(queue) < 250:
                    smaller = split_bbox(chunk, max_area=max(area / 4.0, 0.0001))
                    queue = smaller + queue
                    chunk_records.append({"index": index, "bbox": chunk, "status": "resplit", "error_type": error_type})
                    continue
                raise
            chunk_layer_name = f"{layer_name}_chunk_{index:03d}" if len(chunks) > 1 else layer_name
            chunk_layer = OSMDownloader.load_osm_layer(
                chunk_osm,
                geometry_type,
                chunk_layer_name,
                add_to_project=False,
            )
            loaded_layers.append(chunk_layer)
            finished_total = max(1, len(loaded_layers) + len(queue))
            _emit_acquisition_progress(
                progress_callback,
                tool_name,
                title,
                "下载 Overpass 分块",
                2,
                5,
                len(loaded_layers) / finished_total * 100.0,
                f"已完成 {len(loaded_layers)}/{finished_total} 个分块。",
            )
            chunk_records.append(
                {
                    "index": index,
                    "bbox": chunk,
                    "feature_count": safe_feature_count(chunk_layer),
                }
            )

        _emit_acquisition_progress(
            progress_callback, tool_name, title, "合并并去重", 3, 5, 0,
            f"正在整理 {len(loaded_layers)} 个分块。",
        )
        if len(loaded_layers) == 1:
            source_layer = loaded_layers[0]
        else:
            import processing
            merge_result = processing.run(
                "native:mergevectorlayers",
                {
                    "LAYERS": loaded_layers,
                    "CRS": "EPSG:4326",
                    "OUTPUT": "TEMPORARY_OUTPUT",
                },
            )
            source_layer = merge_result["OUTPUT"]
            source_layer.setName(layer_name)

        source_layer = _deduplicate_vector_layer(source_layer, layer_name)
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "合并并去重", 3, 5, 100,
            "分块合并与 OSM 要素去重完成。",
        )
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "写入输出文件", 4, 5, 0,
            os.path.basename(output_file),
        )
        load_uri = _save_vector_layer(source_layer, output_file, layer_name)
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "写入输出文件", 4, 5, 100,
            os.path.basename(output_file),
        )
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "加载并验证", 5, 5, 0,
            f"正在加载图层 {layer_name}。",
        )
        from .qgis_tools.io_tools import load_vector_layer
        try:
            final_layer = load_vector_layer(load_uri, layer_name, duplicate_policy="replace")
        except Exception:
            from qgis.core import QgsVectorLayer, QgsProject
            final_layer = QgsVectorLayer(load_uri, layer_name, "ogr")
            if not final_layer.isValid():
                final_layer = QgsVectorLayer(output_file, layer_name, "ogr")
            if not final_layer.isValid():
                raise
            QgsProject.instance().addMapLayer(final_layer)
            final_layer.setName(layer_name)
        feature_count = safe_feature_count(final_layer)
        _emit_acquisition_progress(
            progress_callback, tool_name, title, "加载并验证", 5, 5, 100,
            f"图层有效，要素数 {feature_count}。",
        )
        artifacts = [_artifact_entry(output_file, "osm_output", "Final OSM vector output.")]
        return ToolResult.success(
            f"Downloaded OSM features to '{output_file}' and loaded layer '{layer_name}'.",
            data={
                "output_file": output_file,
                "layer_name": layer_name,
                "geometry_type": geometry_type,
                "tags": tags,
                "bbox": bbox,
                "chunk_count": len(loaded_layers),
                "chunks": chunk_records,
                "feature_count": feature_count,
                "temporary_files_cleaned": True,
            },
            artifacts=artifacts,
        ).to_dict()
    except Exception as exc:
        from ..core.progress import DataAcquisitionCancelled
        from ..bridges.osm_bridge import classify_overpass_error

        if isinstance(exc, DataAcquisitionCancelled):
            return ToolResult.failure(
                str(exc),
                error_type="operation_cancelled",
                data={"output_file": output_file, "layer_name": layer_name},
            ).to_dict()
        error_type = getattr(exc, "error_type", None) or classify_overpass_error(str(exc))
        return ToolResult.failure(
            f"Failed to download OSM features: {exc}",
            error_type=error_type if error_type != "overpass_error" else "network_error",
            data={"output_file": output_file, "layer_name": layer_name},
        ).to_dict()
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


def _summarize_layers(kwargs):
    from ..bridges.osm_bridge import safe_feature_count
    from ..core.tool_result import ToolResult
    from qgis.core import QgsProject, QgsMapLayerType, QgsWkbTypes

    include_sources = bool(kwargs.get("include_sources", False))
    max_layers = int(kwargs.get("max_layers", 50) or 50)
    layers = []
    for layer in list(QgsProject.instance().mapLayers().values())[:max_layers]:
        try:
            layer_type = "vector" if layer.type() == QgsMapLayerType.VectorLayer else "raster"
            item = {
                "name": layer.name(),
                "id": layer.id(),
                "type": layer_type,
                "crs": layer.crs().authid() if hasattr(layer, "crs") else "",
            }
            if layer_type == "vector":
                item["feature_count"] = safe_feature_count(layer)
                item["geometry"] = QgsWkbTypes.displayString(layer.wkbType())
                item["fields"] = [field.name() for field in layer.fields()][:20]
            if include_sources:
                item["source"] = layer.source()
            layers.append(item)
        except RuntimeError:
            continue
        except Exception as exc:
            layers.append({"name": getattr(layer, "name", lambda: "<unknown>")(), "error": str(exc)})
    return ToolResult.success(
        f"Found {len(layers)} layer(s).",
        data={"layer_count": len(layers), "layers": layers, "truncated": len(QgsProject.instance().mapLayers()) > max_layers},
    ).to_dict()


def _cleanup_qgis_project(kwargs):
    import os
    from pathlib import Path
    from ..core.tool_result import ToolResult
    from qgis.core import QgsProject

    project = QgsProject.instance()
    removed_layers = []
    if kwargs.get("remove_memory_output_layers", True):
        candidates = []
        for layer in project.mapLayers().values():
            try:
                name = layer.name()
                source = layer.source()
                if name.lower() in {"output", "temporary_output"} or source.lower().startswith("memory:"):
                    candidates.append((layer.id(), name, source))
            except RuntimeError:
                continue
        for layer_id, name, source in candidates:
            try:
                project.removeMapLayer(layer_id)
                removed_layers.append({"name": name, "source": source})
            except Exception:
                pass

    removed_files = []
    chunk_dir = kwargs.get("cleanup_chunk_files_dir") or ""
    if chunk_dir and os.path.isdir(chunk_dir):
        for path in Path(chunk_dir).glob("_chunk_*.osm"):
            try:
                size = path.stat().st_size
                path.unlink()
                removed_files.append({"path": str(path), "size": size})
            except Exception:
                pass

    wal_dir = kwargs.get("cleanup_wal_files_dir") or ""
    if wal_dir and os.path.isdir(wal_dir):
        for pattern in ("*.gpkg-wal", "*.gpkg-shm"):
            for path in Path(wal_dir).rglob(pattern):
                try:
                    size = path.stat().st_size
                    if size == 0:
                        path.unlink()
                        removed_files.append({"path": str(path), "size": size})
                except Exception:
                    pass

    return ToolResult.success(
        f"Cleanup complete: removed {len(removed_layers)} layer(s), {len(removed_files)} file(s).",
        data={"removed_layers": removed_layers, "removed_files": removed_files},
    ).to_dict()


def _remove_qgis_layers_and_data(kwargs):
    """Remove explicit project layers and, only when requested, their local datasets."""
    import os
    from pathlib import Path

    from ..core.tool_result import ToolResult
    from qgis.core import QgsApplication, QgsProject

    scope = str(kwargs.get("scope") or "").strip()
    requested_names = {str(name).strip() for name in (kwargs.get("layer_names") or []) if str(name).strip()}
    delete_sources = bool(kwargs.get("delete_source_files"))
    delete_sidecars = kwargs.get("delete_sidecars", True) is not False
    save_project = kwargs.get("save_project", True) is not False
    project = QgsProject.instance()
    all_layers = list(project.mapLayers().values())

    if scope not in {"all_layers", "named_layers"}:
        return ToolResult.failure(
            "scope must be all_layers or named_layers.",
            error_type="argument_error",
            data={"scope": scope},
        ).to_dict()
    if scope == "named_layers" and not requested_names:
        return ToolResult.failure(
            "layer_names is required when scope is named_layers.",
            error_type="argument_error",
            data={"scope": scope},
        ).to_dict()

    selected_layers = all_layers if scope == "all_layers" else [
        layer for layer in all_layers
        if layer.id() in requested_names or layer.name() in requested_names
    ]
    selected_ids = {layer.id() for layer in selected_layers}
    unmatched_names = sorted(requested_names - {
        value for layer in selected_layers for value in (layer.id(), layer.name())
    })
    if unmatched_names:
        return ToolResult.failure(
            "No deletion was performed because one or more requested layer names/IDs are not present.",
            error_type="qgis_layer_error",
            data={
                "unmatched_layer_names": unmatched_names,
                "available_layers": [layer.name() for layer in all_layers],
            },
            suggestions=["Use exact layer names or IDs returned by summarize_layers before retrying."],
        ).to_dict()

    def source_path(layer):
        try:
            source = str(layer.source() or "").strip()
        except Exception:
            return "", "unreadable layer source"
        if not source or source.lower().startswith("memory:"):
            return "", "memory layer"
        candidate = source.split("|", 1)[0].strip()
        if (
            "://" in candidate
            or candidate.lower().startswith(("pg:", "wfs:", "mssql:", "oracle:", "oci:", "/vsi"))
        ):
            return "", "remote or virtual source"
        if not os.path.isfile(candidate):
            return "", "source is not a local file"
        return os.path.abspath(os.path.normpath(candidate)), ""

    all_source_users = {}
    for layer in all_layers:
        path, _reason = source_path(layer)
        if path:
            all_source_users.setdefault(path, set()).add(layer.id())

    source_candidates = {}
    skipped_sources = []
    for layer in selected_layers:
        path, reason = source_path(layer)
        if not path:
            if reason:
                skipped_sources.append({"layer": layer.name(), "reason": reason})
            continue
        users = all_source_users.get(path, set())
        if scope != "all_layers" and not users.issubset(selected_ids):
            skipped_sources.append({
                "layer": layer.name(),
                "path": path,
                "reason": "source is also used by a layer outside the requested scope",
            })
            continue
        source_candidates[path] = {
            "path": path,
            "layers": sorted(
                layer.name() for layer in selected_layers
                if source_path(layer)[0] == path
            ),
        }

    removed_layers = []
    for layer in selected_layers:
        try:
            layer_name = layer.name()
            layer_id = layer.id()
        except Exception:
            continue
        try:
            project.removeMapLayer(layer_id)
            removed_layers.append({"name": layer_name, "id": layer_id})
        except Exception as exc:
            skipped_sources.append({"layer": layer_name, "reason": f"could not remove layer: {exc}"})

    try:
        QgsApplication.processEvents()
    except Exception:
        pass

    removed_files = []
    file_failures = []
    if delete_sources:
        sidecar_suffixes = {
            ".shp": (".dbf", ".shx", ".prj", ".cpg", ".qix", ".sbn", ".sbx"),
            ".tif": (".tfw", ".ovr"),
            ".tiff": (".tfw", ".ovr"),
            ".img": (".aux", ".ovr"),
            ".gpkg": (".gpkg-wal", ".gpkg-shm"),
        }
        for source in source_candidates.values():
            path = Path(source["path"])
            targets = [path]
            if delete_sidecars:
                for suffix in sidecar_suffixes.get(path.suffix.lower(), ()):
                    if suffix.startswith(".gpkg-"):
                        targets.append(Path(str(path) + suffix[len(".gpkg"):]))
                    else:
                        targets.append(path.with_suffix(suffix))
                for suffix in (".aux.xml",):
                    targets.append(Path(str(path) + suffix))
            for target in targets:
                if not target.exists():
                    continue
                try:
                    size = target.stat().st_size
                    target.unlink()
                    removed_files.append({"path": str(target), "size": size})
                except Exception as exc:
                    file_failures.append({"path": str(target), "error": str(exc)})

    project_saved = None
    if save_project and project.fileName():
        try:
            project_saved = bool(project.write())
            if not project_saved:
                file_failures.append({"path": project.fileName(), "error": "QGIS project write returned false"})
        except Exception as exc:
            file_failures.append({"path": project.fileName(), "error": f"could not save QGIS project: {exc}"})

    data = {
        "scope": scope,
        "delete_source_files": delete_sources,
        "removed_layers": removed_layers,
        "removed_files": removed_files,
        "skipped_sources": skipped_sources,
        "unmatched_layer_names": unmatched_names,
        "project_saved": project_saved,
        "remaining_layer_count": len(project.mapLayers()),
        "file_failures": file_failures,
    }
    if file_failures:
        return ToolResult.failure(
            "Layer removal completed partially, but one or more files or the project could not be removed/saved.",
            error_type="partial_cleanup_error",
            data=data,
            suggestions=["Close file locks and retry only the failed paths; do not assume every source file was deleted."],
        ).to_dict()
    return ToolResult.success(
        f"Removed {len(removed_layers)} layer(s) and {len(removed_files)} local file(s).",
        data=data,
    ).to_dict()


def _validate_project_outputs(kwargs):
    import os
    from ..core.tool_result import ToolResult
    from qgis.core import QgsProject

    expected_layers = list(kwargs.get("expected_layers") or [])
    expected_files = list(kwargs.get("expected_files") or [])
    include_layer_details = kwargs.get("include_layer_details", True)
    current_layers = {layer.name(): layer for layer in QgsProject.instance().mapLayers().values()}
    missing_layers = [name for name in expected_layers if name not in current_layers]
    file_results = []
    missing_files = []
    for path in expected_files:
        exists = os.path.exists(path)
        item = {"path": path, "exists": exists}
        if exists:
            item["size"] = os.path.getsize(path)
        else:
            missing_files.append(path)
        file_results.append(item)
    data = {
        "expected_layers": expected_layers,
        "missing_layers": missing_layers,
        "expected_files": file_results,
        "missing_files": missing_files,
    }
    if include_layer_details:
        data["layers"] = _summarize_layers({"include_sources": False, "max_layers": 100}).get("data", {}).get("layers", [])
    ok = not missing_layers and not missing_files
    if ok:
        return ToolResult.success("All expected layers and files are present.", data=data).to_dict()
    return ToolResult.failure(
        "Some expected layers or files are missing.",
        error_type="qgis_layer_error" if missing_layers else "file_path_error",
        data=data,
    ).to_dict()


def _inspect_raster_file_tool(kwargs):
    from ..core.raster_validation import inspect_raster_file

    return inspect_raster_file(
        kwargs.get("file_path", ""),
        force_read=kwargs.get("force_read", True),
    )


def _validate_raster_has_data_tool(kwargs):
    from ..core.raster_validation import validate_raster_has_data

    return validate_raster_has_data(
        kwargs.get("file_path", ""),
        bands=kwargs.get("bands"),
        min_valid_percent=float(kwargs.get("min_valid_percent", 0.01) or 0.01),
        force_read=kwargs.get("force_read", True),
    )


def _compute_raster_zonal_stats_tool(kwargs):
    from ..core.raster_validation import compute_raster_zonal_stats

    return compute_raster_zonal_stats(
        source_layer_or_path=kwargs.get("source_layer_or_path", ""),
        mask_layer_or_path=kwargs.get("mask_layer_or_path", ""),
        mask_valid_value=float(kwargs.get("mask_valid_value", 1.0) if kwargs.get("mask_valid_value") is not None else 1.0),
        rank_band_pairs=bool(kwargs.get("rank_band_pairs", True)),
    )


def _compute_raster_index_tool(kwargs):
    from ..core.raster_validation import compute_raster_index

    return compute_raster_index(
        source_layer_or_path=kwargs.get("source_layer_or_path", ""),
        output_path=kwargs.get("output_path", ""),
        band_a=int(kwargs.get("band_a")),
        band_b=int(kwargs.get("band_b")),
        index_name=str(kwargs.get("index_name") or "INDEX"),
        mask_layer_or_path=str(kwargs.get("mask_layer_or_path") or ""),
        mask_valid_value=float(kwargs.get("mask_valid_value", 1.0) if kwargs.get("mask_valid_value") is not None else 1.0),
        clip_range=bool(kwargs.get("clip_range", True)),
        load_layer=bool(kwargs.get("load_layer", True)),
        layer_name=str(kwargs.get("layer_name") or ""),
        overwrite=bool(kwargs.get("overwrite", True)),
    )


def _boundary_layer_to_ee_geometry(layer, simplify_tolerance=0.0):
    import json
    import ee
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject

    geometries = []
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        if geometry and not geometry.isEmpty():
            geometries.append(QgsGeometry(geometry))
    if not geometries:
        raise ValueError(f"Boundary layer has no geometry: {layer.name()}")

    geometry = QgsGeometry.unaryUnion(geometries) if len(geometries) > 1 else geometries[0]
    if layer.crs().isValid() and layer.crs().authid() != "EPSG:4326":
        transform = QgsCoordinateTransform(layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        geometry.transform(transform)

    tolerance = float(simplify_tolerance or 0.0)
    if tolerance > 0:
        simplified = geometry.simplify(tolerance)
        if simplified and not simplified.isEmpty():
            geometry = simplified

    geojson = json.loads(geometry.asJson())
    geom_type = geojson.get("type")
    coordinates = geojson.get("coordinates")
    if geom_type == "Polygon":
        return ee.Geometry.Polygon(coordinates)
    if geom_type == "MultiPolygon":
        return ee.Geometry.MultiPolygon(coordinates)
    return ee.Geometry(geojson)


def _run_gee_dem_download_workflow(iface, kwargs, progress_callback=None, cancel_callback=None):
    import os
    import ee
    from ..bridges.gee_bridge import GEEDownloader, GEEManualDownloadRequired, init_gee
    from ..core.raster_validation import validate_raster_has_data
    from ..core.tool_result import ToolResult
    from qgis.core import QgsMapLayerType

    required = ["boundary_layer_name", "output_dir", "output_name", "dataset_id", "scale", "crs", "load_layer"]
    missing = [name for name in required if kwargs.get(name) in (None, "", [])]
    if missing or not kwargs.get("user_confirmed_parameters"):
        return ToolResult.failure(
            "DEM download parameters are incomplete or not user-confirmed.",
            error_type="missing_user_parameters",
            data={
                "missing": missing,
                "user_confirmed_parameters": bool(kwargs.get("user_confirmed_parameters")),
                "required_parameters": required + ["user_confirmed_parameters"],
            },
            suggestions=[
                "Call ask_human before downloading DEM data.",
                "Ask the user to confirm DEM dataset, scale/resolution, output CRS, output name, and whether to load the layer.",
                "Supported datasets are COPERNICUS/DEM/GLO30, NASA/NASADEM_HGT/001, and USGS/SRTMGL1_003.",
            ],
        ).to_dict()

    boundary_name = kwargs.get("boundary_layer_name")
    output_dir = kwargs.get("output_dir")
    dataset_id = str(kwargs.get("dataset_id") or "").strip()
    scale = float(kwargs.get("scale") or 30)
    crs = str(kwargs.get("crs") or "EPSG:4326").strip()
    output_name = kwargs.get("output_name") or "dem.tif"
    output_stem = os.path.splitext(os.path.basename(output_name))[0] or "dem"
    min_valid_percent = float(kwargs.get("min_valid_percent", 0.01) or 0.01)
    simplify_tolerance = float(kwargs.get("simplify_tolerance", 0.0) or 0.0)
    progress_context = {
        "tool_name": "run_gee_dem_download_workflow",
        "title": "GEE DEM 数据获取",
        "stage_count": 6,
    }

    dem_catalog = {
        "COPERNICUS/DEM/GLO30": {
            "band": "DEM",
            "kind": "image_collection",
            "description": "Copernicus DEM GLO-30",
        },
        "NASA/NASADEM_HGT/001": {
            "band": "elevation",
            "kind": "image",
            "description": "NASA NASADEM HGT",
        },
        "USGS/SRTMGL1_003": {
            "band": "elevation",
            "kind": "image",
            "description": "USGS SRTMGL1 30m",
        },
    }
    spec = dem_catalog.get(dataset_id)
    if not spec:
        return ToolResult.failure(
            f"Unsupported DEM dataset_id: {dataset_id}",
            error_type="argument_error",
            data={"dataset_id": dataset_id, "supported_dataset_ids": sorted(dem_catalog.keys())},
            suggestions=["Ask the user to choose one supported DEM dataset or add a tested dataset mapping before retrying."],
        ).to_dict()

    boundary_layer = _find_project_layer(boundary_name)
    if boundary_layer is None:
        return ToolResult.failure(
            f"Boundary layer not found: {boundary_name}",
            error_type="qgis_layer_error",
            data={"boundary_layer_name": boundary_name},
            suggestions=["Call summarize_layers or search_project_layers and retry with the exact layer name."],
        ).to_dict()
    if boundary_layer.type() != QgsMapLayerType.VectorLayer:
        return ToolResult.failure(
            f"Boundary layer must be a vector layer: {boundary_layer.name()}",
            error_type="qgis_layer_error",
            data={"layer": boundary_layer.name()},
        ).to_dict()

    try:
        from ..core.progress import raise_if_cancelled
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "认证 Earth Engine", 1, 6, None, "正在初始化 Earth Engine 会话。",
        )
        raise_if_cancelled(cancel_callback, "GEE DEM acquisition was cancelled by the user.")
        init_gee()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "认证 Earth Engine", 1, 6, 100, "Earth Engine 会话可用。",
        )
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "构建 DEM 云端影像", 2, 6, None, f"数据集 {dataset_id}",
        )
        ee_geometry = _boundary_layer_to_ee_geometry(boundary_layer, simplify_tolerance=simplify_tolerance)
        if spec["kind"] == "image_collection":
            image = ee.ImageCollection(dataset_id).mosaic().select(spec["band"])
        else:
            image = ee.Image(dataset_id).select(spec["band"])

        export_image = image.clip(ee_geometry).toFloat()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "构建 DEM 云端影像", 2, 6, 100, "裁剪影像表达式已构建。",
        )
        os.makedirs(output_dir, exist_ok=True)
        output_path = GEEDownloader.download_ee_object(
            export_image,
            output_stem,
            output_dir,
            scale=scale,
            region=ee_geometry,
            crs=crs,
            exact_geom=ee_geometry,
            no_data=-9999,
            min_coverage_ratio=max(0.0, min(1.0, min_valid_percent / 100.0)),
            progress_callback=progress_callback,
            progress_context=progress_context,
            cancel_callback=cancel_callback,
        )
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "验证本地栅格", 5, 6, None, os.path.basename(output_path),
        )
        validation = validate_raster_has_data(
            output_path,
            bands=[1],
            min_valid_percent=min_valid_percent,
            force_read=True,
        )
        if not validation.get("ok"):
            return ToolResult.failure(
                "Downloaded DEM raster failed validation.",
                error_type=validation.get("error_type", "raster_no_data_error"),
                data={"output_path": output_path, "validation": validation},
                suggestions=validation.get("suggestions", []),
            ).to_dict()

        layer_id = ""
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "加载到 QGIS", 6, 6, 0,
            "正在完成最终加载。" if kwargs.get("load_layer", True) else "用户选择不加载图层。",
        )
        if kwargs.get("load_layer", True):
            from .qgis_tools import load_raster_layer
            layer_name = os.path.splitext(os.path.basename(output_path))[0]
            layer = load_raster_layer(output_path, layer_name, duplicate_policy="replace")
            layer_id = layer.id()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "加载到 QGIS", 6, 6, 100, f"输出已验证{'并加载' if layer_id else ''}。",
        )

        return ToolResult.success(
            "DEM download workflow completed and output raster was validated.",
            data={
                "workflow_complete": True,
                "output_path": output_path,
                "layer_id": layer_id,
                "dataset_id": dataset_id,
                "dataset_description": spec["description"],
                "band": spec["band"],
                "scale": scale,
                "crs": crs,
                "boundary_layer": boundary_layer.name(),
                "simplify_tolerance": simplify_tolerance,
                "validation": validation,
            },
            artifacts=[_artifact_entry(output_path, "raster", "Validated DEM GeoTIFF.")],
        ).to_dict()
    except GEEManualDownloadRequired as exc:
        return ToolResult.failure(
            str(exc),
            error_type="manual_download_required",
            data=exc.to_dict(),
            suggestions=["Complete the listed Google Drive manual download steps, then validate and load the file."],
        ).to_dict()
    except Exception as exc:
        from ..core.progress import DataAcquisitionCancelled
        if isinstance(exc, DataAcquisitionCancelled):
            return ToolResult.failure(
                str(exc),
                error_type="operation_cancelled",
                data={
                    "boundary_layer_name": boundary_name,
                    "output_dir": output_dir,
                    "dataset_id": dataset_id,
                    "cloud_export_may_continue": "task_id=" in str(exc),
                },
                suggestions=["Check Earth Engine Tasks before retrying; a submitted cloud export may still be running."],
            ).to_dict()
        return ToolResult.failure(
            f"DEM download workflow failed: {exc}",
            error_type="gee_download_error",
            data={
                "boundary_layer_name": boundary_name,
                "output_dir": output_dir,
                "dataset_id": dataset_id,
                "scale": scale,
                "crs": crs,
            },
            suggestions=[
                "Do not retry with ee.Image('COPERNICUS/DEM/GLO30'); Copernicus GLO-30 must be loaded as an ImageCollection.",
                "If the boundary is complex, increase simplify_tolerance or export by bbox, then clip locally.",
                "Run inspect_raster_file on any partial output before reusing it.",
            ],
        ).to_dict()


def _run_gee_sentinel2_download_workflow(iface, kwargs, progress_callback=None, cancel_callback=None):
    import os
    import ee
    from ..bridges.gee_bridge import GEEDownloader, GEEManualDownloadRequired, init_gee
    from ..core.raster_validation import validate_raster_has_data
    from ..core.tool_result import ToolResult
    from qgis.core import QgsMapLayerType, QgsProject, QgsRasterLayer

    boundary_name = kwargs.get("boundary_layer_name")
    output_dir = kwargs.get("output_dir")
    required = [
        "boundary_layer_name",
        "output_dir",
        "collection_id",
        "start_date",
        "end_date",
        "bands",
        "cloud_pct",
        "scale",
        "crs",
        "processing_method",
        "output_name",
        "load_layer",
    ]
    missing = [name for name in required if kwargs.get(name) in (None, "", [])]
    if missing or not kwargs.get("user_confirmed_parameters"):
        return ToolResult.failure(
            "Sentinel-2 download parameters are incomplete or not user-confirmed.",
            error_type="missing_user_parameters",
            data={
                "missing": missing,
                "user_confirmed_parameters": bool(kwargs.get("user_confirmed_parameters")),
                "required_parameters": required + ["user_confirmed_parameters"],
            },
            suggestions=[
                "Call ask_human before downloading Sentinel-2 data.",
                "Ask the user to confirm: collection_id, date range, bands, cloud_pct, scale, processing_method, output name.",
                "Do not assume NDVI, RGB, date range, cloud masking, or resolution unless the user explicitly asks for it.",
            ],
        ).to_dict()

    boundary_layer = _find_project_layer(boundary_name)
    if boundary_layer is None:
        return ToolResult.failure(
            f"Boundary layer not found: {boundary_name}",
            error_type="qgis_layer_error",
            data={"boundary_layer_name": boundary_name},
            suggestions=["Call summarize_layers or search_project_layers and retry with the exact layer name."],
        ).to_dict()
    if boundary_layer.type() != QgsMapLayerType.VectorLayer:
        return ToolResult.failure(
            f"Boundary layer must be a vector layer: {boundary_layer.name()}",
            error_type="qgis_layer_error",
            data={"layer": boundary_layer.name()},
        ).to_dict()

    start_date = kwargs.get("start_date")
    end_date = kwargs.get("end_date")
    bands = [str(b).strip() for b in (kwargs.get("bands") or []) if str(b).strip()]
    cloud_pct = float(kwargs.get("cloud_pct"))
    scale = float(kwargs.get("scale"))
    collection_id = kwargs.get("collection_id")
    processing_method = kwargs.get("processing_method")
    min_valid_percent = float(kwargs.get("min_valid_percent", 0.01) or 0.01)
    output_name = kwargs.get("output_name")
    output_stem = os.path.splitext(os.path.basename(output_name))[0] or "sentinel2_export"
    output_crs = str(kwargs.get("crs") or "").strip()
    progress_context = {
        "tool_name": "run_gee_sentinel2_download_workflow",
        "title": "GEE Sentinel-2 数据获取",
        "stage_count": 6,
    }

    supported_collections = {
        "COPERNICUS/S2_SR_HARMONIZED",
        "COPERNICUS/S2_HARMONIZED",
    }
    if collection_id not in supported_collections:
        return ToolResult.failure(
            f"Unsupported Sentinel-2 collection_id: {collection_id}",
            error_type="argument_error",
            data={"collection_id": collection_id, "supported_collection_ids": sorted(supported_collections)},
            suggestions=["Ask the user to choose one of the supported Sentinel-2 Harmonized collections."],
        ).to_dict()

    if not bands:
        return ToolResult.failure(
            "No Sentinel-2 bands were specified.",
            error_type="missing_user_parameters",
            data={"bands": bands},
            suggestions=["Call ask_human and ask which Sentinel-2 bands should be downloaded, such as B2/B3/B4/B8 or RGB B4/B3/B2."],
        ).to_dict()

    try:
        from ..core.progress import raise_if_cancelled
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "认证 Earth Engine", 1, 6, None, "正在初始化 Earth Engine 会话。",
        )
        raise_if_cancelled(cancel_callback, "GEE Sentinel-2 acquisition was cancelled by the user.")
        init_gee()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "认证 Earth Engine", 1, 6, 100, "Earth Engine 会话可用。",
        )
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "筛选影像并构建合成", 2, 6, None,
            f"{start_date} 至 {end_date} · 云量 < {cloud_pct}% · {','.join(bands)}",
        )
        ee_geometry = _boundary_layer_to_ee_geometry(boundary_layer)
        collection = (
            ee.ImageCollection(collection_id)
            .filterDate(start_date, end_date)
            .filterBounds(ee_geometry)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
        )
        image_count = int(collection.size().getInfo())
        if image_count <= 0:
            return ToolResult.failure(
                "No Sentinel-2 scenes matched the boundary/date/cloud filters.",
                error_type="gee_no_data_error",
                data={
                    "collection_id": collection_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "cloud_pct": cloud_pct,
                    "boundary_layer": boundary_layer.name(),
                },
                suggestions=["Relax cloud_pct or expand the date range, then retry."],
            ).to_dict()

        available_bands = [str(value) for value in collection.first().bandNames().getInfo()]
        missing_bands = [band for band in bands if band not in available_bands]
        if missing_bands:
            return ToolResult.failure(
                "Requested Sentinel-2 bands do not exist in the selected collection.",
                error_type="argument_error",
                data={"missing_bands": missing_bands, "available_bands": available_bands, "collection_id": collection_id},
                suggestions=["Ask the user to choose bands available in the confirmed Sentinel-2 collection."],
            ).to_dict()

        if processing_method == "cloud_masked_median":
            if "SCL" in available_bands:
                def _mask_s2_clouds(image):
                    scl = image.select("SCL")
                    mask = (
                        scl.neq(0)
                        .And(scl.neq(1))
                        .And(scl.neq(3))
                        .And(scl.neq(8))
                        .And(scl.neq(9))
                        .And(scl.neq(10))
                        .And(scl.neq(11))
                    )
                    return image.updateMask(mask)
            elif "QA60" in available_bands:
                def _mask_s2_clouds(image):
                    qa = image.select("QA60")
                    cloud_bit = 1 << 10
                    cirrus_bit = 1 << 11
                    return image.updateMask(qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(cirrus_bit).eq(0)))
            else:
                return ToolResult.failure(
                    "The selected Sentinel-2 collection has neither SCL nor QA60 for the requested cloud mask.",
                    error_type="argument_error",
                    data={"collection_id": collection_id, "available_bands": available_bands},
                    suggestions=["Choose median without cloud masking or select a collection with SCL/QA60."],
                ).to_dict()
            image = collection.map(_mask_s2_clouds).median()
        elif processing_method == "median":
            image = collection.median()
        elif processing_method == "mosaic":
            image = collection.mosaic()
        elif processing_method == "least_cloudy":
            image = collection.sort("CLOUDY_PIXEL_PERCENTAGE").first()
        else:
            return ToolResult.failure(
                f"Unsupported Sentinel-2 processing_method: {processing_method}",
                error_type="argument_error",
                data={"processing_method": processing_method},
            ).to_dict()

        export_image = image.select(bands).clip(ee_geometry).toFloat()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "筛选影像并构建合成", 2, 6, 100,
            f"匹配 {image_count} 景影像，处理方法 {processing_method}。",
        )
        os.makedirs(output_dir, exist_ok=True)
        output_path = GEEDownloader.download_ee_object(
            export_image,
            output_stem,
            output_dir,
            scale=scale,
            region=ee_geometry,
            crs=output_crs,
            exact_geom=ee_geometry,
            no_data=-9999,
            min_coverage_ratio=max(0.0, min(1.0, min_valid_percent / 100.0)),
            progress_callback=progress_callback,
            progress_context=progress_context,
            cancel_callback=cancel_callback,
        )
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "验证本地栅格", 5, 6, None, os.path.basename(output_path),
        )
        validation = validate_raster_has_data(
            output_path,
            bands=list(range(1, len(bands) + 1)),
            min_valid_percent=min_valid_percent,
            force_read=True,
        )
        if not validation.get("ok"):
            return ToolResult.failure(
                "Downloaded Sentinel-2 raster failed validation.",
                error_type=validation.get("error_type", "raster_no_data_error"),
                data={"output_path": output_path, "validation": validation},
                suggestions=validation.get("suggestions", []),
            ).to_dict()

        layer_id = ""
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "加载到 QGIS", 6, 6, 0,
            "正在完成最终加载。" if kwargs.get("load_layer", True) else "用户选择不加载图层。",
        )
        if kwargs.get("load_layer", True):
            from .qgis_tools import load_raster_layer
            layer_name = os.path.splitext(os.path.basename(output_path))[0]
            layer = load_raster_layer(output_path, layer_name, duplicate_policy="replace")
            layer_id = layer.id()
        _emit_acquisition_progress(
            progress_callback, progress_context["tool_name"], progress_context["title"],
            "加载到 QGIS", 6, 6, 100, f"输出已验证{'并加载' if layer_id else ''}。",
        )

        return ToolResult.success(
            "Sentinel-2 download workflow completed and output raster was validated.",
            data={
                "workflow_complete": True,
                "output_path": output_path,
                "layer_id": layer_id,
                "scene_count": image_count,
                "collection_id": collection_id,
                "start_date": start_date,
                "end_date": end_date,
                "bands": bands,
                "cloud_pct": cloud_pct,
                "scale": scale,
                "crs": output_crs,
                "processing_method": processing_method,
                "validation": validation,
            },
            artifacts=[_artifact_entry(output_path, "raster", "Validated Sentinel-2 GeoTIFF.")],
        ).to_dict()
    except GEEManualDownloadRequired as exc:
        return ToolResult.failure(
            str(exc),
            error_type="manual_download_required",
            data=exc.to_dict(),
            suggestions=["Complete the listed Google Drive manual download steps, then validate and load the file."],
        ).to_dict()
    except Exception as exc:
        from ..core.progress import DataAcquisitionCancelled
        if isinstance(exc, DataAcquisitionCancelled):
            return ToolResult.failure(
                str(exc),
                error_type="operation_cancelled",
                data={
                    "boundary_layer_name": boundary_name,
                    "output_dir": output_dir,
                    "collection_id": collection_id,
                    "cloud_export_may_continue": "task_id=" in str(exc),
                },
                suggestions=["Check Earth Engine Tasks before retrying; a submitted cloud export may still be running."],
            ).to_dict()
        return ToolResult.failure(
            f"Sentinel-2 download workflow failed: {exc}",
            error_type="gee_download_error",
            data={
                "boundary_layer_name": boundary_name,
                "output_dir": output_dir,
                "collection_id": collection_id,
                "start_date": start_date,
                "end_date": end_date,
                "bands": bands,
                "processing_method": processing_method,
            },
            suggestions=[
                "Run inspect_raster_file on any partial output before reusing it.",
                "Retry only after confirming the user's Sentinel-2 parameters and GEE authentication.",
            ],
        ).to_dict()


def _run_qgis_workflow_batch(iface, kwargs, progress_callback=None, cancel_callback=None):
    from ..core.tool_result import ToolResult
    from ..core.tool_registry import BATCHABLE_TOOLS
    from ..core.validators import validate_tool_call

    allowed = BATCHABLE_TOOLS
    steps = list(kwargs.get("steps") or [])
    stop_on_error = kwargs.get("stop_on_error", True)
    results = []
    for index, step in enumerate(steps, start=1):
        action = (step or {}).get("action", "")
        arguments = (step or {}).get("arguments") or {}
        if action not in allowed:
            result = ToolResult.failure(
                f"Batch step {index} action is not allowed: {action}",
                error_type="argument_error",
                data={"index": index, "action": action},
            ).to_dict()
        else:
            validation = validate_tool_call(action, arguments)
            if not validation.ok:
                result = ToolResult.failure(
                    f"Batch step {index} failed validation before execution.",
                    error_type="argument_error",
                    data={"index": index, "action": action, "validation": validation.to_dict()},
                ).to_dict()
            else:
                result = execute_atomic_tool(
                    iface,
                    action,
                    arguments,
                    progress_callback=progress_callback,
                    cancel_callback=cancel_callback,
                )
        result_ok = bool(result.get("ok")) if isinstance(result, dict) else "error" not in str(result).lower()
        results.append({"index": index, "action": action, "ok": result_ok, "result": result})
        if stop_on_error and not result_ok:
            break
    ok = all(item["ok"] for item in results)
    message = f"Batch workflow finished: {sum(1 for item in results if item['ok'])}/{len(results)} step(s) passed."
    if ok:
        return ToolResult.success(message, data={"steps": results}).to_dict()
    return ToolResult.failure(message, error_type="unknown_error", data={"steps": results}).to_dict()


def execute_atomic_tool(iface, tool_name, kwargs, progress_callback=None, cancel_callback=None):
    try:
        if tool_name == "summarize_layers":
            return _summarize_layers(kwargs)

        if tool_name == "cleanup_qgis_project":
            return _cleanup_qgis_project(kwargs)

        if tool_name == "remove_qgis_layers_and_data":
            return _remove_qgis_layers_and_data(kwargs)

        if tool_name == "validate_project_outputs":
            return _validate_project_outputs(kwargs)

        if tool_name == "inspect_raster_file":
            return _inspect_raster_file_tool(kwargs)

        if tool_name == "validate_raster_has_data":
            return _validate_raster_has_data_tool(kwargs)

        if tool_name == "compute_raster_zonal_stats":
            return _compute_raster_zonal_stats_tool(kwargs)

        if tool_name == "compute_raster_index":
            return _compute_raster_index_tool(kwargs)

        if tool_name == "create_or_update_user_tool":
            from ..core.user_tool_extensions import create_or_update_user_tool

            return create_or_update_user_tool(
                tool_name=kwargs.get("tool_name", ""),
                description=kwargs.get("description", ""),
                parameters_schema=kwargs.get("parameters_schema", {}),
                source_code=kwargs.get("source_code", ""),
                domains=kwargs.get("domains") or ["general"],
            )

        if tool_name == "list_user_tool_extensions":
            from ..core.user_tool_extensions import list_user_tools

            rows = list_user_tools(include_candidates=kwargs.get("include_candidates", True))
            return {
                "ok": True,
                "message": f"Found {len(rows)} user tool extension(s).",
                "data": {"tools": rows},
                "artifacts": [],
                "warnings": [],
            }

        if tool_name == "run_user_tool_extension":
            from ..core.user_tool_extensions import execute_user_tool, get_user_tool
            from ..core.validators import validate_required, validate_schema_values

            extension_name = kwargs.get("tool_name", "")
            definition = get_user_tool(extension_name, include_candidates=True)
            if definition is None:
                return {
                    "ok": False,
                    "message": f"User tool '{extension_name}' is not available.",
                    "data": {},
                    "artifacts": [],
                    "warnings": [],
                    "error_type": "not_found",
                    "suggestions": ["Create the candidate first or list available user tools."],
                }
            arguments = kwargs.get("arguments") or {}
            required_report = validate_required(
                arguments,
                definition.get("parameters_schema", {}).get("required", []),
            )
            argument_report = validate_schema_values(arguments, definition.get("parameters_schema", {}))
            if not required_report.ok or not argument_report.ok:
                issues = required_report.to_dict().get("issues", []) + argument_report.to_dict().get("issues", [])
                return {
                    "ok": False,
                    "message": "User tool arguments do not match its registered parameter schema.",
                    "data": {"validation_issues": issues},
                    "artifacts": [],
                    "warnings": [],
                    "error_type": "argument_error",
                    "suggestions": ["Correct the arguments and retry the candidate test."],
                }
            return execute_user_tool(extension_name, iface, arguments)

        if tool_name == "register_user_tool_extension":
            from ..core.user_tool_extensions import register_user_tool

            return register_user_tool(
                tool_name=kwargs.get("tool_name", ""),
                verification_summary=kwargs.get("verification_summary", ""),
            )

        if tool_name == "run_gee_sentinel2_download_workflow":
            return _run_gee_sentinel2_download_workflow(
                iface,
                kwargs,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        if tool_name == "run_gee_dem_download_workflow":
            return _run_gee_dem_download_workflow(
                iface,
                kwargs,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        if tool_name == "run_osm_acquisition_workflow":
            from .qgis_tools.workflow_tools import run_osm_acquisition_workflow

            return run_osm_acquisition_workflow(
                iface,
                place_name=kwargs.get("place_name", ""),
                output_dir=kwargs.get("output_dir", ""),
                output_prefix=kwargs.get("output_prefix", ""),
                components=kwargs.get("components"),
                max_chunk_area=kwargs.get("max_chunk_area", 0.25),
                overwrite=kwargs.get("overwrite", False),
                continue_on_error=kwargs.get("continue_on_error", True),
                save_project=kwargs.get("save_project", False),
                project_path=kwargs.get("project_path", ""),
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        if tool_name == "load_external_layer":
            from .qgis_tools.external_data import load_external_layer

            return load_external_layer(
                source_path=kwargs.get("source_path", ""),
                layer_name=kwargs.get("layer_name", ""),
                layer_type=kwargs.get("layer_type", "auto"),
                copy_to_project=kwargs.get("copy_to_project", False),
                target_file_name=kwargs.get("target_file_name", ""),
                overwrite=kwargs.get("overwrite", False),
            )

        if tool_name == "run_qgis_workflow_batch":
            return _run_qgis_workflow_batch(
                iface,
                kwargs,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        if tool_name == "repair_common_qgis_code_issues":
            from ..core.code_repair import repair_common_qgis_code_issues
            return repair_common_qgis_code_issues(
                code=kwargs.get("code", ""),
                error_message=kwargs.get("error_message", ""),
                context=kwargs.get("context", ""),
            )

        if tool_name == "rebuild_qgis_catalog":
            from ..core.processing_catalog import rebuild_qgis_catalog
            return rebuild_qgis_catalog(force=kwargs.get("force", True))

        if tool_name == "search_processing_algorithms":
            from ..core.processing_catalog import search_processing_algorithms
            return search_processing_algorithms(
                query=kwargs.get("query", ""),
                provider=kwargs.get("provider", ""),
                limit=kwargs.get("limit", 8),
            )

        if tool_name == "describe_processing_algorithm":
            from ..core.processing_catalog import describe_processing_algorithm
            return describe_processing_algorithm(alg_id=kwargs.get("alg_id", ""))

        if tool_name == "validate_processing_algorithm_call":
            from ..core.processing_catalog import validate_processing_algorithm_call
            return validate_processing_algorithm_call(
                alg_id=kwargs.get("alg_id", ""),
                parameters=kwargs.get("parameters", {}),
            )

        if tool_name == "search_qgis_expression_functions":
            from ..core.processing_catalog import search_qgis_expression_functions
            return search_qgis_expression_functions(
                query=kwargs.get("query", ""),
                limit=kwargs.get("limit", 8),
            )

        if tool_name == "describe_qgis_expression_function":
            from ..core.processing_catalog import describe_qgis_expression_function
            return describe_qgis_expression_function(name=kwargs.get("name", ""))

        if tool_name == "validate_qgis_expression":
            from ..core.processing_catalog import validate_qgis_expression
            return validate_qgis_expression(
                expression=kwargs.get("expression", ""),
                layer_name=kwargs.get("layer_name", ""),
            )

        if tool_name == "search_project_layers":
            from ..core.processing_catalog import search_project_layers
            return search_project_layers(
                query=kwargs.get("query", ""),
                limit=kwargs.get("limit", 20),
            )

        if tool_name == "describe_project_layer":
            from ..core.processing_catalog import describe_project_layer
            return describe_project_layer(layer_name=kwargs.get("layer_name", ""))

        if tool_name == "search_layer_fields":
            from ..core.processing_catalog import search_layer_fields
            return search_layer_fields(
                layer_name=kwargs.get("layer_name", ""),
                query=kwargs.get("query", ""),
                limit=kwargs.get("limit", 20),
            )

        if tool_name == "clip_vector_layers_to_boundary":
            from .qgis_tools.workflow_tools import clip_vector_layers_to_boundary
            return clip_vector_layers_to_boundary(
                boundary_layer_name=kwargs.get("boundary_layer_name", ""),
                clip_tasks=kwargs.get("clip_tasks", []),
                output_dir=kwargs.get("output_dir", ""),
                overwrite=kwargs.get("overwrite", True),
                create_spatial_index=kwargs.get("create_spatial_index", True),
                save_project=kwargs.get("save_project", False),
                project_path=kwargs.get("project_path", ""),
            )

        if tool_name == "save_project_and_verify":
            from ..core.project_persistence import save_project_and_verify
            return save_project_and_verify(
                project_path=kwargs.get("project_path", ""),
                expected_layers=kwargs.get("expected_layers", []),
                min_layer_count=kwargs.get("min_layer_count", 1),
            )

        if tool_name == "search_gee_python_api":
            tool_name = "search_gee_api"

        if tool_name == "install_python_package":
            package_name = kwargs.get("package_name", "")
            if not package_name:
                return "Error: package_name is empty."
            if package_name.strip().startswith("-") or any(sep in package_name for sep in ("\\", "/")):
                return "Error: package_name looks unsafe. Please provide a normal package spec such as 'pandas' or 'pandas==2.2.0'."
                
            iface.messageBar().pushMessage("QGIS Agent", f"正在自动为您安装缺失的依赖库: {package_name}...", level=Qgis.MessageLevel.Info)
            
            try:
                # 1. 内存级调用 (Primary Method)
                from pip._internal import main as pip_main
                ret_code = pip_main(['install', '--user', package_name])
                if ret_code != 0:
                    raise Exception(f"pip_main returned {ret_code}")
            except Exception as e1:
                iface.messageBar().pushMessage("QGIS Agent", f"自动安装库失败: {str(e1)}", level=Qgis.MessageLevel.Warning)
                return f"Failed to install {package_name}. Error: {str(e1)}"
            
            import importlib
            importlib.invalidate_caches()
            iface.messageBar().pushMessage("QGIS Agent", f"依赖库 {package_name} 安装成功！正在恢复任务...", level=Qgis.MessageLevel.Success)
            return f"Successfully installed {package_name}. You can now import it."
            
        if tool_name == "search_gee_api":
            query = kwargs.get("query", "").lower()
            if not query:
                return "Error: query is empty."
                
            import ee
            try:
                algorithms = ee.apifunction.ApiFunction.algorithms()
            except Exception:
                try:
                    from ..bridges.gee_bridge import init_gee
                    init_gee()
                    algorithms = ee.apifunction.ApiFunction.algorithms()
                except Exception as e:
                    return f"Failed to initialize Earth Engine to fetch algorithms. Error: {str(e)}\nPlease check GEE authentication."
            
            results = []
            for name, func in algorithms.items():
                if query in name.lower() or query in func.getSignature().get('description', '').lower():
                    sig = func.getSignature()
                    args_list = []
                    for arg in sig.get('args', []):
                        arg_name = arg.get('name')
                        arg_type = arg.get('type')
                        if arg.get('optional'):
                            args_list.append(f"{arg_name}={arg_type} (optional)")
                        else:
                            args_list.append(f"{arg_name}={arg_type}")
                    
                    sig_str = f"def ee.{name}({', '.join(args_list)}) -> {sig.get('returns')}:"
                    desc = sig.get('description', '')
                    results.append(f"### ee.{name}\n```python\n{sig_str}\n```\n{desc}")
                    
                    if len(results) >= 5: # Limit to top 5 matches
                        break
            
            if not results:
                return f"No API found matching '{query}'"
            
            return "\n\n".join(results)

        if tool_name == "search_data_sources":
            from ..core.data_sources import format_search_results_markdown, search_data_sources

            result = search_data_sources(
                query=kwargs.get("query", ""),
                theme=kwargs.get("theme", ""),
                geometry_type=kwargs.get("geometry_type", ""),
                region=kwargs.get("region", ""),
                limit=kwargs.get("limit", 5),
                allow_auth=kwargs.get("allow_auth", None),
                allow_network=kwargs.get("allow_network", None),
            )
            count = len(result.get("matches", []))
            return {
                "ok": True,
                "message": f"Found {count} matching data source(s).",
                "data": {
                    "search": result,
                    "markdown": format_search_results_markdown(result),
                },
                "artifacts": [
                    {
                        "type": "data_source_search",
                        "path": "data_sources/latest_search.md",
                        "description": "Data source handbook search report.",
                    }
                ],
                "warnings": [],
            }

        if tool_name == "create_data_acquisition_plan":
            from ..core.data_sources import build_data_acquisition_plan

            try:
                plan = build_data_acquisition_plan(
                    task=kwargs.get("task", ""),
                    region=kwargs.get("region", ""),
                    data_type=kwargs.get("data_type", ""),
                    bbox=kwargs.get("bbox", ""),
                    preferred_source_id=kwargs.get("preferred_source_id", ""),
                    output_folder=kwargs.get("output_folder", "data"),
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "message": f"Failed to create data acquisition plan: {exc}",
                    "data": {},
                    "artifacts": [],
                    "warnings": [],
                    "error_type": "argument_error",
                    "suggestions": ["Provide a task or data_type and retry with a concrete data need."],
                }

            primary = ""
            if plan.get("recommended_sources"):
                primary = plan["recommended_sources"][0].get("name", "")
            return {
                "ok": True,
                "message": f"Created data acquisition plan{f' using {primary}' if primary else ''}.",
                "data": {
                    "acquisition_plan": plan,
                    "markdown": plan.get("markdown", ""),
                },
                "artifacts": [
                    {
                        "type": "data_acquisition_plan",
                        "path": "data_sources/acquisition_plan.md",
                        "description": "Data acquisition plan report.",
                    }
                ],
                "warnings": plan.get("warnings", []),
            }
            
        if tool_name == "list_layers":
            layers = QgsProject.instance().mapLayers().values()
            if not layers:
                return "No layers found in the project."
            result = []
            for layer in layers:
                result.append(f"- {layer.name()} (ID: {layer.id()}, Type: {'Vector' if layer.type() == QgsMapLayerType.VectorLayer else 'Raster'})")
            return "\n".join(result)
            
        elif tool_name == "zoom_to_layer":
            layer_name = kwargs.get("layer_name")
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if not layers:
                return f"Layer '{layer_name}' not found."
            layer = layers[0]
            iface.mapCanvas().setExtent(layer.extent())
            iface.mapCanvas().refresh()
            return f"Zoomed to layer '{layer_name}' successfully."
            
        elif tool_name == "set_layer_visibility":
            layer_name = kwargs.get("layer_name")
            visible = kwargs.get("visible")
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if not layers:
                return f"Layer '{layer_name}' not found."
            layer = layers[0]
            root = QgsProject.instance().layerTreeRoot()
            node = root.findLayer(layer.id())
            if node:
                node.setItemVisibilityChecked(visible)
                return f"Layer '{layer_name}' visibility set to {visible}."
            return f"Layer node for '{layer_name}' not found in the layer tree."
            
        elif tool_name == "create_geodatabase":
            from qgis.core import QgsVectorFileWriter
            import os
            from ..core.tool_result import ToolResult
            from ..core.validators import validate_path_within_allowed_roots
            
            db_path = kwargs.get("database_path")
            layer_name = kwargs.get("layer_name")
            geom_type = kwargs.get("geometry_type")
            crs = kwargs.get("crs")
            
            if not db_path:
                return "Error: database_path is required."
            path_report = validate_path_within_allowed_roots(db_path, "database_path")
            if not path_report.ok:
                return ToolResult.failure(
                    "GeoPackage path is outside the allowed workspace.",
                    error_type="file_path_error",
                    data={"database_path": db_path, "validation": path_report.to_dict()},
                ).to_dict()
            
            parent_dir = os.path.dirname(db_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            if os.path.exists(db_path):
                return f"Error: database already exists at {db_path}. Refusing to overwrite it."
            
            if not layer_name:
                try:
                    from osgeo import ogr
                    driver = ogr.GetDriverByName("GPKG")
                    if not driver:
                        return "Error: GDAL GPKG driver is not available."
                    ds = driver.CreateDataSource(db_path)
                    if ds is None:
                        return f"Failed to create GeoPackage database at {db_path}."
                    ds = None
                    return f"Empty GeoPackage database created at {db_path}."
                except Exception as e:
                    return f"Failed to create GeoPackage with GDAL/OGR: {str(e)}"
                
            if not geom_type or not crs:
                return "Error: geometry_type and crs are required when layer_name is provided."

            # Create a layer to initialize the gpkg
            uri = f"{geom_type}?crs={crs}"
            layer = QgsVectorLayer(uri, layer_name, "memory")
            if not layer.isValid():
                return f"Failed to create memory layer for geometry {geom_type} and crs {crs}."
                
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            
            writer_result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                db_path,
                QgsProject.instance().transformContext(),
                options
            )
            error = writer_result[0]
            msg = writer_result[1] if len(writer_result) > 1 else ""
            
            if error == QgsVectorFileWriter.NoError:
                # Load the newly created layer into the project
                gpkg_layer = QgsVectorLayer(f"{db_path}|layername={layer_name}", layer_name, "ogr")
                if gpkg_layer.isValid():
                    QgsProject.instance().addMapLayer(gpkg_layer)
                    return f"GeoPackage database created at {db_path} and initialized with layer '{layer_name}'."
                return f"GeoPackage database created at {db_path}, but failed to load the new layer into QGIS."
            else:
                return f"Failed to create GeoPackage: {msg}"
            
        elif tool_name == "inspect_layer_fields":
            layer_name = kwargs.get("layer_name")
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if not layers:
                return f"Layer '{layer_name}' not found."
            layer = layers[0]
            if layer.type() != QgsMapLayerType.VectorLayer:
                return f"Layer '{layer_name}' is not a vector layer."
            fields = layer.fields()
            result = [f"Fields for vector layer '{layer_name}':"]
            for field in fields:
                result.append(f"- {field.name()}: {field.typeName()}")
            return "\n".join(result)
            
        elif tool_name == "get_selected_features":
            layer_name = kwargs.get("layer_name")
            limit = kwargs.get("limit", 10)
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if not layers:
                return f"Layer '{layer_name}' not found."
            layer = layers[0]
            if layer.type() != QgsMapLayerType.VectorLayer:
                return f"Layer '{layer_name}' is not a vector layer."
            selected = layer.selectedFeatures()
            if not selected:
                return f"No features are currently selected in layer '{layer_name}'."
            result = [f"Total selected features: {len(selected)}"]
            result.append(f"Showing up to {limit} features:")
            for i, feat in enumerate(selected[:limit]):
                attrs = feat.attributes()
                result.append(f"  Feature {feat.id()}: {attrs}")
            return "\n".join(result)
            
        elif tool_name == "select_features_by_expression":
            layer_name = kwargs.get("layer_name")
            expression_str = kwargs.get("expression")
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if not layers:
                return f"Layer '{layer_name}' not found."
            layer = layers[0]
            if layer.type() != QgsMapLayerType.VectorLayer:
                return f"Layer '{layer_name}' is not a vector layer."
            
            exp = QgsExpression(expression_str)
            if exp.hasParserError():
                return f"Expression error: {exp.parserErrorString()}"
                
            layer.selectByExpression(expression_str)
            count = layer.selectedFeatureCount()
            return f"Successfully selected {count} features using expression: {expression_str}"
            
        elif tool_name == "clear_selection":
            layer_name = kwargs.get("layer_name")
            if layer_name:
                layers = QgsProject.instance().mapLayersByName(layer_name)
                if not layers:
                    return f"Layer '{layer_name}' not found."
                layer = layers[0]
                if layer.type() == QgsMapLayerType.VectorLayer:
                    layer.removeSelection()
                    return f"Selection cleared for layer '{layer_name}'."
                return f"Layer '{layer_name}' is not a vector layer."
            else:
                for layer in QgsProject.instance().mapLayers().values():
                    if layer.type() == QgsMapLayerType.VectorLayer:
                        layer.removeSelection()
                return "Selection cleared for all vector layers."
                
        elif tool_name == "zoom_to_selected":
            layer_name = kwargs.get("layer_name")
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if not layers:
                return f"Layer '{layer_name}' not found."
            layer = layers[0]
            if layer.type() != QgsMapLayerType.VectorLayer:
                return f"Layer '{layer_name}' is not a vector layer."
            if layer.selectedFeatureCount() == 0:
                return f"No selected features in layer '{layer_name}' to zoom to."
            box = layer.boundingBoxOfSelected()
            iface.mapCanvas().setExtent(box)
            iface.mapCanvas().refresh()
            return f"Zoomed to selected features in layer '{layer_name}'."
            
        elif tool_name == "run_processing_algorithm":
            from qgis.core import QgsProcessingFeedback
            from qgis.PyQt.QtCore import QCoreApplication
            from ..core.tool_result import ToolResult
            import os
            alg_id = kwargs.get("alg_id")
            params = dict(kwargs.get("parameters", {}))
            try:
                from ..core.processing_catalog import validate_processing_algorithm_call
                live_validation = validate_processing_algorithm_call(alg_id, params)
                if not live_validation.get("ok"):
                    return ToolResult.failure(
                        live_validation.get("message", "Processing algorithm validation failed."),
                        error_type=live_validation.get("error_type", "processing_error"),
                        data=live_validation.get("data", {"alg_id": alg_id, "parameters": params}),
                        suggestions=live_validation.get(
                            "suggestions",
                            ["Search and describe the processing algorithm before retrying."],
                        ),
                    ).to_dict()
            except Exception as validation_exc:
                return ToolResult.failure(
                    f"Processing catalog validation failed internally: {validation_exc}",
                    error_type="processing_error",
                    data={"alg_id": alg_id, "parameters": params},
                    suggestions=["Rebuild the processing catalog and describe the algorithm before retrying."],
                ).to_dict()
            try:
                from ..core.validators import validate_processing_request
                validation = validate_processing_request(alg_id, params)
                if not validation.ok:
                    return ToolResult.failure(
                        "Processing request validation failed.",
                        error_type="processing_error",
                        data={"alg_id": alg_id, "parameters": params, "validation": validation.to_dict()},
                    ).to_dict()
            except Exception as validation_exc:
                return ToolResult.failure(
                    f"Processing request validation failed internally: {validation_exc}",
                    error_type="processing_error",
                    data={"alg_id": alg_id, "parameters": params},
                ).to_dict()
            provider_prefix = str(alg_id).split(":", 1)[0].lower() if ":" in str(alg_id) else ""
            is_external_provider = provider_prefix in {"gdal", "grass", "grass7", "saga"}
            exec_params = dict(params)

            def _resolve_proc_input_value(val):
                if not isinstance(val, str) or not val or val in ("TEMPORARY_OUTPUT", "memory:"):
                    return val
                if os.path.exists(val):
                    return val
                layer_obj = _find_project_layer(val)
                if layer_obj is None:
                    return val
                if is_external_provider:
                    src_file = str(layer_obj.source() or "").split("|", 1)[0]
                    if src_file and os.path.exists(src_file):
                        return src_file
                return layer_obj

            for k, v in list(exec_params.items()):
                if v == "TEMPORARY_OUTPUT":
                    exec_params[k] = "TEMPORARY_OUTPUT"
                elif isinstance(v, str):
                    exec_params[k] = _resolve_proc_input_value(v)
                elif isinstance(v, list):
                    exec_params[k] = [_resolve_proc_input_value(item) for item in v]
                    
            class EventPumpingFeedback(QgsProcessingFeedback):
                def setProgress(self, progress):
                    super().setProgress(progress)
                    QCoreApplication.processEvents()
                    
            feedback = EventPumpingFeedback()
            try:
                try:
                    import processing.core.Processing
                    processing.core.Processing.Processing.initialize()
                except Exception:
                    pass
                result = processing.run(alg_id, exec_params, feedback=feedback)
                output_summary = []
                inspection = {}
                try:
                    from ..core.result_inspector import inspect_processing_result
                    inspection = inspect_processing_result(result)
                    for warning in inspection.get("warnings", []):
                        output_summary.append(f"Validation warning: {warning}")
                except Exception:
                    pass
                for k, v in result.items():
                    if isinstance(v, (QgsVectorLayer, QgsRasterLayer)):
                        from .qgis_tools.io_tools import find_existing_layer
                        layer_type = "raster" if isinstance(v, QgsRasterLayer) else "vector"
                        existing = find_existing_layer(path=v.source(), layer_type=layer_type)
                        if existing:
                            output_summary.append(f"{k}: Reused existing layer {existing.name()} ({v.source()}).")
                            continue
                        QgsProject.instance().addMapLayer(v)
                        output_summary.append(f"{k}: Layer {v.name()} generated and added to project.")
                    elif isinstance(v, str) and (k.upper() == 'OUTPUT' or 'layer' in k.lower()):
                        # In QGIS 3/4, sometimes memory: outputs are returned as string IDs
                        layer = QgsProject.instance().mapLayer(v)
                        if layer:
                            output_summary.append(f"{k}: Layer {layer.name()} generated.")
                        elif os.path.exists(v):
                            layer_name = os.path.splitext(os.path.basename(v))[0]
                            from .qgis_tools.io_tools import load_raster_layer, load_vector_layer
                            try:
                                raster_layer = load_raster_layer(v, layer_name)
                                output_summary.append(f"{k}: Raster layer {raster_layer.name()} generated/reused ({v}).")
                            except Exception:
                                try:
                                    vector_layer = load_vector_layer(v, layer_name)
                                    output_summary.append(f"{k}: Vector layer {vector_layer.name()} generated/reused ({v}).")
                                except Exception:
                                    output_summary.append(f"{k}: {v}")
                        else:
                            output_summary.append(f"{k}: {v}")
                    else:
                        output_summary.append(f"{k}: {v}")
                        
                # Verify that any explicit file outputs actually exist on disk
                missing_outputs = []
                for param_k, param_v in params.items():
                    if isinstance(param_v, str) and (param_v.lower().endswith(('.tif', '.tiff', '.shp', '.geojson', '.gpkg')) or os.path.isabs(param_v)):
                        if param_v not in ("TEMPORARY_OUTPUT", "memory:") and not os.path.exists(param_v):
                            missing_outputs.append((param_k, param_v))

                if missing_outputs:
                    return ToolResult.failure(
                        f"Algorithm '{alg_id}' completed, but output file(s) were not created on disk: "
                        + ", ".join(f"{k}='{v}'" for k, v in missing_outputs)
                        + ". The backend (e.g. GRASS/GDAL) may have encountered memory limits or execution errors.",
                        error_type="missing_output_file",
                        data={"alg_id": alg_id, "parameters": params, "missing_outputs": missing_outputs},
                        suggestions=[
                            "Check memory allocation (e.g. memory=2000 for large DEMs in grass:r.watershed).",
                            "Consider using QGIS native processing algorithms (like native:fillsinkswangliu) or a direct PyQGIS script.",
                        ],
                    ).to_dict()

                return ToolResult.success(
                    f"Algorithm '{alg_id}' completed successfully.",
                    data={
                        "alg_id": alg_id,
                        "parameters": params,
                        "outputs": output_summary,
                        "inspection": inspection,
                    },
                ).to_dict()
            except Exception as e:
                return ToolResult.failure(
                    f"Error running algorithm '{alg_id}': {str(e)}",
                    error_type="processing_error",
                    data={"alg_id": alg_id, "parameters": params},
                ).to_dict()
                
        elif tool_name == "query_pyqgis_doc":
            import pydoc
            target_name = kwargs.get("target_name", "")
            
            target_obj = None
            try:
                import qgis.core
                if hasattr(qgis.core, target_name):
                    target_obj = getattr(qgis.core, target_name)
                else:
                    import qgis.gui
                    if hasattr(qgis.gui, target_name):
                        target_obj = getattr(qgis.gui, target_name)
                    else:
                        import processing
                        if hasattr(processing, target_name) or target_name == "processing":
                            target_obj = getattr(processing, target_name) if hasattr(processing, target_name) else processing
            except Exception as e:
                return f"Error importing modules: {str(e)}"
                
            if not target_obj:
                return f"Could not find PyQGIS object '{target_name}'. Are you sure it's in qgis.core or qgis.gui?"
                
            doc = pydoc.render_doc(target_obj, renderer=pydoc.plaintext)
            # Truncate to 10k chars to avoid blowing up context, but keep it long enough for full signatures
            max_len = 10000
            if len(doc) > max_len:
                doc = doc[:max_len] + f"\n... [Truncated, total length was {len(doc)} chars]"
            return f"--- Native PyQGIS Docs for {target_name} ---\n{doc}"
            
        elif tool_name == "download_osm_data":
            import os
            import tempfile
            from ..core.tool_result import ToolResult
            from ..core.validators import sanitize_file_stem
            from ..bridges.osm_bridge import (
                OSMDownloader,
                OverpassQueryError,
                build_bbox_query,
                classify_overpass_error,
                safe_feature_count,
            )
            
            bbox_str = kwargs.get("bbox")
            tags = kwargs.get("tags")
            raw_layer_name = kwargs.get("layer_name", "OSM_Data")
            layer_name = str(raw_layer_name or "OSM_Data").strip() or "OSM_Data"
            safe_file_stem = sanitize_file_stem(layer_name, "OSM_Data")
            geometry_type = kwargs.get("geometry_type", "lines")
            valid_geometry_types = {"points", "lines", "multilinestrings", "multipolygons", "other_relations"}
            if geometry_type not in valid_geometry_types:
                return ToolResult.failure(
                    f"Invalid geometry_type '{geometry_type}'.",
                    error_type="argument_error",
                    data={"valid_geometry_types": sorted(valid_geometry_types)},
                ).to_dict()
            
            try:
                w, s, e, n = [float(x) for x in bbox_str.split(',')]
            except Exception:
                return ToolResult.failure(
                    "bbox must be 'min_lon,min_lat,max_lon,max_lat'.",
                    error_type="argument_error",
                    data={"bbox": bbox_str},
                ).to_dict()
                
            try:
                from ..core.progress import raise_if_cancelled
                _emit_acquisition_progress(
                    progress_callback,
                    tool_name,
                    "OSM 数据下载",
                    "准备 Overpass 查询",
                    1,
                    4,
                    0,
                    "正在验证范围、标签和几何类型。",
                )
                raise_if_cancelled(cancel_callback, "OSM download was cancelled by the user.")
                query = build_bbox_query(tags, (w, s, e, n), geometry_type=geometry_type, timeout_seconds=180)
                _emit_acquisition_progress(
                    progress_callback,
                    tool_name,
                    "OSM 数据下载",
                    "准备 Overpass 查询",
                    1,
                    4,
                    100,
                    "查询已构建。",
                )
            except Exception as exc:
                from ..core.progress import DataAcquisitionCancelled
                if isinstance(exc, DataAcquisitionCancelled):
                    return ToolResult.failure(
                        str(exc),
                        error_type="operation_cancelled",
                        data={"bbox": bbox_str, "tags": tags, "geometry_type": geometry_type},
                    ).to_dict()
                return ToolResult.failure(
                    f"Invalid OSM query parameters: {exc}",
                    error_type="argument_error",
                    data={"bbox": bbox_str, "tags": tags, "geometry_type": geometry_type},
                ).to_dict()

            try:
                tmp_dir = tempfile.gettempdir()
                file_path = os.path.join(tmp_dir, f"{safe_file_stem}.osm")

                def _transfer_progress(received, total, endpoint):
                    if total > 0:
                        stage_percent = min(100.0, received / total * 100.0)
                        detail = f"{received / (1024 * 1024):.1f}/{total / (1024 * 1024):.1f} MB · {endpoint}"
                    else:
                        stage_percent = None
                        detail = f"已接收 {received / (1024 * 1024):.1f} MB · {endpoint}"
                    _emit_acquisition_progress(
                        progress_callback,
                        tool_name,
                        "OSM 数据下载",
                        "下载 Overpass 响应",
                        2,
                        4,
                        stage_percent,
                        detail,
                    )

                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 数据下载", "下载 Overpass 响应", 2, 4, 0,
                    "正在连接 Overpass 服务。",
                )
                OSMDownloader.query_osm(
                    query,
                    file_path,
                    timeout_seconds=180,
                    transfer_progress_callback=_transfer_progress,
                    cancel_callback=cancel_callback,
                )
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 数据下载", "解析 OSM 数据", 3, 4, 0,
                    f"正在解析 {geometry_type} 子图层。",
                )
                    
                from .qgis_tools.io_tools import load_vector_layer
                try:
                    uri = f"{file_path}|layername={geometry_type}"
                    layer = load_vector_layer(uri, layer_name)
                    _emit_acquisition_progress(
                        progress_callback, tool_name, "OSM 数据下载", "解析 OSM 数据", 3, 4, 100,
                        f"图层 {layer_name} 已加载。",
                    )
                    feature_count = safe_feature_count(layer)
                    _emit_acquisition_progress(
                        progress_callback, tool_name, "OSM 数据下载", "验证结果", 4, 4, 100,
                        f"要素数 {feature_count}。",
                    )
                    return ToolResult.success(
                        f"Successfully downloaded OSM data and loaded layer '{layer_name}'.",
                        data={
                            "file_path": file_path,
                            "layer_name": layer_name,
                            "geometry_type": geometry_type,
                            "feature_count": feature_count,
                            "query_debug_file": os.path.join(tmp_dir, "last_overpass_query.ql"),
                        },
                        artifacts=[
                            _artifact_entry(file_path, "osm_raw_xml", "Raw OSM XML downloaded from Overpass."),
                            _artifact_entry(os.path.join(tmp_dir, "last_overpass_query.ql"), "overpass_query", "Last Overpass query used by download_osm_data."),
                        ],
                    ).to_dict()
                except Exception as exc:
                    return ToolResult.failure(
                        f"Downloaded OSM data but QGIS failed to load sublayer '{geometry_type}': {exc}",
                        error_type="qgis_layer_error",
                        data={"file_path": file_path, "layer_name": layer_name, "geometry_type": geometry_type},
                        suggestions=[
                            "Retry with another geometry_type such as multipolygons, lines, or points.",
                            "Use clip_vector_layers_to_boundary after the source layer is loaded.",
                        ],
                    ).to_dict()
            except OverpassQueryError as e:
                return ToolResult.failure(
                    f"Error downloading OSM data: {str(e)}",
                    error_type=getattr(e, "error_type", "network_error"),
                    data={
                        "bbox": bbox_str,
                        "tags": tags,
                        "layer_name": layer_name,
                        "geometry_type": geometry_type,
                        "endpoint": getattr(e, "endpoint", ""),
                    },
                    warnings=[f"Check Overpass debug files near {file_path} if they were created."],
                ).to_dict()
            except Exception as e:
                from ..core.progress import DataAcquisitionCancelled
                if isinstance(e, DataAcquisitionCancelled):
                    return ToolResult.failure(
                        str(e),
                        error_type="operation_cancelled",
                        data={"bbox": bbox_str, "tags": tags, "layer_name": layer_name, "geometry_type": geometry_type},
                    ).to_dict()
                error_type = classify_overpass_error(str(e))
                return ToolResult.failure(
                    f"Error downloading OSM data: {str(e)}",
                    error_type=error_type if error_type != "overpass_error" else "network_error",
                    data={"bbox": bbox_str, "tags": tags, "layer_name": layer_name, "geometry_type": geometry_type},
                ).to_dict()

        elif tool_name == "download_osm_boundary":
            import os
            from ..bridges.osm_bridge import OSMDownloader, safe_feature_count
            from ..core.tool_result import ToolResult
            from ..core.validators import sanitize_file_stem

            name = kwargs.get("name", "")
            output_file = kwargs.get("output_file", "")
            layer_name = kwargs.get("layer_name") or sanitize_file_stem(name, "osm_boundary")
            overwrite = bool(kwargs.get("overwrite", False))
            try:
                if not name or not output_file:
                    return ToolResult.failure(
                        "name and output_file are required.",
                        error_type="argument_error",
                        data={"name": name, "output_file": output_file},
                    ).to_dict()
                from ..core.progress import raise_if_cancelled
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 行政边界下载", "验证请求", 1, 4, 100,
                    f"目标地名：{name}",
                )
                raise_if_cancelled(cancel_callback, "OSM boundary download was cancelled by the user.")
                _ensure_output_available(output_file, overwrite)
                iface.messageBar().pushMessage("OSM Boundary", f"Downloading boundary for {name}...", Qgis.MessageLevel.Info)
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 行政边界下载", "查询 Nominatim", 2, 4, None,
                    "正在检索具有面几何的行政区结果。",
                )

                def _boundary_transfer(received, total, endpoint):
                    if total > 0:
                        stage_percent = min(100.0, received / total * 100.0)
                        detail = f"{received / 1024:.1f}/{total / 1024:.1f} KB · {endpoint}"
                    else:
                        stage_percent = None
                        detail = f"已接收 {received / 1024:.1f} KB · {endpoint}"
                    _emit_acquisition_progress(
                        progress_callback, tool_name, "OSM 行政边界下载", "查询 Nominatim", 2, 4,
                        stage_percent, detail,
                    )

                layer = OSMDownloader.download_boundary_nominatim(
                    name,
                    output_file,
                    layer_name=layer_name,
                    transfer_progress_callback=_boundary_transfer,
                    cancel_callback=cancel_callback,
                )
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 行政边界下载", "写入 GeoJSON", 3, 4, 100,
                    os.path.basename(output_file),
                )
                feature_count = safe_feature_count(layer)
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 行政边界下载", "加载并验证", 4, 4, 100,
                    f"图层有效，要素数 {feature_count}。",
                )
                return ToolResult.success(
                    f"Downloaded OSM boundary '{layer_name}' to {output_file}.",
                    data={"name": name, "output_file": output_file, "layer_name": layer_name, "feature_count": feature_count},
                    artifacts=[_artifact_entry(output_file, "osm_boundary", "Downloaded OSM/Nominatim boundary GeoJSON.")],
                ).to_dict()
            except Exception as exc:
                from ..core.progress import DataAcquisitionCancelled
                if isinstance(exc, DataAcquisitionCancelled):
                    return ToolResult.failure(
                        str(exc),
                        error_type="operation_cancelled",
                        data={"name": name, "output_file": output_file, "layer_name": layer_name},
                    ).to_dict()
                return ToolResult.failure(
                    f"Failed to download OSM boundary: {exc}",
                    error_type="network_error",
                    data={"name": name, "output_file": output_file, "layer_name": layer_name},
                ).to_dict()

        elif tool_name == "download_osm_roads":
            import os
            from ..bridges.osm_bridge import OSMDownloader, classify_overpass_error, safe_feature_count
            from ..core.tool_result import ToolResult

            boundary_layer_name = kwargs.get("boundary_layer_name", "")
            output_file = kwargs.get("output_file", "")
            network_type = kwargs.get("network_type", "roads") or "roads"
            overwrite = bool(kwargs.get("overwrite", False))
            try:
                if not boundary_layer_name or not output_file:
                    return ToolResult.failure(
                        "boundary_layer_name and output_file are required.",
                        error_type="argument_error",
                        data={"boundary_layer_name": boundary_layer_name, "output_file": output_file},
                    ).to_dict()
                from ..core.progress import raise_if_cancelled
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "验证边界", 1, 4, 0,
                    f"边界图层：{boundary_layer_name}",
                )
                raise_if_cancelled(cancel_callback, "OSM network download was cancelled by the user.")
                _ensure_output_available(output_file, overwrite)
                boundary_layer = _find_project_layer(boundary_layer_name)
                if boundary_layer is None:
                    return ToolResult.failure(
                        f"Boundary layer '{boundary_layer_name}' was not found.",
                        error_type="qgis_layer_error",
                        data={"boundary_layer_name": boundary_layer_name},
                    ).to_dict()
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "验证边界", 1, 4, 100,
                    f"边界图层 {boundary_layer.name()} 有效。",
                )
                iface.messageBar().pushMessage("OSM Roads", f"Downloading {network_type} network...", Qgis.MessageLevel.Info)
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "构建 OSMnx 网络", 2, 4, None,
                    "正在请求网络并构建拓扑，此阶段服务端不提供百分比。",
                )

                def _network_progress(stage_percent, detail):
                    _emit_acquisition_progress(
                        progress_callback, tool_name, "OSM 路网下载", "构建 OSMnx 网络", 2, 4,
                        stage_percent, detail,
                    )

                try:
                    layer = OSMDownloader.download_and_clean_network(
                        boundary_layer,
                        network_type,
                        output_file,
                        task_progress_callback=_network_progress,
                        cancel_callback=cancel_callback,
                    )
                except Exception as net_exc:
                    if "osmnx" not in str(net_exc).lower() and not isinstance(net_exc, ImportError):
                        raise
                    # Automatic zero-dependency fallback via chunked Overpass download
                    fallback_preset = "waterways" if network_type == "water" else "roads"
                    return _execute_osm_feature_download(
                        {
                            "boundary_layer_name": boundary_layer_name,
                            "preset": fallback_preset,
                            "output_file": output_file,
                            "layer_name": os.path.splitext(os.path.basename(output_file))[0],
                            "overwrite": overwrite,
                            "split_large_bbox": True,
                        },
                        progress_callback=progress_callback,
                        cancel_callback=cancel_callback,
                    )
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "写入网络文件", 3, 4, 100,
                    os.path.basename(output_file),
                )
                feature_count = safe_feature_count(layer)
                _emit_acquisition_progress(
                    progress_callback, tool_name, "OSM 路网下载", "加载并验证", 4, 4, 100,
                    f"网络要素数 {feature_count}。",
                )
                return ToolResult.success(
                    f"Downloaded OSM {network_type} network to {output_file}.",
                    data={
                        "boundary_layer_name": boundary_layer_name,
                        "output_file": output_file,
                        "layer_name": layer.name() if hasattr(layer, "name") else os.path.splitext(os.path.basename(output_file))[0],
                        "network_type": network_type,
                        "feature_count": feature_count,
                        "osmnx_cache": os.path.join(os.path.dirname(os.path.abspath(output_file)), "osmnx_cache"),
                    },
                    artifacts=[_artifact_entry(output_file, "osm_network", "Downloaded and cleaned OSM network output.")],
                ).to_dict()
            except Exception as exc:
                from ..core.progress import DataAcquisitionCancelled
                if isinstance(exc, DataAcquisitionCancelled):
                    return ToolResult.failure(
                        str(exc),
                        error_type="operation_cancelled",
                        data={"boundary_layer_name": boundary_layer_name, "output_file": output_file, "network_type": network_type},
                    ).to_dict()
                error_type = getattr(exc, "error_type", None) or classify_overpass_error(str(exc))
                return ToolResult.failure(
                    f"Failed to download OSM network: {exc}",
                    error_type=error_type if error_type != "overpass_error" else "network_error",
                    data={"boundary_layer_name": boundary_layer_name, "output_file": output_file, "network_type": network_type},
                ).to_dict()

        elif tool_name == "download_osm_features":
            return _execute_osm_feature_download(
                kwargs,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        elif tool_name == "read_skill":
            import os
            from ..core.validators import validate_safe_name
            skill_name = kwargs.get("skill_name")
            if not skill_name:
                return "Error: skill_name is required."
            name_report = validate_safe_name(skill_name, "skill_name")
            if not name_report.ok:
                return {
                    "ok": False,
                    "message": "Invalid skill_name.",
                    "data": {"validation": name_report.to_dict()},
                    "artifacts": [],
                    "warnings": [],
                    "error_type": "argument_error",
                    "suggestions": ["Use only letters, numbers, underscore, and hyphen in skill_name."],
                }
            
            # Search in core and dynamic directories
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            core_path = os.path.join(base_dir, "skills", "core", f"{skill_name}.md")
            dynamic_path = os.path.join(base_dir, "skills", "dynamic", f"{skill_name}.md")
            
            if os.path.exists(core_path):
                with open(core_path, 'r', encoding='utf-8') as f:
                    return f.read()
            elif os.path.exists(dynamic_path):
                with open(dynamic_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                return f"Error: Skill '{skill_name}' not found."

        elif tool_name == "save_or_update_dynamic_skill":
            import os
            from ..core.validators import validate_safe_name
            skill_name = kwargs.get("skill_name")
            desc = kwargs.get("description", "")
            rules = kwargs.get("rules")
            action = kwargs.get("action")
            
            if not skill_name or not rules or not action:
                return "Error: skill_name, rules, and action are required."
            name_report = validate_safe_name(skill_name, "skill_name")
            if not name_report.ok:
                return {
                    "ok": False,
                    "message": "Invalid skill_name.",
                    "data": {"validation": name_report.to_dict()},
                    "artifacts": [],
                    "warnings": [],
                    "error_type": "argument_error",
                    "suggestions": ["Use only letters, numbers, underscore, and hyphen in skill_name."],
                }
                
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            dynamic_dir = os.path.join(base_dir, "skills", "dynamic")
            os.makedirs(dynamic_dir, exist_ok=True)
            
            file_path = os.path.join(dynamic_dir, f"{skill_name}.md")
            
            if action == "create":
                if os.path.exists(file_path):
                    return f"Error: Skill '{skill_name}' already exists. Use action='update' instead."
                content = f"<skill>\n<name>{skill_name}</name>\n<description>{desc}</description>\n\n<strict_rules>\n{rules}\n</strict_rules>\n</skill>"
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return f"Successfully created dynamic skill '{skill_name}'."
                
            elif action == "update":
                if not os.path.exists(file_path):
                    # Check if it's trying to update a core skill
                    core_path = os.path.join(base_dir, "skills", "core", f"{skill_name}.md")
                    if os.path.exists(core_path):
                        return f"Error: '{skill_name}' is a core skill and cannot be modified directly. You should create a new dynamic skill to override it."
                    return f"Error: Dynamic skill '{skill_name}' does not exist to update."
                
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write(f"\n\n<!-- UPDATE -->\n<strict_rules>\n{rules}\n</strict_rules>")
                return f"Successfully updated dynamic skill '{skill_name}'."

        else:
            from ..core.user_tool_extensions import get_user_tool, execute_user_tool

            if get_user_tool(tool_name, include_candidates=False) is not None:
                return execute_user_tool(tool_name, iface, kwargs)
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        import traceback
        return f"Error executing tool {tool_name}: {str(e)}\n{traceback.format_exc()}"
