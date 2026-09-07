#!/usr/bin/env python3
"""Print syntaxcheck payloads for all Module.bsl quarters (for MCP or manual check)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ПрисоединениеЖурналаРегистрации" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
OUT = ROOT / "_syntax_chunks"


def split_quarters(text: str) -> list[str]:
    lines = text.splitlines()
    n = len(lines)
    chunk = n // 4
    parts: list[str] = []
    for i in range(4):
        start = i * chunk
        end = (i + 1) * chunk if i < 3 else n
        parts.append("\n".join(lines[start:end]))
    return parts


def main() -> int:
    if not MODULE.is_file():
        print(f"FAIL: {MODULE}", file=sys.stderr)
        return 2
    OUT.mkdir(exist_ok=True)
    parts = split_quarters(MODULE.read_text(encoding="utf-8-sig"))
    for i, part in enumerate(parts, 1):
        path = OUT / f"syntax_payload_q{i}.json"
        payload = {"code": part, "file_name": "Module.bsl"}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        bsl = OUT / f"_q{i}.bsl"
        bsl.write_text(part, encoding="utf-8")
        print(f"q{i}: {len(part.splitlines())} lines -> {path.name}, {bsl.name}")
    print(f"total: {len(parts[0].splitlines()) * 3 + len(parts[3].splitlines())} lines approx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
