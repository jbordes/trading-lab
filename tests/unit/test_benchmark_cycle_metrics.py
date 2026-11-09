from __future__ import annotations

import unittest

from scripts.benchmark_cycle_metrics import _measure


class CycleMetricsBenchmarkTest(unittest.TestCase):
    def test_synthetic_provider_benchmark_covers_every_page(self) -> None:
        result = _measure(count=101, magic_count=3, repeats=1)

        self.assertEqual(result["cycles"], 101)
        self.assertEqual(result["magics"], 3)
        self.assertEqual(result["pages"], 2)
        self.assertGreaterEqual(result["provider_peak_kib"], 0)


if __name__ == "__main__":
    unittest.main()
