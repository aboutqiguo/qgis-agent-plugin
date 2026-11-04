<skill>
<name>gee_execution</name>
<description>Google Earth Engine 数据参数确认、云端处理、下载路由和结果验证。</description>

<strict_rules>
- **初始化**：自定义 GEE 脚本仅使用 `from qgis_agent_plugin.bridges.gee_bridge import init_gee; init_gee()`，不要直接调用 `ee.Initialize()`，也不要再次向用户索取已在插件设置中保存的 Project ID。
- **用户确认**：通用 Sentinel-2 请求不得默认日期、波段、云量、分辨率、collection、合成方法、输出名、输出 CRS 或是否加载。缺少任一关键参数时调用 `ask_human`。不得自行加入 NDVI、RGB 或云掩膜。
- **Sentinel-2 工具**：参数明确后优先使用 `run_gee_sentinel2_download_workflow`，只有用户明确提供或批准全部参数时才能设置 `user_confirmed_parameters=true`。
- **DEM 工具**：通用 DEM 请求缺少数据集、分辨率、输出名、输出 CRS 或是否加载时先调用 `ask_human`，确认后使用 `run_gee_dem_download_workflow`。
- **Copernicus GLO-30**：`COPERNICUS/DEM/GLO30` 是 `ee.ImageCollection`，正确形式为 `ee.ImageCollection(...).mosaic().select('DEM')`。
- **下载路由**：`GEEDownloader.download_ee_object` 先估算 Earth Engine direct download 的实际 32MB/网格维度限制；满足限制时尝试直接下载，超限或 direct 失败时改用批量导出到 Google Drive。Google Drive API 不使用 32MB 或 50MB 文件大小阈值，应以真实 API 请求结果决定是否回退。
- **大范围导出**：复杂边界可用简化后的几何或 bbox 作为云端 export region，下载后再用插件栅格裁剪工具按本地边界精确裁剪。不要直接调用未经 Catalog 验证的 GDAL 算法。
- **自动与人工回退**：批量导出完成后按本次唯一前缀和创建时间定位文件，先尝试 Drive API 流式下载；失败后可尝试已配置的 Drive Desktop 同步。两者都失败时返回 `awaiting_manual_download` 和准确文件信息，不得报告本地下载成功。
- **完整性验证**：下载完成后验证文件可读、尺寸、地理范围、波段数和有效像元比例。损坏、全 NoData 或覆盖不足的影像不得进入后续分析。
- **过程反馈**：下载工具会依次报告认证/查询、云端处理、本地下载、验证和加载阶段。有真实字节总量时显示百分比；GEE 云端处理没有可靠百分比时显示任务 ID、服务端状态和等待时长，不得编造完成比例或剩余时间。
- **取消语义**：本地监控被停止不等于云端导出失败。若工具返回 `operation_cancelled` 且 `cloud_export_may_continue=true`，明确提示用户检查 Earth Engine Tasks；不得立即提交重复导出，也不得归因于认证或配额，除非工具返回相应错误。
- **成功判定**：只能依据本次 GEE 工具结果和已验证的目标 GeoTIFF 判断成功。OSM 图层存在、项目可保存或 Drive 中任务处于 Running 都不能证明 GEE 本地下载完成。
</strict_rules>
</skill>
