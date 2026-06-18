<skill>
<name>qgis_projection_selection</name>
<description>当任务涉及计算面积、距离、或需要进行缓冲区分析 (Buffer)、叠加分析 (Overlay) 等严谨的空间计算时，必须首先阅读此技能，以防止因坐标系错误导致结果严重失真。</description>

<strict_rules>
- **绝对禁止计算经纬度面积**：在 EPSG:4326 (WGS84) 等 Geographic CRS 下计算出来的面积和距离是毫无意义的度（degrees）。**在进行任何 `native:buffer` 或面积统计前，你必须先检查图层的 CRS！** 如果是经纬度，必须使用 `native:reprojectlayer` 进行投影转换！
- **等面积投影 (Equal-Area)**：如果任务是“计算某某省份的森林覆盖面积”、“统计各县域的人口密度”，你必须将图层投影至**等面积投影**（如 Albers Equal-Area Conic）。对于中国区域，推荐使用 `EPSG:102022` (Asia_North_Albers_Equal_Area_Conic) 或根据经纬度自定义 Albers 参数。
- **等角投影 / 局部大比例尺 (Conformal / Local)**：如果任务是“为某个城市建立 500 米缓冲区”、“分析局部的道路距离”，你必须使用 UTM投影 或 高斯-克吕格投影 (Gauss-Kruger)。
- **智能获取最佳投影 (PyQGIS 技巧)**：不要盲目猜 EPSG 代码。你可以通过获取图层的 `extent()` 中点经纬度，然后利用 PyQGIS 的 `QgsCoordinateReferenceSystem` 寻找适合该区域的 UTM 带。例如，对于东经 113 度，UTM 带号为 `int((113 + 180) / 6) + 1` = 49，若在北半球，则是 UTM Zone 49N (EPSG:32649)。
- **栅格计算器与叠加前提**：两个图层（尤其是 Raster 与 Vector，或 Raster 与 Raster）进行运算前，必须确保它们的投影坐标系**完全一致**。如果不一致，必须先重投影基准坐标系。
</strict_rules>
</skill>
