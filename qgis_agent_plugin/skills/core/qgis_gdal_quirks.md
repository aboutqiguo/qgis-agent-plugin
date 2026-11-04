<skill>
<name>qgis_gdal_quirks</name>
<description>当任务涉及 QGIS 原生算法调用、GDAL 空间处理、栅格计算、图层颜色修改与排版时，必须首先阅读此技能。</description>

<strict_rules>
- **遥感指数与波段分区统计优先工具 (CRITICAL)**：
  1. 计算归一化差值指数（NDVI、NDWI、MNDWI、NDMI、NDBI、NBR 等 `(Band_A - Band_B) / (Band_A + Band_B)`）时，**必须优先调用 `compute_raster_index` 工具**，严禁优先使用 `gdal:rastercalculator` 或 `qgis:rastercalculator`！原因：`gdal:rastercalculator` 对 `UInt16` 原始波段直接做 `(A-B)/(A+B)` 会发生无符号整型下溢回绕（算出 `0..30` 的荒谬结果），且 `qgis:rastercalculator` 经常无法解析多波段图层引用。
  2. 统计多波段栅格各波段均值/标准差、掩膜目标区（`mask=1`）与背景区（`mask=0`）区分度（`Cohen's d`、`AUC`）及最佳波段组合时，**必须优先调用 `compute_raster_zonal_stats` 工具**，无需手写冗长的 GDAL/NumPy 脚本。
- **QGIS 3.44 栅格波段与统计 API 铁律 (CRITICAL)**：
  1. `bandName(band_no)` 是 `QgsRasterLayer` 的方法，**`QgsRasterDataProvider` 没有 `bandName()` 方法**！调用 `prov.bandName(b)` 必报 `AttributeError`。
  2. `st = provider.bandStatistics(band_no)` 返回的 `QgsRasterBandStats` 对象中，最小值、最大值、均值、标准差的属性名分别为 **`st.minimumValue`**、**`st.maximumValue`**、**`st.mean`**、**`st.stdDev`**。注意：`st.mean` 是 `float` 属性而非方法（调用 `st.mean()` 必报 `TypeError: 'float' object is not callable`），且不存在 `st.minimum` 或 `st.maximum` 属性！
- **Windows 已加载栅格文件锁释放 (CRITICAL)**：在 Windows 下，如果目标 `.tif` 文件已被加载为 `QgsProject.instance()` 中的图层，直接用 GDAL `Create`/`CreateCopy`、`os.replace` 或 `os.remove` 覆盖/删除该路径必报 `PermissionError: [WinError 32]` 或 `[WinError 5] 拒绝访问`。在覆盖或删除同名栅格文件前，必须先从 `QgsProject.instance()` 移除引用该文件的图层并调用 `gc.collect()`（或者直接调用内置自动解锁的 `compute_raster_index(..., overwrite=True)`）。
- **GDAL Dataset 引用保活 (CRITICAL)**：在 Python GDAL SWIG 绑定中，切勿将 `gdal.Open(path).GetRasterBand(1).ReadAsArray()` 写成单行链式调用，否则临时 `Dataset` 会被立即垃圾回收导致 C++ 野指针 `TypeError: in method 'Band_XSize_get'`。必须先赋给变量：`ds = gdal.Open(path); arr = ds.GetRasterBand(1).ReadAsArray()`，读取完毕后再执行 `ds = None`。
- **Package Installation (CRITICAL)**: NEVER use `subprocess.run([sys.executable, "-m", "pip"...])` inside a PyQGIS script. Stop the workflow and call the high-risk `install_python_package` tool only after explicit user approval; package names must pass the built-in allowlist.
- **Raster Calculator Import**: `QgsRasterCalculator` has moved in recent QGIS versions! Do NOT import it from `qgis.core`. You MUST use `from qgis.analysis import QgsRasterCalculator`.
- **Raster Processing**: NEITHER `native:focalstatistics` NOR `qgis:focalstatistics` exist! You MUST use `gdal:rasterneighbor` instead. `native:contour` does NOT exist, use `gdal:contour`. `native:viewshed` does NOT exist, use `qgis:viewshed`.
- **Qgis MessageLevel**: When using `iface.messageBar().pushMessage()`, you MUST add `from qgis.core import Qgis` at the top of your script and use `Qgis.MessageLevel.Info/Warning/Critical/Success`. Do not use integers like `level=0`!
- **Layer Parameters**: When a QGIS native function (like adding to QgsProject) expects a layer object, you MUST pass the actual `QgsMapLayer` or `QgsVectorLayer` instance. NEVER pass a string ID or absolute file path!
- **GDAL Algorithm Outputs**: GDAL algorithms (e.g., `gdal:slope`, `gdal:aspect`, `gdal:contour`) do NOT support `'memory:'` as output! You MUST use `'TEMPORARY_OUTPUT'` instead.
- **Qt Imports**: Do NOT import `PyQt5` or `PyQt6` directly! ALWAYS use QGIS's version-independent wrapper: `from qgis.PyQt...` (e.g., `from qgis.PyQt.QtCore import Qt`).
- **Reclassify by Table (`native:reclassifybytable`)**: The `TABLE` parameter must be a simple, flat 1D Python list (e.g., `[min1, max1, val1, min2, max2, val2]`), NOT a list of dictionaries.
- **Raster Calculator CRS**: Raster calculator and overlay algorithms strictly require inputs to share the same Projected CRS. If a DEM is Geographic (EPSG:4326), you MUST use `gdal:warpreproject` to project it to a UTM planar CRS first!
- **Raster Clip NoData**: Preserve an existing source NoData value. If the source has no NoData, prefer alpha/mask output; never invent `255`, `65535`, or `-9999` based only on data type.
- **Rasterize / Proximity CRS (CRITICAL)**: Before `gdal:rasterize` or `gdal:proximity`, reproject vector inputs to the same projected CRS as the reference raster and use the reference raster's extent and pixel size. NEVER pass a UTM extent/cell size to an EPSG:4326 vector layer.
- **Idempotent Layer Loading**: Before loading local vector/raster files, prefer `from qgis_agent_plugin.tools.qgis_tools import load_vector_layer, load_raster_layer`. These helpers reuse an existing layer with the same source by default and prevent duplicated layers after retry.
- **GRASS Hydrological Analysis (`grass:r.watershed`)**: When running `grass:r.watershed` in Processing, you MUST provide `threshold` (e.g. `threshold=1000`) and `memory=2000`. If GRASS fails to write `.tif` outputs on Windows, prefer `native:fillsinkswangliu` or a direct PyQGIS/GDAL script.
</strict_rules>
</skill>
