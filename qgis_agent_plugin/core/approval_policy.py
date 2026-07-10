import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


DESTRUCTIVE_CODE_PATTERNS = [
    r"\bos\.remove\s*\(",
    r"\bos\.unlink\s*\(",
    r"\bos\.rmdir\s*\(",
    r"\bshutil\.rmtree\s*\(",
    r"\bPath\s*\([^)]*\)\.unlink\s*\(",
    r"\bPath\s*\([^)]*\)\.rmdir\s*\(",
    r"\bremoveMapLayer\s*\(",
    r"\bremoveAllMapLayers\s*\(",
    r"\bdeleteFeature\s*\(",
    r"\bdeleteFeatures\s*\(",
    r"\bDROP\s+TABLE\b",
    r"\bDELETE\s+FROM\b",
    r"\bopen\s*\([^)]*,\s*['\"][wa]\b",
    r"\bQgsVectorFileWriter\b",
    r"\bQgsRasterFileWriter\b",
    r"\bwriteAsVectorFormat",
]

NETWORK_CODE_PATTERNS = [
    r"\brequests\.(get|post|put|delete|patch)\s*\(",
    r"\burllib\.request\b",
    r"\bhttpx\.(get|post|put|delete|patch)\s*\(",
    r"\baiohttp\b",
]

SUBPROCESS_CODE_PATTERNS = [
    r"\bsubprocess\.(run|Popen|call|check_call|check_output)\s*\(",
    r"\bos\.system\s*\(",
]

PACKAGE_INSTALL_CODE_PATTERNS = [
    r"\bpip_main\s*\(",
    r"\bpip\._internal\b",
    r"python\s+-m\s+pip",
    r"\bpip\s+install\b",
]


@dataclass
class ApprovalDecision:
    requires_approval: bool
    risk_level: str
    reason: str
    approval_prompt: str = ""
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requires_approval": self.requires_approval,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "approval_prompt": self.approval_prompt,
            "warnings": self.warnings,
        }


class ToolApprovalPolicy:
    def __init__(self, plugin_dir: str = ""):
        self.plugin_dir = plugin_dir

    def evaluate(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ApprovalDecision:
        from .tool_registry import get_tool_spec

        args = args or {}
        context = context or {}
        spec = get_tool_spec(tool_name)
        risk_level = spec.risk_level if spec else "high"
        warnings: List[str] = []

        if spec is None:
            return self._decision(
                True,
                "high",
                f"Tool is not registered: {tool_name}",
                tool_name,
                args,
                warnings,
            )

        if tool_name == "execute_pyqgis_script":
            code = args.get("code", "") or context.get("code", "")
            code_risk_reason = self.code_risk_reason(code, bool(args.get("is_destructive")))
            if code_risk_reason:
                return self._decision(
                    True,
                    "high",
                    code_risk_reason,
                    tool_name,
                    args,
                    warnings,
                    preview=code,
                )
            return ApprovalDecision(False, risk_level, "Script did not match destructive patterns.", warnings=warnings)

        if tool_name in {"write_file", "replace_file_content"}:
            file_path = context.get("resolved_file_path") or args.get("file_path", "")
            file_exists = bool(context.get("file_exists", False))
            managed_file = bool(context.get("managed_file", False))
            if file_exists and not managed_file:
                return self._decision(
                    True,
                    "high",
                    "The tool will modify an existing file that is not one of the agent-managed memory/task files.",
                    tool_name,
                    args,
                    warnings,
                    file_path=file_path,
                    preview=context.get("preview", args.get("content", "")),
                )
            return ApprovalDecision(False, risk_level, "File operation is within managed or newly-created path.", warnings=warnings)

        if risk_level == "high":
            return self._decision(
                True,
                "high",
                f"Tool is marked high risk in registry: {tool_name}.",
                tool_name,
                args,
                warnings,
            )

        return ApprovalDecision(False, risk_level, f"Tool risk is {risk_level}; no approval required.", warnings=warnings)

    def is_destructive_code(self, code: str) -> bool:
        return self._matches_any(code, DESTRUCTIVE_CODE_PATTERNS)

    def code_risk_reason(self, code: str, is_destructive: bool = False) -> str:
        if is_destructive:
            return "The script is explicitly marked destructive."
        if self._matches_any(code, DESTRUCTIVE_CODE_PATTERNS):
            return "The script may delete, overwrite, or modify project data/files."
        if self._matches_any(code, SUBPROCESS_CODE_PATTERNS):
            return "The script launches external processes, which can modify the environment or hang QGIS."
        if self._matches_any(code, PACKAGE_INSTALL_CODE_PATTERNS):
            return "The script attempts package installation instead of using the controlled install tool."
        if self._matches_any(code, NETWORK_CODE_PATTERNS):
            return "The script performs network access and may send data to external services."
        return ""

    def _matches_any(self, code: str, patterns: List[str]) -> bool:
        if not code:
            return False
        for pattern in patterns:
            if re.search(pattern, code, flags=re.IGNORECASE):
                return True
        return False

    def _decision(
        self,
        requires_approval: bool,
        risk_level: str,
        reason: str,
        tool_name: str,
        args: Dict[str, Any],
        warnings: List[str],
        file_path: str = "",
        preview: str = "",
    ) -> ApprovalDecision:
        prompt = self._build_prompt(tool_name, risk_level, reason, args, file_path, preview)
        return ApprovalDecision(requires_approval, risk_level, reason, prompt, warnings)

    def _build_prompt(
        self,
        tool_name: str,
        risk_level: str,
        reason: str,
        args: Dict[str, Any],
        file_path: str = "",
        preview: str = "",
    ) -> str:
        safe_args = dict(args or {})
        if "content" in safe_args:
            safe_args["content"] = self._shorten(str(safe_args["content"]))
        if "python_code" in safe_args:
            safe_args["python_code"] = self._shorten(str(safe_args["python_code"]))
        if "code" in safe_args:
            safe_args["code"] = self._shorten(str(safe_args["code"]))

        parts = [
            "QGIS Agent requests approval for a high-risk operation.",
            "",
            f"Tool: {tool_name}",
            f"Risk: {risk_level}",
            f"Reason: {reason}",
        ]
        if file_path:
            parts.append(f"Target file: {os.path.abspath(file_path)}")
        parts.extend(["", "Arguments:", str(safe_args)])
        if preview:
            parts.extend(["", "Preview:", self._shorten(str(preview), 4000)])
        parts.append("")
        parts.append("Approve only if this operation is expected.")
        return "\n".join(parts)

    def _shorten(self, value: str, limit: int = 1200) -> str:
        if len(value) <= limit:
            return value
        return value[:limit] + f"\n...[truncated {len(value) - limit} chars]..."
