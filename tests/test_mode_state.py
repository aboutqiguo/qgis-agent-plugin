import unittest

from qgis_agent_plugin.core.mode_state import (
    is_continuation_message,
    should_resume_approved_plan,
)


class ModeStateTests(unittest.TestCase):
    def test_continuation_message_is_detected(self):
        self.assertTrue(is_continuation_message("按照任务继续"))
        self.assertTrue(is_continuation_message("Continue the current task"))
        self.assertFalse(is_continuation_message("下载新的行政边界"))

    def test_only_incomplete_approved_plan_is_resumed(self):
        self.assertTrue(should_resume_approved_plan("继续", "PLAN", True, True))
        self.assertFalse(should_resume_approved_plan("继续", "WORK", True, True))
        self.assertFalse(should_resume_approved_plan("继续", "PLAN", False, True))
        self.assertFalse(should_resume_approved_plan("新任务", "PLAN", True, True))


if __name__ == "__main__":
    unittest.main()
