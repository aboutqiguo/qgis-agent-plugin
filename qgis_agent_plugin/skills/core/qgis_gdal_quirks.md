<skill>
<name>qgis_gdal_quirks</name>
<description>当任务涉及 QGIS 原生算法调用、GDAL 空间处理、栅格计算、图层颜色修改与排版时，必须首先阅读此技能。</description>

<strict_rules>
- **Package Installation (CRITICAL)**: NEVER use `subprocess.run([sys.executable, "-m", "pip"...])` to install packages! This causes infinite frozen windows in QGIS. Instead, if you get `ModuleNotFoundError`, you MUST interrupt your code and call the `install_python_package` tool to safely install missing packages in memory.
- **Raster Calculator Import**: `QgsRasterCalculator` has moved in recent QGIS versions! Do NOT import it from `qgis.core`. You MUST use `from qgis.analysis import QgsRasterCalculator`.
- **Raster Min/Max Stats**: Do NOT call `maximumValue()` or `minimumValue()` on `QgsRasterLayer` or its provider in QGIS 3.44. Use `provider.bandStatistics(1, QgsRasterBandStats.All)` and then read `stats.maximumValue` / `stats.minimumValue`.
- **Raster Processing**: NEITHER `native:focalstatistics` NOR `qgis:focalstatistics` exist! You MUST use `gdal:rasterneighbor` instead. `native:contour` does NOT exist, use `gdal:contour`. `native:viewshed` does NOT exist, use `qgis:viewshed`.
- **Qgis MessageLevel**: When using `iface.messageBar().pushMessage()`, you MUST add `from qgis.core import Qgis` at the top of your script and use `Qgis.MessageLevel.Info/Warning/Critical/Success`. Do not use integers like `level=0`!
- **Layer Parameters**: When a QGIS native function (like adding to QgsProject) expects a layer object, you MUST pass the actual `QgsMapLayer` or `QgsVectorLayer` instance. NEVER pass a string ID or absolute file path!
- **GDAL Algorithm Outputs**: GDAL algorithms (e.g., `gdal:slope`, `gdal:aspect`, `gdal:contour`) do NOT support `'memory:'` as output! You MUST use `'TEMPORARY_OUTPUT'` instead.
- **Qt Imports**: Do NOT import `PyQt5` or `PyQt6` directly! ALWAYS use QGIS's version-independent wrapper: `from qgis.PyQt...` (e.g., `from qgis.PyQt.QtCore import Qt`).
- **Reclassify by Table (`native:reclassifybytable`)**: The `TABLE` parameter must be a simple, flat 1D Python list (e.g., `[min1, max1, val1, min2, max2, val2]`), NOT a list of dictionaries.
- **Raster Calculator CRS**: Raster calculator and overlay algorithms strictly require inputs to share the same Projected CRS. If a DEM is Geographic (EPSG:4326), you MUST use `gdal:warpreproject` to project it to a UTM planar CRS first!
- **Rasterize / Proximity CRS (CRITICAL)**: Before `gdal:rasterize` or `gdal:proximity`, reproject vector inputs to the same projected CRS as the reference raster and use the reference raster's extent and pixel size. NEVER pass a UTM extent/cell size to an EPSG:4326 vector layer. After rasterize/proximity, inspect dimensions; reject tiny accidental outputs such as 28x28 when the reference raster is about 1000x1000.
- **Processing Logs/Feedback**: Do NOT pass `feedback=None` to `processing.run()`. You MUST use `feedback=PrintFeedback()` to capture underlying QGIS C++ algorithm logs/errors.
- **Layout API**: Do NOT use `QgsLayoutItemNorthArrow`, use `QgsLayoutItemPicture` with an SVG path. Do not use `title.setFontSize()`, use `font = QFont(); font.setPointSize(18); title.setFont(font)`.
- **Idempotent Layer Loading**: Before loading local vector/raster files, prefer `from qgis_agent_plugin.tools.qgis_tools import load_vector_layer, load_raster_layer`. These helpers reuse an existing layer with the same source by default and prevent duplicated layers after retry. Do NOT blindly call `QgsProject.instance().addMapLayer()` for file-backed layers unless you first check that the same source is not already loaded.
</strict_rules>
</skill>
