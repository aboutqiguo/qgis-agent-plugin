from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class DataSource:
    source_id: str
    name: str
    provider: str
    themes: List[str]
    geometry_types: List[str]
    coverage: str
    scale: str
    update_frequency: str
    access_methods: List[str]
    qgis_workflow: List[str]
    auth_required: bool = False
    network_required: bool = True
    license: str = ""
    reliability: str = "medium"
    url: str = ""
    example_queries: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "provider": self.provider,
            "themes": self.themes,
            "geometry_types": self.geometry_types,
            "coverage": self.coverage,
            "scale": self.scale,
            "update_frequency": self.update_frequency,
            "access_methods": self.access_methods,
            "qgis_workflow": self.qgis_workflow,
            "auth_required": self.auth_required,
            "network_required": self.network_required,
            "license": self.license,
            "reliability": self.reliability,
            "url": self.url,
            "example_queries": self.example_queries,
            "limitations": self.limitations,
        }


DATA_SOURCES: List[DataSource] = [
    DataSource(
        source_id="local_project_files",
        name="Local GIS files",
        provider="User project workspace",
        themes=["local", "vector", "raster", "tabular", "test data"],
        geometry_types=["vector", "raster", "table"],
        coverage="project-specific",
        scale="as provided",
        update_frequency="manual",
        access_methods=["read_file", "execute_pyqgis_script"],
        qgis_workflow=[
            "Inspect the current project folder and loaded layers first.",
            "Prefer GeoPackage for generated test fixtures.",
            "Record source paths in the run artifact report.",
        ],
        auth_required=False,
        network_required=False,
        license="user-provided",
        reliability="high",
        example_queries=["local shapefile", "project geopackage", "csv test data"],
        limitations=["Data quality and CRS depend on the user's files."],
    ),
    DataSource(
        source_id="osm_overpass",
        name="OpenStreetMap Overpass",
        provider="OpenStreetMap contributors",
        themes=["roads", "buildings", "poi", "water", "landuse", "transport", "vector"],
        geometry_types=["point", "line", "polygon", "vector"],
        coverage="global",
        scale="street to city",
        update_frequency="continuous community updates",
        access_methods=["download_osm_data", "OSMDownloader.download_and_clean_network"],
        qgis_workflow=[
            "Use a small EPSG:4326 bbox for tests.",
            "Use download_osm_data for simple tag extraction.",
            "Use OSMDownloader.download_and_clean_network for roads or waterways that need topology.",
        ],
        auth_required=False,
        network_required=True,
        license="ODbL",
        reliability="medium",
        url="https://www.openstreetmap.org",
        example_queries=["roads in bbox", "amenity=hospital", "building footprints"],
        limitations=[
            "Coverage is community-maintained and uneven.",
            "Overpass queries can timeout for large regions.",
        ],
    ),
    DataSource(
        source_id="osm_nominatim_boundaries",
        name="OpenStreetMap Nominatim boundaries",
        provider="OpenStreetMap contributors / Nominatim",
        themes=["administrative boundary", "city", "county", "province", "vector"],
        geometry_types=["polygon", "vector"],
        coverage="global",
        scale="administrative regions",
        update_frequency="continuous community updates",
        access_methods=["OSMDownloader.download_boundary_nominatim"],
        qgis_workflow=[
            "Use this source for named administrative boundaries.",
            "Avoid hand-written Overpass boundary queries for named regions.",
            "Save the GeoJSON inside the project data folder and load it into QGIS.",
        ],
        auth_required=False,
        network_required=True,
        license="ODbL",
        reliability="medium",
        url="https://nominatim.openstreetmap.org",
        example_queries=["Changsha county boundary", "Beijing boundary"],
        limitations=["Name ambiguity must be checked before spatial analysis."],
    ),
    DataSource(
        source_id="gee_sentinel2_sr",
        name="Sentinel-2 Surface Reflectance",
        provider="Copernicus / Google Earth Engine",
        themes=["imagery", "remote sensing", "vegetation", "land cover", "raster"],
        geometry_types=["raster"],
        coverage="global land",
        scale="10m to 60m",
        update_frequency="about 5 days",
        access_methods=["Google Earth Engine", "GEEDownloader.download_ee_object"],
        qgis_workflow=[
            "Build the image or composite in Earth Engine.",
            "Use GEEDownloader.download_ee_object for local export.",
            "Clip locally with QGIS/GDAL when the boundary geometry is complex.",
        ],
        auth_required=True,
        network_required=True,
        license="Copernicus free and open data",
        reliability="high",
        url="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED",
        example_queries=["Sentinel-2 NDVI", "cloud-masked imagery", "land cover testing"],
        limitations=[
            "Requires Earth Engine authentication.",
            "Cloud masking and compositing choices affect results.",
        ],
    ),
    DataSource(
        source_id="gee_landsat_c2",
        name="Landsat Collection 2",
        provider="USGS / Google Earth Engine",
        themes=["imagery", "remote sensing", "long time series", "raster"],
        geometry_types=["raster"],
        coverage="global land",
        scale="30m",
        update_frequency="16 days per satellite path",
        access_methods=["Google Earth Engine", "GEEDownloader.download_ee_object"],
        qgis_workflow=[
            "Use Earth Engine for filtering, masking, and compositing.",
            "Export with GEEDownloader.download_ee_object.",
            "Use QGIS raster tools for local clipping and styling.",
        ],
        auth_required=True,
        network_required=True,
        license="USGS public domain",
        reliability="high",
        url="https://developers.google.com/earth-engine/datasets/catalog/landsat",
        example_queries=["historic imagery", "urban expansion", "NDVI trend"],
        limitations=["Lower spatial resolution than Sentinel-2."],
    ),
    DataSource(
        source_id="gee_copernicus_dem",
        name="Copernicus DEM",
        provider="Copernicus / Google Earth Engine",
        themes=["dem", "elevation", "terrain", "slope", "raster"],
        geometry_types=["raster"],
        coverage="global",
        scale="30m or 90m",
        update_frequency="static release",
        access_methods=["Google Earth Engine", "GEEDownloader.download_ee_object"],
        qgis_workflow=[
            "Export DEM from Earth Engine for the test area.",
            "Generate slope, aspect, or contours with QGIS Processing.",
            "Record vertical datum assumptions in the report.",
        ],
        auth_required=True,
        network_required=True,
        license="Copernicus DEM license",
        reliability="high",
        url="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30",
        example_queries=["DEM for slope", "terrain analysis", "watershed test"],
        limitations=["Verify voids and vertical datum for precision work."],
    ),
    DataSource(
        source_id="gee_dynamic_world",
        name="Dynamic World land cover",
        provider="Google / World Resources Institute",
        themes=["land cover", "classification", "sentinel-2", "raster"],
        geometry_types=["raster"],
        coverage="global land",
        scale="10m",
        update_frequency="near real-time",
        access_methods=["Google Earth Engine", "GEEDownloader.download_ee_object"],
        qgis_workflow=[
            "Filter Dynamic World by date and region in Earth Engine.",
            "Export probability or label bands with GEEDownloader.download_ee_object.",
            "Style class labels in QGIS and record class mapping.",
        ],
        auth_required=True,
        network_required=True,
        license="CC-BY 4.0",
        reliability="high",
        url="https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1",
        example_queries=["land cover sample", "urban area test", "vegetation class map"],
        limitations=["Class probabilities should be interpreted with uncertainty."],
    ),
    DataSource(
        source_id="natural_earth",
        name="Natural Earth",
        provider="Natural Earth",
        themes=["basemap", "countries", "admin", "rivers", "roads", "vector"],
        geometry_types=["point", "line", "polygon", "vector"],
        coverage="global",
        scale="1:10m, 1:50m, 1:110m",
        update_frequency="periodic releases",
        access_methods=["manual download", "QGIS XYZ/vector load"],
        qgis_workflow=[
            "Use Natural Earth for lightweight basemap and global context tests.",
            "Prefer 1:10m for country-scale maps and 1:110m for world maps.",
            "Save downloaded files under the project data folder.",
        ],
        auth_required=False,
        network_required=True,
        license="public domain",
        reliability="high",
        url="https://www.naturalearthdata.com",
        example_queries=["world countries", "admin boundaries", "rivers basemap"],
        limitations=["Not suitable for street-level or parcel-level analysis."],
    ),
    DataSource(
        source_id="gadm_boundaries",
        name="GADM administrative boundaries",
        provider="GADM",
        themes=["administrative boundary", "country", "province", "county", "vector"],
        geometry_types=["polygon", "vector"],
        coverage="global",
        scale="country to local admin",
        update_frequency="periodic releases",
        access_methods=["manual download", "read_file"],
        qgis_workflow=[
            "Download the target country package before analysis.",
            "Load GeoPackage or shapefile layers into QGIS.",
            "Check license constraints before redistribution.",
        ],
        auth_required=False,
        network_required=True,
        license="GADM license; redistribution restrictions may apply",
        reliability="high",
        url="https://gadm.org",
        example_queries=["province boundary", "county boundary", "admin level polygons"],
        limitations=["License is not fully open for all redistribution use cases."],
    ),
    DataSource(
        source_id="worldpop_population",
        name="WorldPop population rasters",
        provider="WorldPop",
        themes=["population", "demographics", "raster"],
        geometry_types=["raster"],
        coverage="global",
        scale="about 100m",
        update_frequency="annual products",
        access_methods=["manual download", "Google Earth Engine"],
        qgis_workflow=[
            "Download country/year raster or access through Earth Engine.",
            "Clip to study area in QGIS.",
            "Use zonal statistics for administrative summaries.",
        ],
        auth_required=False,
        network_required=True,
        license="WorldPop terms; often CC-BY 4.0 depending product",
        reliability="high",
        url="https://www.worldpop.org",
        example_queries=["population density", "zonal population", "demographic raster"],
        limitations=["Modelled estimates should not be treated as census boundaries."],
    ),
    DataSource(
        source_id="geofabrik_extracts",
        name="Geofabrik OSM extracts",
        provider="Geofabrik / OpenStreetMap contributors",
        themes=["osm", "roads", "buildings", "pois", "regional extract", "vector"],
        geometry_types=["point", "line", "polygon", "vector"],
        coverage="global regional extracts",
        scale="city to continent",
        update_frequency="daily",
        access_methods=["manual download", "read_file"],
        qgis_workflow=[
            "Use this for larger OSM test data instead of Overpass.",
            "Download the target regional extract and load layers into QGIS.",
            "Filter desired features locally with QGIS expressions.",
        ],
        auth_required=False,
        network_required=True,
        license="ODbL",
        reliability="high",
        url="https://download.geofabrik.de",
        example_queries=["country OSM extract", "large road network", "regional buildings"],
        limitations=["Downloads can be large; choose the smallest region that fits the test."],
    ),
]


QUERY_SYNONYMS = {
    "道路": ["road", "roads", "transport", "line"],
    "路网": ["road", "roads", "network", "transport"],
    "建筑": ["building", "buildings", "polygon"],
    "兴趣点": ["poi", "amenity", "point"],
    "边界": ["boundary", "administrative", "polygon"],
    "行政区": ["boundary", "administrative", "admin", "polygon"],
    "影像": ["imagery", "remote", "sensing", "raster"],
    "遥感": ["imagery", "remote", "sensing", "raster"],
    "哨兵": ["sentinel", "imagery", "raster"],
    "高程": ["dem", "elevation", "terrain", "raster"],
    "地形": ["dem", "elevation", "terrain", "slope"],
    "坡度": ["dem", "slope", "terrain"],
    "人口": ["population", "demographics", "raster"],
    "土地覆盖": ["land", "cover", "classification", "raster"],
    "水系": ["water", "waterway", "line"],
    "矢量": ["vector"],
    "栅格": ["raster"],
    "本地": ["local", "project"],
}


def list_data_sources() -> List[Dict[str, Any]]:
    return [source.to_dict() for source in DATA_SOURCES]


def get_data_source(source_id: str) -> Optional[DataSource]:
    for source in DATA_SOURCES:
        if source.source_id == source_id:
            return source
    return None


def search_data_sources(
    query: str = "",
    theme: str = "",
    geometry_type: str = "",
    region: str = "",
    limit: int = 5,
    allow_auth: Optional[bool] = None,
    allow_network: Optional[bool] = None,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 5), 20))
    scored = []
    for source in DATA_SOURCES:
        if allow_auth is False and source.auth_required:
            continue
        if allow_network is False and source.network_required:
            continue
        if theme and not _source_matches(source, theme):
            continue
        if geometry_type and not _geometry_matches(source, geometry_type):
            continue

        score = _score_source(source, query=query, theme=theme, geometry_type=geometry_type, region=region)
        if score > 0 or not any((query, theme, geometry_type, region)):
            scored.append((score, source))

    scored.sort(key=lambda item: (-item[0], item[1].source_id))
    matches = []
    for score, source in scored[:limit]:
        item = source.to_dict()
        item["match_score"] = score
        item["recommended_for"] = _recommended_for(source)
        matches.append(item)

    return {
        "query": query,
        "theme": theme,
        "geometry_type": geometry_type,
        "region": region,
        "limit": limit,
        "matches": matches,
    }


def build_data_acquisition_plan(
    task: str,
    region: str = "",
    data_type: str = "",
    bbox: str = "",
    preferred_source_id: str = "",
    output_folder: str = "data",
) -> Dict[str, Any]:
    task = (task or "").strip()
    data_type = (data_type or "").strip()
    if not task and not data_type:
        raise ValueError("task or data_type is required.")

    preferred = get_data_source(preferred_source_id) if preferred_source_id else None
    if preferred:
        candidates = [preferred.to_dict()]
    else:
        result = search_data_sources(
            query=f"{task} {data_type}".strip(),
            theme=data_type,
            region=region,
            limit=3,
        )
        candidates = result["matches"]

    warnings = []
    if not candidates:
        warnings.append("No matching data source found in the handbook.")

    steps = [
        "Confirm the study area, CRS, target scale, and licensing constraints.",
        "Prefer local project data if it already exists and is authoritative for the task.",
    ]

    if candidates:
        source = candidates[0]
        steps.extend(_workflow_steps_for_source(source, region=region, bbox=bbox, output_folder=output_folder))
    else:
        steps.append("Ask the user for a concrete source or sample file.")

    markdown = format_acquisition_plan_markdown(
        task=task,
        region=region,
        data_type=data_type,
        bbox=bbox,
        output_folder=output_folder,
        candidates=candidates,
        steps=steps,
        warnings=warnings,
    )
    return {
        "task": task,
        "region": region,
        "data_type": data_type,
        "bbox": bbox,
        "output_folder": output_folder,
        "recommended_sources": candidates,
        "steps": steps,
        "warnings": warnings,
        "markdown": markdown,
    }


def format_search_results_markdown(result: Dict[str, Any]) -> str:
    matches = result.get("matches") or []
    lines = [
        "# Data Source Search",
        "",
        f"- Query: {result.get('query') or '-'}",
        f"- Theme: {result.get('theme') or '-'}",
        f"- Geometry type: {result.get('geometry_type') or '-'}",
        f"- Region: {result.get('region') or '-'}",
        "",
    ]
    if not matches:
        lines.append("No matching data source found.")
        return "\n".join(lines) + "\n"

    lines.extend([
        "| Source | Score | Coverage | Access | Auth | License |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for source in matches:
        lines.append(
            f"| {source['name']} (`{source['source_id']}`) | {source.get('match_score', 0)} | "
            f"{source['coverage']} | {', '.join(source['access_methods'])} | "
            f"{'yes' if source['auth_required'] else 'no'} | {source['license']} |"
        )
    return "\n".join(lines) + "\n"


def format_acquisition_plan_markdown(
    task: str,
    region: str,
    data_type: str,
    bbox: str,
    output_folder: str,
    candidates: List[Dict[str, Any]],
    steps: List[str],
    warnings: List[str],
) -> str:
    lines = [
        "# Data Acquisition Plan",
        "",
        f"- Task: {task or '-'}",
        f"- Region: {region or '-'}",
        f"- Data type: {data_type or '-'}",
        f"- BBox: {bbox or '-'}",
        f"- Output folder: `{output_folder or 'data'}`",
        "",
        "## Recommended Sources",
        "",
    ]
    if candidates:
        for source in candidates:
            lines.extend([
                f"### {source['name']} (`{source['source_id']}`)",
                "",
                f"- Provider: {source['provider']}",
                f"- Coverage: {source['coverage']}",
                f"- Scale: {source['scale']}",
                f"- Access: {', '.join(source['access_methods'])}",
                f"- Auth required: {'yes' if source['auth_required'] else 'no'}",
                f"- Network required: {'yes' if source['network_required'] else 'no'}",
                f"- License: {source['license']}",
                f"- Reliability: {source['reliability']}",
                f"- URL: {source['url'] or '-'}",
                "",
            ])
            if source.get("limitations"):
                lines.append("Limitations:")
                lines.extend(f"- {item}" for item in source["limitations"])
                lines.append("")
    else:
        lines.extend(["No recommended source found.", ""])

    lines.extend(["## Steps", ""])
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. {step}")

    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)

    return "\n".join(lines) + "\n"


def _score_source(source: DataSource, query: str, theme: str, geometry_type: str, region: str) -> int:
    tokens = _tokens(" ".join([query or "", theme or "", geometry_type or "", region or ""]))
    if not tokens:
        return 10

    haystack = _tokens(
        " ".join(
            [
                source.source_id,
                source.name,
                source.provider,
                source.coverage,
                source.scale,
                " ".join(source.themes),
                " ".join(source.geometry_types),
                " ".join(source.access_methods),
                " ".join(source.example_queries),
            ]
        )
    )
    score = 0
    for token in tokens:
        if token in haystack:
            score += 10
        elif any(token in item or item in token for item in haystack):
            score += 4

    if source.reliability == "high":
        score += 5
    if region and ("global" in source.coverage.lower() or "project" in source.coverage.lower()):
        score += 3
    if theme and _source_matches(source, theme):
        score += 8
    if geometry_type and _geometry_matches(source, geometry_type):
        score += 8
    return score


def _source_matches(source: DataSource, value: str) -> bool:
    tokens = _tokens(value)
    haystack = _tokens(" ".join(source.themes + source.example_queries + [source.name, source.source_id]))
    return all(any(token == item or token in item or item in token for item in haystack) for token in tokens)


def _geometry_matches(source: DataSource, value: str) -> bool:
    tokens = _tokens(value)
    haystack = _tokens(" ".join(source.geometry_types))
    return all(any(token == item or token in item or item in token for item in haystack) for token in tokens)


def _tokens(text: str) -> List[str]:
    value = (text or "").lower()
    for char in ",;:/\\()[]{}|_-":
        value = value.replace(char, " ")
    tokens = [token for token in value.split() if token]
    expanded: List[str] = []
    for token in tokens:
        expanded.append(token)
        for key, aliases in QUERY_SYNONYMS.items():
            if key in token:
                expanded.extend(aliases)
    return expanded


def _recommended_for(source: DataSource) -> str:
    if "test data" in source.themes:
        return "Use first when the project already has trustworthy local files."
    if "administrative boundary" in source.themes:
        return "Use for named administrative regions and boundary clipping."
    if "imagery" in source.themes:
        return "Use for raster imagery, classification, and remote sensing tests."
    if "dem" in source.themes:
        return "Use for terrain, slope, and elevation-derived products."
    if "population" in source.themes:
        return "Use for population raster and zonal statistics tests."
    if "osm" in source.themes or "roads" in source.themes:
        return "Use for roads, POIs, buildings, and street-level vector tests."
    return "Use when its coverage and license match the task."


def _workflow_steps_for_source(
    source: Dict[str, Any],
    region: str,
    bbox: str,
    output_folder: str,
) -> List[str]:
    source_id = source.get("source_id", "")
    steps = list(source.get("qgis_workflow") or [])

    if source_id == "osm_overpass":
        if bbox:
            steps.append(f"Call download_osm_data with bbox `{bbox}` and task-specific OSM tags.")
        else:
            steps.append("Ask for or derive a small EPSG:4326 bbox before calling download_osm_data.")
    elif source_id == "osm_nominatim_boundaries":
        target = region or "the requested named region"
        steps.append(f"Use OSMDownloader.download_boundary_nominatim for {target}.")
    elif source_id.startswith("gee_"):
        steps.append("Use search_gee_api if unsure about the exact Earth Engine dataset/API.")
        steps.append("Use GEEDownloader.download_ee_object rather than getDownloadURL for real exports.")
    elif source_id in {"natural_earth", "gadm_boundaries", "worldpop_population", "geofabrik_extracts"}:
        steps.append("Download the smallest suitable package manually or through a future source-specific downloader.")

    steps.append(f"Store downloaded or generated files under `{output_folder or 'data'}`.")
    steps.append("Record source id, URL, license, date, CRS, and processing notes in the run artifacts.")
    return steps
