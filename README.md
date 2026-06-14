# QGIS AI Agent Copilot

🚀 **QGIS AI Agent Copilot** 是一款基于大语言模型（DeepSeek / 智谱 GLM-4V）的下一代智能 GIS 助手插件。
它能够通过自然语言理解您的意图，自动在 QGIS 中编写并执行 PyQGIS 代码，实现数据下载、空间分析、制图出图等全流程的自动化。

## ✨ 核心特性

- **💬 自然语言交互**：直接告诉它“帮我下载长沙县的哨兵2影像”或“对当前图层进行缓冲区分析”，彻底解放双手。
- **🌍 深度集成 Google Earth Engine (GEE)**：
  - 智能路由：小范围数据秒速直连下载，大范围数据自动无缝降级到 Drive API 后台排队。
  - 原生进度条：所有的 GEE 任务均使用 `QgsTask` 后台线程，不仅带有原生进度条，且绝对不会卡死 QGIS 主界面。
- **👁️ 视觉多模态能力 (GLM-4V)**：支持一键截取当前 QGIS 地图画布发送给视觉大模型，让 AI 拥有“眼睛”，不仅能写代码，还能帮您审查地图布局和排版！
- **🧠 记忆与性格池**：支持自定义全局经验避坑指南和单项目专属记忆，AI 会在错误中自我进化。

---

## 🛠️ 安装与环境配置

### 1. 依赖安装 (非常重要)
本插件依赖 `openai` 和 `earthengine-api` 库。您必须在 QGIS 的 Python 环境中安装它们。
打开 **OSGeo4W Shell**（通常在您的开始菜单的 QGIS 文件夹下），运行以下命令：
```cmd
python -m pip install openai earthengine-api requests
```

### 2. 插件安装
1. 在本仓库的 [Releases](#) 页面下载最新的 `qgis_agent_plugin_vX.X.X.zip`。
2. 打开 QGIS，点击顶部菜单栏的 `插件 (Plugins)` -> `管理并安装插件 (Manage and Install Plugins)`。
3. 选择左侧的 **从 ZIP 安装 (Install from ZIP)**，选中下载的压缩包并安装。

### 3. 配置您的 API Keys
1. 在 QGIS 工具栏中点击 **QGIS AI Agent Copilot** 图标，打开设置面板。
2. 在左侧导航栏中填入您的：
   - **DeepSeek API Key**（用于核心代码生成与思考）。
   - **智谱 AI API Key**（用于视觉图像审查功能）。
3. 如果您需要用到 GEE 相关功能，请在 GEE 面板点击**“重新认证 (Re-Authenticate)”**绑定您的 Google 账号与 Project ID。

---

## 🔄 在线热更新 (OTA Updates)

我们提供原生 QGIS 插件库的热更新支持。当有新版本发布时，您可以直接在 QGIS 内部收到更新推送并一键升级。
1. 打开 QGIS `插件` -> `管理并安装插件` -> `设置 (Settings)`。
2. 向下滑动找到 **插件库 (Plugin Repositories)**，点击 **添加 (Add)**。
3. 名称随意（如：QGIS AI Agent Repo），URL 请填入本仓库提供的 `plugins.xml` 的原始链接（Raw URL）。
4. 勾选“启动时检查更新”，以后有新版本即可无缝热更新！

---

## 📄 协议与开源声明

本项目遵循 [MIT License](LICENSE) 协议。欢迎提交 Issue 和 Pull Request 共同完善这个项目！
