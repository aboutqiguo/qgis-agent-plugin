# -*- coding: utf-8 -*-
"""Verification test: Ensure current version can execute the exact code from agent_run.log."""

import os
import unittest
from qgis_agent_plugin.core.code_execution_guard import analyze_main_thread_code

class AgentRunLogCompatibilityTest(unittest.TestCase):
    def test_log_snippet_1_folder_exploration(self):
        """Line 54-81 in agent_run.log: explore folder using sorted(items)."""
        code = '''
import os
folder = r"D:\\txy1\\NDVI_07_11"
if not os.path.exists(folder):
    pass
else:
    items = os.listdir(folder)
    for f in sorted(items):
        fpath = os.path.join(folder, f)
        if os.path.isfile(fpath):
            pass
'''
        findings = analyze_main_thread_code(code)
        # Must not have any blocking findings!
        self.assertEqual([], findings, f"Unexpected findings: {findings}")

    def test_log_snippet_2_read_hdrs(self):
        """Line 115-129 in agent_run.log: parse HDR headers."""
        code = '''
import os
folder = r"D:\\txy1\\NDVI_07_11"
hdr_files = [f for f in os.listdir(folder) if f.upper().endswith('.HDR') or f.endswith('.hdr')]
for hdr in sorted(hdr_files):
    hdr_path = os.path.join(folder, hdr)
'''
        findings = analyze_main_thread_code(code)
        self.assertEqual([], findings)

    def test_log_snippet_3_pixel_sampling_and_plotting(self):
        """Line 960-1050 in agent_run.log: numpy sampling and matplotlib plotting."""
        code = '''
import os
import random
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

years_list = [2007, 2008, 2009, 2010, 2011]
pixel_values = [[0.2, 0.35, 0.42, 0.38, 0.45], [0.15, 0.28, 0.33, 0.31, 0.36]]

for pi in range(2):
    fig = plt.figure(figsize=(10, 6))
    plt.plot(years_list, pixel_values[pi], 'o-', label=f"Pixel {pi+1}")
    plt.axhline(y=0.3, color='r', linestyle='--', label="Threshold 0.3")
    plt.close(fig)
'''
        findings = analyze_main_thread_code(code)
        self.assertEqual([], findings)

if __name__ == "__main__":
    unittest.main()
