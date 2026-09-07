from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import benchmark_event_log as bench


class BenchmarkEventLogTests(unittest.TestCase):
    def test_generator_reaches_target_and_has_valid_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.lgp"
            records = bench.write_synthetic_lgp(path, bench.SOURCE_GUID, 32 * 1024)
            self.assertGreater(records, 1)
            self.assertGreaterEqual(path.stat().st_size, 32 * 1024)
            text = path.read_text(encoding="utf-8-sig")
            self.assertTrue(text.startswith("1CV8LOG(ver 2.0)\n"))
            self.assertIn(bench.SOURCE_GUID, text[:100])
            self.assertFalse(text.rstrip().endswith(","))

    def test_small_attach_benchmark_reports_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = bench.benchmark(
                sizes=[0.03],
                scenarios=["remap"],
                modes=["attach"],
                repeat=1,
                work_dir=Path(tmp),
            )
            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(result["mode"], "attach")
            self.assertEqual(result["scenario"], "remap")
            self.assertGreater(result["records"], 1)
            self.assertGreater(result["elapsed_seconds"], 0)
            self.assertGreater(result["throughput_mib_s"], 0)

    def test_report_contains_reproducibility_metadata(self) -> None:
        report = bench.build_report([])
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["results"], [])
        self.assertEqual(len(report["environment"]["engine_sha256"]), 64)
        self.assertTrue(report["environment"]["python"])

    def test_parse_sizes_rejects_non_positive_values(self) -> None:
        with self.assertRaises(Exception):
            bench.parse_sizes("100,0")

    def test_disk_estimate_accounts_for_retained_remap_output(self) -> None:
        estimated = bench.estimate_benchmark_disk_bytes(
            sizes=[100],
            scenarios=["no-remap", "remap"],
            modes=["attach"],
            repeat=1,
        )
        self.assertEqual(estimated, (2 * 100 + 3 * 100) * bench.MIB + bench.FREE_SPACE_MARGIN)

    def test_benchmark_rejects_insufficient_space_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            usage = type("Usage", (), {"free": 1})()
            with mock.patch.object(bench.shutil, "disk_usage", return_value=usage):
                with self.assertRaisesRegex(RuntimeError, "not enough free space"):
                    bench.benchmark(
                        sizes=[1],
                        scenarios=["remap"],
                        modes=["attach"],
                        repeat=1,
                        work_dir=Path(tmp),
                    )
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
