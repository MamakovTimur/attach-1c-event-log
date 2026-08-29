#!/usr/bin/env python3
"""Copy _tmp_ib/1Cv8Log into tests/fixtures with distinct GUIDs for smoke_analyze."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_IB = ROOT / "_tmp_ib" / "1Cv8Log"
FIXTURES = ROOT / "tests" / "fixtures"
JR_SRC = FIXTURES / "jr_src"
JR_DST = FIXTURES / "jr_dst"
OLD_GUID = "59d64961-e311-4ee2-8582-7a2a46a59363"
NEW_GUID = "a1b2c3d4-e311-4ee2-8582-7a2a46a59363"


def write_tree(target: Path, guid_replace: str | None) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for item in SRC_IB.iterdir():
        text = item.read_text(encoding="utf-8-sig")
        if guid_replace:
            text = text.replace(OLD_GUID, guid_replace)
        (target / item.name).write_text(text, encoding="utf-8-sig")


def main() -> int:
    if not (SRC_IB / "1Cv8.lgf").exists():
        print(f"Missing source IB log: {SRC_IB}", file=sys.stderr)
        return 1
    write_tree(JR_SRC, None)
    write_tree(JR_DST, NEW_GUID)
    print(f"OK: {JR_SRC.name}, {JR_DST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
