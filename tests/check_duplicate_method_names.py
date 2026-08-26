# Fail if Module.bsl declares the same Процедура/Функция name more than once.
# In 1C form modules &НаКлиенте and &НаСервере cannot share a name.

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ПрисоединениеЖурналаРегистрации" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"

DECL_RE = re.compile(
    r"(?:^|\n)\s*(?:Процедура|Функция)\s+(\w+)\s*\(",
    re.MULTILINE,
)


def main() -> int:
    if not MODULE.is_file():
        print(f"FAIL: module not found: {MODULE}", file=sys.stderr)
        return 2

    text = MODULE.read_text(encoding="utf-8-sig")
    names = DECL_RE.findall(text)
    counts = Counter(names)
    dupes = sorted((name, n) for name, n in counts.items() if n > 1)

    if dupes:
        print("FAIL: duplicate procedure/function declarations in Module.bsl:")
        for name, n in dupes:
            print(f"  {name}: {n} times")
        return 1

    print(f"OK: {len(names)} unique declarations in {MODULE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
