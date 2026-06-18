import os
import urllib.request
import urllib.error
import logging
from qgis.core import QgsVectorLayer, QgsProject, Qgis
from qgis.utils import iface

logger = logging.getLogger(__name__)

class OSMDownloader:
    @staticmethod
    def query_osm(overpass_ql: str, output_file: str):
        """
        Executes an Overpass QL query, ensuring the output is XML format, and saves to output_file.
        """
        # Ensure the query explicitly asks for XML and has a timeout
        prefix = ""
        if "[out:" not in overpass_ql:
            prefix += "[out:xml]"
        if "[timeout:" not in overpass_ql:
            prefix += "[timeout:180]"
        if prefix:
            overpass_ql = f"{prefix};\n{overpass_ql}"
            
        from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
        from qgis.PyQt.QtCore import QUrl, QEventLoop, QByteArray
        
        url = "https://overpass-api.de/api/interpreter"
        data = overpass_ql.encode('utf-8')
        
        manager = QNetworkAccessManager()
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/x-www-form-urlencoded")
        request.setRawHeader(b"User-Agent", b"QGIS Agent Plugin (QtNetwork)")
        
        iface.messageBar().pushMessage("OSM", "Downloading data from Overpass API... Please wait.", level=Qgis.MessageLevel.Info)
        
        loop = QEventLoop()
        reply = manager.post(request, QByteArray(data))
        reply.finished.connect(loop.quit)
        loop.exec() # Pumps the Qt event loop, preventing QGIS GUI from freezing!
        
        if reply.error() != QNetworkReply.NoError:
            err_msg = reply.readAll().data().decode('utf-8', errors='replace')
            raise Exception(f"Overpass API Network Error: {reply.errorString()} - {err_msg}")
            
        content = reply.readAll().data()
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        with open(output_file, 'wb') as f:
            f.write(content)
            
        iface.messageBar().pushMessage("OSM", f"Successfully downloaded OSM data to {output_file}.", level=Qgis.MessageLevel.Success)
        return output_file

    @staticmethod
    def load_osm_layer(osm_file: str, geometry_type: str, layer_name: str):
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
        layer = QgsVectorLayer(uri, layer_name, "ogr")
        
        if not layer.isValid():
            raise Exception(f"Failed to load OSM layer. Make sure the query actually returned {geometry_type}.")
            
        QgsProject.instance().addMapLayer(layer)
        iface.messageBar().pushMessage("OSM", f"Layer '{layer_name}' loaded successfully.", level=Qgis.MessageLevel.Success)
        return layer

    @staticmethod
    def download_boundary_nominatim(name: str, output_file: str, layer_name: str = None):
        """
        Downloads a GeoJSON boundary from Nominatim API for the given name (e.g., '长沙县').
        Saves it to output_file and loads it into QGIS as a vector layer.
        """
        import json
        from urllib import request, parse
        
        if not layer_name:
            layer_name = f"{name}_boundary"
            
        url = f"https://nominatim.openstreetmap.org/search?q={parse.quote(name)}&polygon_geojson=1&format=json"
        
        req = request.Request(url, headers={'User-Agent': 'QGISAgentPlugin/1.0'})
        iface.messageBar().pushMessage("Nominatim", f"Searching for boundary of {name}...", level=Qgis.MessageLevel.Info)
        
        try:
            with request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
        except Exception as e:
            raise Exception(f"Nominatim API Error: {str(e)}")
            
        if not data:
            raise Exception(f"No results found for '{name}' via Nominatim API.")
            
        # Find the first result that has a Polygon or MultiPolygon geojson
        geojson_feature = None
        for item in data:
            if 'geojson' in item and item['geojson']['type'] in ['Polygon', 'MultiPolygon']:
                geojson_feature = item['geojson']
                break
                
        if not geojson_feature:
            raise Exception(f"No polygon boundary found for '{name}'.")
            
        # Create a valid GeoJSON FeatureCollection
        feature_collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": name, "display_name": data[0].get("display_name", "")},
                    "geometry": geojson_feature
                }
            ]
        }
        
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(feature_collection, f, ensure_ascii=False)
            
        # Load the layer
        layer = QgsVectorLayer(output_file, layer_name, "ogr")
        if not layer.isValid():
            raise Exception(f"Failed to load downloaded boundary file: {output_file}")
            
        QgsProject.instance().addMapLayer(layer)
        iface.messageBar().pushMessage("Nominatim", f"Boundary '{layer_name}' loaded successfully.", level=Qgis.MessageLevel.Success)
        return layer

    @staticmethod
    def download_and_clean_network(bbox_layer: QgsVectorLayer, network_type: str, output_path: str):
        """
        Robustly downloads a network (roads or water) using OSMnx for perfect topology.
        """
        import os
        from qgis.utils import iface
        from qgis.core import Qgis, QgsProject, QgsVectorLayer
        
        try:
            import osmnx as ox
            import geopandas as gpd
            import shapely.wkt
        except ImportError:
            raise Exception("缺失核心空间图论分析库！请在您的 Python 环境中运行: `pip install osmnx geopandas`")
            
        if network_type not in ['roads', 'water']:
            raise ValueError("network_type must be 'roads' or 'water'")
            
        iface.messageBar().pushMessage("OSMnx", f"正在使用 OSMnx 构建 {network_type} 的空间拓扑图，请稍候...", level=Qgis.MessageLevel.Info)
        
        features = list(bbox_layer.getFeatures())
        if not features:
            raise Exception("边界图层为空，无法裁剪！")
            
        geom = features[0].geometry()
        polygon = shapely.wkt.loads(geom.asWkt())
        
        if network_type == 'roads':
            G = ox.graph_from_polygon(polygon, network_type='drive', simplify=True)
        else:
            custom_filter = '["waterway"~"river|stream|canal"]'
            G = ox.graph_from_polygon(polygon, custom_filter=custom_filter, retain_all=True, simplify=True)
            
        gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)
        
        # 兼容 Shapefile 的列表字段转换 - 使用原生循环避免 GeoSeries.apply() 问题
        import pandas as pd
        for col in gdf_edges.columns:
            # 跳过几何列
            if col == 'geometry':
                continue
            # 使用 Python 原生循环检查是否有 list 值
            has_list = False
            for val in gdf_edges[col]:
                if isinstance(val, list):
                    has_list = True
                    break
            if has_list:
                gdf_edges[col] = gdf_edges[col].apply(lambda x: str(x) if isinstance(x, list) else x)
                
        gdf_edges = gdf_edges.reset_index()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        gdf_edges.to_file(output_path, driver='ESRI Shapefile')
        
        final_layer = QgsVectorLayer(output_path, f"Cleaned_{network_type}", "ogr")
        if not final_layer.isValid():
            raise Exception("OSMnx 生成文件加载失败！")
            
        QgsProject.instance().addMapLayer(final_layer)
        iface.messageBar().pushMessage("Topology", f"网络拓扑图已由 OSMnx 生成并加载。", level=Qgis.MessageLevel.Success)
        return final_layer
