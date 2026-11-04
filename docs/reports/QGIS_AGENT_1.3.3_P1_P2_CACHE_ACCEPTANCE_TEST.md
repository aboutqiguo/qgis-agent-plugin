# QGIS Agent v1.3.3 P1/P2 与缓存优化验收测试

## 1. 测试目标

本轮重点检验：

- 用户任务开始后，系统提示词、工具集合和 QGIS 环境快照保持稳定。
- OSM 多数据获取由一次高层工具调用连续完成，不在每个数据集之间重复请求模型。
- GEE 云端处理、本地下载、栅格校验和加载尽量由一个高层工作流完成。
- 简单工具或完整工作流成功后，由本地 verifier 结束任务，不额外请求模型生成过渡说明。
- 下载过程显示真实的分阶段进度，并在失败时返回明确状态。
- DeepSeek 缓存监控记录请求、命中/未命中 Token、结构变化和费用估算。
- OSM、GEE、QGIS API、波段计算、工程保存等核心能力没有回归。

插件版本保持 1.3.3。

## 2. 测试前准备

1. 彻底退出并重新启动 QGIS，确保新模块已经重新载入。
2. 新建空白工程并保存为：

~~~text
C:\Users\SevenLita\Desktop\QGISCE\test1\p1_p2_acceptance.qgz
~~~

3. 测试数据目录：

~~~text
C:\Users\SevenLita\Desktop\QGISCE\test1\p1_p2_acceptance_data
~~~

4. 打开“设置 -> 缓存监控”，刷新并记录测试前数据：

~~~text
API 请求数：____
命中缓存输入：____
未命中缓存输入：____
缓存命中率：____
工具结构变化：____
稳定前缀变化：____
~~~

5. 记录测试开始时间，完成前不要清除日志。

## 3. 当前能力边界

- 连续 OSM 工作流支持 roads、buildings、poi、waterways、water。
- 多项获取时应使用连续工作流，行政边界自动作为第一阶段下载。
- 只获取一项标准数据时可使用 download_osm_features。
- landuse 和自定义 OSM 标签走通用 OSM 工具，不属于连续工作流的五类组件。
- 当前不要用 components=[] 表示“仅边界”；现实现会把空数组解释为默认全部组件。仅边界应使用边界下载工具。
- 普通 roads 是 OSM 道路线；需要可路由拓扑网络时，应明确要求道路网络工具。

## 4. 第一阶段：启动与缓存预热

### 测试 1：工程环境检查

在 Work 模式发送：

~~~text
请检查当前 QGIS 工程状态，只列出工程路径、项目 CRS、图层数量和图层名称，不要下载数据，不要写 Python 代码，也不要修改工程。
~~~

通过标准：

- 正确返回当前工程路径。
- 不产生无关文件或图层。
- 正常情况下只增加约 1 次 API 请求。
- 工具成功后不再出现长篇过渡性模型回复。

### 测试 2：重复请求与缓存预热

连续发送两次完全相同的提示词：

~~~text
请汇总当前 QGIS 工程中的图层数量、名称、类型、CRS 和数据源路径，只读检查，不修改任何内容。
~~~

通过标准：

- 两次结果一致，每次正常情况下约增加 1 次 API 请求。
- 第二次请求后缓存命中 Token 应增长。
- 若供应商暂未返回缓存字段，但结构诊断稳定，记录为“供应商缓存待观察”，不要直接判定插件失败。

## 5. 第二阶段：OSM 连续工作流

研究区使用“成都理工大学, 成都市, 四川省, 中国”，范围较小，便于快速验证。

### 测试 3：选择三个组件连续下载

~~~text
请在一次连续 OSM 获取工作流中下载“成都理工大学, 成都市, 四川省, 中国”的行政边界、道路、建筑物和 POI。
只请求 components=[roads, buildings, poi]，输出目录为 C:/Users/SevenLita/Desktop/QGISCE/test1/p1_p2_acceptance_data/osm_core，输出前缀为 acc_core，max_chunk_area=0.01，overwrite=true，continue_on_error=true。
逐项显示有效进度，完成后验证文件、图层和要素数量，并保存当前工程。不要把道路、建筑和 POI 拆成多个独立模型回合。
~~~

预期阶段：验证参数 -> 行政边界 -> roads -> buildings -> poi -> 汇总验证。

预期输出：

~~~text
acc_core_boundary.geojson
acc_core_roads.gpkg
acc_core_buildings.gpkg
acc_core_poi.gpkg
~~~

通过标准：

- 一个 Agent 工具调用内部完成边界和三个组件。
- 正常情况下整个提示词只增加约 1 次 API 请求。
- 各阶段有状态变化，进度不是直接从 0 跳到 100。
- 任一组件失败时，后续组件仍继续，并在最终结果列出 failed_components。
- 全部成功时出现本地验证摘要，不额外请求模型生成过渡说明。

### 测试 4：只选择水系两个组件

~~~text
请在一次连续 OSM 获取工作流中下载“成都理工大学, 成都市, 四川省, 中国”的行政边界、河流线和水面。
只请求 components=[waterways, water]，输出目录为 C:/Users/SevenLita/Desktop/QGISCE/test1/p1_p2_acceptance_data/osm_water，输出前缀为 acc_water，max_chunk_area=0.01，overwrite=true，continue_on_error=true。
逐项验证并保存工程；某类要素为空时要返回明确状态，不能无提示暂停。
~~~

通过标准：

- 不下载 roads、buildings 或 poi。
- 执行阶段包含边界、waterways、water 和最终汇总。
- 水系后不会无提示停止。
- 正常情况下只增加约 1 次 API 请求。

### 测试 5：单项标准数据

~~~text
使用现有 acc_core_boundary，只获取建筑物数据，保存为 C:/Users/SevenLita/Desktop/QGISCE/test1/p1_p2_acceptance_data/osm_single/acc_single_buildings.gpkg，图层名 acc_single_buildings，overwrite=true，max_chunk_area=0.01。不要重新下载道路、POI、水系或水面。完成后验证文件和要素数。
~~~

通过标准：只生成建筑物，不误触发五类全量下载，不重复加载同源图层。

### 测试 6：其他 OSM 预设

~~~text
使用现有 acc_core_boundary，只获取 OSM landuse 数据，保存为 C:/Users/SevenLita/Desktop/QGISCE/test1/p1_p2_acceptance_data/osm_other/acc_landuse.gpkg，图层名 acc_landuse，overwrite=true，max_chunk_area=0.01。请使用通用 OSM 要素下载能力，不要把 landuse 错误传给连续工作流。
~~~

通过标准：使用 landuse 预设；输出为面；为空时明确说明；不产生不支持组件错误。

### 可选测试 7：自定义 OSM 标签

~~~text
使用现有 acc_core_boundary，获取 OSM 中 amenity=restaurant 的节点。使用显式标签 node["amenity"="restaurant"]，geometry_type=points，保存为 C:/Users/SevenLita/Desktop/QGISCE/test1/p1_p2_acceptance_data/osm_other/acc_restaurants.gpkg，图层名 acc_restaurants，overwrite=true，max_chunk_area=0.01。完成后验证字段和要素数。
~~~

通过标准：使用显式 tags；输出为点；为空时明确返回，不伪造要素数。

## 6. 第三阶段：GEE 参数询问与高层工作流

### 测试 8：Sentinel-2 缺少参数时必须询问

先发送：

~~~text
请使用 acc_core_boundary 从 GEE 下载 Sentinel-2 数据到 p1_p2_acceptance_data/gee。除研究区和输出目录外，我还没有确定其他参数。
~~~

通过标准：Agent 不自行决定波段、日期、云量、分辨率或处理方法；通过弹窗询问；确认前不启动导出。

在弹窗回复：

~~~text
数据集使用 COPERNICUS/S2_SR_HARMONIZED；时间为 2024-06-01 至 2024-09-30；波段按 B2、B3、B4、B8 顺序；云量阈值 20%；处理方法 cloud_masked_median；分辨率 10 米；输出 CRS 为 EPSG:32648；输出文件名 acc_s2_b2348_2024.tif；加载到 QGIS；我确认以上参数。
~~~

通过标准：

- 同一任务中的工具集合和稳定前缀不变化。
- 参数确认后使用 Sentinel-2 高层工作流。
- 进度能区分场景查询、云端处理、下载路由、本地下载、栅格校验和加载。
- 成功后验证 4 个波段、有效像元、CRS、文件大小和 QGIS 图层。
- 内部阶段不得逐阶段重复调用模型。

### 测试 9：DEM 高层工作流

~~~text
使用 acc_core_boundary 从 GEE 获取 COPERNICUS/DEM/GLO30，分辨率 30 米，输出 CRS EPSG:32648，输出到 C:/Users/SevenLita/Desktop/QGISCE/test1/p1_p2_acceptance_data/gee/acc_dem_glo30.tif，加载到 QGIS。我确认数据集、分辨率、CRS 和输出文件名。请使用 DEM 高层工作流完成云端处理、下载路由、本地校验和加载。
~~~

通过标准：

- 正常情况下只增加约 1 次 API 请求。
- 进度能区分云端准备和本地下载/校验。
- 必须检查非空像元，不能仅因文件存在判定成功。
- 自动下载失败时返回 Drive 任务或人工下载状态与操作说明，不得谎报完成。

## 7. 第四阶段：QGIS API 与波段计算

### 测试 10：裁剪与投影

~~~text
使用 acc_core_boundary 精确裁剪 acc_core_roads 和 acc_core_buildings，将结果保存到 p1_p2_acceptance_data/analysis；随后重投影为 EPSG:32648，输出 acc_roads_utm.gpkg 和 acc_buildings_utm.gpkg。使用注册的 QGIS/Processing 工具，执行前确认算法参数，完成后验证 CRS、几何类型、要素数和文件。不要编写临时 Python 脚本。
~~~

通过标准：使用真实 QGIS Processing/API；结果位于边界内；投影为 EPSG:32648；多步骤不无提示停止。

### 测试 11：显式 NDVI 波段计算

仅在 Sentinel-2 成功后执行：

~~~text
检查 acc_s2_b2348_2024 的波段顺序确实为 B2、B3、B4、B8。确认后计算 NDVI=(B8-B4)/(B8+B4)，即第4波段和第3波段，输出 C:/Users/SevenLita/Desktop/QGISCE/test1/p1_p2_acceptance_data/analysis/acc_ndvi_2024.tif，Float32，NoData=-9999，图层名 acc_ndvi_2024。验证有效像元比例、最小值和最大值，主要有效值应位于 -1 到 1。这里是我明确要求计算 NDVI，不要在其他 GEE 下载任务中自动附加 NDVI。
~~~

通过标准：先验证波段顺序；输出为单波段 Float32；NDVI 只在明确要求后生成。

### 测试 12：保存与最终验证

~~~text
保存当前工程到 C:/Users/SevenLita/Desktop/QGISCE/test1/p1_p2_acceptance.qgz，并验证工程可保存、主要输出文件存在、图层有效且没有同源重复图层。汇总本次生成的边界、道路、建筑、POI、水系、水面、landuse、Sentinel-2、DEM 和 NDVI；缺失项必须标明 failed、partial 或 awaiting_manual_download，不能标记为 succeeded。
~~~

## 8. 缓存与 API 轮次验收

测试后刷新缓存监控并记录：

~~~text
测试后 API 请求数：____
本轮新增请求数：____
命中缓存输入：____
未命中缓存输入：____
缓存命中率：____
估算实际费用：____
估算节省费用：____
工具结构变化：____
稳定前缀变化：____
上下文截断：____
~~~

判定原则：

- 单次 OSM 多组件成功工作流目标约 1 次模型请求，而不是“组件数 + 汇总”多次请求。
- 参数完整的 DEM 高层工作流目标约 1 次模型请求。
- Sentinel-2 参数询问允许因“询问 -> 用户确认”产生额外请求，但确认后的内部处理不得逐阶段请求模型。
- 同一多轮任务内，tool_schema_sha256 和 stable_prefix_sha256 应保持一致。
- 不同领域的新任务可能使用不同固定工具包；跨任务工具结构变化不能直接判为失败。
- 缓存命中率受 DeepSeek 服务端影响。结构稳定但未命中属于外部缓存表现；同一任务内结构哈希变化才属于插件问题。

## 9. 日志位置

主运行日志：

~~~text
C:\Users\SevenLita\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\qgis_agent_plugin\utils\agent_run.log
~~~

缓存监控日志：

~~~text
C:\Users\SevenLita\AppData\Roaming\QGIS\QGIS3\profiles\default\qgis_agent\telemetry\cache_usage.jsonl
~~~

缓存日志以设置页底部显示为准；它跟随当前 QGIS 用户配置目录，不依赖 QGIS 安装磁盘。

## 10. 测试记录表

| 编号 | 测试项 | 结果 | API 增量 | 耗时 | 备注 |
| --- | --- | --- | ---: | ---: | --- |
| 1 | 工程环境检查 | 待测 |  |  |  |
| 2 | 重复只读与缓存预热 | 待测 |  |  |  |
| 3 | OSM 三组件连续下载 | 待测 |  |  |  |
| 4 | OSM 水系两组件 | 待测 |  |  |  |
| 5 | OSM 单项建筑 | 待测 |  |  |  |
| 6 | OSM landuse | 待测 |  |  |  |
| 7 | 自定义 OSM 标签 | 可选 |  |  |  |
| 8 | Sentinel-2 参数询问与下载 | 待测 |  |  |  |
| 9 | GEE DEM 高层工作流 | 待测 |  |  |  |
| 10 | QGIS 裁剪与投影 | 待测 |  |  |  |
| 11 | NDVI 波段计算 | 待测 |  |  |  |
| 12 | 工程保存与最终验证 | 待测 |  |  |  |

## 11. 失败时保留的信息

出现失败、暂停或卡顿时，不要立即清除日志。记录：

- 失败提示词编号和发送时间。
- Agent 面板最后阶段和百分比。
- 是否仍显示 Agent is thinking。
- QGIS 是否还能操作菜单和地图。
- 已生成文件名称与大小。
- 缓存监控 API 请求增量。
- 弹窗、错误文本或截图。

测试完成后再抓取主运行日志、缓存监控日志和整个测试项目目录进行分析。
