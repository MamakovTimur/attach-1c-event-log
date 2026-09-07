#!/usr/bin/env python3
"""Split Module.bsl and invoke syntaxcheck via MCP stdio (if configured)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ПрисоединениеЖурналаРегистрации/Forms/Форма/Ext/Form/Module.bsl"
CHUNK_DIR = ROOT / "_syntax_chunks"


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
    text = MODULE.read_text(encoding="utf-8-sig")
    CHUNK_DIR.mkdir(exist_ok=True)
    parts = split_quarters(text)
    for i, part in enumerate(parts, 1):
        payload = {"code": part, "file_name": f"Module_part{i}.bsl"}
        path = CHUNK_DIR / f"syntax_payload_q{i}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"q{i}: {len(part.splitlines())} lines, {len(part)} chars -> {path.name}")
    print(f"total: {len(text.splitlines())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
