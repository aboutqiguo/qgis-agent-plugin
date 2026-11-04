import os
import json
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


def _install_qgis_import_stubs():
    qgis_module = sys.modules.setdefault("qgis", types.ModuleType("qgis"))
    core_module = sys.modules.setdefault("qgis.core", types.ModuleType("qgis.core"))
    for name in (
        "QgsProject",
        "QgsMapLayerType",
        "QgsVectorLayer",
        "QgsRasterLayer",
        "QgsExpression",
        "Qgis",
    ):
        if not hasattr(core_module, name):
            setattr(core_module, name, type(name, (), {}))
    qgis_module.core = core_module
    sys.modules.setdefault("processing", types.ModuleType("processing"))


_install_qgis_import_stubs()

from qgis_agent_plugin.core.approval_policy import ToolApprovalPolicy  # noqa: E402
from qgis_agent_plugin.core.request_profile import frozen_tool_names  # noqa: E402
from qgis_agent_plugin.core.tool_registry import (  # noqa: E402
    build_all_tool_openai_schemas,
    get_atomic_tool_names,
    get_tool_spec,
    validate_registry_health,
)
from qgis_agent_plugin.core.user_tool_extensions import (  # noqa: E402
    create_or_update_user_tool,
    execute_user_tool,
    get_registered_user_tool_domains,
    get_user_tool,
    list_user_tools,
    register_user_tool,
)
from qgis_agent_plugin.core.validators import validate_tool_call  # noqa: E402
from qgis_agent_plugin.tools.tools import execute_atomic_tool_structured  # noqa: E402


PARAMETERS_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
}
SOURCE_CODE = '''def run(iface, arguments):
    return {
        "ok": True,
        "message": "candidate passed",
        "data": {"value": arguments["value"]},
        "artifacts": [],
        "warnings": [],
    }
'''


class UserToolExtensionTests(unittest.TestCase):
    def test_candidate_must_succeed_before_registration_and_then_is_visible(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ, {"QGIS_AGENT_USER_TOOL_ROOT": root}, clear=False
        ):
            created = create_or_update_user_tool(
                "user_echo_value",
                "Return a supplied value for a controlled user-tool test.",
                PARAMETERS_SCHEMA,
                SOURCE_CODE,
                domains=["processing"],
            )
            self.assertTrue(created["ok"], created)
            self.assertEqual("candidate", get_user_tool("user_echo_value")["status"])

            premature = register_user_tool("user_echo_value", "not tested")
            self.assertFalse(premature["ok"])
            self.assertEqual("verification_required", premature["error_type"])

            executed = execute_user_tool("user_echo_value", None, {"value": "verified"})
            self.assertTrue(executed["ok"], executed)
            self.assertEqual("verified", executed["data"]["value"])

            registered = register_user_tool("user_echo_value", "Returned the provided value with ok=true.")
            self.assertTrue(registered["ok"], registered)
            definition = get_user_tool("user_echo_value", include_candidates=False)
            self.assertEqual("registered", definition["status"])
            self.assertEqual(1, definition["success_count"])

            updated = create_or_update_user_tool(
                "user_echo_value",
                "Return a supplied value after a candidate source update.",
                PARAMETERS_SCHEMA,
                SOURCE_CODE,
                domains=["processing"],
            )
            self.assertTrue(updated["ok"], updated)
            reset_definition = get_user_tool("user_echo_value")
            self.assertEqual("candidate", reset_definition["status"])
            self.assertEqual(0, reset_definition["success_count"])
            self.assertFalse(register_user_tool("user_echo_value", "old test must not be reused")["ok"])

            self.assertTrue(execute_user_tool("user_echo_value", None, {"value": "verified again"})["ok"])
            self.assertTrue(register_user_tool("user_echo_value", "Retested after the source update.")["ok"])

            domains = get_registered_user_tool_domains()
            self.assertEqual(["processing"], domains["user_echo_value"])
            available = {item["function"]["name"] for item in build_all_tool_openai_schemas()}
            self.assertIn("user_echo_value", available)
            self.assertIn("user_echo_value", get_atomic_tool_names())
            self.assertEqual("high", get_tool_spec("user_echo_value").risk_level)
            self.assertTrue(validate_registry_health()["ok"])

    def test_registered_tool_only_joins_matching_future_domain_pack(self):
        available = {
            "ask_human",
            "execute_pyqgis_script",
            "create_or_update_user_tool",
            "run_user_tool_extension",
            "register_user_tool_extension",
            "list_user_tool_extensions",
            "summarize_layers",
            "validate_project_outputs",
            "save_project_and_verify",
            "search_project_layers",
            "describe_project_layer",
            "user_echo_value",
        }
        mapping = {"user_echo_value": ["processing"]}
        processing_pack = frozen_tool_names(
            "对栅格进行波段计算",
            available,
            user_tool_domains=mapping,
        )
        osm_pack = frozen_tool_names("下载 OSM 建筑", available, user_tool_domains=mapping)
        self.assertIn("execute_pyqgis_script", processing_pack)
        self.assertIn("run_user_tool_extension", processing_pack)
        self.assertIn("user_echo_value", processing_pack)
        self.assertNotIn("user_echo_value", osm_pack)

    def test_invalid_source_is_rejected_before_it_is_written(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ, {"QGIS_AGENT_USER_TOOL_ROOT": root}, clear=False
        ):
            result = create_or_update_user_tool(
                "user_unsafe_test",
                "Attempt to run an external process and should be rejected.",
                PARAMETERS_SCHEMA,
                "def run(iface, arguments):\n    import subprocess\n    return subprocess.run(['x'])\n",
            )
            self.assertFalse(result["ok"])
            self.assertIn("subprocess is not allowed", " ".join(result["data"]["errors"]))
            self.assertEqual([], list_user_tools())

    def test_creation_and_execution_always_require_high_risk_approval(self):
        create_decision = ToolApprovalPolicy().evaluate(
            "create_or_update_user_tool",
            {"source_code": SOURCE_CODE},
        )
        run_decision = ToolApprovalPolicy().evaluate(
            "run_user_tool_extension",
            {"tool_name": "user_echo_value"},
        )
        self.assertTrue(create_decision.requires_approval)
        self.assertTrue(run_decision.requires_approval)
        self.assertIn("run(iface, arguments)", create_decision.approval_prompt)

    def test_tool_call_validation_requires_user_tool_contract(self):
        valid = validate_tool_call("create_or_update_user_tool", {
            "tool_name": "user_echo_value",
            "description": "Return a supplied value for a controlled user-tool test.",
            "parameters_schema": PARAMETERS_SCHEMA,
            "source_code": SOURCE_CODE,
            "domains": ["processing"],
        })
        invalid = validate_tool_call("run_user_tool_extension", {"tool_name": "not_a_user_tool"})
        self.assertTrue(valid.ok, valid.to_dict())
        self.assertFalse(invalid.ok)

    def test_atomic_dispatch_supports_candidate_test_and_registered_name(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ, {"QGIS_AGENT_USER_TOOL_ROOT": root}, clear=False
        ):
            created = json.loads(execute_atomic_tool_structured(None, "create_or_update_user_tool", {
                "tool_name": "user_direct_echo",
                "description": "Return a supplied value through the atomic dispatch path.",
                "parameters_schema": PARAMETERS_SCHEMA,
                "source_code": SOURCE_CODE,
                "domains": ["general"],
            }))
            self.assertTrue(created["ok"], created)
            tested = json.loads(execute_atomic_tool_structured(None, "run_user_tool_extension", {
                "tool_name": "user_direct_echo",
                "arguments": {"value": "candidate"},
            }))
            self.assertTrue(tested["ok"], tested)
            registered = json.loads(execute_atomic_tool_structured(None, "register_user_tool_extension", {
                "tool_name": "user_direct_echo",
                "verification_summary": "Atomic candidate run returned the requested value.",
            }))
            self.assertTrue(registered["ok"], registered)
            direct = json.loads(execute_atomic_tool_structured(None, "user_direct_echo", {"value": "registered"}))
            self.assertTrue(direct["ok"], direct)
            self.assertEqual("registered", direct["data"]["value"])


if __name__ == "__main__":
    unittest.main()
