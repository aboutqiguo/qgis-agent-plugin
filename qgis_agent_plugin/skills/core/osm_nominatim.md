<skill>
<name>osm_nominatim</name>
<description>当任务涉及下载行政边界（如省、市、县界、高校园区）或使用 OpenStreetMap (OSM) / Overpass API 下载路网、水系、建筑物、POI 等空间数据时，必须首先阅读此技能。</description>

<strict_rules>
- **优先使用已注册的 OSM 原子/工作流工具 (CRITICAL)**：严禁在 `execute_pyqgis_script` 中手写同步网络请求或直接调用 `OSMDownloader`（主线程代码守卫会拦截同步网络 I/O）。必须优先调用以下注册工具：
  1. **一站式多要素获取**：当同时需要某区域的行政边界 + 道路/建筑/水系/POI 时，优先调用 `run_osm_acquisition_workflow`。
  2. **行政区/高校/园区边界**：调用 `download_osm_boundary(name=..., output_file=..., layer_name=..., overwrite=True)`（内部基于 Nominatim，自动校验面几何）。
  3. **建筑物/水系/道路/POI/土地利用分块下载**：调用 `download_osm_features(boundary_layer_name=..., preset="buildings"|"roads"|"waterways"|"water"|"poi"|"landuse", output_file=..., overwrite=True)`。该工具内置自动分块、Overpass 多镜像容灾、按 `osm_id` 去重及 GeoPackage/GeoJSON 落盘，**无需依赖 `osmnx` 或 `geopandas`**。
  4. **拓扑路网下载**：`download_osm_roads` 会在具备 `osmnx` 时构建拓扑图，若当前 QGIS 环境未安装 `osmnx/geopandas`，会自动无感回退至 `download_osm_features` 分块 Overpass 管线，无需中断任务安装依赖。
- **BBox 顺序规范**：若显式传入 `bbox` 参数给 `download_osm_features`，格式必须为 WGS84 (`EPSG:4326`) 的 `'min_lon,min_lat,max_lon,max_lat'`（如 `'116.3,39.9,116.4,40.0'`）；而原生 Overpass QL 内部括号语法为 `(south,west,north,east)` 即 `(minLat,minLon,maxLat,maxLon)`，切勿混淆。
- **输出格式完整性**：推荐优先使用 `.gpkg` 或 `.geojson` 作为 `output_file` 后缀；仅在用户明确要求 Shapefile 时使用 `.shp`。
- **多专题连续下载隔离**：连续下载多类 OSM 要素时，每次调用必须指定独立的 `output_file` 和 `layer_name`，下载后检查返回的 `feature_count` 与 `geometry_type`，并在需要精确贴合研究区边界时调用 `clip_vector_layers_to_boundary`。
</strict_rules>
</skill>
