# Fail if Module.bsl (or ObjectModule.bsl) has mismatched
# Функция/КонецФункции or Процедура/КонецПроцедуры pairs.
# Catches cross-closings that some syntax checkers miss.

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    ROOT
    / "ПрисоединениеЖурналаРегистрации"
    / "Forms"
    / "Форма"
    / "Ext"
    / "Form"
    / "Module.bsl",
    ROOT / "ПрисоединениеЖурналаРегистрации" / "Ext" / "ObjectModule.bsl",
]

OPEN_RE = re.compile(r"^\s*(Функция|Процедура)\s+(\w+)", re.UNICODE)
CLOSE_RE = re.compile(r"^\s*(КонецФункции|КонецПроцедуры)\b", re.UNICODE)
EXPECT = {"Функция": "КонецФункции", "Процедура": "КонецПроцедуры"}


def check_module(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"module not found: {path}"]

    stack: list[tuple[str, str, int]] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.split("//", 1)[0]
        m = OPEN_RE.match(line)
        if m:
            stack.append((m.group(1), m.group(2), i))
            continue
        m = CLOSE_RE.match(line)
        if not m:
            continue
        close = m.group(1)
        if not stack:
            errors.append(f"{path.name}:{i}: orphan {close}")
            continue
        kind, name, start = stack.pop()
        expected = EXPECT[kind]
        if close != expected:
            errors.append(
                f"{path.name}:{i}: {name} opened as {kind} at {start}, "
                f"closed as {close} (expected {expected})"
            )

    for kind, name, start in stack:
        errors.append(f"{path.name}:{start}: unclosed {kind} {name}")
    return errors


def main() -> int:
    all_errors: list[str] = []
    checked = 0
    for module in MODULES:
        errs = check_module(module)
        if errs and errs[0].startswith("module not found"):
            print(f"FAIL: {errs[0]}", file=sys.stderr)
            return 2
        all_errors.extend(errs)
        checked += 1

    if all_errors:
        print("FAIL: BSL Function/Procedure block imbalance:")
        for err in all_errors:
            print(f"  {err}")
        return 1

    print(f"OK: Function/Procedure blocks balanced in {checked} module(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
