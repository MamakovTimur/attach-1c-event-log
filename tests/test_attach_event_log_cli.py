# -*- coding: utf-8 -*-
"""Tests for tools/attach_event_log.py CLI (analyze + attach MVP)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "attach_event_log.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run_cli(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(CLI), *args]
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def write_lgf(path: Path, guid: str, rows: list[str]) -> None:
    body = "\r\n".join(rows)
    text = f"1CV8LOG(ver 2.0)\r\n{guid}\r\n\r\n{body}\r\n"
    path.write_bytes(("\ufeff" + text).encode("utf-8"))


def write_lgp(path: Path, guid: str, records: list[str]) -> None:
    # last record without trailing comma
    lines = ["1CV8LOG(ver 2.0)", guid, ""]
    for i, rec in enumerate(records):
        r = rec.strip()
        if i < len(records) - 1 and not r.endswith(","):
            r += ","
        if i == len(records) - 1 and r.endswith(","):
            r = r[:-1]
        lines.append(r)
    text = "\r\n".join(lines) + "\r\n"
    path.write_bytes(("\ufeff" + text).encode("utf-8"))


def ev(dt: str, user: str, computer: str = "1", app: str = "1", event: str = "1") -> str:
    return (
        f"{{{dt},N,"
        f"{{0,0}},{user},{computer},{app},1,{event},I,\"\",0,"
        f'{{\"U\"}},\"\",0,0,0,1,0,'
        f"{{0}}}}"
    )


class AttachEventLogCliTests(unittest.TestCase):
    def make_minimal_journals(self, root: Path) -> tuple[Path, Path, str]:
        guid = "cccccccc-e311-4ee2-8582-7a2a46a59363"
        src = root / "src"
        dst = root / "dst"
        src.mkdir()
        dst.mkdir()
        rows = [
            '{1,22222222-2222-2222-2222-222222222222,"U",1},',
            '{2,"PC",1},',
            '{3,"App",1},',
            '{4,"Evt",1}',
        ]
        write_lgf(src / "1Cv8.lgf", guid, rows)
        write_lgf(dst / "1Cv8.lgf", guid, list(rows))
        return src, dst, guid

    def test_analyze_fixtures(self) -> None:
        src = FIXTURES / "jr_src"
        dst = FIXTURES / "jr_dst"
        if not (src / "1Cv8.lgf").exists():
            self.skipTest("fixtures jr_src/jr_dst missing")
        proc = run_cli(
            ["--mode", "analyze", "--src", str(src), "--dst", str(dst)]
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ANALYZE OK", proc.stdout)

    def test_attach_copy_and_renumber(self) -> None:
        guid_src = "aaaaaaaa-e311-4ee2-8582-7a2a46a59363"
        guid_dst = "bbbbbbbb-e311-4ee2-8582-7a2a46a59363"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            dst = root / "dst"
            src.mkdir()
            dst.mkdir()

            # src: user#1, computer#1, event#1
            write_lgf(
                src / "1Cv8.lgf",
                guid_src,
                [
                    '{1,11111111-1111-1111-1111-111111111111,"UserA",1},',
                    '{2,"PC-A",1},',
                    '{3,"App",1},',
                    '{4,"Evt",1}',
                ],
            )
            # dst: same user UUID but different numbers for computer/event
            write_lgf(
                dst / "1Cv8.lgf",
                guid_dst,
                [
                    '{1,11111111-1111-1111-1111-111111111111,"UserA",5},',
                    '{2,"PC-OTHER",2},',
                    '{3,"App",1},',
                    '{4,"EvtOther",3}',
                ],
            )
            write_lgp(
                src / "20260101000000.lgp",
                guid_src,
                [ev("20260101120000", "1", "1", "1", "1")],
            )

            log_path = root / "attach.log"
            proc = run_cli(
                [
                    "--mode",
                    "attach",
                    "--src",
                    str(src),
                    "--dst",
                    str(dst),
                    "--conflict",
                    "merge",
                    "--files",
                    "20260101000000.lgp",
                    "--out-log",
                    str(log_path),
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("ATTACH OK", log_text)

            out_lgp = (dst / "20260101000000.lgp").read_text(encoding="utf-8-sig")
            self.assertIn(guid_dst, out_lgp)
            # user 1 -> 5, computer 1 is new -> max was 2 so 3, event 1 is new -> 4
            self.assertIn(",5,3,1,1,4,", out_lgp.replace("\r\n", "").replace("\n", ""))

            dst_lgf = (dst / "1Cv8.lgf").read_text(encoding="utf-8-sig")
            self.assertIn('"PC-A"', dst_lgf)
            self.assertIn('"Evt"', dst_lgf)

    def test_attach_merge_without_remap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst, guid = self.make_minimal_journals(root)
            write_lgp(src / "20260102000000.lgp", guid, [ev("20260102120000", "1")])
            write_lgp(dst / "20260102000000.lgp", guid, [ev("20260102110000", "1")])

            proc = run_cli(
                [
                    "--mode",
                    "attach",
                    "--src",
                    str(src),
                    "--dst",
                    str(dst),
                    "--conflict",
                    "merge",
                    "--files",
                    "20260102000000.lgp",
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            text = (dst / "20260102000000.lgp").read_text(encoding="utf-8-sig")
            self.assertIn("20260102110000", text)
            self.assertIn("20260102120000", text)

    def test_files_from_utf8_bom_processes_first_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst, guid = self.make_minimal_journals(root)
            selected = "20260103000000.lgp"
            unselected = "20260104000000.lgp"
            write_lgp(src / selected, guid, [ev("20260103120000", "1")])
            write_lgp(src / unselected, guid, [ev("20260104120000", "1")])
            files_from = root / "files.txt"
            files_from.write_text(selected + "\n", encoding="utf-8-sig")

            proc = run_cli(
                [
                    "--mode",
                    "attach",
                    "--src",
                    str(src),
                    "--dst",
                    str(dst),
                    "--files-from",
                    str(files_from),
                ]
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue((dst / selected).exists())
            self.assertFalse((dst / unselected).exists())

    def test_files_from_rejects_dictionary_name_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst, _ = self.make_minimal_journals(root)
            before = (dst / "1Cv8.lgf").read_bytes()
            files_from = root / "files.txt"
            files_from.write_text("1Cv8.lgf|replace\n", encoding="utf-8-sig")

            proc = run_cli(
                [
                    "--mode",
                    "attach",
                    "--src",
                    str(src),
                    "--dst",
                    str(dst),
                    "--files-from",
                    str(files_from),
                ]
            )

            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("недопустимое имя", proc.stdout.lower())
            self.assertEqual((dst / "1Cv8.lgf").read_bytes(), before)

    def test_files_from_rejects_unknown_action_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst, guid = self.make_minimal_journals(root)
            name = "20260107000000.lgp"
            write_lgp(src / name, guid, [ev("20260107120000", "1")])
            before = (dst / "1Cv8.lgf").read_bytes()
            files_from = root / "files.txt"
            files_from.write_text(f"{name}|merg\n", encoding="utf-8")

            proc = run_cli(
                [
                    "--mode",
                    "attach",
                    "--src",
                    str(src),
                    "--dst",
                    str(dst),
                    "--files-from",
                    str(files_from),
                ]
            )

            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("неизвестное действие", proc.stdout.lower())
            self.assertEqual((dst / "1Cv8.lgf").read_bytes(), before)

    def test_attach_rejects_same_directory_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "journal"
            journal.mkdir()
            guid = "dddddddd-e311-4ee2-8582-7a2a46a59363"
            write_lgf(journal / "1Cv8.lgf", guid, ['{4,"Evt",1}'])
            write_lgp(journal / "20260105000000.lgp", guid, [ev("20260105120000", "1")])
            before = (journal / "1Cv8.lgf").read_bytes()

            proc = run_cli(
                ["--mode", "attach", "--src", str(journal), "--dst", str(journal)]
            )

            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("один и тот же каталог", proc.stdout.lower())
            self.assertEqual((journal / "1Cv8.lgf").read_bytes(), before)

    def test_analyze_rejects_equivalent_resolved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = root / "journal"
            journal.mkdir()
            write_lgf(
                journal / "1Cv8.lgf",
                "eeeeeeee-e311-4ee2-8582-7a2a46a59363",
                ['{4,"Evt",1}'],
            )
            alias = journal / ".." / "journal"

            proc = run_cli(
                ["--mode", "analyze", "--src", str(journal), "--dst", str(alias)]
            )

            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("один и тот же каталог", proc.stdout.lower())

    def test_large_raw_merge_preserves_all_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst, guid = self.make_minimal_journals(root)
            name = "20260106000000.lgp"
            source_records = [ev(f"20260106{i % 24:02d}{i % 60:02d}00", "1") for i in range(20000)]
            write_lgp(src / name, guid, source_records)
            write_lgp(dst / name, guid, [ev("20260106000000", "1")])

            proc = run_cli(
                [
                    "--mode",
                    "attach",
                    "--src",
                    str(src),
                    "--dst",
                    str(dst),
                    "--files",
                    name,
                ]
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            text = (dst / name).read_text(encoding="utf-8-sig")
            self.assertEqual(text.count("{20260106"), 20001)

    def test_dedup_flag_rejected(self) -> None:
        src = FIXTURES / "jr_src"
        dst = FIXTURES / "jr_dst"
        if not (src / "1Cv8.lgf").exists():
            self.skipTest("fixtures missing")
        proc = run_cli(
            [
                "--mode",
                "attach",
                "--src",
                str(src),
                "--dst",
                str(dst),
                "--dedup",
            ]
        )
        self.assertEqual(proc.returncode, 1)
        combined = (proc.stdout + proc.stderr).lower()
        self.assertTrue(
            "dedup" in combined or "mvp" in combined,
            msg=repr(combined),
        )

    def test_split_by_day_flag_rejected(self) -> None:
        src = FIXTURES / "jr_src"
        dst = FIXTURES / "jr_dst"
        if not (src / "1Cv8.lgf").exists():
            self.skipTest("fixtures missing")
        proc = run_cli(
            [
                "--mode",
                "attach",
                "--src",
                str(src),
                "--dst",
                str(dst),
                "--split-by-day",
            ]
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("split-by-day", (proc.stdout + proc.stderr).lower())


if __name__ == "__main__":
    unittest.main()
