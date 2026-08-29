#!/usr/bin/env python3
"""Fail if BSL uses chained method calls on Новый constructors.

In 1C BSL, `Новый Файл(Путь).Размер()` does not compile
(«Неопознанный оператор»). Require an intermediate variable.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "ПрисоединениеЖурналаРегистрации" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl",
    ROOT / "ПрисоединениеЖурналаРегистрации" / "Ext" / "ObjectModule.bsl",
]

# Новый Something(...).Method — allows nested parens only one level deep roughly.
CHAINED_NEW = re.compile(
    r"Новый\s+\w+\s*\([^)]*\)\s*\.",
    re.UNICODE,
)


def scan(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8-sig")
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        if CHAINED_NEW.search(line):
            hits.append((i, line.strip()))
    return hits


def main() -> int:
    total = 0
    for path in TARGETS:
        if not path.is_file():
            print(f"MISSING: {path}", file=sys.stderr)
            return 2
        hits = scan(path)
        if hits:
            print(f"FAIL: chained Новый (...). in {path.relative_to(ROOT)}")
            for line_no, line in hits:
                print(f"  L{line_no}: {line}")
            total += len(hits)
        else:
            print(f"OK: no chained Новый in {path.name}")
    if total:
        print(f"TOTAL: {total} illegal chain(s)", file=sys.stderr)
        return 1
    print("PASS: check_no_new_chained_calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
