import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


CATALOG_SCHEMA_VERSION = "1.0"


SYNONYMS = {
    "buffer": ["buffer", "缓冲", "缓冲区"],
    "缓冲": ["buffer", "缓冲", "缓冲区"],
    "clip": ["clip", "裁剪", "裁切", "掩膜"],
    "裁剪": ["clip", "裁剪", "裁切", "掩膜"],
    "intersect": ["intersect", "intersection", "相交", "叠置"],
    "相交": ["intersect", "intersection", "相交", "叠置"],
    "dissolve": ["dissolve", "融合", "溶解"],
    "融合": ["dissolve", "融合", "溶解"],
    "slope": ["slope", "坡度"],
    "坡度": ["slope", "坡度"],
    "aspect": ["aspect", "坡向"],
    "坡向": ["aspect", "坡向"],
    "contour": ["contour", "等值线", "等高线"],
    "等值线": ["contour", "等值线", "等高线"],
    "reproject": ["reproject", "warp", "投影", "重投影", "坐标转换"],
    "重投影": ["reproject", "warp", "投影", "重投影", "坐标转换"],
    "rasterize": ["rasterize", "栅格化"],
    "栅格化": ["rasterize", "栅格化"],
    "polygonize": ["polygonize", "矢量化", "面化"],
    "矢量化": ["polygonize", "矢量化", "面化"],
    "select": ["select", "selection", "选择", "筛选"],
    "选择": ["select", "selection", "选择", "筛选"],
    "nearest": ["nearest", "最近邻", "最近"],
    "最近邻": ["nearest", "最近邻", "最近"],
}


def _safe_call(obj: Any, name: str, default: Any = "") -> Any:
    try:
        value = getattr(obj, name)
        return value() if callable(value) else value
    except Exception:
        return default


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


def _to_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _tokenize_query(query: str) -> List[str]:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", query or "", flags=re.UNICODE)
    out: List[str] = []
    for token in tokens:
        lowered = token.lower()
        out.append(lowered)
        out.extend(SYNONYMS.get(lowered, []))
    deduped: List[str] = []
    seen = set()
    for token in out:
        token = token.strip().lower()
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped[:16]


def _fts_match_query(query: str) -> str:
    tokens = _tokenize_query(query)
    if not tokens:
        return ""
    parts = []
    for token in tokens:
        escaped = token.replace('"', '""')
        if re.fullmatch(r"[a-z0-9_]+", token):
            parts.append(f'"{escaped}"*')
        else:
            parts.append(f'"{escaped}"')
    return " OR ".join(parts)


def _like_pattern(query: str) -> str:
    tokens = _tokenize_query(query)
    return "%" + "%".join(tokens[:4] or [query]) + "%"


def _catalog_path() -> str:
    try:
        from qgis.core import QgsApplication

        root = QgsApplication.qgisSettingsDirPath()
        if root:
            os.makedirs(root, exist_ok=True)
            return os.path.join(root, "qgis_agent_catalog.db")
    except Exception:
        pass
    try:
        from qgis.core import QgsProject

        home = QgsProject.instance().homePath()
        if home:
            return os.path.join(home, "qgis_agent_catalog.db")
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".qgis_agent_catalog.db")


class QgisCatalogDB:
    def __init__(self, db_path: str = ""):
        self.db_path = db_path or _catalog_path()
        self.conn: Optional[sqlite3.Connection] = None
        self.has_fts = False

    def close(self) -> None:
        if self.conn:
            self.conn.close()
        self.conn = None

    def _connect(self) -> sqlite3.Connection:
        if self.conn:
            return self.conn
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        return self.conn

    def _init_schema(self) -> None:
        conn = self.conn
        if not conn:
            return
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_algorithms (
                alg_id TEXT PRIMARY KEY,
                provider_id TEXT,
                provider_name TEXT,
                name TEXT,
                display_name TEXT,
                group_name TEXT,
                group_id TEXT,
                short_description TEXT,
                help_url TEXT,
                tags_json TEXT,
                flags TEXT,
                can_execute INTEGER,
                execute_error TEXT,
                parameter_count INTEGER,
                output_count INTEGER,
                qgis_version TEXT,
                provider_signature TEXT,
                updated_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_parameters (
                alg_id TEXT,
                name TEXT,
                description TEXT,
                type_name TEXT,
                type_id TEXT,
                default_value TEXT,
                optional INTEGER,
                flags TEXT,
                help_text TEXT,
                metadata_json TEXT,
                options_json TEXT,
                accepted_layer_types_json TEXT,
                sort_order INTEGER,
                PRIMARY KEY (alg_id, name)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_outputs (
                alg_id TEXT,
                name TEXT,
                description TEXT,
                type_name TEXT,
                sort_order INTEGER,
                PRIMARY KEY (alg_id, name)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_parameter_types (
                type_id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                python_class TEXT,
                flags TEXT,
                updated_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS expression_functions (
                name TEXT PRIMARY KEY,
                group_name TEXT,
                help_text TEXT,
                tags_json TEXT,
                params_json TEXT,
                uses_geometry INTEGER,
                updated_at TEXT
            )
            """
        )
        self.has_fts = False
        try:
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS processing_algorithms_fts USING fts5(
                    alg_id UNINDEXED,
                    provider_id,
                    display_name,
                    group_name,
                    short_description,
                    tags,
                    parameters,
                    outputs,
                    search_text
                )
                """
            )
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS expression_functions_fts USING fts5(
                    name UNINDEXED,
                    group_name,
                    help_text,
                    tags,
                    params,
                    search_text
                )
                """
            )
            self.has_fts = True
        except Exception:
            self.has_fts = False
        conn.commit()

    def ensure_ready(self, force: bool = False) -> Dict[str, Any]:
        conn = self._connect()
        signature = self._processing_signature()
        stored = self._get_meta("processing_signature")
        if force or stored != signature:
            self.rebuild_processing_catalog(signature=signature)
        expr_signature = self._expression_signature()
        if force or self._get_meta("expression_signature") != expr_signature:
            self.rebuild_expression_catalog(signature=expr_signature)
        return {
            "db_path": self.db_path,
            "has_fts": self.has_fts,
            "processing_signature": signature,
            "expression_signature": expr_signature,
            "schema_version": CATALOG_SCHEMA_VERSION,
        }

    def _get_meta(self, key: str) -> str:
        cur = self._connect().cursor()
        cur.execute("SELECT value FROM catalog_meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        self._connect().execute(
            "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES (?, ?)",
            (key, value),
        )

    def _processing_signature(self) -> str:
        try:
            from qgis.core import Qgis, QgsApplication

            registry = QgsApplication.processingRegistry()
            providers = []
            for provider in registry.providers():
                alg_ids = sorted(_safe_call(alg, "id", "") for alg in provider.algorithms())
                providers.append(
                    {
                        "id": _safe_call(provider, "id", ""),
                        "name": _safe_call(provider, "name", ""),
                        "alg_ids": alg_ids,
                    }
                )
            payload = {
                "schema": CATALOG_SCHEMA_VERSION,
                "qgis_version": getattr(Qgis, "QGIS_VERSION", ""),
                "providers": sorted(providers, key=lambda item: item["id"]),
            }
            return hashlib.sha256(_to_json(payload).encode("utf-8")).hexdigest()
        except Exception as exc:
            return f"unavailable:{exc}"

    def _expression_signature(self) -> str:
        try:
            from qgis.core import Qgis, QgsExpression

            names = sorted(str(_safe_call(function, "name", "")) for function in QgsExpression.Functions())
            payload = {
                "schema": CATALOG_SCHEMA_VERSION,
                "qgis_version": getattr(Qgis, "QGIS_VERSION", ""),
                "functions": names,
            }
            return hashlib.sha256(_to_json(payload).encode("utf-8")).hexdigest()
        except Exception as exc:
            return f"unavailable:{exc}"

    def rebuild_processing_catalog(self, signature: str = "", progress_callback: Any = None) -> Dict[str, Any]:
        from qgis.core import Qgis, QgsApplication

        conn = self._connect()
        cur = conn.cursor()
        for table in (
            "processing_algorithms",
            "processing_parameters",
            "processing_outputs",
            "processing_parameter_types",
        ):
            cur.execute(f"DELETE FROM {table}")
        if self.has_fts:
            cur.execute("DELETE FROM processing_algorithms_fts")

        registry = QgsApplication.processingRegistry()
        if progress_callback:
            progress_callback(0, 1, "Preparing Processing catalog tables")
        qgis_version = getattr(Qgis, "QGIS_VERSION", "")
        provider_signature = signature or self._processing_signature()
        now = _now()
        alg_count = 0
        param_count = 0
        output_count = 0
        parameter_types = list(registry.parameterTypes())

        for index, parameter_type in enumerate(parameter_types, start=1):
            type_id = str(_safe_call(parameter_type, "id", ""))
            if not type_id:
                continue
            cur.execute(
                """
                INSERT OR REPLACE INTO processing_parameter_types
                (type_id, name, description, python_class, flags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    type_id,
                    str(_safe_call(parameter_type, "name", "")),
                    str(_safe_call(parameter_type, "description", "")),
                    parameter_type.__class__.__name__,
                    str(_safe_call(parameter_type, "flags", "")),
                    now,
                ),
            )
            if progress_callback and (index == len(parameter_types) or index % 20 == 0):
                progress_callback(index, max(len(parameter_types), 1), "Indexing Processing parameter types")

        algorithms = list(registry.algorithms())
        for alg_index, alg in enumerate(algorithms, start=1):
            row = self._algorithm_row(alg, qgis_version, provider_signature, now)
            cur.execute(
                """
                INSERT OR REPLACE INTO processing_algorithms
                (alg_id, provider_id, provider_name, name, display_name, group_name, group_id,
                 short_description, help_url, tags_json, flags, can_execute, execute_error,
                 parameter_count, output_count, qgis_version, provider_signature, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["alg_id"],
                    row["provider_id"],
                    row["provider_name"],
                    row["name"],
                    row["display_name"],
                    row["group_name"],
                    row["group_id"],
                    row["short_description"],
                    row["help_url"],
                    row["tags_json"],
                    row["flags"],
                    row["can_execute"],
                    row["execute_error"],
                    row["parameter_count"],
                    row["output_count"],
                    row["qgis_version"],
                    row["provider_signature"],
                    row["updated_at"],
                ),
            )

            parameters_text = []
            for index, param in enumerate(_safe_call(alg, "parameterDefinitions", [])):
                param_row = self._parameter_row(row["alg_id"], param, index)
                parameters_text.append(
                    " ".join(
                        str(param_row.get(key, ""))
                        for key in ("name", "description", "type_name", "type_id", "options_json")
                    )
                )
                cur.execute(
                    """
                    INSERT OR REPLACE INTO processing_parameters
                    (alg_id, name, description, type_name, type_id, default_value, optional,
                     flags, help_text, metadata_json, options_json, accepted_layer_types_json, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        param_row["alg_id"],
                        param_row["name"],
                        param_row["description"],
                        param_row["type_name"],
                        param_row["type_id"],
                        param_row["default_value"],
                        param_row["optional"],
                        param_row["flags"],
                        param_row["help_text"],
                        param_row["metadata_json"],
                        param_row["options_json"],
                        param_row["accepted_layer_types_json"],
                        param_row["sort_order"],
                    ),
                )
                param_count += 1

            outputs_text = []
            for index, output in enumerate(_safe_call(alg, "outputDefinitions", [])):
                output_row = self._output_row(row["alg_id"], output, index)
                outputs_text.append(
                    " ".join(str(output_row.get(key, "")) for key in ("name", "description", "type_name"))
                )
                cur.execute(
                    """
                    INSERT OR REPLACE INTO processing_outputs
                    (alg_id, name, description, type_name, sort_order)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        output_row["alg_id"],
                        output_row["name"],
                        output_row["description"],
                        output_row["type_name"],
                        output_row["sort_order"],
                    ),
                )
                output_count += 1

            if self.has_fts:
                tags = " ".join(json.loads(row["tags_json"] or "[]"))
                search_text = " ".join(
                    [
                        row["alg_id"],
                        row["provider_id"],
                        row["provider_name"],
                        row["name"],
                        row["display_name"],
                        row["group_name"],
                        row["short_description"],
                        tags,
                        " ".join(parameters_text),
                        " ".join(outputs_text),
                    ]
                )
                cur.execute(
                    """
                    INSERT INTO processing_algorithms_fts
                    (alg_id, provider_id, display_name, group_name, short_description,
                     tags, parameters, outputs, search_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["alg_id"],
                        row["provider_id"],
                        row["display_name"],
                        row["group_name"],
                        row["short_description"],
                        tags,
                        " ".join(parameters_text),
                        " ".join(outputs_text),
                        search_text,
                    ),
                )
            alg_count += 1
            if progress_callback and (alg_index == len(algorithms) or alg_index % 10 == 0):
                progress_callback(alg_index, max(len(algorithms), 1), "Indexing Processing algorithms")

        self._set_meta("processing_signature", provider_signature)
        self._set_meta("processing_built_at", now)
        self._set_meta("schema_version", CATALOG_SCHEMA_VERSION)
        conn.commit()
        if progress_callback:
            progress_callback(1, 1, "Processing catalog committed")
        return {
            "algorithm_count": alg_count,
            "parameter_count": param_count,
            "output_count": output_count,
            "parameter_type_count": len(parameter_types),
            "db_path": self.db_path,
        }

    def rebuild_expression_catalog(self, signature: str = "", progress_callback: Any = None) -> Dict[str, Any]:
        from qgis.core import QgsExpression

        conn = self._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM expression_functions")
        if self.has_fts:
            cur.execute("DELETE FROM expression_functions_fts")
        now = _now()
        count = 0
        functions = list(QgsExpression.Functions())
        for index, function in enumerate(functions, start=1):
            row = self._expression_function_row(function, now)
            if not row["name"]:
                continue
            cur.execute(
                """
                INSERT OR REPLACE INTO expression_functions
                (name, group_name, help_text, tags_json, params_json, uses_geometry, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["name"],
                    row["group_name"],
                    row["help_text"],
                    row["tags_json"],
                    row["params_json"],
                    row["uses_geometry"],
                    row["updated_at"],
                ),
            )
            if self.has_fts:
                tags = " ".join(json.loads(row["tags_json"] or "[]"))
                cur.execute(
                    """
                    INSERT INTO expression_functions_fts
                    (name, group_name, help_text, tags, params, search_text)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["name"],
                        row["group_name"],
                        row["help_text"],
                        tags,
                        row["params_json"],
                        " ".join([row["name"], row["group_name"], row["help_text"], tags, row["params_json"]]),
                    ),
                )
            count += 1
            if progress_callback and (index == len(functions) or index % 20 == 0):
                progress_callback(index, max(len(functions), 1), "Indexing expression functions")
        self._set_meta("expression_signature", signature or self._expression_signature())
        self._set_meta("expression_built_at", now)
        conn.commit()
        if progress_callback:
            progress_callback(1, 1, "Expression catalog committed")
        return {"function_count": count, "db_path": self.db_path}

    def _algorithm_row(self, alg: Any, qgis_version: str, provider_signature: str, now: str) -> Dict[str, Any]:
        provider = _safe_call(alg, "provider", None)
        execute_error = ""
        can_execute = 1
        try:
            can_execute = 1 if alg.canExecute() else 0
        except Exception as exc:
            can_execute = 0
            execute_error = str(exc)
        return {
            "alg_id": str(_safe_call(alg, "id", "")),
            "provider_id": str(_safe_call(provider, "id", "")) if provider else "",
            "provider_name": str(_safe_call(provider, "name", "")) if provider else "",
            "name": str(_safe_call(alg, "name", "")),
            "display_name": str(_safe_call(alg, "displayName", "")),
            "group_name": str(_safe_call(alg, "group", "")),
            "group_id": str(_safe_call(alg, "groupId", "")),
            "short_description": str(_safe_call(alg, "shortDescription", "")),
            "help_url": str(_safe_call(alg, "helpUrl", "")),
            "tags_json": _to_json(_safe_call(alg, "tags", [])),
            "flags": str(_safe_call(alg, "flags", "")),
            "can_execute": can_execute,
            "execute_error": execute_error,
            "parameter_count": len(_safe_call(alg, "parameterDefinitions", [])),
            "output_count": len(_safe_call(alg, "outputDefinitions", [])),
            "qgis_version": qgis_version,
            "provider_signature": provider_signature,
            "updated_at": now,
        }

    def _parameter_row(self, alg_id: str, param: Any, index: int) -> Dict[str, Any]:
        return {
            "alg_id": alg_id,
            "name": str(_safe_call(param, "name", "")),
            "description": str(_safe_call(param, "description", "")),
            "type_name": param.__class__.__name__,
            "type_id": str(_safe_call(param, "type", "")),
            "default_value": str(_safe_call(param, "defaultValue", "")),
            "optional": 1 if self._parameter_optional(param) else 0,
            "flags": str(_safe_call(param, "flags", "")),
            "help_text": str(_safe_call(param, "help", "")),
            "metadata_json": _to_json(_safe_call(param, "metadata", {})),
            "options_json": _to_json(_safe_call(param, "options", [])),
            "accepted_layer_types_json": _to_json(_safe_call(param, "dataTypes", [])),
            "sort_order": index,
        }

    def _parameter_optional(self, param: Any) -> bool:
        try:
            from qgis.core import QgsProcessingParameterDefinition

            flags = _safe_call(param, "flags", None)
            flag_optional = getattr(QgsProcessingParameterDefinition, "FlagOptional", None)
            if flag_optional is not None and flags is not None:
                return bool(flags & flag_optional)
        except Exception:
            pass
        text = str(_safe_call(param, "flags", "")).lower()
        return "optional" in text

    def _output_row(self, alg_id: str, output: Any, index: int) -> Dict[str, Any]:
        return {
            "alg_id": alg_id,
            "name": str(_safe_call(output, "name", "")),
            "description": str(_safe_call(output, "description", "")),
            "type_name": output.__class__.__name__,
            "sort_order": index,
        }

    def _expression_function_row(self, function: Any, now: str) -> Dict[str, Any]:
        name = str(_safe_call(function, "name", ""))
        tags = []
        try:
            from qgis.core import QgsExpression

            tags = list(QgsExpression.tags(name))
        except Exception:
            tags = _safe_call(function, "tags", [])
        return {
            "name": name,
            "group_name": str(_safe_call(function, "group", "")),
            "help_text": str(_safe_call(function, "helpText", "")),
            "tags_json": _to_json(tags),
            "params_json": _to_json(_safe_call(function, "params", [])),
            "uses_geometry": 1 if bool(_safe_call(function, "usesGeometry", False)) else 0,
            "updated_at": now,
        }

    def search_processing_algorithms(
        self,
        query: str,
        provider: str = "",
        limit: int = 8,
    ) -> Dict[str, Any]:
        self.ensure_ready()
        limit = max(1, min(int(limit or 8), 20))
        rows: List[sqlite3.Row] = []
        cur = self._connect().cursor()
        if self.has_fts:
            match_query = _fts_match_query(query)
            try:
                sql = """
                    SELECT a.*, bm25(processing_algorithms_fts) AS rank
                    FROM processing_algorithms_fts
                    JOIN processing_algorithms a ON a.alg_id = processing_algorithms_fts.alg_id
                    WHERE processing_algorithms_fts MATCH ?
                """
                params: List[Any] = [match_query]
                if provider:
                    sql += " AND a.provider_id = ?"
                    params.append(provider)
                sql += " ORDER BY rank LIMIT ?"
                params.append(limit)
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                rows = []
        if not rows:
            pattern = _like_pattern(query)
            sql = """
                SELECT *, 0 AS rank FROM processing_algorithms
                WHERE (alg_id LIKE ? OR display_name LIKE ? OR group_name LIKE ?
                       OR short_description LIKE ? OR tags_json LIKE ?)
            """
            params = [pattern, pattern, pattern, pattern, pattern]
            if provider:
                sql += " AND provider_id = ?"
                params.append(provider)
            sql += " ORDER BY provider_id, display_name LIMIT ?"
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
        matches = [self._format_algorithm_match(row) for row in rows]
        return {
            "ok": True,
            "message": f"Found {len(matches)} processing algorithm candidate(s).",
            "data": {
                "query": query,
                "provider": provider,
                "matches": matches,
                "db_path": self.db_path,
                "has_fts": self.has_fts,
            },
        }

    def describe_processing_algorithm(self, alg_id: str) -> Dict[str, Any]:
        self.ensure_ready()
        cur = self._connect().cursor()
        cur.execute("SELECT * FROM processing_algorithms WHERE alg_id = ?", (alg_id,))
        alg = cur.fetchone()
        if not alg:
            suggestions = self.search_processing_algorithms(alg_id, limit=5)["data"]["matches"]
            return {
                "ok": False,
                "message": f"Processing algorithm was not found: {alg_id}",
                "error_type": "processing_error",
                "data": {"alg_id": alg_id, "suggestions": suggestions},
            }
        cur.execute(
            "SELECT * FROM processing_parameters WHERE alg_id = ? ORDER BY sort_order",
            (alg_id,),
        )
        parameters = [self._row_to_parameter(row) for row in cur.fetchall()]
        cur.execute(
            "SELECT * FROM processing_outputs WHERE alg_id = ? ORDER BY sort_order",
            (alg_id,),
        )
        outputs = [dict(row) for row in cur.fetchall()]
        example_parameters = {}
        for param in parameters:
            name = param["name"]
            if name.upper().endswith("OUTPUT") or name.upper() == "OUTPUT":
                example_parameters[name] = "TEMPORARY_OUTPUT"
            elif not param["optional"]:
                example_parameters[name] = self._example_value_for_parameter(param)
        data = dict(alg)
        data["tags"] = json.loads(data.pop("tags_json") or "[]")
        data["parameters"] = parameters
        data["outputs"] = outputs
        data["example_parameters"] = example_parameters
        return {
            "ok": True,
            "message": f"Loaded processing algorithm signature for {alg_id}.",
            "data": data,
        }

    def _format_algorithm_match(self, row: sqlite3.Row) -> Dict[str, Any]:
        cur = self._connect().cursor()
        cur.execute(
            "SELECT name, description, type_name, optional FROM processing_parameters WHERE alg_id = ? ORDER BY sort_order LIMIT 12",
            (row["alg_id"],),
        )
        params_preview = []
        for param in cur.fetchall():
            optional = "optional" if param["optional"] else "required"
            params_preview.append(
                f"{param['name']}: {param['type_name']} ({optional}) - {param['description']}"
            )
        return {
            "alg_id": row["alg_id"],
            "display_name": row["display_name"],
            "provider_id": row["provider_id"],
            "provider_name": row["provider_name"],
            "group": row["group_name"],
            "short_description": row["short_description"],
            "help_url": row["help_url"],
            "tags": json.loads(row["tags_json"] or "[]"),
            "can_execute": bool(row["can_execute"]),
            "rank": row["rank"] if "rank" in row.keys() else 0,
            "parameters_preview": params_preview,
        }

    def _row_to_parameter(self, row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        for key in ("metadata_json", "options_json", "accepted_layer_types_json"):
            public_key = key.replace("_json", "")
            try:
                item[public_key] = json.loads(item.pop(key) or "[]")
            except Exception:
                item[public_key] = []
        item["optional"] = bool(item["optional"])
        return item

    def _example_value_for_parameter(self, param: Dict[str, Any]) -> Any:
        name = param.get("name", "")
        type_text = " ".join([param.get("type_name", ""), param.get("type_id", "")]).lower()
        if "raster" in type_text or "vector" in type_text or "source" in type_text or "layer" in type_text:
            return f"<{name} layer name or id>"
        if "distance" in name.lower() or "double" in type_text or "number" in type_text:
            return 1.0
        if "integer" in type_text or "number" in type_text:
            return 1
        if "boolean" in type_text or "bool" in type_text:
            return False
        if "enum" in type_text:
            return 0
        return param.get("default_value") or f"<{name}>"

    def search_expression_functions(self, query: str, limit: int = 8) -> Dict[str, Any]:
        self.ensure_ready()
        limit = max(1, min(int(limit or 8), 20))
        rows: List[sqlite3.Row] = []
        cur = self._connect().cursor()
        if self.has_fts:
            try:
                cur.execute(
                    """
                    SELECT f.*, bm25(expression_functions_fts) AS rank
                    FROM expression_functions_fts
                    JOIN expression_functions f ON f.name = expression_functions_fts.name
                    WHERE expression_functions_fts MATCH ?
                    ORDER BY rank LIMIT ?
                    """,
                    (_fts_match_query(query), limit),
                )
                rows = cur.fetchall()
            except Exception:
                rows = []
        if not rows:
            pattern = _like_pattern(query)
            cur.execute(
                """
                SELECT *, 0 AS rank FROM expression_functions
                WHERE name LIKE ? OR group_name LIKE ? OR help_text LIKE ? OR tags_json LIKE ?
                ORDER BY group_name, name LIMIT ?
                """,
                (pattern, pattern, pattern, pattern, limit),
            )
            rows = cur.fetchall()
        matches = [self._format_expression_function(row) for row in rows]
        return {
            "ok": True,
            "message": f"Found {len(matches)} QGIS expression function candidate(s).",
            "data": {"query": query, "matches": matches, "db_path": self.db_path},
        }

    def describe_expression_function(self, name: str) -> Dict[str, Any]:
        self.ensure_ready()
        cur = self._connect().cursor()
        cur.execute("SELECT * FROM expression_functions WHERE name = ?", (name,))
        row = cur.fetchone()
        if not row:
            suggestions = self.search_expression_functions(name, limit=5)["data"]["matches"]
            return {
                "ok": False,
                "message": f"QGIS expression function was not found: {name}",
                "error_type": "argument_error",
                "data": {"name": name, "suggestions": suggestions},
            }
        return {
            "ok": True,
            "message": f"Loaded expression function signature for {name}.",
            "data": self._format_expression_function(row, include_help=True),
        }

    def _format_expression_function(self, row: sqlite3.Row, include_help: bool = False) -> Dict[str, Any]:
        help_text = row["help_text"] or ""
        return {
            "name": row["name"],
            "group": row["group_name"],
            "tags": json.loads(row["tags_json"] or "[]"),
            "params": json.loads(row["params_json"] or "[]"),
            "uses_geometry": bool(row["uses_geometry"]),
            "help_text": help_text if include_help else help_text[:500],
            "rank": row["rank"] if "rank" in row.keys() else 0,
        }


def rebuild_qgis_catalog(force: bool = True) -> Dict[str, Any]:
    db = QgisCatalogDB()
    status = db.ensure_ready(force=force)
    return {"ok": True, "message": "QGIS Agent catalog is ready.", "data": status}


def search_processing_algorithms(query: str, provider: str = "", limit: int = 8) -> Dict[str, Any]:
    return QgisCatalogDB().search_processing_algorithms(query=query, provider=provider, limit=limit)


def describe_processing_algorithm(alg_id: str) -> Dict[str, Any]:
    return QgisCatalogDB().describe_processing_algorithm(alg_id=alg_id)


def search_qgis_expression_functions(query: str, limit: int = 8) -> Dict[str, Any]:
    return QgisCatalogDB().search_expression_functions(query=query, limit=limit)


def describe_qgis_expression_function(name: str) -> Dict[str, Any]:
    return QgisCatalogDB().describe_expression_function(name=name)


def validate_qgis_expression(expression: str, layer_name: str = "") -> Dict[str, Any]:
    from qgis.core import QgsExpression, QgsProject

    expr = QgsExpression(expression or "")
    data: Dict[str, Any] = {
        "expression": expression,
        "layer_name": layer_name,
        "parser_ok": not expr.hasParserError(),
        "parser_error": expr.parserErrorString() if expr.hasParserError() else "",
        "referenced_columns": sorted(list(expr.referencedColumns())) if not expr.hasParserError() else [],
        "referenced_functions": sorted(list(expr.referencedFunctions())) if not expr.hasParserError() else [],
        "referenced_variables": sorted(list(expr.referencedVariables())) if not expr.hasParserError() else [],
        "needs_geometry": bool(expr.needsGeometry()) if not expr.hasParserError() else False,
        "missing_fields": [],
    }
    if layer_name and data["parser_ok"]:
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if not layers:
            return {
                "ok": False,
                "message": f"Layer was not found: {layer_name}",
                "error_type": "qgis_layer_error",
                "data": data,
            }
        fields = {field.name() for field in layers[0].fields()}
        referenced = {name for name in data["referenced_columns"] if not name.startswith("@")}
        data["available_fields"] = sorted(fields)
        data["missing_fields"] = sorted(referenced - fields)
    ok = data["parser_ok"] and not data.get("missing_fields")
    return {
        "ok": ok,
        "message": "Expression is valid." if ok else "Expression validation failed.",
        "error_type": "" if ok else "argument_error",
        "data": data,
        "suggestions": [] if ok else ["Search expression functions or inspect the layer fields before retrying."],
    }


def search_project_layers(query: str = "", limit: int = 20) -> Dict[str, Any]:
    from qgis.core import QgsMapLayerType, QgsProject, QgsWkbTypes

    tokens = _tokenize_query(query)
    limit = max(1, min(int(limit or 20), 100))
    matches = []
    for layer in QgsProject.instance().mapLayers().values():
        try:
            layer_type = "vector" if layer.type() == QgsMapLayerType.VectorLayer else "raster"
            fields = []
            geometry = ""
            if layer_type == "vector":
                fields = [field.name() for field in layer.fields()]
                geometry = QgsWkbTypes.displayString(layer.wkbType())
            haystack = " ".join([layer.name(), layer.id(), layer_type, geometry, " ".join(fields)]).lower()
            if tokens and not any(token.lower() in haystack for token in tokens):
                continue
            matches.append(
                {
                    "name": layer.name(),
                    "id": layer.id(),
                    "type": layer_type,
                    "geometry": geometry,
                    "crs": layer.crs().authid() if hasattr(layer, "crs") else "",
                    "field_count": len(fields),
                    "fields_preview": fields[:20],
                }
            )
            if len(matches) >= limit:
                break
        except RuntimeError:
            continue
    return {
        "ok": True,
        "message": f"Found {len(matches)} matching project layer(s).",
        "data": {"query": query, "matches": matches},
    }


def describe_project_layer(layer_name: str) -> Dict[str, Any]:
    from qgis.core import QgsMapLayerType, QgsProject, QgsWkbTypes

    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        layer = QgsProject.instance().mapLayer(layer_name)
        layers = [layer] if layer else []
    if not layers:
        return {
            "ok": False,
            "message": f"Layer was not found: {layer_name}",
            "error_type": "qgis_layer_error",
            "data": {"layer_name": layer_name},
        }
    layer = layers[0]
    layer_type = "vector" if layer.type() == QgsMapLayerType.VectorLayer else "raster"
    data = {
        "name": layer.name(),
        "id": layer.id(),
        "type": layer_type,
        "crs": layer.crs().authid() if hasattr(layer, "crs") else "",
        "source": layer.source(),
        "extent": layer.extent().toString(),
    }
    if layer_type == "vector":
        data["geometry"] = QgsWkbTypes.displayString(layer.wkbType())
        data["feature_count"] = int(layer.featureCount())
        data["fields"] = [
            {
                "name": field.name(),
                "type": field.typeName(),
                "length": field.length(),
                "precision": field.precision(),
            }
            for field in layer.fields()
        ]
    else:
        data["width"] = layer.width()
        data["height"] = layer.height()
        data["band_count"] = layer.bandCount()
    return {"ok": True, "message": f"Loaded layer details for {layer.name()}.", "data": data}


def search_layer_fields(layer_name: str, query: str = "", limit: int = 20) -> Dict[str, Any]:
    detail = describe_project_layer(layer_name)
    if not detail.get("ok"):
        return detail
    fields = detail.get("data", {}).get("fields", [])
    tokens = _tokenize_query(query)
    matches = []
    for field in fields:
        haystack = " ".join([field.get("name", ""), field.get("type", "")]).lower()
        if tokens and not any(token.lower() in haystack for token in tokens):
            continue
        matches.append(field)
        if len(matches) >= limit:
            break
    return {
        "ok": True,
        "message": f"Found {len(matches)} matching field(s) in layer {layer_name}.",
        "data": {"layer_name": layer_name, "query": query, "matches": matches},
    }


def validate_processing_algorithm_call(alg_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    from qgis.core import QgsApplication, QgsProcessingContext

    registry = QgsApplication.processingRegistry()
    alg = registry.algorithmById(alg_id)
    if not alg:
        suggestions = search_processing_algorithms(alg_id, limit=5).get("data", {}).get("matches", [])
        return {
            "ok": False,
            "message": f"Processing algorithm was not found: {alg_id}",
            "error_type": "processing_error",
            "data": {"alg_id": alg_id, "suggestions": suggestions},
            "suggestions": ["Call search_processing_algorithms and retry with a real alg_id."],
        }
    parameters = parameters or {}
    definitions = list(_safe_call(alg, "parameterDefinitions", []))
    valid_names = {str(_safe_call(param, "name", "")) for param in definitions}
    unknown = sorted(name for name in parameters.keys() if name not in valid_names)
    missing = []
    db = QgisCatalogDB()
    for param in definitions:
        name = str(_safe_call(param, "name", ""))
        if not name or name in parameters:
            continue
        if db._parameter_optional(param):
            continue
        default = _safe_call(param, "defaultValue", None)
        if default in (None, ""):
            missing.append(name)
    data = {
        "alg_id": alg_id,
        "unknown_parameters": unknown,
        "missing_required_parameters": missing,
        "valid_parameters": sorted(valid_names),
        "signature": describe_processing_algorithm(alg_id).get("data", {}),
    }
    if unknown or missing:
        return {
            "ok": False,
            "message": "Processing algorithm parameters failed signature validation.",
            "error_type": "processing_error",
            "data": data,
            "suggestions": ["Use describe_processing_algorithm to rebuild the parameters dictionary."],
        }
    try:
        context = QgsProcessingContext()
        ok = bool(alg.checkParameterValues(parameters, context))
        if not ok:
            return {
                "ok": False,
                "message": "QGIS rejected the processing parameter values.",
                "error_type": "processing_error",
                "data": data,
                "suggestions": ["Inspect layer names, parameter types, and enum values before retrying."],
            }
    except Exception as exc:
        data["qgis_check_error"] = str(exc)
    return {"ok": True, "message": "Processing algorithm call is valid.", "data": data}
