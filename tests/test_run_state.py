import unittest

from qgis_agent_plugin.core.run_state import (
    AWAITING_INPUT,
    AWAITING_APPROVAL,
    AWAITING_MANUAL_DOWNLOAD,
    CANCELLED,
    FAILED,
    FINAL_STATES,
    PARTIAL,
    SUCCEEDED,
    derive_run_outcome,
)
from qgis_agent_plugin.core.task_state import (
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_PENDING,
    TaskPlan,
    TaskStep,
)


class RunStateTests(unittest.TestCase):
    def test_special_failures_do_not_become_generic_success(self):
        manual = derive_run_outcome(last_tool_ok=False, last_failure_type="manual_download_required")
        missing = derive_run_outcome(last_tool_ok=False, last_failure_type="missing_user_parameters")
        denied = derive_run_outcome(last_tool_ok=False, last_failure_type="permission_error")
        approval = derive_run_outcome(last_tool_ok=False, last_failure_type="approval_required")
        self.assertEqual(AWAITING_MANUAL_DOWNLOAD, manual.status)
        self.assertEqual(AWAITING_INPUT, missing.status)
        self.assertEqual(CANCELLED, denied.status)
        self.assertEqual(AWAITING_APPROVAL, approval.status)
        self.assertTrue({manual.status, missing.status, denied.status, approval.status}.issubset(FINAL_STATES))

    def test_plan_requires_all_steps_to_pass(self):
        complete = TaskPlan("x", [TaskStep("1", "a", status=STATUS_PASSED)])
        pending = TaskPlan(
            "x",
            [TaskStep("1", "a", status=STATUS_PASSED), TaskStep("2", "b", status=STATUS_PENDING)],
        )
        failed = TaskPlan(
            "x",
            [TaskStep("1", "a", status=STATUS_PASSED), TaskStep("2", "b", status=STATUS_FAILED)],
        )
        self.assertEqual(SUCCEEDED, derive_run_outcome(plan=complete).status)
        self.assertEqual(PARTIAL, derive_run_outcome(plan=pending).status)
        self.assertEqual(PARTIAL, derive_run_outcome(plan=failed).status)

    def test_failed_last_tool_is_failed(self):
        outcome = derive_run_outcome(tool_failure_count=1, last_tool_ok=False)
        self.assertEqual(FAILED, outcome.status)
        self.assertFalse(outcome.ok)


if __name__ == "__main__":
    unittest.main()
