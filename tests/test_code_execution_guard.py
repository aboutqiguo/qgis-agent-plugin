import unittest

from qgis_agent_plugin.core.code_execution_guard import (
    MainThreadCodeRejected,
    MainThreadExecutionTimeout,
    analyze_main_thread_code,
    execute_main_thread_code,
)


class CodeExecutionGuardTests(unittest.TestCase):
    def test_short_bounded_qgis_style_code_is_allowed(self):
        code = "values = []\nfor i in range(5):\n    values.append(i * 2)"
        self.assertEqual([], analyze_main_thread_code(code))
        namespace = {}
        execute_main_thread_code(code, namespace, timeout_seconds=1)
        self.assertEqual([0, 2, 4, 6, 8], namespace["values"])
        listdir_code = "import os\nfor f in sorted(os.listdir('.')):\n    pass"
        self.assertEqual([], analyze_main_thread_code(listdir_code))

    def test_while_loop_is_rejected(self):
        findings = analyze_main_thread_code("while True:\n    pass")
        self.assertTrue(any("while loops" in finding.message for finding in findings))
        with self.assertRaises(MainThreadCodeRejected):
            execute_main_thread_code("while True:\n    pass", {}, timeout_seconds=1)

    def test_network_and_processing_calls_are_rejected(self):
        network = analyze_main_thread_code("import requests\nrequests.get('https://example.com')")
        processing = analyze_main_thread_code("import processing\nprocessing.run('native:buffer', {})")
        self.assertTrue(network)
        self.assertTrue(any("Processing" in finding.message for finding in processing))

    def test_large_literal_range_is_rejected(self):
        findings = analyze_main_thread_code("for i in range(1000001):\n    pass")
        self.assertTrue(any("iterations" in finding.message for finding in findings))

    def test_runtime_deadline_interrupts_non_while_infinite_iterator(self):
        code = "limit = int('999999999')\nfor _ in range(limit):\n    value = 1"
        with self.assertRaises(MainThreadExecutionTimeout):
            execute_main_thread_code(code, {}, timeout_seconds=0.02)

    def test_aliases_and_unknown_iterator_materialization_are_rejected(self):
        aliased_processing = analyze_main_thread_code(
            "import processing as p\np.run('native:buffer', {})"
        )
        materialization = analyze_main_thread_code("features = list(layer.getFeatures())")
        sentinel = analyze_main_thread_code("for value in iter(int, 1):\n    pass")
        self.assertTrue(aliased_processing)
        self.assertTrue(any("unknown-size iterator" in finding.message for finding in materialization))
        self.assertTrue(any("sentinel loop" in finding.message for finding in sentinel))


if __name__ == "__main__":
    unittest.main()
