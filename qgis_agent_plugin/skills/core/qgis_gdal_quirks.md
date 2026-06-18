<skill>
<name>qgis_gdal_quirks</name>
<description>当任务涉及 QGIS 原生算法调用、GDAL 空间处理、栅格计算、图层颜色修改与排版时，必须首先阅读此技能。</description>

<strict_rules>
- **Raster Processing**: `native:focalstatistics` does NOT exist. Use `gdal:rasterneighbor`. `native:contour` does NOT exist. Use `gdal:contour`. `native:viewshed` does NOT exist. Use `qgis:viewshed`.
- **GDAL Algorithm Outputs**: GDAL algorithms (e.g., `gdal:slope`, `gdal:aspect`, `gdal:contour`) do NOT support `'memory:'` as output! You MUST use `'TEMPORARY_OUTPUT'` instead.
- **Qt Imports**: Do NOT import `PyQt5` or `PyQt6` directly! ALWAYS use QGIS's version-independent wrapper: `from qgis.PyQt...` (e.g., `from qgis.PyQt.QtCore import QVariant`, `from qgis.PyQt.QtGui import QFont`).
- **Reclassify by Table (`native:reclassifybytable`)**: The `TABLE` parameter must be a simple, flat 1D Python list (e.g., `[min1, max1, val1, min2, max2, val2]`), NOT a list of dictionaries.
- **Raster Calculator CRS**: Raster calculator and overlay algorithms strictly require inputs to share the same Projected CRS. If a DEM is in Geographic CRS (EPSG:4490 or EPSG:4326), you MUST use `gdal:warpreproject` to project it to a UTM planar CRS before calculating slope or distance!
- **Processing Logs/Feedback**: Do NOT pass `feedback=None` to `processing.run()`. You MUST use `feedback=PrintFeedback()` (this class is globally available in your environment) to capture and print underlying QGIS C++ algorithm logs/errors.
- **Qgis MessageLevel**: ALWAYS import `Qgis` from `qgis.core` and use `Qgis.Info`, `Qgis.Warning`, `Qgis.Success`, `Qgis.Critical` for `pushMessage` levels. Do NOT use integers like `level=0`!
- **Layout API**: Do NOT use `QgsLayoutItemNorthArrow`, use `QgsLayoutItemPicture` with an SVG path. Do not use `title.setFontSize()`, use `font = QFont(); font.setPointSize(18); title.setFont(font)`.
</strict_rules>
</skill>
