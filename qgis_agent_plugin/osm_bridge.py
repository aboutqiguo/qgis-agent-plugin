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
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/x-www-form-urlencoded")
        request.setRawHeader(b"User-Agent", b"QGIS Agent Plugin (QtNetwork)")
        
        iface.messageBar().pushMessage("OSM", "Downloading data from Overpass API... Please wait.", level=Qgis.MessageLevel.Info)
        
        loop = QEventLoop()
        reply = manager.post(request, QByteArray(data))
        reply.finished.connect(loop.quit)
        loop.exec() # Pumps the Qt event loop, preventing QGIS GUI from freezing!
        
        if reply.error() != QNetworkReply.NetworkError.NoError:
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
