"""Preflight and runtime guards for approved code executed on the QGIS main thread."""

from __future__ import annotations

import ast
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_MAIN_THREAD_TIMEOUT_SECONDS = 20.0
MAX_CODE_AST_NODES = 4000
MAX_CODE_CHARACTERS = 60000
MAX_LITERAL_RANGE = 100000


class MainThreadCodeRejected(RuntimeError):
    pass


class MainThreadExecutionTimeout(RuntimeError):
    pass


@dataclass(frozen=True)
class CodeGuardFinding:
    message: str
    suggestion: str
    line: int = 0


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _literal_int(node: ast.AST) -> Optional[int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
    ):
        value = int(node.operand.value)
        return -value if isinstance(node.op, ast.USub) else value
    return None


def _literal_range_size(node: ast.AST) -> Optional[int]:
    if not isinstance(node, ast.Call) or _qualified_name(node.func) != "range" or not node.args:
        return None
    literal_values = [_literal_int(arg) for arg in node.args[:3]]
    if not all(value is not None for value in literal_values):
        return None
    if len(literal_values) == 1:
        return max(0, literal_values[0])
    start, stop = literal_values[:2]
    step = literal_values[2] if len(literal_values) > 2 else 1
    if step == 0:
        return MAX_LITERAL_RANGE + 1
    distance = stop - start
    if (distance > 0 and step < 0) or (distance < 0 and step > 0):
        return 0
    return max(0, (abs(distance) + abs(step) - 1) // abs(step))


def _blocked_call_reason(name: str) -> Optional[CodeGuardFinding]:
    lowered = (name or "").lower()
    if not lowered:
        return None
    if lowered in {"sleep", "time.sleep"} or lowered.endswith(".sleep"):
        return CodeGuardFinding(
            "Blocking sleep calls are not allowed on the QGIS main thread.",
            "Use a registered asynchronous workflow or QgsTask instead.",
        )
    if lowered in {
        "exec",
        "eval",
        "compile",
        "__import__",
        "builtins.exec",
        "builtins.eval",
        "builtins.compile",
        "builtins.__import__",
        "__builtins__.exec",
        "__builtins__.eval",
        "__builtins__.compile",
        "__builtins__.__import__",
        "importlib.import_module",
    }:
        return CodeGuardFinding(
            "Dynamic code evaluation is not allowed inside approved PyQGIS scripts.",
            "Put the complete, reviewable code directly in the tool call.",
        )
    if lowered in {"sys.settrace", "threading.settrace"}:
        return CodeGuardFinding(
            "The script may not replace the execution deadline tracer.",
            "Remove settrace calls.",
        )
    if lowered.startswith(("subprocess.", "requests.", "httpx.", "aiohttp.", "urllib.request.", "ctypes.")):
        return CodeGuardFinding(
            "Synchronous process, native FFI, or network calls are not allowed in main-thread PyQGIS scripts.",
            "Use a registered network/data-source tool or a cancellable background workflow.",
        )
    if lowered in {
        "os.system",
        "os.popen",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "os.execl",
        "os.execle",
        "os.execlp",
        "os.execlpe",
        "os.execv",
        "os.execve",
        "os.execvp",
        "os.execvpe",
    }:
        return CodeGuardFinding(
            "External process execution is not allowed in PyQGIS scripts.",
            "Use a registered tool instead.",
        )
    if lowered in {
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.removedirs",
        "shutil.rmtree",
        "pathlib.path.unlink",
        "pathlib.path.rmdir",
    } or lowered.endswith((".rmtree", ".removedirs")):
        return CodeGuardFinding(
            "Destructive filesystem deletion is not allowed in main-thread PyQGIS scripts.",
            "Write outputs to a new file path instead of deleting existing files or directories.",
        )
    if lowered in {"processing.run", "processing.runandloadresults"}:
        return CodeGuardFinding(
            "QGIS Processing must not run through the arbitrary main-thread code fallback.",
            "Use run_processing_algorithm so progress, cancellation, validation, and artifacts remain available.",
        )
    if lowered in {"getinfo", "getdownloadurl"} or lowered.endswith((".getinfo", ".getdownloadurl")):
        return CodeGuardFinding(
            "Synchronous Earth Engine requests are not allowed in main-thread PyQGIS scripts.",
            "Use a registered GEE workflow so cloud work and local download remain cancellable.",
        )
    if lowered.endswith((".waitforfinished", ".waitforexit", ".wait")):
        return CodeGuardFinding(
            "Blocking wait calls are not allowed on the QGIS main thread.",
            "Use signals, a registered workflow, or QgsTask completion callbacks.",
        )
    if lowered.endswith((".exec_", ".exec")):
        return CodeGuardFinding(
            "Nested Qt event loops are not allowed in approved PyQGIS scripts.",
            "Use the Agent approval/input tools for modal interaction.",
        )
    return None


def analyze_main_thread_code(code: str) -> List[CodeGuardFinding]:
    try:
        tree = ast.parse(code or "")
    except SyntaxError as exc:
        return [CodeGuardFinding(f"Python syntax error: {exc.msg}", "Fix the script before execution.", exc.lineno or 0)]

    findings: List[CodeGuardFinding] = []
    if len(code or "") > MAX_CODE_CHARACTERS:
        findings.append(CodeGuardFinding(
            f"The script exceeds the {MAX_CODE_CHARACTERS}-character main-thread limit.",
            "Create a registered, testable tool instead of submitting a large one-off script.",
        ))
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_CODE_AST_NODES:
        findings.append(CodeGuardFinding(
            f"The script is too complex for main-thread fallback execution ({len(nodes)} AST nodes).",
            "Split the capability into a registered tool or a cancellable workflow.",
        ))

    blocked_modules = {
        "aiohttp", "ctypes", "ee", "httpx", "importlib", "multiprocessing", "processing", "pty", "requests", "socket", "subprocess", "urllib"
    }
    for node in nodes:
        if isinstance(node, ast.While):
            findings.append(CodeGuardFinding(
                "while loops are blocked in main-thread PyQGIS scripts because their termination cannot be proven.",
                "Use a bounded for loop or move polling into a registered asynchronous workflow.",
                getattr(node, "lineno", 0),
            ))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0].lower()
                if root in blocked_modules:
                    findings.append(CodeGuardFinding(
                        f"Module '{root}' is not allowed in main-thread PyQGIS scripts.",
                        "Use a registered network or background tool.",
                        getattr(node, "lineno", 0),
                    ))
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0].lower()
            if root in blocked_modules or root == "urllib":
                findings.append(CodeGuardFinding(
                    f"Module '{root}' is not allowed in main-thread PyQGIS scripts.",
                    "Use a registered network or background tool.",
                    getattr(node, "lineno", 0),
                ))
        elif isinstance(node, ast.Call):
            name = _qualified_name(node.func)
            reason = _blocked_call_reason(name)
            if reason:
                findings.append(CodeGuardFinding(reason.message, reason.suggestion, getattr(node, "lineno", 0)))
            if name == "getattr" and node.args:
                target_name = _qualified_name(node.args[0])
                if target_name in {"__builtins__", "builtins"}:
                    findings.append(CodeGuardFinding(
                        "Dynamic builtin lookup via getattr(__builtins__, ...) is not allowed in PyQGIS scripts.",
                        "Use standard, reviewable Python constructs directly.",
                        getattr(node, "lineno", 0),
                    ))
            if name == "iter" and len(node.args) == 2:
                findings.append(CodeGuardFinding(
                    "Two-argument iter() can create a non-terminating sentinel loop on the QGIS main thread.",
                    "Use a statically bounded iterator or a registered background tool.",
                    getattr(node, "lineno", 0),
                ))
            if name in {"itertools.count", "itertools.cycle"}:
                findings.append(CodeGuardFinding(
                    f"{name}() creates an unbounded iterator on the QGIS main thread.",
                    "Use a bounded range or a cancellable background tool.",
                    getattr(node, "lineno", 0),
                ))
            if name in {"list", "tuple", "set", "sorted", "sum", "min", "max", "any", "all"} and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.GeneratorExp):
                    findings.append(CodeGuardFinding(
                        f"{name}() may synchronously consume an unknown-size generator on the QGIS main thread.",
                        "Iterate in a bounded for loop or use a registered inspection/processing tool.",
                        getattr(node, "lineno", 0),
                    ))
                elif isinstance(arg0, ast.Call):
                    called_name = _qualified_name(arg0.func).lower()
                    if any(term in called_name for term in ("getfeatures", "features")):
                        findings.append(CodeGuardFinding(
                            f"{name}() may synchronously consume an unknown-size iterator on the QGIS main thread.",
                            "Use layer.getFeatures(QgsFeatureRequest().setLimit(...)) or inspect in small chunks.",
                            getattr(node, "lineno", 0),
                        ))
                    elif called_name == "range":
                        bounded_size = _literal_range_size(arg0)
                        if bounded_size is None or bounded_size > MAX_LITERAL_RANGE:
                            findings.append(CodeGuardFinding(
                                f"{name}() consumes a large range on the QGIS main thread.",
                                "Iterate in a bounded for loop.",
                                getattr(node, "lineno", 0),
                            ))
            if name == "range" and node.args:
                estimated = _literal_range_size(node)
                if estimated is not None and estimated > MAX_LITERAL_RANGE:
                    findings.append(CodeGuardFinding(
                        f"Literal range may execute about {estimated} iterations on the QGIS main thread.",
                        "Use a registered tool, QgsTask, or process the data in bounded chunks.",
                        getattr(node, "lineno", 0),
                    ))

    deduped: List[CodeGuardFinding] = []
    seen = set()
    for finding in findings:
        key = (finding.message, finding.line)
        if key not in seen:
            seen.add(key)
            deduped.append(finding)
    return deduped


def ensure_main_thread_code_safe(code: str) -> None:
    findings = analyze_main_thread_code(code)
    if not findings:
        return
    details = "; ".join(
        f"line {finding.line}: {finding.message}" if finding.line else finding.message
        for finding in findings[:8]
    )
    raise MainThreadCodeRejected(details)


@contextmanager
def execution_deadline(
    timeout_seconds: float = DEFAULT_MAIN_THREAD_TIMEOUT_SECONDS,
    cancel_callback=None,
) -> Iterable[None]:
    timeout = max(0.1, float(timeout_seconds))
    deadline = time.monotonic() + timeout
    previous_trace = sys.gettrace()

    def tracer(frame, event, arg):
        if cancel_callback and cancel_callback():
            raise MainThreadExecutionTimeout("PyQGIS execution was cancelled.")
        if time.monotonic() >= deadline:
            raise MainThreadExecutionTimeout(
                f"PyQGIS main-thread execution exceeded {timeout:g} seconds and was interrupted."
            )
        return tracer

    sys.settrace(tracer)
    try:
        yield
    finally:
        sys.settrace(previous_trace)


# ---------------------------------------------------------------------------
# GDAL/OGR temporary-dataset auto-fix
# ---------------------------------------------------------------------------
# In SWIG-wrapped GDAL, ``gdal.Open(p).GetRasterBand(1).ReadAsArray()`` crashes
# with "in method 'Band_XSize_get', argument 1 of type 'GDALRasterBandShadow *'"
# because the temporary Dataset is garbage-collected before the band is used.
# Models write this pattern constantly (4 failures in one session), so we wrap
# only the *chained temporary* opener call in a keep-alive helper. Code that
# assigns the dataset to a variable is untouched, so write/flush semantics of
# ``ds = None`` stay exactly as the author intended.

GDAL_KEEPALIVE_HELPER = "_qgis_agent_keep"
_GDAL_OPENER_CALLS = {
    "gdal.Open", "gdal.OpenEx", "gdal.OpenShared", "ogr.Open", "ogr.OpenShared",
    "gdal.Warp", "gdal.Translate", "gdal.BuildVRT",
    "osgeo.gdal.Open", "osgeo.gdal.OpenEx", "osgeo.ogr.Open",
}
_GDAL_CHILD_ACCESSORS = {
    "GetRasterBand", "GetLayer", "GetLayerByName", "GetLayerByIndex",
    "ReadAsArray", "GetGeoTransform", "GetProjection",
}


def _char_span(code_lines: List[str], line_offsets: List[int], node: ast.AST):
    start_line = code_lines[node.lineno - 1]
    end_line = code_lines[node.end_lineno - 1]
    start_col = len(start_line.encode("utf-8")[: node.col_offset].decode("utf-8", errors="ignore"))
    end_col = len(end_line.encode("utf-8")[: node.end_col_offset].decode("utf-8", errors="ignore"))
    return line_offsets[node.lineno - 1] + start_col, line_offsets[node.end_lineno - 1] + end_col


def autofix_gdal_temporary_datasets(code: str):
    """Wrap chained temporary GDAL/OGR datasets in a keep-alive helper.

    Returns ``(fixed_code, fix_count)``. Line numbers are preserved because the
    helper is inserted inline, so tracebacks still point at the author's lines.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, 0
    targets = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _GDAL_CHILD_ACCESSORS:
            continue
        inner = node.func.value
        if isinstance(inner, ast.Call) and _qualified_name(inner.func) in _GDAL_OPENER_CALLS:
            if getattr(inner, "end_lineno", None) is None:
                continue
            targets.append(inner)
    if not targets:
        return code, 0
    lines = code.splitlines(True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    spans = sorted({_char_span(lines, offsets, node) for node in targets}, reverse=True)
    fixed = code
    for start, end in spans:
        fixed = fixed[:start] + GDAL_KEEPALIVE_HELPER + "(" + fixed[start:end] + ")" + fixed[end:]
    return fixed, len(spans)


BLOCKED_RUNTIME_MODULES = frozenset({
    "aiohttp",
    "ctypes",
    "ee",
    "httpx",
    "importlib",
    "multiprocessing",
    "processing",
    "pty",
    "requests",
    "socket",
    "subprocess",
    "urllib",
})


def build_restricted_builtins() -> Dict[str, Any]:
    import builtins as _builtins

    real_import = _builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = str(name or "").split(".", 1)[0].lower()
        if root in BLOCKED_RUNTIME_MODULES:
            raise MainThreadCodeRejected(
                f"Module '{root}' is blocked at runtime in main-thread PyQGIS scripts."
            )
        return real_import(name, globals, locals, fromlist, level)

    safe_builtins = dict(_builtins.__dict__)
    for forbidden in ("eval", "exec", "compile", "breakpoint", "input"):
        safe_builtins.pop(forbidden, None)
    safe_builtins["__import__"] = _guarded_import
    return safe_builtins


def execute_main_thread_code(
    code: str,
    globals_dict: Dict[str, Any],
    *,
    timeout_seconds: float = DEFAULT_MAIN_THREAD_TIMEOUT_SECONDS,
    cancel_callback=None,
) -> None:
    ensure_main_thread_code_safe(code)
    code, _fix_count = autofix_gdal_temporary_datasets(code)
    keepalive: List[Any] = []

    def _keep(dataset):
        keepalive.append(dataset)
        return dataset

    globals_dict["__builtins__"] = build_restricted_builtins()
    globals_dict[GDAL_KEEPALIVE_HELPER] = _keep
    compiled = compile(code, "<qgis-agent-approved-code>", "exec")
    try:
        with execution_deadline(timeout_seconds, cancel_callback=cancel_callback):
            exec(compiled, globals_dict, globals_dict)
    finally:
        # Release kept datasets so GDAL closes file handles (avoids Windows locks).
        keepalive.clear()
