#!/usr/bin/env python3
"""Run syntaxcheck on ObjectModule + Module.bsl quarters via MCP HTTP."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "_syntax_chunks"
OBJECT = ROOT / "ПрисоединениеЖурналаРегистрации" / "Ext" / "ObjectModule.bsl"
OUT = CHUNKS / "syntaxcheck_summary.json"


def count_errors(text: str) -> int:
    """Count syntaxcheck failures beyond severity: error only.

    MCP/LS may emit Critical, ParseError, or Russian diagnostics
    (e.g. expected EndFunction) without severity: error.
    """
    low = text.lower()
    patterns = [
        r"severity:\s*error",
        r"severity:\s*critical",
        r"(?<![\w.])critical(?![\w])",
        r"parse\s*error|parseerror",
        r"ожидалось\s+конецфункции",
        r"ожидалось\s+конецпроцедуры",
    ]
    # Count per line so severity:critical is not double-counted with bare critical.
    lines = low.splitlines() or [low]
    return sum(1 for line in lines if any(re.search(pat, line) for pat in patterns))


async def main() -> int:
    results: dict[str, dict[str, object]] = {}
    async with streamable_http_client("http://localhost:8002/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            obj = OBJECT.read_text(encoding="utf-8-sig")
            r = await session.call_tool(
                "syntaxcheck", {"code": obj, "file_name": "ObjectModule.bsl"}
            )
            text = r.content[0].text if r.content else str(r)
            results["ObjectModule.bsl"] = {
                "errors": count_errors(text),
                "response": text,
            }

            for i in range(1, 5):
                code = (CHUNKS / f"_sc_input_q{i}.txt").read_text(encoding="utf-8")
                r = await session.call_tool(
                    "syntaxcheck", {"code": code, "file_name": "Module.bsl"}
                )
                text = r.content[0].text if r.content else str(r)
                results[f"Module_q{i}"] = {
                    "errors": count_errors(text),
                    "response": text,
                }

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    total_err = sum(int(v["errors"]) for v in results.values())
    for name, data in results.items():
        print(f"{name}: errors={data['errors']}")
    print(f"TOTAL errors={total_err}")
    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
