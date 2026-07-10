# QGIS AI Agent Copilot

QGIS AI Agent Copilot 是一个面向 QGIS 的智能 GIS 助手插件。它将大语言模型、PyQGIS、QGIS Processing Toolbox、OpenStreetMap 和 Google Earth Engine 连接到 QGIS 内部，让用户可以用自然语言完成数据获取、空间分析、遥感处理、制图、项目保存与结果验证。

- 当前稳定版本：`v1.3.2`
- 推荐 QGIS：`3.34 LTR` 或 `3.44`
- 最低 QGIS：`3.28`
- 项目仓库：[aboutqiguo/qgis-agent-plugin](https://github.com/aboutqiguo/qgis-agent-plugin)
- 安装包：`qgis_agent_plugin_v1.3.2.zip`

---

## ✨ 核心特性

### 自然语言驱动 GIS 工作流

- 将用户输入的自然语言任务拆解为可执行步骤。
- 支持计划模式、任务审批、执行进度展示和任务日志归档。
- 可调用 PyQGIS、QGIS Processing、OSM、GEE、文件读写和项目保存等工具。
- 支持项目级记忆，记录数据路径、历史错误、修复经验和当前项目上下文。

### OpenStreetMap 矢量数据获取

- 行政边界：通过 Nominatim 获取县区、市、省等边界。
- 道路网络：支持 OSMnx 下载、拓扑清理和加载。
- 常用 OSM 要素：建筑物、POI、水系、水面、土地利用等。
- 大范围数据：支持 bbox 分块下载、合并、保存和加载。
- 输出验证：返回图层名、路径、几何类型、要素数量和标签信息，降低下载错层风险。

### Google Earth Engine 数据获取

- 支持 GEE 认证、Project ID 配置和任务导出。
- 支持 Sentinel-2、DEM 等影像数据获取。
- 支持 GEE 云端合成、裁剪、波段选择、云量筛选和本地加载。
- Sentinel-2 泛化请求会主动询问数据集、时间、波段、云量、分辨率、处理方式和输出名，不再擅自生成 NDVI 或默认波段。
- DEM 下载新增专用工作流，避免手写 GEE 代码造成数据集类型错误。

### QGIS API 与 Processing 调用

- 封装常用 QGIS API 和 Processing 调用。
- 内置 Processing 算法目录数据库，可查询算法、参数和表达式函数。
- 支持栅格裁剪、矢量裁剪、投影转换、空间索引、栅格验证和项目保存校验。
- 内置常见 PyQGIS 错误修复器，覆盖颜色渲染、图层加载、GEE 导入路径、DEM 数据集加载等高频问题。

### 稳定性与 token 优化

- 压缩工具返回，减少重复图层扫描。
- 优先使用高层工作流工具，减少临场生成长代码。
- 对长耗时 GEE/OSM/Processing 任务提供阶段性反馈，降低 QGIS 被误判为卡死的概率。
- 对下载后的 GeoTIFF 做可读性和有效像元验证，避免损坏文件进入后续分析。

---

## 🛠️ 安装与环境配置

### 环境要求

- QGIS：最低 `3.28`，推荐 `3.34 LTR` 或 `3.44`。
- Python 依赖：`openai`、`earthengine-api`、`requests`。
- 可选组件：Google Drive Desktop，用于较大 GEE 导出文件的本地同步。
- 可选服务：智谱 GLM Vision API，用于截图和地图画布视觉分析。

### 安装 Python 依赖

#### Windows 环境

在 QGIS 对应的 OSGeo4W Shell 中运行：

```cmd
python -m pip install openai earthengine-api requests
```

#### macOS 环境

打开 QGIS 的 Python 控制台（顶部菜单 `插件` -> `Python 控制台`），粘贴并执行以下代码来安装依赖。

注：因 QGIS 线程设计，执行下载任务时 UI 可能会短暂卡死，耐心等待结束即可。

```python
import sys
import runpy

original_argv = sys.argv[:]
sys.argv = [
    "pip",
    "install",
    "--user",
    "openai",
    "earthengine-api",
    "requests",
    "-i",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
]

try:
    print("正在直接从内存中唤醒 pip 模块进行安装，请稍候...")
    runpy.run_module("pip", run_name="__main__")
except SystemExit as e:
    if e.code == 0:
        print("🎉 所有依赖安装成功！请彻底重启 QGIS (Cmd + Q) 后使用。")
    else:
        print(f"安装结束，但可能存在警告，退出状态码：{e.code}")
except Exception as e:
    print(f"安装异常：{e}")
finally:
    sys.argv = original_argv
```

### 从 ZIP 安装插件

1. 从 [Releases](https://github.com/aboutqiguo/qgis-agent-plugin/releases/latest) 下载 `qgis_agent_plugin_v1.3.2.zip`。
2. 打开 QGIS。
3. 进入 `插件` -> `管理并安装插件`。
4. 选择 `从 ZIP 安装`。
5. 选择下载的 ZIP 文件。
6. 安装完成后重启 QGIS。

### 本地构建安装包

在仓库根目录运行：

```cmd
python build.py
```

构建完成后会生成：

```text
qgis_agent_plugin_v1.3.2.zip
```

### 插件配置

打开 QGIS 后，在插件面板中进入设置页，建议配置：

- DeepSeek API Key：用于主要对话、任务拆解和代码生成。
- GLM API Key：用于截图、图像和地图画布视觉分析。
- GEE Project ID：用于 Google Earth Engine 认证和云端任务。
- Google Drive 本地路径：用于较大 GEE 导出文件的本地同步。

GEE 首次使用时，点击 `Re-Authenticate` 完成 Google 授权。

---

## 🌍 GEE 数据下载策略

`v1.3.2` 采用稳定优先的 GEE 下载路线：

```text
GEE Export.image.toDrive
        |
        v
Google Drive API 查询导出文件
        |
        +-- 文件总量 <= 32MB
        |       |
        |       v
        |   Drive API 直连下载
        |       |
        |       +-- 字节数校验 + raster 校验成功 -> 加载到本地
        |       |
        |       +-- 下载失败或 raster 校验失败 -> Google Drive Desktop 同步
        |
        +-- 文件总量 > 32MB
                |
                v
           Google Drive Desktop 本地同步
                |
                +-- 同步/复制/校验成功 -> 加载到本地
                |
                +-- 自动路线失败 -> 给出 Google Drive 手动下载链接
```

关键规则：

- 常规遥感下载不使用 `image.getDownloadURL()`，该接口只适合很小的直接下载任务。
- 统一通过插件封装的 `GEEDownloader.download_ee_object()` 导出和下载。
- Drive API 直连下载阈值为 `32MB`，更大文件优先走 Google Drive Desktop 同步，避免 GeoTIFF 不完整或 tile 损坏。
- Sentinel-2 请求必须确认数据集、时间范围、波段、云量阈值、分辨率、处理方法和输出名。
- DEM 请求必须确认 DEM 数据集、分辨率、输出 CRS、输出名和是否加载图层。
- Copernicus DEM GLO-30 在 GEE 中是 `ImageCollection`，插件已封装正确加载方式。

---

## 🔄 插件更新

### 普通用户

1. 下载最新 ZIP：`qgis_agent_plugin_v1.3.2.zip`。
2. 在 QGIS 中进入 `插件` -> `管理并安装插件` -> `从 ZIP 安装`。
3. 选择新 ZIP 并覆盖安装。
4. 重启 QGIS。

### 开发者

1. 拉取仓库最新代码。
2. 检查 `qgis_agent_plugin/metadata.txt` 版本号。
3. 运行 `python build.py` 重新生成 ZIP。
4. 在 QGIS 中从 ZIP 安装并重启。

### 发布检查清单

- `qgis_agent_plugin/metadata.txt` 中 `version=1.3.2`。
- `plugins.xml` 中版本号、文件名和下载 URL 与 Release 一致。
- ZIP 包内不包含 `__pycache__`、`.pyc`、`.log`、`.idea`、`agent_run.log`、`token_usage.jsonl`。
- GEE、OSM、Processing、项目保存和插件 UI 至少完成一次基础 smoke test。

---

## 📖 功能与使用说明

### OSM 数据获取示例

```text
请在 QGIS 当前项目中获取长沙市雨花区的 OSM 行政边界、道路、建筑物、POI 和水系数据，保存到项目目录，并按边界裁剪后加载到 QGIS。
```

### GEE Sentinel-2 下载示例

```text
请基于当前项目中的雨花区边界，从 GEE 下载 Sentinel-2 SR Harmonized 数据。
时间范围为 2024-06-01 到 2024-09-30，云量小于 20%，下载 B2、B3、B4、B8 波段，分辨率 10 米，使用云掩膜后的 median 合成，输出为 yuhua_s2_2024_summer_b2348.tif。
```

### DEM 下载示例

```text
请基于当前项目中的研究区边界，从 GEE 下载 Copernicus DEM GLO-30，分辨率 30 米，输出 CRS 为 EPSG:4326，保存为 study_area_dem.tif，并加载到 QGIS。
```

### 波段计算示例

```text
请使用当前项目中的 Sentinel-2 影像计算 NDVI，公式为 (B8 - B4) / (B8 + B4)，输出为 GeoTIFF，并加载到 QGIS 中使用绿-黄-红渐变渲染。
```

### QGIS Processing 分析示例

```text
请将建筑物图层裁剪到研究区边界内，创建空间索引，统计裁剪后建筑物数量，并保存当前 QGIS 工程。
```

### 工作建议

- 复杂任务建议使用计划模式，先审阅步骤再执行。
- GEE 数据请求越明确越稳定，尤其是时间范围、波段、分辨率、处理方式和输出名。
- OSM 连续下载多个主题时，建议检查每次返回的 `output_file`、`layer_name`、`geometry_type` 和 `tags`。
- 栅格叠加、距离分析和 rasterize/proximity 前，应确保输入数据 CRS、范围和像元大小一致。

---

## 📈 更新日志 (Changelog)

### v1.3.2

- 锁定稳定版本 `1.3.2`。
- QGIS 最低版本调整为 `3.28`。
- 新增/强化 GEE 智能下载路由：Drive API 小文件、Google Drive Desktop 大文件、失败时给出手动下载提示。
- Drive API 直连阈值调整为 `32MB`，并加入字节数与 raster 校验。
- 新增 DEM 下载工作流，修复 Copernicus GLO-30 数据集类型问题。
- Sentinel-2 下载必须由用户确认参数，不再自动假设 NDVI、波段、日期或处理方式。
- 新增 raster 可读性和有效像元校验。
- 新增 QGIS Processing Catalog 数据库与算法查询能力。
- 增强 OSM 矢量下载、分块、裁剪和结果验证。
- 优化计划模式与工具调用链路，减少无效执行和 token 消耗。
- 修复浅色/深色主题下部分 UI 可读性问题。

### v1.3.1-beta

- 强化工具可用性测试与模拟测试。
- 优化 OSM、GEE、Processing、Skill、Prompt 的协同逻辑。
- 增强项目记忆、日志分析和 token 消耗估算。
- 改进 QGIS API 常见错误修复策略。

### v1.1.0

- 完成基础架构、线程安全和 QGIS UI 兼容性优化。
- 初步接入 OSM、GEE、PyQGIS 和 Processing 调用。
- 增加基础自然语言任务拆解和执行能力。
- 改进 ZIP 打包和跨平台路径兼容性。

---

## 👨‍💻 开发者信息

### 目录结构

```text
qgis_agent_plugin/
  agent_plugin.py              插件入口
  metadata.txt                 QGIS 插件元数据
  bridges/                     GEE、OSM 等外部数据桥接
  core/                        规划、验证、工具注册、结果检查、记忆、Catalog
  prompts/                     系统提示词
  skills/                      GEE、OSM、QGIS API 等技能规则
  tools/                       Agent 可调用工具
  ui/                          聊天面板和设置窗口
  utils/                       日志、更新检查等工具
```

### 开发与测试

```cmd
python -m py_compile qgis_agent_plugin\tools\tools.py qgis_agent_plugin\bridges\gee_bridge.py qgis_agent_plugin\core\harness_thread.py
python build.py
```

建议测试覆盖：

- OSM 行政边界、道路、建筑物、POI、水系下载。
- GEE DEM 下载。
- GEE Sentinel-2 参数确认和下载。
- raster 校验、裁剪、波段计算。
- QGIS Processing 算法调用。
- 项目保存与预期图层验证。
- 深色/浅色主题 UI 可读性。

### 参考项目

本插件开发过程中参考了开源项目 [GeoCode](https://github.com/chenyusheng2001/GeoCode) 的部分工程设计思路，感谢相关开源工作对 GIS Agent 方向的探索。

---

## 📄 协议与开源声明

本项目采用 MIT License。

欢迎通过 GitHub Issues 提交问题、建议和复现实验记录。提交问题时建议附带：

- QGIS 版本。
- 插件版本。
- 操作系统。
- 任务提示词。
- `agent_run.log` 相关片段。
- 测试项目路径或最小可复现数据。
