import html
import logging
import os
import re
from pathlib import Path
from urllib import parse

from qgis.core import QgsVectorLayer, QgsProject, Qgis
from qgis.utils import iface

logger = logging.getLogger(__name__)


OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

OSM_TAG_TEMPLATES = {
    "buildings": {"tags": ['way["building"]', 'relation["building"]'], "geometry_type": "multipolygons"},
    "roads": {"tags": ['way["highway"]'], "geometry_type": "lines"},
    "waterways": {"tags": ['way["waterway"]', 'relation["waterway"]'], "geometry_type": "lines"},
    "water": {
        "tags": ['way["natural"="water"]', 'relation["natural"="water"]', 'way["waterway"]'],
        "geometry_type": "multipolygons",
    },
    "poi": {"tags": ['node["amenity"]', 'node["tourism"]', 'node["shop"]'], "geometry_type": "points"},
    "landuse": {"tags": ['way["landuse"]', 'relation["landuse"]'], "geometry_type": "multipolygons"},
}


class OverpassQueryError(Exception):
    def __init__(self, message: str, error_type: str = "overpass_error", endpoint: str = "", response_text: str = ""):
        super().__init__(message)
        self.error_type = error_type
        self.endpoint = endpoint
        self.response_text = response_text


def _safe_push_message(title: str, message: str, level=None, duration: int = 8) -> None:
    try:
        iface.messageBar().pushMessage(title, message, level=level or Qgis.MessageLevel.Info, duration=duration)
    except Exception:
        logger.info("%s: %s", title, message)


def _strip_overpass_settings(query: str, setting_name: str) -> str:
    return re.sub(rf"\[\s*{re.escape(setting_name)}\s*:[^\]]+\]\s*;?", "", query, flags=re.IGNORECASE)


def _inline_global_bbox(query: str, bbox_value: str) -> str:
    """Move a global bbox setting into node/way/relation selectors.

    GDAL/Overpass paths used by the plugin are more reliable with inline bbox
    filters than a standalone [bbox:...] statement.
    """
    bbox_clause = f"({bbox_value.strip()})"
    selector_re = re.compile(r"^(\s*)(node|way|relation)(\s*\[[^;\n]+?\])(\s*;.*)$", re.IGNORECASE)
    lines = []
    for line in query.splitlines():
        match = selector_re.match(line)
        if match and not re.search(r"\]\s*\([^)]*\)\s*;", line):
            line = f"{match.group(1)}{match.group(2)}{match.group(3)}{bbox_clause}{match.group(4)}"
        lines.append(line)
    return "\n".join(lines)


def normalize_overpass_ql(overpass_ql: str, timeout_seconds: int = 180) -> str:
    """Return a compact Overpass QL query with one out/timeout header."""
    query = (overpass_ql or "").strip()
    if not query:
        raise ValueError("Overpass QL query is empty.")

    out_match = re.search(r"\[\s*out\s*:\s*([a-zA-Z0-9_]+)\s*\]\s*;?", query, flags=re.IGNORECASE)
    out_value = out_match.group(1) if out_match else "xml"
    query = _strip_overpass_settings(query, "out")

    timeout_match = re.search(r"\[\s*timeout\s*:\s*(\d+)\s*\]\s*;?", query, flags=re.IGNORECASE)
    timeout_value = timeout_match.group(1) if timeout_match else str(int(timeout_seconds))
    query = _strip_overpass_settings(query, "timeout")

    bbox_match = re.search(r"\[\s*bbox\s*:\s*([^\]]+)\]\s*;?", query, flags=re.IGNORECASE)
    bbox_value = bbox_match.group(1).strip() if bbox_match else ""
    query = _strip_overpass_settings(query, "bbox")
    if bbox_value:
        query = _inline_global_bbox(query, bbox_value)

    query = "\n".join(line.strip() for line in query.splitlines() if line.strip())
    return f"[out:{out_value}][timeout:{timeout_value}];\n{query}"


def build_bbox_query(tags, bbox, geometry_type: str = "lines", timeout_seconds: int = 180) -> str:
    """Build a GDAL-friendly bbox query.

    bbox order accepted here is min_lon, min_lat, max_lon, max_lat.
    Overpass receives south, west, north, east.
    """
    if isinstance(tags, str):
        tag_list = [tags]
    else:
        tag_list = list(tags or [])
    if not tag_list:
        raise ValueError("At least one OSM tag expression is required.")

    west, south, east, north = [float(value) for value in bbox]
    cleaned = []
    bbox_clause = f"({south},{west},{north},{east})"
    for tag in tag_list:
        item = str(tag).strip().rstrip(";")
        item = re.sub(r"\([^)]*\)\s*$", "", item).strip()
        if not re.match(r"^(node|way|relation)\s*\[", item):
            raise ValueError(f"Unsupported OSM tag expression: {tag}")
        cleaned.append(f"  {item}{bbox_clause};")

    body = "\n".join(cleaned)
    recurse = "(._;>;);\nout body;" if geometry_type in {"lines", "multipolygons", "multilinestrings"} else "out body;"
    return normalize_overpass_ql(
        f"""
(
{body}
);
{recurse}
""",
        timeout_seconds=timeout_seconds,
    )


def safe_feature_count(layer) -> int:
    """Return a trustworthy feature count for providers that report -1."""
    if layer is None:
        return 0
    try:
        count = int(layer.featureCount())
        if count >= 0:
            return count
    except Exception:
        pass
    try:
        return sum(1 for _ in layer.getFeatures())
    except Exception:
        return -1


def parse_bbox(bbox) -> tuple:
    if isinstance(bbox, str):
        values = [float(value.strip()) for value in bbox.split(",")]
    else:
        values = [float(value) for value in bbox]
    if len(values) != 4:
        raise ValueError("bbox must contain 4 values: min_lon,min_lat,max_lon,max_lat.")
    min_lon, min_lat, max_lon, max_lat = values
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise ValueError("bbox values are outside valid WGS84 bounds or not ordered.")
    return min_lon, min_lat, max_lon, max_lat


def bbox_area(bbox) -> float:
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    return (max_lon - min_lon) * (max_lat - min_lat)


def split_bbox(bbox, max_area: float = 0.25, max_chunk_area: float = None) -> list:
    """Split bbox into a grid where each chunk is at most max_area square degrees."""
    if max_chunk_area is not None:
        max_area = max_chunk_area
    max_area = float(max_area)
    if not 0 < max_area <= 5.0:
        raise ValueError("max_area must be greater than 0 and no more than 5 square degrees.")
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    area = bbox_area((min_lon, min_lat, max_lon, max_lat))
    if area <= max_area:
        return [(min_lon, min_lat, max_lon, max_lat)]
    width = max_lon - min_lon
    height = max_lat - min_lat
    import math

    parts = max(1, int(math.ceil(area / max_area)))
    cols = max(1, int(math.ceil(math.sqrt(parts * width / max(height, 1e-12)))))
    rows = max(1, int(math.ceil(parts / cols)))
    lon_step = width / cols
    lat_step = height / rows
    chunks = []
    for row in range(rows):
        y1 = min_lat + row * lat_step
        y2 = max_lat if row == rows - 1 else min_lat + (row + 1) * lat_step
        for col in range(cols):
            x1 = min_lon + col * lon_step
            x2 = max_lon if col == cols - 1 else min_lon + (col + 1) * lon_step
            chunks.append((x1, y1, x2, y2))
    return chunks


def resolve_tag_template(preset: str = "", tags=None, geometry_type: str = "") -> tuple:
    if tags:
        tag_list = [tags] if isinstance(tags, str) else list(tags)
        return tag_list, geometry_type or "lines"
    key = str(preset or "").strip().lower()
    if key not in OSM_TAG_TEMPLATES:
        raise ValueError(f"Unknown OSM preset '{preset}'. Available presets: {', '.join(sorted(OSM_TAG_TEMPLATES))}.")
    template = OSM_TAG_TEMPLATES[key]
    return list(template["tags"]), geometry_type or template["geometry_type"]


def extract_overpass_errors(response_text: str) -> str:
    text = response_text or ""
    matches = re.findall(r"<strong[^>]*>\s*Error\s*</strong>\s*:\s*([^<]+)", text, flags=re.IGNORECASE)
    if matches:
        return "; ".join(html.unescape(item).strip() for item in matches if item.strip())
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = html.unescape(re.sub(r"\s+", " ", plain)).strip()
    return plain[:1000]


def classify_overpass_error(message: str, response_text: str = "") -> str:
    lowered = f"{message or ''}\n{response_text or ''}".lower()
    if "parse error" in lowered or "unknown type" in lowered or "empty query" in lowered:
        return "overpass_parse_error"
    if "too many requests" in lowered or "rate limit" in lowered or "429" in lowered:
        return "overpass_rate_limited"
    if "timeout" in lowered or "timed out" in lowered or "gateway" in lowered:
        return "overpass_timeout"
    if "0 bytes" in lowered or "empty result" in lowered:
        return "overpass_empty_result"
    if "network" in lowered or "host" in lowered or "ssl" in lowered:
        return "network_error"
    return "overpass_error"


def _write_overpass_debug_files(output_file: str, query: str, response_text: str = "") -> None:
    try:
        base_dir = os.path.dirname(os.path.abspath(output_file)) or os.getcwd()
        with open(os.path.join(base_dir, "last_overpass_query.ql"), "w", encoding="utf-8") as handle:
            handle.write(query)
        if response_text:
            with open(os.path.join(base_dir, "last_overpass_error.html"), "w", encoding="utf-8") as handle:
                handle.write(response_text)
    except Exception:
        logger.exception("Failed to write Overpass debug artifacts.")


class OSMDownloader:
    @staticmethod
    def query_osm(
        overpass_ql: str,
        output_file: str,
        timeout_seconds: int = 180,
        endpoints=None,
        transfer_progress_callback=None,
        cancel_callback=None,
    ):
        """
        Executes an Overpass QL query, ensuring the output is XML format, and saves to output_file.
        """
        normalized_query = normalize_overpass_ql(overpass_ql, timeout_seconds=timeout_seconds)
        _write_overpass_debug_files(output_file, normalized_query)

        from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
        from qgis.PyQt.QtCore import QUrl, QEventLoop, QByteArray, QTimer
        
        body = parse.urlencode({"data": normalized_query}).encode("utf-8")
        endpoint_list = list(endpoints or OVERPASS_ENDPOINTS)
        last_error = None

        for endpoint in endpoint_list:
            from ..core.progress import raise_if_cancelled
            raise_if_cancelled(cancel_callback, "OSM download was cancelled by the user.")
            manager = QNetworkAccessManager()
            request = QNetworkRequest(QUrl(endpoint))
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/x-www-form-urlencoded; charset=UTF-8")
            request.setRawHeader(b"User-Agent", b"QGIS Agent Plugin (QtNetwork)")
            if hasattr(request, "setTransferTimeout"):
                try:
                    request.setTransferTimeout(int(timeout_seconds * 1000))
                except Exception:
                    pass

            _safe_push_message("OSM", f"Downloading data from Overpass API: {endpoint}", Qgis.MessageLevel.Info)

            loop = QEventLoop()
            timed_out = {"value": False}
            cancelled = {"value": False}
            timer = QTimer()
            timer.setSingleShot(True)
            cancel_timer = QTimer()
            cancel_timer.setInterval(250)

            def _timeout():
                timed_out["value"] = True
                try:
                    reply.abort()
                except Exception:
                    pass
                loop.quit()

            reply = manager.post(request, QByteArray(body))
            if transfer_progress_callback:
                def _transfer_progress(received, total, current_endpoint=endpoint):
                    try:
                        transfer_progress_callback(int(received), int(total), current_endpoint)
                    except Exception:
                        pass
                reply.downloadProgress.connect(_transfer_progress)

            def _check_cancel():
                try:
                    should_cancel = bool(cancel_callback and cancel_callback())
                except Exception:
                    should_cancel = False
                if should_cancel:
                    cancelled["value"] = True
                    try:
                        reply.abort()
                    except Exception:
                        pass
                    loop.quit()

            timer.timeout.connect(_timeout)
            cancel_timer.timeout.connect(_check_cancel)
            reply.finished.connect(loop.quit)
            timer.start(int(timeout_seconds * 1000))
            cancel_timer.start()
            loop.exec()
            timer.stop()
            cancel_timer.stop()

            if cancelled["value"]:
                from ..core.progress import DataAcquisitionCancelled
                raise DataAcquisitionCancelled("OSM download was cancelled by the user.")

            if timed_out["value"]:
                last_error = OverpassQueryError(
                    f"Overpass request timed out after {timeout_seconds}s at {endpoint}.",
                    error_type="overpass_timeout",
                    endpoint=endpoint,
                )
                continue

            response_bytes = reply.readAll().data()
            response_text = response_bytes.decode("utf-8", errors="replace")
            if reply.error() != QNetworkReply.NoError:
                parsed_error = extract_overpass_errors(response_text)
                _write_overpass_debug_files(output_file, normalized_query, response_text)
                error_type = classify_overpass_error(f"{reply.errorString()} {parsed_error}", response_text)
                last_error = OverpassQueryError(
                    f"Overpass API Error at {endpoint}: {reply.errorString()} - {parsed_error}",
                    error_type=error_type,
                    endpoint=endpoint,
                    response_text=response_text,
                )
                if error_type in {"overpass_parse_error", "overpass_empty_result"}:
                    break
                continue

            if not response_bytes.strip():
                last_error = OverpassQueryError(
                    f"Overpass API returned an empty response at {endpoint}.",
                    error_type="overpass_empty_result",
                    endpoint=endpoint,
                )
                continue

            if transfer_progress_callback:
                try:
                    transfer_progress_callback(len(response_bytes), len(response_bytes), endpoint)
                except Exception:
                    pass

            os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            with open(output_file, 'wb') as f:
                f.write(response_bytes)
            
            _safe_push_message("OSM", f"Successfully downloaded OSM data to {output_file}.", Qgis.MessageLevel.Success)
            return output_file

        if last_error:
            raise last_error
        raise OverpassQueryError("Overpass API failed without a detailed error.", error_type="overpass_error")

    @staticmethod
    def load_osm_layer(osm_file: str, geometry_type: str, layer_name: str, add_to_project: bool = True):
        """
        Loads a specific geometry type from an .osm file using GDAL.
        geometry_type must be one of: 'points', 'lines', 'multilinestrings', 'multipolygons', 'other_relations'
        """
        valid_types = ['points', 'lines', 'multilinestrings', 'multipolygons', 'other_relations']
        if geometry_type not in valid_types:
            raise ValueError(f"Invalid geometry_type. Must be one of {valid_types}")
            
        if not os.path.exists(osm_file):
            raise FileNotFoundError(f"OSM file not found: {osm_file}")
            
        uri = f"{osm_file}|layername={geometry_type}"
        try:
            if add_to_project:
                from ..tools.qgis_tools import load_vector_layer
                layer = load_vector_layer(uri, layer_name)
            else:
                layer = QgsVectorLayer(uri, layer_name, "ogr")
                if not layer.isValid():
                    raise ValueError("invalid OSM sublayer")
        except Exception:
            raise Exception(f"Failed to load OSM layer. Make sure the query actually returned {geometry_type}.")

        feature_count = -1
        try:
            feature_count = int(layer.featureCount())
        except Exception:
            pass
        if feature_count == 0:
            raise OverpassQueryError(
                f"OSM layer '{layer_name}' loaded but contains 0 features.",
                error_type="overpass_empty_result",
            )

        _safe_push_message("OSM", f"Layer '{layer_name}' loaded successfully.", Qgis.MessageLevel.Success)
        return layer

    @staticmethod
    def download_boundary_nominatim(
        name: str,
        output_file: str,
        layer_name: str = None,
        transfer_progress_callback=None,
        cancel_callback=None,
        timeout_seconds: int = 120,
    ):
        """
        Downloads a GeoJSON boundary from Nominatim API for the given name (e.g., '长沙县').
        Saves it to output_file and loads it into QGIS as a vector layer.
        """
        import json
        from urllib import parse
        from qgis.PyQt.QtCore import QByteArray, QEventLoop, QTimer, QUrl
        from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
        
        if not layer_name:
            layer_name = f"{name}_boundary"
            
        url = f"https://nominatim.openstreetmap.org/search?q={parse.quote(name)}&polygon_geojson=1&format=json"
        
        _safe_push_message("Nominatim", f"Searching for boundary of {name}...", Qgis.MessageLevel.Info)

        manager = QNetworkAccessManager()
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", b"QGISAgentPlugin/1.3.3 (QGIS geodata client)")
        if hasattr(request, "setTransferTimeout"):
            try:
                request.setTransferTimeout(int(timeout_seconds * 1000))
            except Exception:
                pass

        loop = QEventLoop()
        timeout_timer = QTimer()
        timeout_timer.setSingleShot(True)
        cancel_timer = QTimer()
        cancel_timer.setInterval(250)
        timed_out = {"value": False}
        cancelled = {"value": False}
        reply = manager.get(request)

        def _timeout():
            timed_out["value"] = True
            reply.abort()
            loop.quit()

        def _check_cancel():
            try:
                should_cancel = bool(cancel_callback and cancel_callback())
            except Exception:
                should_cancel = False
            if should_cancel:
                cancelled["value"] = True
                reply.abort()
                loop.quit()

        if transfer_progress_callback:
            def _transfer(received, total):
                try:
                    transfer_progress_callback(int(received), int(total), "https://nominatim.openstreetmap.org")
                except Exception:
                    pass
            reply.downloadProgress.connect(_transfer)
        timeout_timer.timeout.connect(_timeout)
        cancel_timer.timeout.connect(_check_cancel)
        reply.finished.connect(loop.quit)
        timeout_timer.start(int(timeout_seconds * 1000))
        cancel_timer.start()
        loop.exec()
        timeout_timer.stop()
        cancel_timer.stop()

        if cancelled["value"]:
            from ..core.progress import DataAcquisitionCancelled
            raise DataAcquisitionCancelled("OSM boundary download was cancelled by the user.")
        if timed_out["value"]:
            raise Exception(f"Nominatim request timed out after {timeout_seconds}s.")
        if reply.error() != QNetworkReply.NoError:
            raise Exception(f"Nominatim API Error: {reply.errorString()}")
        try:
            response_bytes = reply.readAll().data()
            data = json.loads(response_bytes.decode("utf-8"))
            if transfer_progress_callback:
                transfer_progress_callback(len(response_bytes), len(response_bytes), "https://nominatim.openstreetmap.org")
        except Exception as e:
            raise Exception(f"Nominatim response parsing failed: {str(e)}")
            
        if not data:
            raise Exception(f"No results found for '{name}' via Nominatim API.")
            
        # Find the first result that has a Polygon or MultiPolygon geojson
        geojson_feature = None
        selected_item = None
        for item in data:
            if 'geojson' in item and item['geojson']['type'] in ['Polygon', 'MultiPolygon']:
                geojson_feature = item['geojson']
                selected_item = item
                break
                
        if not geojson_feature:
            raise Exception(f"No polygon boundary found for '{name}'.")
            
        # Create a valid GeoJSON FeatureCollection
        feature_collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": name, "display_name": (selected_item or {}).get("display_name", "")},
                    "geometry": geojson_feature
                }
            ]
        }
        
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(feature_collection, f, ensure_ascii=False)
            
        from ..tools.qgis_tools import load_vector_layer
        try:
            layer = load_vector_layer(output_file, layer_name)
        except Exception:
            raise Exception(f"Failed to load downloaded boundary file: {output_file}")

        _safe_push_message("Nominatim", f"Boundary '{layer_name}' loaded successfully.", Qgis.MessageLevel.Success)
        return layer

    @staticmethod
    def download_and_clean_network(
        bbox_layer: QgsVectorLayer,
        network_type: str,
        output_path: str,
        task_progress_callback=None,
        cancel_callback=None,
    ):
        """
        Downloads a network (roads or water) with OSMnx and preserves its graph topology.
        """
        from qgis.utils import iface
        from qgis.core import Qgis, QgsProject, QgsVectorLayer
        
        try:
            import osmnx as ox
            import geopandas as gpd
            import shapely.wkt
        except ImportError:
            raise Exception("缺少 osmnx/geopandas。请停止当前任务，并在用户批准后使用 install_python_package 安装允许的依赖。")
            
        if network_type not in ['roads', 'water']:
            raise ValueError("network_type must be 'roads' or 'water'")
            
        _safe_push_message("OSMnx", f"正在使用 OSMnx 构建 {network_type} 的空间拓扑图，请稍候...", Qgis.MessageLevel.Info)
        
        features = list(bbox_layer.getFeatures())
        if not features:
            raise Exception("边界图层为空，无法裁剪！")
            
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry
        geometries = [feature.geometry() for feature in features if feature.hasGeometry() and not feature.geometry().isEmpty()]
        if not geometries:
            raise Exception("边界图层没有有效几何，无法下载网络！")
        geom = QgsGeometry.unaryUnion(geometries)
        if bbox_layer.crs().isValid() and bbox_layer.crs().authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(
                bbox_layer.crs(),
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance(),
            )
            geom.transform(transform)
        polygon = shapely.wkt.loads(geom.asWkt())
        
        output_dir = os.path.dirname(os.path.abspath(output_path)) or os.getcwd()
        cache_dir = os.path.join(output_dir, "osmnx_cache")
        os.makedirs(cache_dir, exist_ok=True)
        try:
            ox.settings.use_cache = True
            ox.settings.cache_folder = cache_dir
        except Exception:
            logger.exception("Failed to set OSMnx cache folder.")

        os.makedirs(output_dir, exist_ok=True)
        layer_name = Path(output_path).stem
        suffix = Path(output_path).suffix.lower()
        if suffix not in {".gpkg", ".geojson", ".json", ".shp"}:
            raise ValueError("Unsupported output format. Use .gpkg, .geojson, or .shp.")

        from qgis.core import QgsApplication, QgsTask
        from qgis.PyQt.QtCore import QEventLoop, QTimer
        from ..core.progress import DataAcquisitionCancelled

        class _OSMnxNetworkTask(QgsTask):
            def __init__(self):
                super().__init__(f"Build OSMnx {network_type} network", QgsTask.CanCancel)
                self.exception = None
                self.detail = "正在请求 OSM 网络并构建拓扑"

            def progress_detail(self):
                return self.detail

            def run(self):
                try:
                    if network_type == "roads":
                        graph = ox.graph_from_polygon(polygon, network_type="drive", simplify=True)
                    else:
                        custom_filter = '["waterway"~"river|stream|canal"]'
                        graph = ox.graph_from_polygon(
                            polygon,
                            custom_filter=custom_filter,
                            retain_all=True,
                            simplify=True,
                        )
                    if self.isCanceled():
                        return False
                    self.detail = "网络已获取，正在转换边要素"
                    self.setProgress(35)
                    _nodes, edges = ox.graph_to_gdfs(graph)

                    for col in edges.columns:
                        if col == "geometry":
                            continue
                        if any(isinstance(value, list) for value in edges[col]):
                            edges[col] = edges[col].apply(
                                lambda value: str(value) if isinstance(value, list) else value
                            )
                    if self.isCanceled():
                        return False
                    edges = edges.reset_index()
                    self.detail = "正在写入网络文件"
                    self.setProgress(70)
                    if suffix == ".gpkg":
                        edges.to_file(output_path, layer=layer_name, driver="GPKG")
                    elif suffix in {".geojson", ".json"}:
                        edges.to_file(output_path, driver="GeoJSON")
                    else:
                        edges.to_file(output_path, driver="ESRI Shapefile")
                    self.detail = "网络文件写入完成"
                    self.setProgress(100)
                    return True
                except Exception as exc:
                    self.exception = exc
                    return False

        task = _OSMnxNetworkTask()
        loop = QEventLoop()
        task.taskCompleted.connect(loop.quit)
        task.taskTerminated.connect(loop.quit)
        if task_progress_callback:
            task.progressChanged.connect(
                lambda value: task_progress_callback(float(value), task.progress_detail())
            )
            task_progress_callback(None, task.progress_detail())

        cancel_timer = QTimer()
        cancel_timer.setInterval(500)

        def _check_cancel():
            try:
                should_cancel = bool(cancel_callback and cancel_callback())
            except Exception:
                should_cancel = False
            if should_cancel:
                task.cancel()

        cancel_timer.timeout.connect(_check_cancel)
        QgsApplication.taskManager().addTask(task)
        cancel_timer.start()
        loop.exec()
        cancel_timer.stop()

        if task.exception:
            raise task.exception
        if task.status() == QgsTask.Terminated:
            raise DataAcquisitionCancelled("OSM network download was cancelled by the user.")

        layer_uri = f"{output_path}|layername={layer_name}" if suffix == ".gpkg" else output_path
        
        final_layer = QgsVectorLayer(layer_uri, layer_name, "ogr")
        if not final_layer.isValid():
            raise Exception("OSMnx 生成文件加载失败！")
        if final_layer.featureCount() == 0:
            raise OverpassQueryError("OSMnx generated a valid layer with 0 features.", error_type="overpass_empty_result")
            
        QgsProject.instance().addMapLayer(final_layer)
        _safe_push_message("Topology", f"网络拓扑图已由 OSMnx 生成并加载。", Qgis.MessageLevel.Success)
        return final_layer
