from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def make_journals_with_new_event(
        self,
        root: Path,
        names: tuple[str, ...] = ("20260101000000.lgp",),
    ) -> tuple[Path, Path, str]:
        guid = "cccccccc-e311-4ee2-8582-7a2a46a59363"
        source = root / "src"
        destination = root / "dst"
        source.mkdir()
        destination.mkdir()
        destination_rows = [
            '{1,22222222-2222-2222-2222-222222222222,"U",1},',
            '{2,"PC",1},',
            '{3,"App",1},',
            '{4,"Evt",1}',
        ]
        source_rows = [*destination_rows[:-1], '{4,"Evt",1},', '{4,"Evt2",2}']
        write_lgf(source / "1Cv8.lgf", guid, source_rows)
        write_lgf(destination / "1Cv8.lgf", guid, destination_rows)
        for name in names:
            write_lgp(source / name, guid, [ev("20260101120000", "1", event="2")])
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

    def test_required_space_includes_lgf_rollback_copy(self) -> None:
        required = engine.required_free_space_bytes(
            [],
            need_remap=False,
            lgf_destination_bytes=100,
            added_lgf_bytes=20,
        )
        self.assertEqual(
            required,
            engine.FREE_SPACE_MARGIN + engine.MIB + 220,
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
            source, destination, _ = self.make_journals_with_new_event(Path(tmp))
            lgf_before = (destination / "1Cv8.lgf").read_bytes()
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
            self.assertEqual((destination / "1Cv8.lgf").read_bytes(), lgf_before)

    def test_partial_result_keeps_dictionary_for_published_lgp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            names = ("20260101000000.lgp", "20260102000000.lgp")
            source, destination, _ = self.make_journals_with_new_event(
                Path(tmp), names
            )
            original_verify = engine.verify_lgp_header
            temp_verifications = 0

            def fail_second_temp(path: Path, version: str, guid: str) -> None:
                nonlocal temp_verifications
                if path.suffix == ".tmp":
                    temp_verifications += 1
                    if temp_verifications == 2:
                        raise ValueError("synthetic second-file failure")
                original_verify(path, version, guid)

            output = io.StringIO()
            with (
                mock.patch.object(
                    engine,
                    "verify_lgp_header",
                    side_effect=fail_second_temp,
                ),
                redirect_stdout(output),
            ):
                result = engine.attach_cmd(
                    source,
                    destination,
                    conflict="merge",
                    files=",".join(names),
                    files_from=None,
                    dedup=False,
                    split_by_day=False,
                )

            self.assertEqual(result, engine.EXIT_BUSY)
            self.assertTrue((destination / names[0]).exists())
            self.assertFalse((destination / names[1]).exists())
            self.assertIn('"Evt2"', (destination / "1Cv8.lgf").read_text("utf-8-sig"))
            self.assertIn("Частичный результат", output.getvalue())
            self.assertIn(names[0], output.getvalue())
            self.assertTrue(engine.operation_state_path(destination).exists())

            first_result = (destination / names[0]).read_bytes()
            resumed_output = io.StringIO()
            with redirect_stdout(resumed_output):
                resumed_result = engine.attach_cmd(
                    source,
                    destination,
                    conflict="merge",
                    files=",".join(names),
                    files_from=None,
                    dedup=False,
                    split_by_day=False,
                )

            self.assertEqual(resumed_result, engine.EXIT_OK)
            self.assertEqual((destination / names[0]).read_bytes(), first_result)
            self.assertTrue((destination / names[1]).exists())
            self.assertFalse(engine.operation_state_path(destination).exists())
            self.assertIn(
                "Продолжение незавершённой операции",
                resumed_output.getvalue(),
            )

    def test_restart_restores_dictionary_before_first_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            name = "20260101000000.lgp"
            source, destination, _ = self.make_journals_with_new_event(Path(tmp))
            original_lgf = (destination / "1Cv8.lgf").read_bytes()
            rollback = destination / ".synthetic-lgf-rollback.tmp"
            rollback.write_bytes(original_lgf)
            (destination / "1Cv8.lgf").write_bytes(
                (source / "1Cv8.lgf").read_bytes()
            )
            request = engine.operation_request_signature(
                source,
                destination,
                "merge",
                [(name, None)],
            )
            engine.write_operation_state(
                destination,
                {
                    "request": request,
                    "phase": "dictionary_ready",
                    "rollback_file": rollback.name,
                    "published_files": [],
                    "completed_files": [],
                    "uncertain_files": [],
                    "current_file": None,
                },
            )

            output = io.StringIO()
            with redirect_stdout(output):
                result = engine.attach_cmd(
                    source,
                    destination,
                    conflict="merge",
                    files=name,
                    files_from=None,
                    dedup=False,
                    split_by_day=False,
                )

            self.assertEqual(result, engine.EXIT_OK)
            self.assertTrue((destination / name).exists())
            lgf_text = (destination / "1Cv8.lgf").read_text("utf-8-sig")
            self.assertEqual(lgf_text.count('"Evt2"'), 1)
            self.assertFalse(rollback.exists())
            self.assertFalse(engine.operation_state_path(destination).exists())
            self.assertIn("восстановлен исходный 1Cv8.lgf", output.getvalue())

    def test_restart_blocks_uncertain_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            name = "20260101000000.lgp"
            source, destination, _ = self.make_journals_with_new_event(Path(tmp))
            request = engine.operation_request_signature(
                source,
                destination,
                "merge",
                [(name, None)],
            )
            engine.write_operation_state(
                destination,
                {
                    "request": request,
                    "phase": "publishing",
                    "rollback_file": None,
                    "published_files": [],
                    "completed_files": [],
                    "uncertain_files": [],
                    "current_file": {
                        "name": name,
                        "action": "copy",
                        "destination_existed": False,
                    },
                },
            )

            output = io.StringIO()
            with redirect_stdout(output):
                result = engine.attach_cmd(
                    source,
                    destination,
                    conflict="merge",
                    files=name,
                    files_from=None,
                    dedup=False,
                    split_by_day=False,
                )

            self.assertEqual(result, engine.EXIT_BUSY)
            self.assertFalse((destination / name).exists())
            self.assertTrue(engine.operation_state_path(destination).exists())
            self.assertIn(
                "Автоматическое продолжение заблокировано",
                output.getvalue(),
            )

    def test_state_write_failure_cannot_replace_lgf_with_empty_reserve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, destination, _ = self.make_journals_with_new_event(Path(tmp))
            lgf_before = (destination / "1Cv8.lgf").read_bytes()

            with mock.patch.object(
                engine,
                "write_operation_state",
                side_effect=OSError("synthetic state write failure"),
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
            self.assertEqual((destination / "1Cv8.lgf").read_bytes(), lgf_before)
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
