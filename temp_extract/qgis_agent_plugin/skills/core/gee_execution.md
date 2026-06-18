<skill>
<name>gee_execution</name>
<description>当任务涉及 Google Earth Engine (GEE) 数据获取、空间分析、云端计算与数据下载时，必须首先阅读此技能。</description>

<strict_rules>
- **GEE Initialization**: ALWAYS use `from qgis_agent_plugin.bridges.gee_bridge import init_gee; init_gee()` at the start of your Earth Engine scripts. NEVER call `ee.Initialize()` directly and NEVER ask the user for their Project ID, as `init_gee()` reads it automatically from the user's settings!
- **GEE Download Protocol (CRITICAL)**: To download an `ee.Image` from Google Earth Engine to the local disk, you are FORBIDDEN from manually writing `ee.batch.Export.image.toDrive` or using `image.getDownloadURL()`. `getDownloadURL` will CRASH with an `EEException` for any region larger than a tiny thumbnail due to the strict 50MB limit! You MUST ALWAYS use the high-level wrapper: `from qgis_agent_plugin.bridges.gee_bridge import GEEDownloader; dest_path = GEEDownloader.download_ee_object(ee_object=image, filename='output_name', dest_dir='C:/path', scale=30, region=roi_geometry, crs='EPSG:4326')`. This wrapper automatically reads the user's UI settings for download routing (Google Drive sync vs Direct API) and runs safely in a background thread. Trust it blindly!
- **GEE Payload Limit & Complex Geometries (CRITICAL)**: GEE API has a strict 10MB payload limit. If you have a highly complex local boundary layer (e.g. province/county) and need to download GEE imagery for it:
  1. DO NOT convert the raw polygon into an `ee.Geometry.Polygon(coords)`. It will crash the API!
  2. Extract the Bounding Box of the layer first: `bbox = geom.boundingBox()`. Create an `ee.Geometry.Rectangle([bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum()])`.
  3. Pass this Rectangle as the `region` to `GEEDownloader.download_ee_object`.
  4. AFTER the raster is downloaded locally, use `processing.run('gdal:cliprasterbymasklayer', ...)` with your complex local SHP to crop the raster precisely. This utilizes Local computing power and saves Cloud payload!
- **GEE Mosaicing**: always use `.mosaic()` or `.median()` on the filtered ImageCollection to ensure the entire ROI is covered. DO NOT just use `.first()` because a single scene might only partially cover the ROI!
- **UI Feedback (Anti-Freeze Rule)**: During complex GEE computations or processing pipelines, you must not remain completely silent while waiting for server responses. Use `iface.messageBar().pushMessage("GEE Processing", "Computing composite... please wait", level=Qgis.Info, duration=30)` to inform the user of the current stage, preventing them from thinking QGIS has crashed.
</strict_rules>
</skill>
