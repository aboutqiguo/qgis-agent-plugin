# QGIS AI Agent Copilot v1.3.3 稳定性优化与测试报告

日期：2026-07-13

## 优化结论

本轮完成运行协议、工具安全、计划验证、OSM、GEE、Processing、提示词和 token 链路的系统性修复。版本由 `1.3.2` 更新为 `1.3.3`。

## 已完成修复

### P0：执行链路与状态可靠性

- 新增 `message_protocol.py`，修复中断、多工具缺失结果、孤立/重复 tool 消息，避免下一轮 API 400。
- 新增结构化运行状态：`succeeded`、`partial`、`blocked`、`cancelled`、`failed`、`awaiting_input`、`awaiting_approval`、`awaiting_manual_download`。
- 最终状态由工具结果、计划步骤和 verifier 推导，不再仅依赖模型最后一句话。
- 用户输入/审批等待超时后停止本轮，不再重复请求模型消耗 token。
- 任意 PyQGIS 代码执行、依赖安装和 skill 写入均要求高风险审批。

### P1：工具、OSM、GEE 与 QGIS API

- 统一 54 个工具的风险、线程、读写、输出和批处理契约；批处理对子步骤递归校验。
- Processing Catalog 参数检查改为 fail-closed，并正确处理 `checkParameterValues()` 的返回结构。
- 删除对任意 Python 循环自动注入 `processEvents()` 的代码改写，避免语义变化和重入。
- 地理坐标数据的米制分析优先选择研究区本地 UTM，不再使用 EPSG:3857 作为通用分析 CRS。
- 栅格裁剪保留已有 NoData；没有 NoData 时使用 alpha/mask，不再臆造 255、65535 或 -9999。
- OSM 增加 WGS84 bbox 转换、自适应重分块、临时图层隔离、合并去重和安全覆盖写入。
- GEE 区分 Earth Engine direct download 限制和 Drive API 能力；Drive API 不再设置 32MB/50MB 人工阈值。
- GEE 增加唯一导出前缀、创建时间过滤、流式下载、`.part` 断点续传、字节数检查、同名图层锁释放、GeoTIFF 验证和人工下载状态。
- Sentinel-2 和 DEM 的数据集/日期/波段/分辨率/处理方式/输出 CRS/输出名/加载行为必须由用户确认。
- 修复 Sentinel-2 波段存在性、SCL/QA60 云掩膜、有效像元百分比与覆盖率比例混用，以及 DEM 默认简化边界的问题。

### P2：提示词、skill 与 token

- 系统提示词从 6550 字符压缩到 2059 字符，减少约 68.6%。
- 默认不再注入全部工具；GEE 计划任务工具 schema 约从 32672 字符降到 8338 字符，OSM+Processing 计划任务降到 9577 字符。
- Auto-RAG 不再注入完整 Python skill，仅返回不可信元数据；需要时再定向读取。
- 删除“完成后自动写 MEMORY/USER”和“用户说继续就强制改用另一套技术”的历史触发器。
- token 统计纳入完整消息结构、tool calls、reasoning 字段和工具 schema，不再只计算 content。

## 模拟测试

执行命令：

```cmd
python -m unittest discover -s tests -v
python -m compileall -q qgis_agent_plugin tests
```

结果：`29/29` 项通过，Python 编译检查通过。

覆盖范围：

- tool_calls 多工具中断修复、孤立/重复结果清理。
- 运行状态和计划步骤完成判定。
- GEE 32MB/网格维度 direct 路由边界。
- OSM bbox 坐标顺序、分块上限和 Overpass 错误分类。
- 结构化计划 expected_outputs 与文件 verifier。
- 54 个工具注册表健康、唯一 schema、风险等级和批处理白名单。
- 依赖安装 allowlist、Sentinel-2 参数确认、日期、CRS、有效像元阈值和 OSM 分块参数。
- 提示词、GEE skill、设置页和计划模式关键规则静态回归。

## 仍需 QGIS 内验证

当前命令环境未发现可调用的 `qgis_process`/QGIS Python 运行时，因此以下项目不能用普通 Python 伪造为成功：

- 真实 QGIS Processing provider/Catalog 构建与算法执行。
- QGIS 主线程、任务管理器取消和 UI 弹窗交互。
- 在线 OSM/Nominatim/Overpass 下载。
- 真实 GEE 认证、direct download、Drive API、Drive Desktop 和人工回退。
- GeoTIFF/GPKG 在 QGIS 3.28、3.34、3.44 中的加载与工程保存。

安装后建议优先执行：参数缺失的 Sentinel-2 弹窗测试、小范围 GEE direct、大范围 Drive batch、OSM 建筑/水系连续下载、Processing 裁剪/坡度、取消执行、覆盖同名输出和工程重开验证。
