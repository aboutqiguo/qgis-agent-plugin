<skill>
<name>remote_sensing_indices</name>
<description>当任务涉及多光谱遥感影像波段识别（Sentinel-2 / Landsat）、遥感指数计算（NDVI、NDWI、MNDWI、NDMI、NDBI、NBR、NDRE）、二值掩膜分区统计或最佳指数方案推荐时，必须首先阅读此技能。</description>

<strict_rules>
- **第一步：核实波段数量与传感器波段映射（严禁盲目假设波段号）**：
  - 调用 `compute_raster_zonal_stats(source_layer_or_path=...)` 一次性获取波段数、波段描述（Description）、数值范围（min/max/mean/std）。
  - **10 波段 Sentinel-2 常见标准子集映射**：当影像有 10 个波段且 DN 量级在 `0~25000`（反射率 × 10000）时，标准顺序通常为：
    - `Band 1 = B2 (Blue, 490nm)`
    - `Band 2 = B3 (Green, 560nm)`
    - `Band 3 = B4 (Red, 665nm)`
    - `Band 4 = B5 (Red Edge 1, 705nm)`
    - `Band 5 = B6 (Red Edge 2, 740nm)`
    - `Band 6 = B7 (Red Edge 3, 783nm)`
    - `Band 7 = B8 (NIR 宽近红外, 842nm, 10m)`
    - `Band 8 = B8A (Narrow NIR 窄近红外, 865nm, 20m)`
    - `Band 9 = B11 (SWIR 1 短波红外1, 1610nm)`
    - `Band 10 = B12 (SWIR 2 短波红外2, 2190nm)`
    - **特别注意**：在 10 波段子集中，`B8` 是第 7 波段，`B8A` 是第 8 波段，`B11` 是第 9 波段！若波段描述为空，向用户说明该映射假设或请用户确认。
- **第二步：二值掩膜（Mask）目标区与背景区统计及指数优选**：
  - 当给定掩膜图层（如 `mask=1` 为目标区，`mask=0` 为背景区）时，直接调用：
    `compute_raster_zonal_stats(source_layer_or_path=..., mask_layer_or_path=..., mask_valid_value=1, rank_band_pairs=True)`
  - 该工具会直接返回全部波段的目标区/背景区均值、标准差、`Cohen's d`，以及按区分度 `|Cohen's d|` 和 `AUC` 排序的 Top 12 归一化差值波段对 `(Bi - Bj) / (Bi + Bj)` 和建议分割阈值，无需手写 Python 循环。
- **第三步：标准遥感指数计算（使用 `compute_raster_index`）**：
  - 始终调用 `compute_raster_index(source_layer_or_path=..., output_path=..., band_a=..., band_b=..., index_name=..., mask_layer_or_path=..., overwrite=True)`：
    - **NDVI（归一化植被指数）**：`(NIR - Red) / (NIR + Red)` → 10 波段 S2 中 `band_a=7` (B8) 或 `8` (B8A)，`band_b=3` (B4)。
    - **NDWI（McFeeters 水体指数）**：`(Green - NIR) / (Green + NIR)` → 10 波段 S2 中 `band_a=2` (B3)，`band_b=7` (B8) 或 `8` (B8A)。
    - **MNDWI（改进型归一化水体指数）**：`(Green - SWIR1) / (Green + SWIR1)` → 10 波段 S2 中 `band_a=2` (B3)，`band_b=9` (B11)。
    - **NDMI（归一化湿度/冠层水分指数）**：`(NIR - SWIR1) / (NIR + SWIR1)` → 10 波段 S2 中 `band_a=7` (B8) 或 `8` (B8A)，`band_b=9` (B11)。
    - **NBR（归一化火烧迹地指数）**：`(NIR - SWIR2) / (NIR + SWIR2)` → 10 波段 S2 中 `band_a=7` (B8) 或 `8` (B8A)，`band_b=10` (B12)。
  - **注意**：若用户点名了一个单波段指数结果图层（如“计算 `@shijiao_ndvi_2019101` 的 NDWI”），应先检查该图层波段数；若其仅为 1 波段派生结果，应自动回溯同工程下的原始多波段源图层（如 `shijiao_2019101`）提取绿光与近红外波段进行计算，并向用户清晰说明。
</strict_rules>
</skill>
