# Audit Module.bsl for wrong client/server visibility.
# Does not replace syntaxcheck — catches cross-context calls that compile-check may miss
# until the form module is loaded in Designer.

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ПрисоединениеЖурналаРегистрации" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
DIRECTIVE_RE = re.compile(
    r"^&(?:НаКлиенте|НаСервере|НаСервереБезКонтекста|НаКлиентеНаСервереБезКонтекста)\s*$"
)
DECL_RE = re.compile(r"^(?:Процедура|Функция)\s+(\w+)\s*\(")
CALL_RE = re.compile(
    r"(?<![.А-Яа-яA-Za-z0-9_])([А-Яа-яA-Za-z_][А-Яа-яA-Za-z0-9_]*)\s*\("
)

SERVER_CONTEXTS = {"НаСервере", "НаСервереБезКонтекста"}
CLIENT_CONTEXTS = {"НаКлиенте"}
SHARED_CONTEXTS = {"НаКлиентеНаСервереБезКонтекста"}


@dataclass
class Symbol:
    name: str
    context: str
    line: int


@dataclass
class CallSite:
    name: str
    line: int
    caller: str
    caller_context: str


def parse_directives(text: str) -> tuple[dict[str, Symbol], list[Symbol]]:
    """Return case-insensitive symbol table and declarations with line numbers."""
    symbols: list[Symbol] = []
    by_name: dict[str, Symbol] = {}
    current_directive = "НаКлиенте"
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if DIRECTIVE_RE.match(line):
            current_directive = line.lstrip("&")
            continue
        m = DECL_RE.match(line)
        if m:
            name = m.group(1)
            symbol = Symbol(name, current_directive, lineno)
            symbols.append(symbol)
            by_name[name.casefold()] = symbol
    return by_name, symbols


def caller_context_visible(caller_ctx: str, callee_ctx: str) -> bool:
    # Client may call server procedures (implicit server round-trip).
    if caller_ctx in CLIENT_CONTEXTS:
        return True
    if caller_ctx == "НаСервере":
        return callee_ctx in SERVER_CONTEXTS | SHARED_CONTEXTS
    if caller_ctx == "НаСервереБезКонтекста":
        return callee_ctx in {"НаСервереБезКонтекста"} | SHARED_CONTEXTS
    if caller_ctx in SHARED_CONTEXTS:
        return callee_ctx in SHARED_CONTEXTS
    return False


def code_without_strings_or_comments(raw: str, in_string: bool) -> tuple[str, bool]:
    """Mask BSL strings/comments while preserving character positions."""
    chars = list(raw)
    index = 0
    while index < len(raw):
        if in_string:
            chars[index] = " "
            if raw[index] == '"':
                if index + 1 < len(raw) and raw[index + 1] == '"':
                    chars[index + 1] = " "
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if raw.startswith("//", index):
            for rest in range(index, len(chars)):
                chars[rest] = " "
            break
        if raw[index] == '"':
            chars[index] = " "
            in_string = True
        index += 1
    return "".join(chars), in_string


def collect_calls(text: str, by_name: dict[str, Symbol]) -> list[CallSite]:
    calls: list[CallSite] = []
    current_directive = "НаКлиенте"
    current_caller = "<module>"
    in_string = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if DIRECTIVE_RE.match(line):
            current_directive = line.lstrip("&")
            continue
        m = DECL_RE.match(line)
        if m:
            current_caller = m.group(1)
            continue
        # Dotted calls are methods of a value, not calls to form-module routines.
        # Strings and // comments cannot contain executable calls either.
        code, in_string = code_without_strings_or_comments(raw, in_string)
        for cm in CALL_RE.finditer(code):
            name = cm.group(1)
            if name.casefold() not in by_name:
                continue
            calls.append(
                CallSite(name, lineno, current_caller, current_directive)
            )
    return calls


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if not MODULE.is_file():
        print(f"FAIL: module not found: {MODULE}", file=sys.stderr)
        return 2

    module_text = MODULE.read_text(encoding="utf-8-sig")
    by_name, _ = parse_directives(module_text)
    calls = collect_calls(module_text, by_name)

    visibility_errors: list[str] = []

    for call in calls:
        callee = by_name[call.name.casefold()]
        if not caller_context_visible(call.caller_context, callee.context):
            visibility_errors.append(
                f"  L{call.line}: {call.caller} ({call.caller_context}) -> "
                f"{callee.name} ({callee.context}, declaration L{callee.line})"
            )

    failed = False
    if visibility_errors:
        failed = True
        print("FAIL: invalid client/server context calls (compile error in form module):")
        for item in visibility_errors:
            print(item)
    if failed:
        return 1

    print(
        f"OK: {len(by_name)} declarations, {len(calls)} call sites, "
        "no invalid cross-context module calls"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
