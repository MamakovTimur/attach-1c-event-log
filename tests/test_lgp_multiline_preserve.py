# Regression: renumber must preserve LF/CRLF break types inside .lgp records.

from __future__ import annotations


def collect_flat_and_breaks(buffer: str) -> tuple[str, list[tuple[int, str]]]:
    flat_chars: list[str] = []
    breaks: list[tuple[int, str]] = []
    i = 0
    while i < len(buffer):
        if buffer.startswith("\r\n", i):
            breaks.append((len(flat_chars), "\r\n"))
            i += 2
        elif buffer[i] == "\n":
            breaks.append((len(flat_chars), "\n"))
            i += 1
        elif buffer[i] == "\r":
            breaks.append((len(flat_chars), "\r"))
            i += 1
        else:
            flat_chars.append(buffer[i])
            i += 1
    return "".join(flat_chars), breaks


def adjust_breaks(breaks: list[tuple[int, str]], threshold: int, delta: int) -> None:
    for i, (pos, br) in enumerate(breaks):
        if pos >= threshold:
            breaks[i] = (pos + delta, br)


def insert_breaks(flat: str, breaks: list[tuple[int, str]]) -> str:
    result = flat
    for pos, br in reversed(breaks):
        if 0 <= pos <= len(result):
            result = result[:pos] + br + result[pos:]
    return result


def renumber_flat_preserve_lines(buffer: str, replacements: dict[str, str]) -> str:
    """Mirror of ПеренумероватьЗаписьLgpСохраняяСтроки with typed breaks."""
    flat, breaks = collect_flat_and_breaks(buffer)
    stripped = flat.rstrip(",")
    assert stripped.startswith("{") and stripped.endswith("}")

    body = stripped[1:-1]
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    in_quotes = False
    for ch in body:
        if in_quotes:
            current.append(ch)
            if ch == '"':
                in_quotes = False
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
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current or body:
        parts.append("".join(current).strip())

    new_parts = list(parts)
    pos = 2
    for i, old in enumerate(parts):
        new = replacements.get(old, old)
        delta = len(new) - len(old)
        if delta:
            adjust_breaks(breaks, pos + len(old), delta)
        new_parts[i] = new
        pos += len(old) + 1

    trailing = flat.endswith(",")
    new_flat = "{" + ",".join(new_parts) + "}"
    if trailing:
        new_flat += ","
    return insert_breaks(new_flat, breaks)


SAMPLE = (
    "{20260819070002,N,\n"
    "{0,0},1,1,1,144608,1,I,\"\",0,\n"
    "{\"U\"},\"\",1,1,0,1,0,\n"
    "{0}\n"
    "},"
)

SAMPLE_MIXED = (
    "{20260819070002,N,\r\n"
    '{0,0},1,1,1,144608,1,I,"line\nwith LF",0,\r\n'
    '{"U"},"",1,1,0,1,0,\r\n'
    "{0}\r\n"
    "},"
)


def test_renumber_keeps_line_count() -> None:
    result = renumber_flat_preserve_lines(SAMPLE, {"1": "99", "144608": "200000"})
    assert result.count("\n") == SAMPLE.count("\n")
    assert "99" in result
    assert "200000" in result
    assert result.endswith("},") or result.rstrip().endswith("},")


def test_no_single_line_when_source_multiline() -> None:
    result = renumber_flat_preserve_lines(SAMPLE, {"1": "2"})
    lines = result.split("\n")
    assert len(lines) == 5
    assert lines[0].startswith("{20260819070002,N,")


def test_single_line_record_unchanged_layout() -> None:
    one_line = "{20260819070002,N,{0,0},1,1,1,144608,1,I,\"\",0,{\"U\"},\"\",1,1,0,1,0,{0}},"
    result = renumber_flat_preserve_lines(one_line, {"144608": "999"})
    assert "\n" not in result
    assert "999" in result


def test_preserves_lf_inside_quotes_and_crlf_structure() -> None:
    result = renumber_flat_preserve_lines(SAMPLE_MIXED, {"144608": "200000"})
    assert "line\nwith LF" in result
    assert result.count("\r\n") == SAMPLE_MIXED.count("\r\n")
    # one LF-only (inside quotes) remains LF-only
    lf_only = result.count("\n") - result.count("\r\n")
    assert lf_only == 1
    assert "200000" in result


if __name__ == "__main__":
    test_renumber_keeps_line_count()
    test_no_single_line_when_source_multiline()
    test_single_line_record_unchanged_layout()
    test_preserves_lf_inside_quotes_and_crlf_structure()
    print("OK")
