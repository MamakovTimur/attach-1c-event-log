"""Golden / synthetic tests for Phase 2 merge quality (dedup, tx, day-split, archive)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lgp_merge_quality import (  # noqa: E402
    day_from_lgp_filename,
    detect_archive_format,
    fingerprint,
    iter_records,
    merge_records_dedup,
    merge_warn_transactions,
    record_tokens,
    scan_transaction_boundary,
    split_by_day,
    split_header_body,
    write_golden_fixtures,
)

FIXTURES = ROOT / "tests" / "fixtures" / "golden"


class TestMergeQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        write_golden_fixtures(ROOT)

    def test_fixtures_exist(self) -> None:
        names = [
            "day_a.lgp",
            "day_b_overlap.lgp",
            "multiday.lgp",
            "open_tx_tail.lgp",
            "archive_packed.lgp",
            "emptyish.lgp",
            "renumber_src.lgp",
            "renumber_dst.lgp",
        ]
        for name in names:
            self.assertTrue((FIXTURES / name).is_file(), name)

    def test_dedup_skips_overlapping_fingerprint(self) -> None:
        a = (FIXTURES / "day_a.lgp").read_text(encoding="utf-8-sig")
        b = (FIXTURES / "day_b_overlap.lgp").read_text(encoding="utf-8-sig")
        _, body_a = split_header_body(a)
        _, body_b = split_header_body(b)
        dest = list(iter_records(body_a))
        src = list(iter_records(body_b))
        merged, stats = merge_records_dedup(dest, src, dedup=True)
        self.assertEqual(stats.skipped, 1)
        self.assertEqual(stats.written, 1)
        self.assertEqual(len(merged), 4)  # 3 dest + 1 new

        merged_off, stats_off = merge_records_dedup(dest, src, dedup=False)
        self.assertEqual(stats_off.skipped, 0)
        self.assertEqual(len(merged_off), 5)

    def test_fingerprint_stable(self) -> None:
        a = (FIXTURES / "day_a.lgp").read_text(encoding="utf-8-sig")
        _, body = split_header_body(a)
        rec = next(iter_records(body))
        tokens = record_tokens(rec)
        fp1 = fingerprint(tokens)
        fp2 = fingerprint(tokens)
        self.assertEqual(fp1, fp2)
        self.assertIn("20260820010101", fp1)

    def test_transaction_open_at_end_warned(self) -> None:
        text = (FIXTURES / "open_tx_tail.lgp").read_text(encoding="utf-8-sig")
        boundary = scan_transaction_boundary(text)
        self.assertTrue(boundary.open_at_end)
        self.assertTrue(boundary.warnings)

    def test_merge_tx_warnings_across_files(self) -> None:
        dest = (FIXTURES / "open_tx_tail.lgp").read_text(encoding="utf-8-sig")
        src = (FIXTURES / "day_b_overlap.lgp").read_text(encoding="utf-8-sig")
        warnings = merge_warn_transactions(dest, src)
        self.assertTrue(any("незакрытой транзакцией" in w for w in warnings))

    def test_split_by_day_basic(self) -> None:
        text = (FIXTURES / "multiday.lgp").read_text(encoding="utf-8-sig")
        _, body = split_header_body(text)
        records = list(iter_records(body))
        buckets = split_by_day(records, protect_transactions=True)
        self.assertIn("20260820", buckets)
        self.assertIn("20260821", buckets)
        # U on 22 + C on 23 stick to begin day 22
        self.assertIn("20260822", buckets)
        self.assertEqual(len(buckets["20260822"]), 2)
        self.assertNotIn("20260823", buckets)

    def test_split_by_day_without_tx_protection(self) -> None:
        text = (FIXTURES / "multiday.lgp").read_text(encoding="utf-8-sig")
        _, body = split_header_body(text)
        records = list(iter_records(body))
        buckets = split_by_day(records, protect_transactions=False)
        self.assertIn("20260823", buckets)
        self.assertEqual(len(buckets["20260822"]), 1)

    def test_archive_detection(self) -> None:
        text = (FIXTURES / "archive_packed.lgp").read_text(encoding="utf-8-sig")
        result = detect_archive_format(text)
        self.assertTrue(result.is_archive)
        self.assertTrue(result.has_dict_rows)
        self.assertTrue(result.has_event_rows)

        plain = (FIXTURES / "day_a.lgp").read_text(encoding="utf-8-sig")
        self.assertFalse(detect_archive_format(plain).is_archive)

    def test_day_from_filename(self) -> None:
        self.assertEqual(day_from_lgp_filename("20260824000000.lgp"), "20260824")
        self.assertEqual(day_from_lgp_filename("other.lgp"), "")

    def test_closed_tx_file_clean(self) -> None:
        text = (FIXTURES / "day_a.lgp").read_text(encoding="utf-8-sig")
        boundary = scan_transaction_boundary(text)
        self.assertFalse(boundary.open_at_end)


if __name__ == "__main__":
    raise SystemExit(0 if unittest.main(verbosity=2).result.wasSuccessful() else 1)
