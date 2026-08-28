# Smoke-тест анализа ЖР (старый формат) без UI 1С.
# Повторяет ключевую логику: чтение lgf, карта перенумерации, список lgp.

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    in_quotes = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quotes:
            current.append(ch)
            if ch == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    current.append('"')
                    i += 2
                    continue
                in_quotes = False
            i += 1
            continue
        if ch == '"':
            in_quotes = True
            current.append(ch)
        elif ch == "{":
            depth += 1
            current.append(ch)
        elif ch == "}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            tokens.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current or text:
        tokens.append("".join(current).strip())
    return tokens


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('""', '"')
    return value


def parse_number(token: str) -> int:
    token = token.strip()
    return int(token) if token.isdigit() else 0


def update_brackets(line: str, depth: int, in_quotes: bool) -> tuple[int, bool]:
    i = 0
    while i < len(line):
        ch = line[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < len(line) and line[i + 1] == '"':
                    i += 2
                    continue
                in_quotes = False
        elif ch == '"':
            in_quotes = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return depth, in_quotes


def iter_lgf_records(lines: list[str]):
    """Stream dictionary entries from lgf body (after header), including multiline."""
    buffer = ""
    depth = 0
    in_quotes = False
    for line in lines[2:]:
        if depth == 0 and not buffer and not line.strip():
            continue
        if buffer:
            buffer += "\n"
        buffer += line
        depth, in_quotes = update_brackets(line, depth, in_quotes)
        if depth == 0 and buffer.strip():
            yield buffer
            buffer = ""


def add_lgf_record(result: dict, record: str) -> None:
    line = record.strip().rstrip(",")
    if not (line.startswith("{") and line.endswith("}")):
        return
    tokens = tokenize(line[1:-1])
    if len(tokens) < 3:
        return
    obj_type = parse_number(tokens[0])
    number = parse_number(tokens[-1])
    if obj_type < 1 or obj_type > 8 or number <= 0:
        return
    if obj_type in (1, 5) and len(tokens) >= 4:
        uuid = unquote(tokens[1])
        name = unquote(tokens[2])
        key = (uuid or name).lower()
    else:
        uuid = ""
        name = unquote(tokens[1])
        key = name.lower()
    if not key:
        return
    result["by_number"][obj_type][number] = {"type": obj_type, "number": number, "name": name, "uuid": uuid, "key": key}
    result["by_key"][obj_type][key] = number
    result["max_number"][obj_type] = max(result["max_number"][obj_type], number)
    result["count"] += 1


def read_lgf(path: Path) -> dict:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="strict")
    if "1CV8LOG" not in text.splitlines()[0]:
        text = raw.decode("utf-16", errors="strict")
    lines = text.splitlines()
    if not lines or "1CV8LOG" not in lines[0]:
        raise RuntimeError(f"Not an event log dictionary: {path}")

    result = {
        "version": lines[0].strip(),
        "guid": lines[1].strip() if len(lines) > 1 else "",
        "by_number": {t: {} for t in range(1, 9)},
        "by_key": {t: {} for t in range(1, 9)},
        "max_number": {t: 0 for t in range(1, 9)},
        "count": 0,
    }

    for record in iter_lgf_records(lines):
        add_lgf_record(result, record)
    return result


def build_maps(src: dict, dst: dict) -> dict:
    maps = {}
    added = 0
    need_remap = False
    for obj_type in range(1, 9):
        mapping = {}
        max_n = dst["max_number"][obj_type]
        dst_by_key = dict(dst["by_key"][obj_type])
        for old_number, descr in src["by_number"][obj_type].items():
            new_number = dst_by_key.get(descr["key"])
            if new_number is None:
                max_n += 1
                new_number = max_n
                added += 1
                dst_by_key[descr["key"]] = new_number
            mapping[old_number] = new_number
            if new_number != old_number:
                need_remap = True
        maps[obj_type] = mapping
        dst["max_number"][obj_type] = max_n
    return {"maps": maps, "added": added, "need_remap": need_remap}


def normalize_jr_dir(path: Path) -> Path:
    if (path / "1Cv8.lgf").exists():
        return path
    nested = path / "1Cv8Log"
    if (nested / "1Cv8.lgf").exists():
        return nested
    raise FileNotFoundError(f"1Cv8.lgf not found under {path}")


def analyze(src_dir: Path, dst_dir: Path) -> int:
    src_dir = normalize_jr_dir(src_dir)
    dst_dir = normalize_jr_dir(dst_dir)
    src = read_lgf(src_dir / "1Cv8.lgf")
    dst = read_lgf(dst_dir / "1Cv8.lgf")
    result = build_maps(src, dst)
    src_lgp = sorted(p.name for p in src_dir.glob("*.lgp"))
    dst_lgp = {p.name for p in dst_dir.glob("*.lgp")}

    print(f"SRC: {src_dir}")
    print(f"DST: {dst_dir}")
    print(f"SRC dictionary entries: {src['count']}")
    print(f"DST dictionary entries: {dst['count']}")
    print(f"Same GUID: {src['guid'] == dst['guid']}")
    print(f"Need remap: {result['need_remap']}")
    print(f"New dictionary rows: {result['added']}")
    print(f"SRC lgp ({len(src_lgp)}): {', '.join(src_lgp)}")
    print(f"DST lgp ({len(dst_lgp)}): {', '.join(sorted(dst_lgp))}")
    for name in src_lgp:
        action = "merge/conflict" if name in dst_lgp else "copy"
        print(f"  {name}: {action}")

    assert src["count"] > 0, "source dictionary empty"
    assert dst["count"] > 0, "target dictionary empty"
    assert src_lgp, "no source .lgp files"
    print("SMOKE OK: analyze")
    return 0


def main() -> int:
    desktop = Path(r"C:\Users\mamak\OneDrive\Desktop")
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else desktop / "1"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else desktop / "2"
    return analyze(src, dst)


if __name__ == "__main__":
    raise SystemExit(main())
