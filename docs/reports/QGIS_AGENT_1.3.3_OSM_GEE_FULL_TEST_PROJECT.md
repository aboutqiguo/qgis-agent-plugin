# QGIS Agent v1.3.3 OSM + GEE 全流程测试项目

## 1. 测试目标

以“长沙市雨花区城市开发强度与生态状况”为主题，完整测试：

- OSM 行政边界、道路、建筑物、POI、水面和河流数据获取。
- GEE Sentinel-2 与 DEM 参数确认、云端处理、direct/batch 下载和本地验证。
- QGIS 矢量/栅格处理、字段计算、波段计算、空间统计和结果整理。
- 图层幂等加载、工程保存、输出验证、制图布局和 PDF/PNG 导出。
- 中断恢复、人工审批、错误状态和 token 消耗记录。

研究区：长沙市雨花区，湖南省，中国。

建议环境：QGIS 3.34 LTR 或 3.44，QGIS Agent v1.3.3。

## 2. 测试目录

在测试前手动创建并保存一个空白工程：

```text
C:\Users\SevenLita\Desktop\QGISCE\test1\yuhua_agent_test.qgz
```

必须先保存空白工程，使该目录成为 QGIS 项目主目录。后续全部输出都应位于该目录内。

预期目录：

```text
test1/
├── yuhua_agent_test.qgz
├── 01_boundary/
├── 02_osm_raw/
├── 03_osm_clipped/
├── 04_gee/
├── 05_analysis/
├── 06_map/
└── 07_report/
```

## 3. 固定参数

| 项目 | 固定值 |
| --- | --- |
| 分析 CRS | EPSG:32649（WGS 84 / UTM zone 49N） |
| Sentinel-2 collection | COPERNICUS/S2_SR_HARMONIZED |
| 时间范围 | 2024-06-01 至 2024-09-30 |
| 波段 | B2、B3、B4、B8，保持此顺序 |
| 云量阈值 | CLOUDY_PIXEL_PERCENTAGE < 20 |
| 合成方法 | cloud_masked_median |
| Sentinel-2 分辨率 | 10m |
| DEM | COPERNICUS/DEM/GLO30 |
| DEM 分辨率 | 30m |
| 分析网格 | 500m × 500m |
| 栅格 NoData | -9999，仅用于 GEE 导出；本地裁剪不得臆造新值 |

## 4. 执行规则

1. 使用 Work 模式逐条执行下面的提示词，不要把所有提示词一次发送。
2. 每一步完成后检查图层、文件和工具返回，再继续下一步。
3. 任意 Python 代码执行、依赖安装或 skill 写入出现审批弹窗时，先阅读代码/目标后再决定。
4. 工具返回失败时保留原始报错，不要让 Agent 反复执行完全相同的调用。
5. GEE 自动下载失败并返回 `awaiting_manual_download` 时，按提示完成 Drive 下载，放入指定目录后再继续验证，不得直接跳过。

## 5. 分步提示词

### 步骤 1：初始化工程结构

```text
当前 QGIS 工程已经保存到 C:/Users/SevenLita/Desktop/QGISCE/test1/yuhua_agent_test.qgz。
请确认项目主目录正确，创建 01_boundary、02_osm_raw、03_osm_clipped、04_gee、05_analysis、06_map、07_report 文件夹。
不要创建项目目录之外的文件。完成后保存并验证工程。
```

验收：七个目录存在，工程仍可保存和打开。

### 步骤 2：获取行政边界

```text
请从 OSM Nominatim 获取“长沙市雨花区, 湖南省, 中国”的行政边界。
输出到 01_boundary/yuhua_boundary.geojson，QGIS 图层名设为 yt_boundary。
加载后检查图层有效、几何为面、CRS 为 EPSG:4326、要素数大于 0，并缩放到该图层。
不要使用模糊的“雨花区”查询结果；返回 selected display_name 供我核对。保存工程。
```

验收：`yuhua_boundary.geojson` 存在；`yt_boundary` 唯一且有效；返回结果明确属于长沙市。

### 步骤 3：获取 OSM 道路和建筑物

```text
以 yt_boundary 的 EPSG:4326 外接矩形为请求范围，使用注册的 OSM 下载工具获取：
1. roads：保存为 02_osm_raw/yuhua_roads_raw.gpkg，图层名 yt_roads_raw；
2. buildings：保存为 02_osm_raw/yuhua_buildings_raw.gpkg，图层名 yt_buildings_raw。
开启大范围自动分块，max_chunk_area=0.05，允许 Overpass 超时或限流后自适应细分。
每个输出都要检查 geometry_type、feature_count、tags 和实际文件，不要手写 Overpass 分块脚本。保存工程。
```

验收：两个 GPKG 均可打开；道路为线、建筑为面；要素数均大于 0；临时 chunk 图层未留在项目中。

### 步骤 4：获取 OSM POI、水面和河流

```text
继续以 yt_boundary 范围获取以下 OSM 数据：
1. poi -> 02_osm_raw/yuhua_poi_raw.gpkg，图层名 yt_poi_raw；
2. water -> 02_osm_raw/yuhua_water_raw.gpkg，图层名 yt_water_raw；
3. waterways -> 02_osm_raw/yuhua_waterways_raw.gpkg，图层名 yt_waterways_raw。
使用 max_chunk_area=0.05。逐项验证文件、几何类型和要素数量。即使某一类为空，也要返回明确状态，不要让后续工具无提示暂停。保存工程。
```

验收：POI 为点、水面为面、河流为线；执行过程没有在水系后无状态停止。

### 步骤 5：按边界精确裁剪 OSM 数据

```text
使用 yt_boundary 将 yt_roads_raw、yt_buildings_raw、yt_poi_raw、yt_water_raw、yt_waterways_raw 精确裁剪到雨花区。
输出分别为：
- 03_osm_clipped/yuhua_roads.gpkg，yt_roads；
- 03_osm_clipped/yuhua_buildings.gpkg，yt_buildings；
- 03_osm_clipped/yuhua_poi.gpkg，yt_poi；
- 03_osm_clipped/yuhua_water.gpkg，yt_water；
- 03_osm_clipped/yuhua_waterways.gpkg，yt_waterways。
优先使用 clip_vector_layers_to_boundary；为每个任务指定明确文件名和图层名，创建空间索引并验证输出。原始图层保留但设为不可见。保存工程。
```

验收：五个裁剪文件存在；所有几何位于边界内；项目中没有 `_clipped_clipped` 或重复同源图层。

### 步骤 6：测试 Sentinel-2 参数询问

先发送不完整请求：

```text
请从 GEE 下载雨花区的 Sentinel-2 数据并加载到项目。
```

预期行为：Agent 必须弹窗询问 collection、日期、波段、云量、分辨率、处理方法、输出名、输出 CRS 和是否加载；此时不得开始下载，不得自动加入 NDVI。

在弹窗中回答：

```text
collection=COPERNICUS/S2_SR_HARMONIZED；日期=2024-06-01 至 2024-09-30；波段=B2,B3,B4,B8，保持此顺序；云量阈值=20%；分辨率=10m；处理方法=cloud_masked_median；输出名=yuhua_s2_2024_b2348.tif；输出 CRS=EPSG:32649；下载后加载图层；输出目录=C:/Users/SevenLita/Desktop/QGISCE/test1/04_gee。
```

验收：先询问、后执行；输出为 4 波段 GeoTIFF；不得生成 NDVI 文件；大于 direct 限制时走 batch/Drive 路线。

### 步骤 7：下载 DEM

```text
使用 yt_boundary 从 GEE 下载 COPERNICUS/DEM/GLO30。
分辨率 30m，输出 CRS EPSG:32649，输出名 yuhua_dem_30m.tif，保存到 04_gee，并加载为 yt_dem_30m。
这些参数已经由我明确确认，load_layer=true，边界不做默认简化。
下载后验证 GeoTIFF 可读性、范围、波段数和有效像元比例。保存工程。
```

验收：DEM 为 1 波段；CRS 为 EPSG:32649；通常应满足小文件 direct 路由，若实际估算超限则允许 batch，但必须返回真实路线。

### 步骤 8：本地精确裁剪和栅格验证

```text
将 yuhua_s2_2024_b2348.tif 和 yuhua_dem_30m.tif 按 yt_boundary 精确裁剪，输出为：
- 04_gee/yuhua_s2_2024_b2348_clipped.tif；
- 04_gee/yuhua_dem_30m_clipped.tif。
使用插件栅格裁剪工具。保留源 NoData；若源没有 NoData，则使用 alpha/mask，不得根据数据类型臆造 255、65535 或 -9999。
裁剪后强制读取并验证范围、尺寸、波段数和有效像元，再加载为 yt_s2_clipped、yt_dem_clipped。保存工程。
```

验收：S2 仍为 4 波段，DEM 为 1 波段；无损坏 block/tile；两个输出与边界重叠。

### 步骤 9：重投影矢量并计算基础字段

```text
将 yt_boundary、yt_roads、yt_buildings、yt_poi、yt_water、yt_waterways 重投影到 EPSG:32649，保存到 05_analysis/yuhua_analysis.gpkg，图层名分别加后缀 _utm。
通过 Processing Catalog 搜索、描述并验证所需算法后执行，不要猜参数名。
新增并计算：边界 area_km2；道路和河流 length_km；建筑 footprint_m2。字段计算前验证表达式。保存工程。
```

验收：六个 UTM 图层均为 EPSG:32649；面积和长度字段非负；雨花区面积结果量级合理。

### 步骤 10：波段计算和坡度计算

```text
检查 yt_s2_clipped 的波段顺序确实为 B2、B3、B4、B8。
计算 NDVI=(B8-B4)/(B8+B4)，即使用第 4 波段和第 3 波段，输出 05_analysis/yuhua_ndvi_2024.tif，图层名 yt_ndvi_2024，Float32，NoData=-9999。
再从 yt_dem_clipped 计算角度制坡度，输出 05_analysis/yuhua_slope_deg.tif，图层名 yt_slope_deg。
先通过 Processing Catalog 确认实际算法和参数，执行后验证两个栅格。NDVI 有效值应主要位于 -1 到 1，坡度不得小于 0。保存工程。
```

验收：两个分析栅格均有效；NDVI 不是四波段原图的误命名副本；没有对地理 CRS 直接进行坡度计算。

### 步骤 11：建立 500m 分析网格

```text
在 EPSG:32649 下创建覆盖 yt_boundary_utm 的 500m×500m 方格，按边界裁剪后保存到 05_analysis/yuhua_analysis.gpkg，图层名 yt_grid_500m。
创建唯一 grid_id，计算每格实际 area_km2。为空或边界外的格网不得保留。创建空间索引并验证几何有效性。
```

验收：网格唯一、无空几何，面积大于 0，边缘格网面积小于或等于 0.25km²。

### 步骤 12：道路、建筑和栅格统计

```text
以 yt_grid_500m 为统计单元完成：
1. 道路与网格相交，按 grid_id 汇总格内道路长度 road_km；
2. 建筑与网格相交，按 grid_id 汇总 building_count 和建筑相交面积 building_area_m2；
3. 对 yt_ndvi_2024 计算每格 ndvi_mean；
4. 对 yt_slope_deg 计算每格 slope_mean。
将结果连接回一个最终图层 yt_grid_stats，保存到 05_analysis/yuhua_analysis.gpkg。
新增 road_density=road_km/area_km2 和 building_coverage_pct=building_area_m2/(area_km2*1000000)*100。
所有算法和表达式先查询/验证；处理空值和除零。完成后列出字段、非空率、最小值、最大值和均值。
```

验收字段：`grid_id`、`area_km2`、`road_km`、`road_density`、`building_count`、`building_area_m2`、`building_coverage_pct`、`ndvi_mean`、`slope_mean`。

### 步骤 13：分类和结果整理

```text
在 yt_grid_stats 中新增 intensity_class：
- building_coverage_pct>=30 或 road_density>=15 -> High；
- building_coverage_pct>=15 或 road_density>=8 -> Medium；
- 其余 -> Low。
空值统一按 0 处理。验证表达式后计算，并统计 High/Medium/Low 的格网数量。

整理图层树为：01_Boundary、02_OSM_Raw、03_OSM_Clipped、04_GEE、05_Analysis、06_Final。
原始图层默认隐藏；最终保留 yt_boundary_utm、yt_roads_utm、yt_water_utm、yt_ndvi_2024、yt_grid_stats 为可见。
按规范化 source/path 去除重复图层，不删除有效输出文件。保存工程。
```

验收：分类只有 High/Medium/Low；同一文件源不重复加载；图层分组清晰。

### 步骤 14：样式与专题图布局

```text
制作“长沙市雨花区城市开发强度与生态状况（2024）”A3 横向布局，布局名 Yuhua_Urban_Ecology_2024。
主图使用 yt_grid_stats 的 intensity_class 分类：High 红色、Medium 黄色、Low 绿色；叠加灰色道路、蓝色水面/河流和深色行政边界。
增加一个 NDVI 插图，使用 yt_ndvi_2024 的棕-黄-绿连续色带，范围按实际统计设置但限制在 -1 到 1 内。
布局应包含标题、图例、比例尺、指北针、EPSG:32649、数据来源、时间范围和制图日期。中文字体优先 Microsoft YaHei，缺失时使用可用的 CJK 字体。
数据来源写明：© OpenStreetMap contributors；Google Earth Engine；Copernicus Sentinel-2 SR Harmonized；Copernicus DEM GLO-30。
导出 06_map/yuhua_urban_ecology_2024.pdf 和 06_map/yuhua_urban_ecology_2024.png，PNG 分辨率 300dpi。导出后验证文件存在且非空。保存工程。
```

验收：布局元素不重叠；主图和插图范围正确；PDF/PNG 均可打开；图例只保留有意义图层。

### 步骤 15：最终验证和报告

```text
对当前测试项目执行最终验证：
1. 检查 yuhua_agent_test.qgz 可保存；
2. 检查所有预期 GPKG、GeoTIFF、PDF、PNG；
3. 检查最终图层 CRS、几何类型、要素数、字段和栅格波段；
4. 检查项目中没有失效或重复同源图层；
5. 汇总 OSM 要素数量、GEE scene_count、下载路线、栅格有效像元比例、分类统计和输出文件大小。
将报告写入 07_report/final_validation.md。只有全部必需输出验证通过后才将状态标记为 succeeded；人工下载未完成、文件缺失或 verifier 未通过时必须使用对应的 awaiting/partial/failed 状态。
最后保存并验证工程。
```

## 6. 必需输出清单

```text
01_boundary/yuhua_boundary.geojson
03_osm_clipped/yuhua_roads.gpkg
03_osm_clipped/yuhua_buildings.gpkg
03_osm_clipped/yuhua_poi.gpkg
03_osm_clipped/yuhua_water.gpkg
03_osm_clipped/yuhua_waterways.gpkg
04_gee/yuhua_s2_2024_b2348.tif
04_gee/yuhua_dem_30m.tif
04_gee/yuhua_s2_2024_b2348_clipped.tif
04_gee/yuhua_dem_30m_clipped.tif
05_analysis/yuhua_ndvi_2024.tif
05_analysis/yuhua_slope_deg.tif
05_analysis/yuhua_analysis.gpkg
06_map/yuhua_urban_ecology_2024.pdf
06_map/yuhua_urban_ecology_2024.png
07_report/final_validation.md
yuhua_agent_test.qgz
```

## 7. 稳定性附加测试

### A. 幂等加载

重复执行步骤 15，确认图层数量不增加、同源图层不重复。

### B. 覆盖写入

在明确批准覆盖后重新生成 `yuhua_ndvi_2024.tif`，确认旧图层先释放、文件可替换并只加载一次。

### C. 中断恢复

在一个非关键 Processing 操作中点击停止，再发送“继续检查当前项目”。预期下一轮无 tool message API 400，上一轮状态为 cancelled/partial，新一轮能继续读取工程。

### D. 参数保护

再次发送“下载一份 Sentinel-2”，不提供任何参数。预期仍先询问，不得沿用或猜测上一轮日期和波段。

### E. 人工下载状态

若 Drive API 和 Desktop 同步均不可用，确认返回 `awaiting_manual_download`、准确文件名和 Drive 信息；完成人工下载并验证后才能继续。

## 8. 评分表

| 模块 | 分值 | 通过标准 |
| --- | ---: | --- |
| 工程初始化与保存 | 5 | 目录、工程和项目主目录正确 |
| OSM 边界 | 5 | 地名匹配、面有效、EPSG:4326 |
| OSM 多主题下载 | 15 | 五类数据真实有效、无静默暂停 |
| OSM 裁剪与去重 | 10 | 精确裁剪、无 chunk/重复图层 |
| GEE 参数询问 | 10 | 缺参必问、不自动 NDVI |
| Sentinel-2 下载 | 10 | 4 波段、路线真实、栅格有效 |
| DEM 下载 | 5 | 1 波段、30m、EPSG:32649 |
| 栅格裁剪/NDVI/坡度 | 10 | NoData、波段和数值范围正确 |
| 网格与空间统计 | 15 | 字段完整、公式正确、空值受控 |
| 图层整理与幂等性 | 5 | 分组清晰、无重复同源图层 |
| 制图输出 | 5 | A3 PDF/PNG 可读且布局完整 |
| 最终 verifier 与状态 | 5 | 必需输出通过后才 succeeded |

总分 100。建议：90 分以上可进入稳定发布；80–89 分需修复非阻断问题；低于 80 分或任何核心数据为假/空时不通过。

## 9. 日志与 token 记录

测试结束后保留：

- `qgis_agent_plugin/utils/agent_run.log`
- `qgis_agent_plugin/utils/token_usage.jsonl`
- 项目目录 `.qgis_agent_runs/` 下本次运行产物
- `07_report/final_validation.md`

重点统计：LLM 请求次数、prompt/completion/total tokens、active_tool_count、tool_schema_chars、高风险审批次数、失败重试次数、OSM 分块次数、GEE direct/batch 路线和人工下载次数。

目标：无相同参数的机械重试；任一失败最多进行一次有参数变化的重试；普通步骤不注入完整 54 工具 schema；除确实缺少注册能力外不使用长篇任意 PyQGIS 脚本。
