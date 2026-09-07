#!/usr/bin/env python3
"""Fail if form attributes are read in no-context form module methods.

&НаКлиентеНаСервереБезКонтекста and &НаСервереБезКонтекста have no form
context: bare names of Form.xml attributes must be parameters or locals
(assigned in the method body), not implicit form fields.

Catches the class of bug that makes the form fail to open with
«Переменная не определена (КаталогРезервнойКопии)».
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = (
    ROOT
    / "ПрисоединениеЖурналаРегистрации"
    / "Forms"
    / "Форма"
    / "Ext"
    / "Form"
    / "Module.bsl"
)
FORM_XML = (
    ROOT
    / "ПрисоединениеЖурналаРегистрации"
    / "Forms"
    / "Форма"
    / "Ext"
    / "Form.xml"
)

NOCTX_RE = re.compile(
    r"^&(НаКлиентеНаСервереБезКонтекста|НаСервереБезКонтекста)\s*$"
)
DIR_RE = re.compile(r"^&")
PROC_RE = re.compile(r"^(Процедура|Функция)\s+(\w+)\s*\((.*)\)\s*(Экспорт)?\s*$")
END_RE = re.compile(r"^(КонецПроцедуры|КонецФункции)\s*$")
ATTR_RE = re.compile(r'<Attribute name="([^"]+)"')
# Skip root "Объект" — rarely a false positive target for bare reads.
SKIP_ATTRS = {"Объект"}


def form_attributes(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    return sorted({m for m in ATTR_RE.findall(text) if m not in SKIP_ATTRS})


def strip_noise(line: str) -> str:
    no_str = re.sub(r'"(?:[^"]|"")*"', '""', line)
    return re.sub(r"//.*", "", no_str)


def param_names(param_str: str) -> set[str]:
    names: set[str] = set()
    for part in param_str.split(","):
        part = part.strip()
        if not part:
            continue
        part = re.sub(r"^Знач\s+", "", part)
        name = part.split("=", 1)[0].strip().split()[0]
        if name:
            names.add(name)
    return names


def local_names(body_lines: list[str]) -> set[str]:
    """Names introduced as locals via assignment or Для Каждого."""
    locals_: set[str] = set()
    for raw in body_lines:
        line = strip_noise(raw)
        m = re.match(r"^\s*([А-Яа-яA-Za-z_][\w]*)\s*=", line)
        if m:
            locals_.add(m.group(1))
        m = re.search(r"Для\s+Каждого\s+([А-Яа-яA-Za-z_][\w]*)\s+Из\b", line)
        if m:
            locals_.add(m.group(1))
    return locals_


def scan(module: Path, attrs: list[str]) -> list[str]:
    lines = module.read_text(encoding="utf-8-sig").splitlines()
    issues: list[str] = []
    in_noctx = False
    current_dir = ""
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if NOCTX_RE.match(s):
            current_dir = s
            in_noctx = True
            i += 1
            continue
        if DIR_RE.match(s) and not NOCTX_RE.match(s):
            in_noctx = False
            i += 1
            continue
        m = PROC_RE.match(s)
        if m and in_noctx:
            proc = m.group(2)
            declared = param_names(m.group(3))
            j = i + 1
            body: list[str] = []
            while j < len(lines):
                if END_RE.match(lines[j].strip()):
                    break
                body.append(lines[j])
                j += 1
            declared |= local_names(body)
            for attr in attrs:
                if attr in declared:
                    continue
                pat = re.compile(r"(?<![\w.])" + re.escape(attr) + r"(?![\w])")
                for offset, raw in enumerate(body):
                    cleaned = strip_noise(raw)
                    if pat.search(cleaned):
                        ln = i + 2 + offset  # body starts at i+1 (1-based: i+2)
                        issues.append(
                            f"{current_dir} {proc}:{ln}: bare form attr "
                            f"{attr!r} (pass as parameter)"
                        )
            i = j
            in_noctx = False
            continue
        i += 1
    return issues


def main() -> int:
    if not MODULE.is_file():
        print(f"FAIL: module not found: {MODULE}", file=sys.stderr)
        return 2
    if not FORM_XML.is_file():
        print(f"FAIL: Form.xml not found: {FORM_XML}", file=sys.stderr)
        return 2

    attrs = form_attributes(FORM_XML)
    issues = scan(MODULE, attrs)
    if issues:
        print("FAIL: form attributes used in no-context methods:")
        for issue in issues:
            print(f"  {issue}")
        return 1

    print(
        f"OK: no bare form attrs in no-context methods "
        f"({len(attrs)} attrs checked, {MODULE.name})"
    )
    print("PASS: check_no_form_attrs_in_nocontext")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
