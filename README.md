# QGIS AI Agent Copilot（基于QGIS 3.44，4.0的插件目前太少）

**QGIS AI Agent Copilot** 是一款基于大语言模型（如 DeepSeek、GLM-4V）的 QGIS 智能助手插件。
插件旨在通过自然语言交互，辅助用户自动生成并执行 PyQGIS 代码，以简化数据获取、空间分析和制图工作流。

---

## 📈 更新日志 (Changelog)

### v1.1.0 (架构与兼容性更新)
本次 `v1.1.0` 在底层线程安全、外部数据桥接（GEE/OSM）、分析策略及跨平台 UI 兼容性方面进行了重构与优化。
- **线程安全**：新增 AST 注入器 (`LoopInjector`)，在耗时循环中自动注入 `processEvents()`，以防 QGIS 界面卡死。
- **任务策略**：调整系统提示词逻辑，要求 Agent 优先使用 QGIS `Processing Toolbox` 中的原生算法（如 GRASS、SAGA）处理空间分析任务。
- **数据桥接器**：重构 GEE 模块的数据请求机制以规避端口异常；OSM 下载模块引入 `QNetworkAccessManager` 实现异步获取。
- **栅格裁切**：重构 `clip_raster` 工具，修正了先前版本中使用 Alpha 波段及 NoData 掩膜导致的光谱波段数与张量维度改变的问题。
- **UI 与跨平台适配**：
  - 移除了 UI 面板中的固定背景色，使用 `palette(base)` 适配 QGIS 的原生深浅色主题。
  - 修正了打包脚本（`build.py`）中的路径分隔符，解决 Windows 打包的 ZIP 导致 macOS / Linux 下安装失败的问题。

### 🤝 致谢 (Acknowledgments)
本插件在开发过程中，部分底层代码逻辑与工程设计参考了开源项目 [GeoCode](https://github.com/chenyusheng2001/GeoCode) (GeoCode-Release)。特此向 GeoCode 团队的开源贡献表示感谢！

---

## ✨ 核心特性

- **自然语言交互**：通过对话式指令完成 QGIS 内的操作（如加载图层、修改样式、工具箱处理）。
- **Google Earth Engine (GEE) 集成**：
  - **动态 API 提取**：在内存中动态反射 GEE Python API 签名，减少幻觉和参数错误。
  - **异常捕获与重试**：当执行 GEE 操作报错时，底层自动抓取错误日志并附带官方 API 文档返回给模型，辅助模型修正代码。
  - **多模式下载**：支持小范围数据的直连下载，以及大范围影像的 Google Drive 后台异步同步。
  - **无阻塞任务**：GEE 下载请求通过 `QgsTask` 后台线程运行，并带有进度反馈，不会导致 QGIS 主界面假死。
- **视觉多模态能力**：集成视觉大模型（如 GLM-4V），支持一键截取当前 QGIS 画布交由模型分析和审查。
- **项目记忆机制**：插件会将重要踩坑经验或历史设定记录在当前工作目录的 `MEMORY.md` 中，提供长期的项目级上下文。

---

## 📖 功能与使用说明

本插件不仅能辅助代码编写，还涵盖了常见 GIS 任务的全流程，以下为典型使用场景：

### 1. 矢量数据获取与处理
除了本地数据，您可以直接让大模型获取开源的矢量数据。
- **示例用法**：“帮我下载长沙市范围内的 OpenStreetMap 道路矢量数据，只保留主干道，并按道路类型进行分类符号化。”
- **示例用法**：“生成一个位于坐标 (112.98, 28.19) 的点图层，并以它为中心生成一个半径 5 公里的缓冲区。”

### 2. 空间分析与工具箱调用
模型可自动调用 QGIS 原生的 Processing Toolbox（空间处理工具箱）完成地理计算。
- **示例用法**：“用‘关注区’图层去裁剪‘土地利用’图层，并将结果存为临时图层。”
- **示例用法**：“计算当前 DEM 数据的坡度和坡向，并应用相应的伪彩色渲染。”

### 3. 遥感影像与 GEE 运算
借助集成的 Earth Engine 环境，可以在 QGIS 内完成云端的遥感计算。
- **示例用法**：“帮我查询 2023 年夏季长沙县范围内云量低于 10% 的 Sentinel-2 影像，计算 NDVI，并将结果加载到画布中。”

### 4. 制图审查与视觉辅助
在完成图层叠加后，可以让大模型作为“视觉审核员”。
- **示例用法**：“查看当前画布，帮我评估一下洪涝风险图的配色是否合理？底图的山体阴影是否太深影响了信息读取？”

---

## 🛠️ 安装与环境配置

### 1. 环境依赖安装
本插件依赖 `openai` 和 `earthengine-api` 库。需要在 QGIS 自带的 Python 环境中完成安装：

#### 💻 Windows 环境
1. 在 Windows 开始菜单中找到 QGIS 目录下的 **OSGeo4W Shell**。
2. ⚠️ **右键点击，选择“以管理员身份运行”**（极其重要，否则可能出现权限报错）。
3. 运行以下命令：
```cmd
python -m pip install openai earthengine-api requests
```

#### 🍎 macOS 环境
打开 QGIS 的 **Python 控制台**（顶部菜单 `插件` -> `Python 控制台`），粘贴并执行以下代码来安装依赖：
*(注：因 QGIS 线程设计，执行下载任务时 UI 可能会短暂卡死，耐心等待结束即可)*
```python
import sys
import runpy
original_argv = sys.argv[:]
sys.argv = [
    'pip', 
    'install', 
    '--user',
    'openai', 
    'earthengine-api', 
    'requests', 
    '-i', 
    'https://pypi.tuna.tsinghua.edu.cn/simple'
]
try:
    print("正在直接从内存中唤醒 pip 模块进行安装，请稍候...")
    runpy.run_module('pip', run_name='__main__')
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

### 2. 插件安装
1. 在本仓库的 [Releases](https://github.com/aboutqiguo/qgis-agent-plugin/releases/latest) 页面下载最新的 `.zip` 压缩包（如 `qgis_agent_plugin_v1.0.0.zip`）。（开发者可 clone 仓库后运行 `python build.py` 自行打包）。
2. 打开 QGIS，点击顶部菜单 `插件` -> `管理并安装插件`。
3. 在左侧选择 **从 ZIP 安装 (Install from ZIP)**，选中压缩包并完成安装。

### 3. 配置 API Keys
1. 在 QGIS 工具栏中点击 **QGIS AI Agent Copilot** 图标，打开停靠面板。
2. 在设置页面填入您的：
   - **DeepSeek API Key**（用于基础对话和代码生成）。
   - **智谱 AI API Key**（用于图像识别等视觉功能）。
3. 如需使用 GEE 相关功能，请在设置面板的 GEE 选项卡中点击 **重新认证 (Re-Authenticate)** 完成 Google 账号授权。

---

## 🌍 GEE 数据下载策略

对于 GEE 导出的遥感影像，插件在设置中提供了两种下载模式，请根据实际需求选择：

### 模式一：智能直连路由 (Smart Direct) 
- **适用场景**：下载小面积地块或低分辨率缩略图（请求体积受限于 GEE 接口，通常 < 48 MB）。
- **特点**：无需第三方工具，代码生成下载链接后直接存入本地。若体积超限会报错或自动触发降采样。

### 模式二：Google Drive 客户端同步 (推荐用于大范围数据)
对于需要下载市级/省级的高清影像（如 10m 分辨率），推荐使用此模式。
- **使用方法**：
  1. 在电脑上安装 [Google Drive 桌面客户端](https://www.google.com/intl/zh-CN/drive/download/) 并登录。
  2. 记住 Google Drive 在电脑上挂载的盘符或路径（如 `G:\我的云端硬盘`）。
  3. 在插件设置的 GEE 面板中，将下载策略改为 **Google Drive 客户端同步**，并填入您的本地挂载路径。
- **机制**：模型将通过大批量 `Export.image.toDrive` 任务向 GEE 提交计算。Google Drive 客户端在后台完成文件同步后，插件会自动监听并将其加载至 QGIS 中。

---

## 🔄 插件更新

本插件支持通过 QGIS 插件库进行在线更新：
1. 打开 QGIS `插件` -> `管理并安装插件` -> `设置`。
2. 找到 **插件库 (Plugin Repositories)**，点击 **添加**。
3. 填入名称，并在 URL 中填入本仓库 `plugins.xml` 的 Raw 链接。
4. 勾选“启动时检查更新”，以后在管理面板中即可直接升级。

---

## 👨‍💻 开发者信息
- **API 异常动态反射**：在 `exec()` 执行遇错时拦截异常，通过动态调用底层库实时获取官方文档进行 prompt 增强。
- **内存安全管理**：针对 PyQGIS 中删除图层后立刻操作图层树易导致 C++ 悬空指针崩溃的问题，系统通过 `MEMORY.md` 知识库约束模型生成的代码逻辑结构。
- **解耦设计**：UI 线程与代码执行线程隔离，耗时网络请求与 GEE 数据流均封装于后台进程。

---

## 📄 协议与开源声明

本项目遵循 [MIT License](LICENSE) 协议。欢迎提交 Issue 和 Pull Request。
