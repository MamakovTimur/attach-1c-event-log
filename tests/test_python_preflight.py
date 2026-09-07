from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_attach_event_log_cli import ev, write_lgf, write_lgp
from tools import attach_event_log as engine


class PythonPreflightTests(unittest.TestCase):
    def make_journals(self, root: Path) -> tuple[Path, Path, str]:
        guid = "cccccccc-e311-4ee2-8582-7a2a46a59363"
        source = root / "src"
        destination = root / "dst"
        source.mkdir()
        destination.mkdir()
        rows = [
            '{1,22222222-2222-2222-2222-222222222222,"U",1},',
            '{2,"PC",1},',
            '{3,"App",1},',
            '{4,"Evt",1}',
        ]
        write_lgf(source / "1Cv8.lgf", guid, rows)
        write_lgf(destination / "1Cv8.lgf", guid, rows)
        write_lgp(
            source / "20260101000000.lgp",
            guid,
            [ev("20260101120000", "1")],
        )
        return source, destination, guid

    def test_estimate_includes_destination_for_merge(self) -> None:
        estimated = engine.estimate_lgp_temp_bytes(
            source_bytes=100,
            destination_bytes=70,
            action="merge",
            need_remap=True,
        )
        self.assertEqual(estimated, 200 + 70 + engine.MIB)

    def test_insufficient_space_is_rejected_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, destination, _ = self.make_journals(Path(tmp))
            lgf_before = (destination / "1Cv8.lgf").read_bytes()
            usage = shutil._ntuple_diskusage(total=100, used=99, free=1)
            with mock.patch.object(engine.shutil, "disk_usage", return_value=usage):
                result = engine.attach_cmd(
                    source,
                    destination,
                    conflict="merge",
                    files="20260101000000.lgp",
                    files_from=None,
                    dedup=False,
                    split_by_day=False,
                )
            self.assertEqual(result, engine.EXIT_BUSY)
            self.assertEqual((destination / "1Cv8.lgf").read_bytes(), lgf_before)
            self.assertFalse((destination / "20260101000000.lgp").exists())

    def test_required_space_includes_previously_published_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = []
            for number in range(2):
                source = root / f"source-{number}.lgp"
                destination = root / f"destination-{number}.lgp"
                source.write_bytes(b"x" * 100)
                plan.append((source.name, source, destination, "copy"))
            required = engine.required_free_space_bytes(
                plan,
                need_remap=False,
                lgf_destination_bytes=10,
                added_lgf_bytes=0,
            )
            self.assertEqual(
                required,
                engine.FREE_SPACE_MARGIN + engine.MIB + 200,
            )

    def test_skip_only_plan_does_not_change_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, destination, guid = self.make_journals(Path(tmp))
            write_lgp(
                destination / "20260101000000.lgp",
                guid,
                [ev("20260101110000", "1")],
            )
            lgf_before = (destination / "1Cv8.lgf").read_bytes()
            result = engine.attach_cmd(
                source,
                destination,
                conflict="skip",
                files="20260101000000.lgp",
                files_from=None,
                dedup=False,
                split_by_day=False,
            )
            self.assertEqual(result, engine.EXIT_VALIDATION)
            self.assertEqual((destination / "1Cv8.lgf").read_bytes(), lgf_before)

    def test_failed_temp_verification_does_not_publish_lgp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, destination, _ = self.make_journals(Path(tmp))
            with mock.patch.object(
                engine,
                "verify_lgp_header",
                side_effect=ValueError("synthetic verification failure"),
            ):
                result = engine.attach_cmd(
                    source,
                    destination,
                    conflict="merge",
                    files="20260101000000.lgp",
                    files_from=None,
                    dedup=False,
                    split_by_day=False,
                )
            self.assertEqual(result, engine.EXIT_BUSY)
            self.assertFalse((destination / "20260101000000.lgp").exists())

    def test_invalid_report_extension_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, destination, _ = self.make_journals(Path(tmp))
            lgf_before = (destination / "1Cv8.lgf").read_bytes()
            result = engine.attach_cmd(
                source,
                destination,
                conflict="merge",
                files="20260101000000.lgp",
                files_from=None,
                dedup=False,
                split_by_day=False,
                report_json=Path(tmp) / "report.txt",
            )
            self.assertEqual(result, engine.EXIT_VALIDATION)
            self.assertEqual((destination / "1Cv8.lgf").read_bytes(), lgf_before)
            self.assertFalse((destination / "20260101000000.lgp").exists())


if __name__ == "__main__":
    unittest.main()
