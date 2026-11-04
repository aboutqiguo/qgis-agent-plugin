# Declarative tool schemas for the 64 QGIS AI Agent atomic tools.

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

