<skill>
<name>osm_nominatim</name>
<description>当任务涉及下载行政边界（如省、市、县界）或使用 OpenStreetMap (OSM) / Overpass API 下载路网、水系、POI 等空间数据时，必须首先阅读此技能。</description>

<strict_rules>
- **Administrative Boundaries (CRITICAL)**: When asked to download the boundary of a specific administrative region (e.g. "长沙县", "北京市"), **ABSOLUTELY DO NOT** use Overpass QL! You MUST use the fast and reliable Nominatim API wrapper: `layer = OSMDownloader.download_boundary_nominatim('长沙县', 'C:/temp/changsha.geojson')`. This bypasses all OSM tagging issues and GDAL Relation parsing bugs!
- **Overpass API / OSM (For POIs/Roads only)**: ALWAYS use `qgis_agent_plugin.bridges.osm_bridge.OSMDownloader` to query XML and load layers (`points`, `lines`, `multipolygons`). **CRITICAL OVERPASS RULES**: 
  1. **Roads & Waterways (CRITICAL)**: When asked to download a road network or water network for spatial analysis, DO NOT write Overpass QL! You MUST use: `from qgis_agent_plugin.bridges.osm_bridge import OSMDownloader; layer = OSMDownloader.download_and_clean_network(bbox_layer, 'roads', 'C:/temp/roads.shp')`. This automatically handles robust downloading and performs mandatory topological cleaning (`native:snapgeometries` and `native:splitwithlines`).
  2. **BBox Order**: Overpass uses `(south, west, north, east)` which is `(minLat, minLon, maxLat, maxLon)`. DO NOT USE `(minX, minY, maxX, maxY)`! 
  3. **GDAL Compatibility**: To ensure QGIS GDAL can parse polygons and relations, your query MUST end with `(._;>;); out body;`. Do NOT use `out geom;` or `out skel qt;` because GDAL needs the explicit nodes/ways structure at the root level!
  4. **Precise Area Filtering**: To extract features strictly inside a city/province without downloading neighbors, ALWAYS define the area first: `area["name"="重庆市"]["admin_level"="4"]->.a;`.
  5. **Building Query Template (CRITICAL)**: For buildings inside a bbox, use inline bbox filters on each selector:
     `[out:xml][timeout:180]; ( way["building"](south,west,north,east); relation["building"](south,west,north,east); ); (._;>;); out body;`
     DO NOT use a standalone `[bbox:south,west,north,east];` line; Overpass may reject it in this plugin/GDAL path.
  6. **Output Format Integrity**: If the requested output is `.gpkg`, the writer must use the `GPKG` driver and produce a file, not a directory of Shapefile sidecars. Use `.shp` only when the user explicitly asks for Shapefile.
  7. **Consecutive Downloads Integrity**: When downloading multiple OSM themes in sequence, every `download_osm_features` call must use a distinct `output_file` and `layer_name`, then inspect the returned `data.output_file`, `data.layer_name`, `data.geometry_type`, and `data.tags`. If the returned file/layer does not match the requested theme, stop and retry with explicit `tags` instead of trusting `preset`.
</strict_rules>
</skill>
