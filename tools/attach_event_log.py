#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI ускорения присоединения ЖР (старый текстовый формат lgf/lgp).

MVP: analyze + attach (copy / merge / replace + перенумерация ссылок).
Дедупликация и разбивка по дням — phase-2 (флаги принимаются, но отклоняются
с понятным сообщением, если включены).

Exit codes:
  0 — OK
  1 — ошибка валидации / данных
  2 — файлы заняты / нет доступа на запись
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator, TextIO

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_BUSY = 2
MIB = 1024 * 1024
FREE_SPACE_MARGIN = 64 * MIB
OPERATION_STATE_NAME = ".attach-event-log.operation.json"
OPERATION_STATE_SCHEMA = 1

HEADER_MARKER = "1CV8LOG"
UUID_TYPES = frozenset({1, 5})
PORT_TYPES = frozenset({7, 8})

# 0-based field indices (Infostart 1-based − 1)
REF_FIELDS: list[tuple[int, int, bool]] = [
    (3, 1, False),  # user
    (4, 2, False),  # computer
    (5, 3, False),  # app
    (7, 4, False),  # event
    (10, 5, True),  # metadata composite
    (13, 6, False),  # server
    (14, 7, False),  # main port
    (15, 8, False),  # aux port
]

_log_fp: TextIO | None = None


def log(msg: str) -> None:
    line = msg.rstrip("\n")
    print(line, flush=True)
    if _log_fp is not None:
        _log_fp.write(line + "\n")
        _log_fp.flush()


def detect_newline(sample: str) -> str:
    if "\r\n" in sample:
        return "\r\n"
    if "\r" in sample and "\n" not in sample:
        return "\r"
    return "\n"


def read_text_utf8(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    text = raw.decode("utf-8-sig")
    if text and "1CV8LOG" not in text.splitlines()[0]:
        text = raw.decode("utf-16")
    return text


def write_text_utf8(path: Path, text: str) -> None:
    # UTF-8 with BOM — как у нативных файлов ЖР на Windows
    temp = make_output_temp(path)
    try:
        temp.write_bytes(("\ufeff" + text).encode("utf-8"))
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def paths_refer_to_same_location(left: Path, right: Path) -> bool:
    """Compare existing paths through aliases, junctions and ``..`` components."""
    try:
        if left.samefile(right):
            return True
    except OSError:
        pass
    return os.path.normcase(str(left.resolve())) == os.path.normcase(
        str(right.resolve())
    )


def open_text_preserving_newlines(path: Path) -> TextIO:
    """Open a journal text file without loading it or translating newlines."""
    with open(path, "rb") as probe:
        marker = probe.read(4)
    encoding = (
        "utf-16"
        if marker.startswith((b"\xff\xfe", b"\xfe\xff"))
        else "utf-8-sig"
    )
    return open(path, "r", encoding=encoding, newline="")


def read_lgp_header(stream: TextIO) -> tuple[str, str, str, str, str]:
    """Return version, GUID, newline, complete header and initial body text."""
    version_line = stream.readline(4096)
    guid_line = stream.readline(4096)
    # A native blank separator is tiny. The limit avoids loading an entire first
    # event when a non-native file omits that separator.
    third_line = stream.readline(4096)
    nl = detect_newline(version_line + guid_line + third_line)
    version = version_line.rstrip("\r\n")
    guid = guid_line.rstrip("\r\n")
    if third_line.strip() == "":
        header = version_line + guid_line + third_line
        initial_body = ""
    else:
        header = version_line + guid_line
        initial_body = third_line
    if not header.endswith(("\r", "\n")):
        header += nl
    return version, guid, nl, header, initial_body


def iter_body_chunks(
    stream: TextIO, initial: str, size: int = 1024 * 1024
) -> Iterator[str]:
    if initial:
        yield initial
    while True:
        chunk = stream.read(size)
        if not chunk:
            return
        yield chunk


def make_output_temp(dst: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent)
    os.close(fd)
    return Path(name)


def verify_lgp_header(path: Path, expected_version: str, expected_guid: str) -> None:
    """Reject a temporary result whose journal identity is not the receiver's."""
    with open_text_preserving_newlines(path) as stream:
        version, guid, _, _, _ = read_lgp_header(stream)
    if version != expected_version or guid.lower() != expected_guid.lower():
        raise ValueError(
            f"Проверка результата не пройдена для {path.name}: "
            f"ожидались {expected_version}, {expected_guid}; "
            f"получены {version}, {guid}."
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(MIB)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = make_output_temp(path)
    try:
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def operation_state_path(destination: Path) -> Path:
    return destination / OPERATION_STATE_NAME


def write_operation_state(destination: Path, state: dict[str, object]) -> None:
    state["schema_version"] = OPERATION_STATE_SCHEMA
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(operation_state_path(destination), state)


def read_operation_state(destination: Path) -> dict[str, object] | None:
    path = operation_state_path(destination)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise ValueError(f"Повреждён журнал незавершённой операции {path}: {e}") from e
    if not isinstance(value, dict) or value.get("schema_version") != OPERATION_STATE_SCHEMA:
        raise ValueError(f"Неподдерживаемый формат журнала операции: {path}")
    return value


def remove_operation_state(destination: Path) -> None:
    operation_state_path(destination).unlink(missing_ok=True)


def copy_file_atomic(
    src: Path,
    dst: Path,
    expected_version: str,
    expected_guid: str,
) -> None:
    """Copy a file beside its destination and publish it in one replace."""
    temp = make_output_temp(dst)
    try:
        shutil.copy2(src, temp)
        verify_lgp_header(temp, expected_version, expected_guid)
        os.replace(temp, dst)
    finally:
        if temp.exists():
            temp.unlink()


def write_utf8(output: BinaryIO, text: str) -> None:
    output.write(text.encode("utf-8"))


def insert_comma_after_last_record(output: BinaryIO) -> None:
    """Insert a comma after a trailing record, shifting only on-disk bytes."""
    end = output.seek(0, os.SEEK_END)
    pos = end
    last = b""
    while pos:
        size = min(64 * 1024, pos)
        pos -= size
        output.seek(pos)
        block = output.read(size)
        for offset in range(size - 1, -1, -1):
            if block[offset] not in b" \t\r\n":
                pos += offset
                last = block[offset : offset + 1]
                break
        if last:
            break
    if last != b"}":
        output.seek(0, os.SEEK_END)
        return

    insert_at = pos + 1
    read_at = end
    output.truncate(end + 1)
    while read_at > insert_at:
        size = min(64 * 1024, read_at - insert_at)
        read_at -= size
        output.seek(read_at)
        block = output.read(size)
        output.seek(read_at + 1)
        output.write(block)
    output.seek(insert_at)
    output.write(b",")
    output.seek(0, os.SEEK_END)


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


def quote_name(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


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
    if obj_type in UUID_TYPES and len(tokens) >= 4:
        uuid = unquote(tokens[1])
        name = unquote(tokens[2])
        key = (uuid or name).lower()
    else:
        uuid = ""
        name = unquote(tokens[1])
        key = name.lower()
    if not key:
        return
    descr = {"type": obj_type, "number": number, "name": name, "uuid": uuid, "key": key}
    result["by_number"][obj_type][number] = descr
    result["by_key"][obj_type][key] = number
    result["max_number"][obj_type] = max(result["max_number"][obj_type], number)
    result["count"] += 1


def read_lgf(path: Path) -> dict:
    text = read_text_utf8(path)
    lines = text.splitlines()
    if not lines or HEADER_MARKER not in lines[0]:
        raise RuntimeError(f"Не словарь журнала регистрации: {path}")
    result = {
        "version": lines[0].strip(),
        "guid": lines[1].strip() if len(lines) > 1 else "",
        "by_number": {t: {} for t in range(1, 9)},
        "by_key": {t: {} for t in range(1, 9)},
        "max_number": {t: 0 for t in range(1, 9)},
        "count": 0,
        "newline": detect_newline(text),
        "raw_text": text,
    }
    for record in iter_lgf_records(lines):
        add_lgf_record(result, record)
    return result


def format_lgf_row(descr: dict, number: int) -> str:
    t = descr["type"]
    n = str(number)
    ts = str(t)
    if t in UUID_TYPES:
        uuid = descr["uuid"] or '""'
        if uuid != '""' and not uuid.startswith('"'):
            # native: UUID without quotes
            pass
        else:
            uuid = '""' if not descr["uuid"] else descr["uuid"]
        if not descr["uuid"]:
            uuid_part = '""'
        else:
            uuid_part = descr["uuid"]
        return "{" + ts + "," + uuid_part + "," + quote_name(descr["name"]) + "," + n + "},"
    if t in PORT_TYPES:
        return "{" + ts + "," + descr["name"] + "," + n + "},"
    return "{" + ts + "," + quote_name(descr["name"]) + "," + n + "},"


def build_maps(src: dict, dst: dict) -> dict:
    maps: dict[int, dict[int, int]] = {}
    added_rows: list[str] = []
    need_remap = False
    # mutate copies of max/by_key so caller dst stays consistent after append
    max_n = dict(dst["max_number"])
    by_key = {t: dict(dst["by_key"][t]) for t in range(1, 9)}
    for obj_type in range(1, 9):
        mapping: dict[int, int] = {}
        for old_number, descr in src["by_number"][obj_type].items():
            new_number = by_key[obj_type].get(descr["key"])
            if new_number is None:
                max_n[obj_type] += 1
                new_number = max_n[obj_type]
                added_rows.append(format_lgf_row(descr, new_number))
                by_key[obj_type][descr["key"]] = new_number
            mapping[old_number] = new_number
            if new_number != old_number:
                need_remap = True
        maps[obj_type] = mapping
    return {
        "maps": maps,
        "added_rows": added_rows,
        "need_remap": need_remap,
        "max_number": max_n,
        "by_key": by_key,
    }


def normalize_jr_dir(path: Path) -> Path:
    if (path / "1Cv8.lgf").exists():
        return path
    nested = path / "1Cv8Log"
    if (nested / "1Cv8.lgf").exists():
        return nested
    raise FileNotFoundError(f"1Cv8.lgf не найден в {path}")


def split_header_body(text: str) -> tuple[str, str]:
    nl = detect_newline(text)
    # Keep structural newlines; find end of header (version, guid, blank)
    lines_with = text.splitlines(keepends=True)
    if len(lines_with) < 2:
        return text, ""
    idx = 2
    if idx < len(lines_with) and lines_with[idx].strip() == "":
        idx += 1
    header = "".join(lines_with[:idx])
    body = "".join(lines_with[idx:])
    # Ensure header ends with blank line terminator for native layout
    if not header.endswith(("\n", "\r")):
        header += nl
    return header, body


def ensure_trailing_comma_on_last_record(body: str) -> str:
    if not body.strip():
        return body
    # Find last top-level record end
    depth = 0
    in_quotes = False
    last_end = -1
    i = 0
    while i < len(body):
        ch = body[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < len(body) and body[i + 1] == '"':
                    i += 2
                    continue
                in_quotes = False
            i += 1
            continue
        if ch == '"':
            in_quotes = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_end = i
        i += 1
    if last_end < 0:
        return body
    j = last_end + 1
    while j < len(body) and body[j] in " \t":
        j += 1
    if j < len(body) and body[j] == ",":
        return body
    return body[: last_end + 1] + "," + body[last_end + 1 :]


def strip_trailing_comma_last_lgf_line(lines: list[str]) -> None:
    i = len(lines) - 1
    while i >= 0 and not lines[i].strip():
        i -= 1
    if i < 0:
        return
    s = lines[i].rstrip()
    if s.endswith(","):
        lines[i] = s[:-1]


def append_rows_to_lgf(path: Path, rows: list[str], newline: str) -> None:
    if not rows:
        return
    text = read_text_utf8(path)
    nl = detect_newline(text) or newline
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        last = lines[-1].rstrip()
        if last and not last.endswith(","):
            lines[-1] = last + ","
    lines.extend(r.rstrip(",") + "," for r in rows)
    strip_trailing_comma_last_lgf_line(lines)
    write_text_utf8(path, nl.join(lines) + nl)


def top_level_token_spans(text: str) -> list[tuple[int, int]]:
    """Return field spans inside the first outer brace without copying fields."""
    opening = text.find("{")
    if opening < 0:
        return []
    spans: list[tuple[int, int]] = []
    token_start = opening + 1
    depth = 0
    in_quotes = False
    i = token_start
    while i < len(text):
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    i += 2
                    continue
                in_quotes = False
        elif ch == '"':
            in_quotes = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            if depth == 0:
                spans.append((token_start, i))
                return spans
            depth -= 1
        elif ch == "," and depth == 0:
            spans.append((token_start, i))
            token_start = i + 1
        i += 1
    return []


def replace_number_token(token: str, mapping: dict[int, int] | None) -> str:
    """Replace one numeric field while retaining its surrounding whitespace."""
    if mapping is None:
        return token
    left = len(token) - len(token.lstrip())
    right = len(token.rstrip())
    value = token[left:right]
    if not value.isdigit():
        return token
    replacement = mapping.get(int(value))
    if replacement is None:
        return token
    return token[:left] + str(replacement) + token[right:]


def renumber_composite(token: str, mapping: dict[int, int] | None) -> str:
    if mapping is None:
        return token
    spans = top_level_token_spans(token)
    if not spans:
        return replace_number_token(token, mapping)
    result = token
    for start, end in reversed(spans):
        old = result[start:end]
        new = replace_number_token(old, mapping)
        if new != old:
            result = result[:start] + new + result[end:]
    return result


def renumber_record_preserving_breaks(
    buffer: str,
    maps: dict[int, dict[int, int]],
    spans: list[tuple[int, int]] | None = None,
) -> str:
    if spans is None:
        spans = top_level_token_spans(buffer)
    if not spans:
        return buffer
    result = buffer
    for idx, obj_type, composite in reversed(REF_FIELDS):
        if idx >= len(spans):
            continue
        start, end = spans[idx]
        old = result[start:end]
        mapping = maps.get(obj_type)
        new = (
            renumber_composite(old, mapping)
            if composite
            else replace_number_token(old, mapping)
        )
        if new != old:
            result = result[:start] + new + result[end:]
    return result


def iter_top_level_records(body: str) -> Iterable[str]:
    depth = 0
    in_quotes = False
    buf: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if in_quotes:
            buf.append(ch)
            if ch == '"':
                if i + 1 < len(body) and body[i + 1] == '"':
                    buf.append('"')
                    i += 2
                    continue
                in_quotes = False
            i += 1
            continue
        if ch == '"':
            in_quotes = True
            buf.append(ch)
        elif ch == "{":
            depth += 1
            buf.append(ch)
        elif ch == "}":
            depth -= 1
            buf.append(ch)
            if depth == 0 and buf:
                # include optional trailing comma and whitespace until next '{'
                j = i + 1
                while j < len(body) and body[j] in " \t":
                    buf.append(body[j])
                    j += 1
                if j < len(body) and body[j] == ",":
                    buf.append(",")
                    j += 1
                while j < len(body) and body[j] in " \t\r\n":
                    # keep structural newlines between records
                    if body.startswith("\r\n", j):
                        buf.append("\r\n")
                        j += 2
                    elif body[j] in "\r\n":
                        buf.append(body[j])
                        j += 1
                    else:
                        buf.append(body[j])
                        j += 1
                    if j < len(body) and body[j] == "{":
                        break
                yield "".join(buf)
                buf = []
                i = j
                continue
        elif depth == 0:
            pass
        else:
            buf.append(ch)
        i += 1


def iter_top_level_records_with_spans_stream(
    chunks: Iterable[str],
) -> Iterator[tuple[str, list[tuple[int, int]]]]:
    """Parse records and retain field spans discovered during the same pass."""
    depth = 0
    in_quotes = False
    quote_pending = False
    complete = False
    buf: list[str] = []
    spans: list[tuple[int, int]] = []
    token_start = 0

    for chunk in chunks:
        for ch in chunk:
            reprocess = True
            while reprocess:
                reprocess = False
                if complete:
                    if ch == "{":
                        yield "".join(buf), spans
                        buf = [ch]
                        depth = 1
                        spans = []
                        token_start = 1
                        complete = False
                    elif ch in " \t\r\n,":
                        buf.append(ch)
                    continue

                if depth == 0:
                    if ch == "{":
                        buf = [ch]
                        depth = 1
                        spans = []
                        token_start = 1
                    continue

                if in_quotes:
                    if quote_pending:
                        if ch == '"':
                            buf.append(ch)
                            quote_pending = False
                            continue
                        in_quotes = False
                        quote_pending = False
                        reprocess = True
                        continue
                    buf.append(ch)
                    if ch == '"':
                        quote_pending = True
                    continue

                buf.append(ch)
                position = len(buf) - 1
                if ch == '"':
                    in_quotes = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    if depth == 1:
                        spans.append((token_start, position))
                    depth -= 1
                    if depth == 0:
                        complete = True
                elif ch == "," and depth == 1:
                    spans.append((token_start, position))
                    token_start = position + 1

    if complete and buf:
        yield "".join(buf), spans


def iter_top_level_records_stream(chunks: Iterable[str]) -> Iterator[str]:
    """Compatibility wrapper yielding only record text."""
    for record, _ in iter_top_level_records_with_spans_stream(chunks):
        yield record


def file_locked(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with open(path, "a+b"):
            return False
    except OSError:
        return True


def delete_lgx(dst_dir: Path) -> int:
    n = 0
    for p in dst_dir.glob("*.lgx"):
        try:
            p.unlink()
            n += 1
        except OSError as e:
            log(f"Не удалось удалить индекс {p.name}: {e}")
    return n


def copy_lgp_with_header(src: Path, dst: Path, version: str, guid: str) -> None:
    temp = make_output_temp(dst)
    try:
        with open_text_preserving_newlines(src) as source, open(temp, "wb") as output:
            _, _, nl, _, initial = read_lgp_header(source)
            output.write(b"\xef\xbb\xbf")
            write_utf8(output, version + nl + guid + nl + nl)
            for chunk in iter_body_chunks(source, initial):
                write_utf8(output, chunk)
        verify_lgp_header(temp, version, guid)
        os.replace(temp, dst)
    finally:
        if temp.exists():
            temp.unlink()


def merge_lgp_raw(src: Path, dst: Path) -> bool:
    temp = make_output_temp(dst)
    source_has_body = False
    try:
        with (
            open_text_preserving_newlines(src) as source,
            open_text_preserving_newlines(dst) as destination,
            open(temp, "w+b") as output,
        ):
            _, _, _, _, src_initial = read_lgp_header(source)
            dst_version, dst_guid, _, dst_header, dst_initial = read_lgp_header(
                destination
            )
            output.write(b"\xef\xbb\xbf")
            write_utf8(output, dst_header)
            for chunk in iter_body_chunks(destination, dst_initial):
                write_utf8(output, chunk)
            insert_comma_after_last_record(output)
            for chunk in iter_body_chunks(source, src_initial):
                if chunk.strip():
                    source_has_body = True
                write_utf8(output, chunk)
        if source_has_body:
            verify_lgp_header(temp, dst_version, dst_guid)
            os.replace(temp, dst)
        return source_has_body
    finally:
        if temp.exists():
            temp.unlink()


def rewrite_lgp_renumber(
    src: Path,
    dst: Path,
    version: str,
    guid: str,
    maps: dict[int, dict[int, int]],
    *,
    merge: bool,
) -> int:
    temp = make_output_temp(dst)
    count = 0
    try:
        with open_text_preserving_newlines(src) as source:
            _, _, nl, _, initial = read_lgp_header(source)
            records = iter_top_level_records_with_spans_stream(
                iter_body_chunks(source, initial)
            )
            first = next(records, None)
            if first is None and merge and dst.exists():
                return 0

            with open(temp, "w+b") as output:
                output.write(b"\xef\xbb\xbf")
                if merge and dst.exists():
                    with open_text_preserving_newlines(dst) as destination:
                        _, _, _, header, dst_initial = read_lgp_header(destination)
                        write_utf8(output, header)
                        for chunk in iter_body_chunks(destination, dst_initial):
                            write_utf8(output, chunk)
                    insert_comma_after_last_record(output)
                else:
                    write_utf8(output, version + nl + guid + nl + nl)

                if first is not None:
                    first_record, first_spans = first
                    write_utf8(
                        output,
                        renumber_record_preserving_breaks(
                            first_record, maps, first_spans
                        ),
                    )
                    count = 1
                for rec, rec_spans in records:
                    write_utf8(
                        output,
                        renumber_record_preserving_breaks(rec, maps, rec_spans),
                    )
                    count += 1
                    if count % 5000 == 0:
                        log(f"  … перенумеровано записей: {count}")
        verify_lgp_header(temp, version, guid)
        os.replace(temp, dst)
        return count
    finally:
        if temp.exists():
            temp.unlink()


def analyze_cmd(src_dir: Path, dst_dir: Path) -> int:
    src_dir = normalize_jr_dir(src_dir)
    dst_dir = normalize_jr_dir(dst_dir)
    if paths_refer_to_same_location(src_dir, dst_dir):
        log("Каталоги источника и приёмника указывают на один и тот же каталог.")
        return EXIT_VALIDATION
    src = read_lgf(src_dir / "1Cv8.lgf")
    dst = read_lgf(dst_dir / "1Cv8.lgf")
    result = build_maps(src, dst)
    src_lgp = sorted(p.name for p in src_dir.glob("*.lgp"))
    dst_lgp = {p.name for p in dst_dir.glob("*.lgp")}
    log(f"SRC: {src_dir}")
    log(f"DST: {dst_dir}")
    log(f"SRC dictionary entries: {src['count']}")
    log(f"DST dictionary entries: {dst['count']}")
    log(f"Same GUID: {src['guid'].lower() == dst['guid'].lower()}")
    log(f"Need remap: {result['need_remap']}")
    log(f"New dictionary rows: {len(result['added_rows'])}")
    log(f"SRC lgp ({len(src_lgp)}): {', '.join(src_lgp)}")
    for name in src_lgp:
        action = "merge" if name in dst_lgp else "copy"
        size = (src_dir / name).stat().st_size
        log(f"  {name}: {action}, {size} bytes")
    log("ANALYZE OK")
    return EXIT_OK


def parse_files_list(
    files: str | None, files_from: Path | None, src_dir: Path
) -> list[tuple[str, str | None]]:
    """Return list of (name, optional per-file conflict override)."""
    items: list[tuple[str, str | None]] = []

    def safe_lgp_name(raw: str) -> str:
        candidate = raw.strip()
        if (
            not candidate
            or candidate != Path(candidate).name
            or "/" in candidate
            or "\\" in candidate
            or ":" in candidate
            or Path(candidate).suffix.lower() != ".lgp"
        ):
            raise ValueError(f"Недопустимое имя файла периода: {raw!r}")
        return candidate

    def normalized_action(raw: str | None) -> str | None:
        if raw is None or not raw.strip():
            return None
        value = raw.strip().lower()
        aliases = {
            "merge": "merge",
            "объединить": "merge",
            "skip": "skip",
            "пропустить": "skip",
            "replace": "replace",
            "заменить": "replace",
            "copy": "copy",
            "скопировать": "copy",
        }
        if value not in aliases:
            raise ValueError(f"Неизвестное действие для файла: {raw!r}")
        return aliases[value]
    if files_from is not None:
        text = files_from.read_text(encoding="utf-8-sig")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                name, action = line.split("|", 1)
                items.append((safe_lgp_name(name), normalized_action(action)))
            else:
                items.append((safe_lgp_name(line), None))
    if files:
        for part in files.split(","):
            part = part.strip()
            if part:
                items.append((safe_lgp_name(part), None))
    if not items:
        items = [(p.name, None) for p in sorted(src_dir.glob("*.lgp"))]
    seen: set[str] = set()
    out: list[tuple[str, str | None]] = []
    for name, action in items:
        if name not in seen:
            seen.add(name)
            out.append((name, action))
    return out


def estimate_lgp_temp_bytes(
    source_bytes: int,
    destination_bytes: int,
    action: str,
    need_remap: bool,
) -> int:
    """Conservative peak size of the temporary file published beside LGP."""
    transformed_source = source_bytes * 2 if need_remap else source_bytes
    if action == "merge":
        transformed_source += destination_bytes
    return transformed_source + MIB


def required_free_space_bytes(
    plan: list[tuple[str, Path, Path, str]],
    need_remap: bool,
    lgf_destination_bytes: int,
    added_lgf_bytes: int,
) -> int:
    """Return free bytes needed before the first destination mutation."""
    rollback_bytes = lgf_destination_bytes if added_lgf_bytes else 0
    largest_temp = (
        rollback_bytes + lgf_destination_bytes + added_lgf_bytes + MIB
    )
    committed_growth = rollback_bytes + added_lgf_bytes
    for _, source, destination, action in plan:
        destination_bytes = destination.stat().st_size if destination.exists() else 0
        source_bytes = source.stat().st_size
        transformed_source = source_bytes * 2 if need_remap else source_bytes
        final_bytes = transformed_source
        if action == "merge":
            final_bytes += destination_bytes
        temp_bytes = estimate_lgp_temp_bytes(
            source_bytes,
            destination_bytes,
            action,
            need_remap,
        )
        largest_temp = max(largest_temp, committed_growth + temp_bytes)
        committed_growth += max(0, final_bytes - destination_bytes)
    return largest_temp + FREE_SPACE_MARGIN


def make_lgf_rollback_copy(path: Path) -> Path:
    rollback = make_output_temp(path)
    try:
        shutil.copy2(path, rollback)
        return rollback
    except OSError:
        if rollback.exists():
            rollback.unlink()
        raise


def finish_failed_attach(
    lgf_rollback: Path | None,
    lgf_destination: Path,
    published_files: list[str],
) -> None:
    """Keep dictionary consistency after a failed multi-file operation."""
    if lgf_rollback is None:
        return
    if published_files:
        log(
            "Частичный результат: словарь сохранён, потому что уже "
            "опубликованы LGP: " + ", ".join(published_files)
        )
        log("Повторите присоединение для оставшихся файлов после устранения ошибки.")
        try:
            lgf_rollback.unlink(missing_ok=True)
        except OSError as e:
            log(f"Не удалось удалить резервную копию 1Cv8.lgf: {e}")
        return
    try:
        os.replace(lgf_rollback, lgf_destination)
        log("Изменения 1Cv8.lgf отменены: ни один LGP не был опубликован.")
    except OSError as e:
        log(
            "Не удалось автоматически восстановить 1Cv8.lgf. "
            f"Копия сохранена в {lgf_rollback}: {e}"
        )


def attach_cmd(
    src_dir: Path,
    dst_dir: Path,
    *,
    conflict: str,
    files: str | None,
    files_from: Path | None,
    dedup: bool,
    split_by_day: bool,
    report_json: Path | None = None,
) -> int:
    if dedup or split_by_day:
        log(
            "MVP Python: опции --dedup / --split-by-day пока не реализованы. "
            "Выполните присоединение в обработке 1С или отключите эти галки."
        )
        return EXIT_VALIDATION

    try:
        src_dir = normalize_jr_dir(src_dir)
        dst_dir = normalize_jr_dir(dst_dir)
    except FileNotFoundError as e:
        log(str(e))
        return EXIT_VALIDATION

    if paths_refer_to_same_location(src_dir, dst_dir):
        log("Каталоги источника и приёмника указывают на один и тот же каталог.")
        return EXIT_VALIDATION

    if report_json is not None and report_json.suffix.lower() != ".json":
        log("Итоговый отчёт должен иметь расширение .json.")
        return EXIT_VALIDATION

    lgf_src = src_dir / "1Cv8.lgf"
    lgf_dst = dst_dir / "1Cv8.lgf"
    if not lgf_src.exists() or not lgf_dst.exists():
        log("Не найден 1Cv8.lgf в источнике или приёмнике.")
        return EXIT_VALIDATION

    for probe in (lgf_dst,):
        if file_locked(probe):
            log(f"Файл занят (нет записи): {probe}")
            return EXIT_BUSY

    try:
        file_items = parse_files_list(files, files_from, src_dir)
    except (OSError, UnicodeError, ValueError) as e:
        log(str(e))
        return EXIT_VALIDATION
    if not file_items:
        log("Нет файлов .lgp для присоединения.")
        return EXIT_VALIDATION

    log("=== Начало присоединения (Python) ===")
    log(f"SRC: {src_dir}")
    log(f"DST: {dst_dir}")
    log(f"Conflict default: {conflict}")
    log(f"Files: {', '.join(n for n, _ in file_items)}")

    src = read_lgf(lgf_src)
    dst = read_lgf(lgf_dst)
    maps_info = build_maps(src, dst)
    need_remap = maps_info["need_remap"]
    log(f"Need remap: {need_remap}")
    log(f"New dictionary rows: {len(maps_info['added_rows'])}")

    plan: list[tuple[str, Path, Path, str]] = []
    for name, per_file in file_items:
        src_path = src_dir / name
        dst_path = dst_dir / name
        if not src_path.exists():
            log(f"Пропуск (нет в источнике): {name}")
            continue
        exists = dst_path.exists()
        action = per_file or conflict or "merge"
        if not exists:
            action = "copy"
        elif action == "skip":
            log(f"Пропущен (уже есть): {name}")
            continue
        if action not in ("copy", "replace", "merge"):
            log(f"Неизвестный режим конфликта: {action}")
            return EXIT_VALIDATION
        if file_locked(dst_path):
            log(f"Файл приёмника занят: {name}")
            return EXIT_BUSY
        plan.append((name, src_path, dst_path, action))

    if not plan:
        log("Нет файлов .lgp, требующих присоединения.")
        return EXIT_VALIDATION

    added_lgf_bytes = sum(
        len((row + dst["newline"]).encode("utf-8"))
        for row in maps_info["added_rows"]
    )
    try:
        required_bytes = required_free_space_bytes(
            plan,
            need_remap,
            lgf_dst.stat().st_size,
            added_lgf_bytes,
        )
        free_bytes = shutil.disk_usage(dst_dir).free
    except OSError as e:
        log(f"Не удалось определить свободное место: {e}")
        return EXIT_BUSY
    log(
        f"Свободное место: {free_bytes / MIB:.1f} МиБ; "
        f"требуется не менее {required_bytes / MIB:.1f} МиБ."
    )
    if free_bytes < required_bytes:
        log("Недостаточно свободного места для безопасной временной записи.")
        return EXIT_BUSY

    lgf_rollback: Path | None = None
    try:
        if maps_info["added_rows"]:
            lgf_rollback = make_lgf_rollback_copy(lgf_dst)
        append_rows_to_lgf(lgf_dst, maps_info["added_rows"], dst["newline"])
    except OSError as e:
        if lgf_rollback is not None:
            finish_failed_attach(lgf_rollback, lgf_dst, [])
        log(f"Не удалось обновить словарь: {e}")
        return EXIT_BUSY

    if maps_info["added_rows"]:
        log(f"В 1Cv8.lgf добавлено записей: {len(maps_info['added_rows'])}")
    else:
        log("Словарь приёмника уже содержит все объекты источника.")

    processed = 0
    published_files: list[str] = []
    file_results: list[dict[str, object]] = []
    for name, src_path, dst_path, action in plan:
        if file_locked(dst_path):
            log(f"Файл приёмника занят: {name}")
            finish_failed_attach(lgf_rollback, lgf_dst, published_files)
            return EXIT_BUSY

        log(f"Обработка {name} ({action}, remap={need_remap})…")
        records_processed: int | None = None
        current_published = False
        try:
            if action in ("replace", "copy"):
                if need_remap:
                    records_processed = rewrite_lgp_renumber(
                        src_path,
                        dst_path,
                        dst["version"],
                        dst["guid"],
                        maps_info["maps"],
                        merge=False,
                    )
                    current_published = True
                    log(f"Переписан с перенумерацией: {name}")
                else:
                    try:
                        with open_text_preserving_newlines(src_path) as source:
                            src_ver, src_hdr_guid, _, _, _ = read_lgp_header(source)
                    except OSError:
                        src_hdr_guid = ""
                        src_ver = ""
                    if (
                        src_hdr_guid.lower() != dst["guid"].lower()
                        or src_ver != dst["version"]
                    ):
                        copy_lgp_with_header(src_path, dst_path, dst["version"], dst["guid"])
                        current_published = True
                        log(f"Скопирован с заголовком приёмника: {name}")
                    else:
                        copy_file_atomic(
                            src_path,
                            dst_path,
                            dst["version"],
                            dst["guid"],
                        )
                        current_published = True
                        log(f"Скопирован: {name}")
            elif action == "merge":
                if need_remap:
                    records_processed = rewrite_lgp_renumber(
                        src_path,
                        dst_path,
                        dst["version"],
                        dst["guid"],
                        maps_info["maps"],
                        merge=True,
                    )
                    current_published = records_processed > 0
                    log(f"Объединён с перенумерацией: {name}")
                else:
                    current_published = merge_lgp_raw(src_path, dst_path)
                    log(f"Объединён: {name}")
            else:
                log(f"Неизвестный режим конфликта: {action}")
                return EXIT_VALIDATION
            verify_lgp_header(dst_path, dst["version"], dst["guid"])
            result: dict[str, object] = {
                "name": name,
                "action": action,
                "renumbered": need_remap,
                "size_bytes": dst_path.stat().st_size,
                "records_processed": records_processed,
                "version": dst["version"],
                "guid": dst["guid"],
            }
            if report_json is not None:
                result["sha256"] = sha256_file(dst_path)
        except (OSError, ValueError) as e:
            if current_published:
                published_files.append(name)
            log(f"Ошибка записи {name}: {e}")
            finish_failed_attach(lgf_rollback, lgf_dst, published_files)
            return EXIT_BUSY
        if current_published:
            published_files.append(name)
        file_results.append(result)
        records_text = (
            str(records_processed)
            if records_processed is not None
            else "не подсчитывались (быстрый побайтовый режим)"
        )
        log(
            f"Проверено: {name}; размер {result['size_bytes']} байт; "
            f"записей источника: {records_text}."
        )
        processed += 1

    n_lgx = delete_lgx(dst_dir)
    log(f"Обработано файлов: {processed}")
    log(f"Удалено индексов *.lgx: {n_lgx}")
    if report_json is not None:
        report = {
            "schema_version": 1,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": str(src_dir),
            "destination": str(dst_dir),
            "files_processed": processed,
            "indexes_deleted": n_lgx,
            "files": file_results,
        }
        try:
            write_json_atomic(report_json, report)
            log(f"Итоговый JSON-отчёт: {report_json}")
        except OSError as e:
            log(
                "Присоединение завершено, но итоговый JSON-отчёт "
                f"не удалось сохранить: {e}"
            )
    if lgf_rollback is not None:
        try:
            lgf_rollback.unlink(missing_ok=True)
        except OSError as e:
            log(f"Не удалось удалить резервную копию 1Cv8.lgf: {e}")
    log("=== Конец присоединения (Python) ===")
    log("ATTACH OK")
    return EXIT_OK


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Ускоренное присоединение журнала регистрации (lgf/lgp), MVP"
    )
    p.add_argument("--src", required=True, help="Каталог старого ЖР (1Cv8Log)")
    p.add_argument("--dst", required=True, help="Каталог текущего ЖР (1Cv8Log)")
    p.add_argument(
        "--mode",
        choices=("analyze", "attach"),
        required=True,
        help="analyze — план; attach — запись",
    )
    p.add_argument(
        "--conflict",
        choices=("merge", "skip", "replace"),
        default="merge",
        help="Если файл периода уже есть в приёмнике",
    )
    p.add_argument("--files", default=None, help="Список имён .lgp через запятую")
    p.add_argument(
        "--files-from",
        default=None,
        help="Файл со списком имён .lgp (по одному в строке)",
    )
    p.add_argument("--dedup", action="store_true", help="Дедуп (MVP: не поддерживается)")
    p.add_argument(
        "--split-by-day",
        action="store_true",
        help="Разбивка по дням (MVP: не поддерживается)",
    )
    p.add_argument("--out-log", default=None, help="Путь к лог-файлу прогресса (UTF-8)")
    p.add_argument(
        "--report-json",
        default=None,
        help="Итоговый JSON с проверенными заголовками, размерами и SHA-256",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    global _log_fp
    args = build_arg_parser().parse_args(argv)
    out_log = Path(args.out_log) if args.out_log else None
    if out_log is not None:
        out_log.parent.mkdir(parents=True, exist_ok=True)
        _log_fp = open(out_log, "w", encoding="utf-8", newline="\n")
    try:
        src = Path(args.src)
        dst = Path(args.dst)
        if args.mode == "analyze":
            return analyze_cmd(src, dst)
        return attach_cmd(
            src,
            dst,
            conflict=args.conflict,
            files=args.files,
            files_from=Path(args.files_from) if args.files_from else None,
            dedup=args.dedup,
            split_by_day=args.split_by_day,
            report_json=Path(args.report_json) if args.report_json else None,
        )
    except Exception as e:  # noqa: BLE001 — CLI boundary
        log(f"Ошибка: {e}")
        return EXIT_VALIDATION
    finally:
        if _log_fp is not None:
            _log_fp.close()
            _log_fp = None


if __name__ == "__main__":
    raise SystemExit(main())
