<skill>
<name>qgis_layout_design</name>
<description>当任务涉及制图、排版、导出专题图（Thematic Map、PDF、图片）、或配置打印布局 (Print Layout) 时，必须首先阅读此技能，以符合制图规范。</description>

<strict_rules>
- **布局对象初始化**：在 PyQGIS 中进行制图，绝不要使用 matplotlib！你必须使用 `QgsPrintLayout`。初始化布局后，必须将其添加到项目管理器中：`project.layoutManager().addLayout(layout)`。
- **核心制图要素（不可或缺）**：一张规范的专题图必须包含：1) 主地图视图 (`QgsLayoutItemMap`)，2) 地图标题 (`QgsLayoutItemLabel`)，3) 比例尺 (`QgsLayoutItemScaleBar`)，4) 指北针 (`QgsLayoutItemPicture`)。如有不同图例分类，还需加入图例 (`QgsLayoutItemLegend`)。
- **主地图视图设置**：添加 `QgsLayoutItemMap` 后，必须调用 `map.setExtent(canvas.extent())` 或指定图层的 extent，以确保数据能完整显示在页面中央。
- **废弃接口警告 (CRITICAL)**：绝对禁止使用 `QgsLayoutItemNorthArrow`！这是一个在 QGIS 3.x 早期就被废弃并引起崩溃的类。指北针必须使用 `QgsLayoutItemPicture`，并为其设置系统的默认指北针 SVG 路径：`picture.setPicturePath(":/images/north_arrows/layout_default_north_arrow.svg")`。
- **字体与样式**：修改文字大小和字体时，禁止调用不存在的 `label.setFontSize()`。必须使用 Qt 的 QFont 对象：`from qgis.PyQt.QtGui import QFont; font = QFont("Arial", 16, QFont.Bold); label.setFont(font)`。
- **视觉大模型审查机制 (Vision Critic)**：在调用 `QgsLayoutExporter` 将地图最终导出为 PDF 或图片之前，你强烈建议应该调用 `ask_vision_critic` 工具（如果可用），将当前生成的布局截图发给大模型进行审美评估。根据返回的建议（如“标题过于靠左”、“比例尺被图层遮挡”）自动调整 Layout Item 的坐标 (`attemptMove`) 和大小 (`attemptResize`)。
</strict_rules>
</skill>
