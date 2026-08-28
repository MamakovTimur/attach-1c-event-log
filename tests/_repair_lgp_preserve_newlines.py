# Rebuild .lgp from native SRC with renumbering, preserving LF/CRLF exactly.
# Root cause of «Ошибка формата потока»: ЗаписатьСтроку turned in-string LF into CRLF.
from __future__ import annotations

import sys
from pathlib import Path

# allow import of smoke_analyze
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_analyze import build_maps, read_lgf, tokenize  # noqa: E402

SRC_DIR = Path(r"C:\Users\mamak\OneDrive\Desktop\1")
DST_LGF = Path(r"C:\Users\mamak\OneDrive\Desktop\2\1Cv8.lgf")
OUT_DIR = Path(r"C:\Users\mamak\OneDrive\Desktop\2_repaired")

# Field indices 0-based (Infostart 1-based minus 1) — mirror Module.bsl ПоляСсылокЗаписиLgp
# Session field (index 16) is NOT remapped.
REF_FIELDS = [
    (3, 1, False),   # users
    (4, 2, False),   # computers
    (5, 3, False),   # apps
    (7, 4, False),   # events
    (10, 5, True),   # metadata composite
    (13, 6, False),  # servers
    (14, 7, False),  # main ports
    (15, 8, False),  # add ports
]


def flatten_keep_breaks(text: str) -> tuple[str, list[tuple[int, str]]]:
    flat: list[str] = []
    breaks: list[tuple[int, str]] = []
    i = 0
    while i < len(text):
        if text.startswith("\r\n", i):
            breaks.append((len(flat), "\r\n"))
            i += 2
        elif text[i] == "\n":
            breaks.append((len(flat), "\n"))
            i += 1
        elif text[i] == "\r":
            breaks.append((len(flat), "\r"))
            i += 1
        else:
            flat.append(text[i])
            i += 1
    return "".join(flat), breaks


def adjust_breaks(breaks: list[tuple[int, str]], threshold: int, delta: int) -> None:
    for i, (pos, br) in enumerate(breaks):
        if pos >= threshold:
            breaks[i] = (pos + delta, br)


def insert_breaks(flat: str, breaks: list[tuple[int, str]]) -> str:
    if not breaks:
        return flat
    parts: list[str] = []
    last = 0
    for pos, br in breaks:
        parts.append(flat[last:pos])
        parts.append(br)
        last = pos
    parts.append(flat[last:])
    return "".join(parts)


def replace_number(token: str, mapping: dict[int, int]) -> str:
    t = token.strip()
    if not t.isdigit():
        return token
    n = int(t)
    new = mapping.get(n)
    if new is None or new == n:
        return token
    # preserve surrounding spaces if any
    return token.replace(t, str(new), 1)


def renumber_composite(token: str, mapping: dict[int, int]) -> str:
    s = token.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return token
    body = s[1:-1]
    parts = tokenize(body)
    changed = False
    new_parts = []
    for p in parts:
        np = replace_number(p, mapping)
        if np != p:
            changed = True
        new_parts.append(np)
    if not changed:
        return token
    return "{" + ",".join(new_parts) + "}"


def renumber_record(record: str, maps: dict[int, dict[int, int]]) -> str:
    flat, breaks = flatten_keep_breaks(record)
    stripped = flat.rstrip()
    trailing_comma = stripped.endswith(",")
    core = stripped[:-1] if trailing_comma else stripped
    # also strip spaces after for safety
    core_s = core.strip()
    if not (core_s.startswith("{") and core_s.endswith("}")):
        return record
    body = core_s[1:-1]
    tokens = tokenize(body)
    new_tokens = list(tokens)
    for idx, typ, composite in REF_FIELDS:
        if idx >= len(new_tokens):
            continue
        if composite:
            new_tokens[idx] = renumber_composite(new_tokens[idx], maps.get(typ, {}))
        else:
            new_tokens[idx] = replace_number(new_tokens[idx], maps.get(typ, {}))

    # adjust breaks for length changes (same algorithm as BSL)
    pos = 2  # after '{'
    for old, new in zip(tokens, new_tokens):
        delta = len(new) - len(old)
        if delta:
            adjust_breaks(breaks, pos + len(old), delta)
        pos += len(old) + 1

    new_flat = "{" + ",".join(new_tokens) + "}"
    if trailing_comma:
        new_flat += ","
    # preserve any trailing whitespace after comma that flat had? rare
    return insert_breaks(new_flat, breaks)


def iter_records_raw(text: str) -> tuple[str, list[str]]:
    """Return (header_including_blank, list of raw record strings with original separators)."""
    # Find end of header: version line, guid line, blank line — tolerate \r\n or \n
    m_ver = 0
    # scan first three logical lines keeping exact bytes
    i = 0
    lines_found = 0
    while i < len(text) and lines_found < 3:
        if text.startswith("\r\n", i):
            lines_found += 1
            i += 2
            continue
        if text[i] == "\n":
            lines_found += 1
            i += 1
            continue
        i += 1
    header = text[:i]
    body = text[i:]

    records: list[str] = []
    buf_start = 0
    depth = 0
    in_q = False
    j = 0
    while j < len(body):
        ch = body[j]
        if in_q:
            if ch == '"':
                if j + 1 < len(body) and body[j + 1] == '"':
                    j += 2
                    continue
                in_q = False
            j += 1
            continue
        if ch == '"':
            in_q = True
            j += 1
            continue
        if ch == "{":
            if depth == 0:
                buf_start = j
            depth += 1
            j += 1
            continue
        if ch == "}":
            depth -= 1
            j += 1
            if depth == 0:
                # include trailing comma if present
                end = j
                if end < len(body) and body[end] == ",":
                    end += 1
                records.append(body[buf_start:end])
                # skip whitespace/newlines between records — attach to following? keep in gap
                # gaps between records: we need to preserve them. Store separately.
            continue
        j += 1

    # Rebuild with gaps: simpler approach — split by records positions
    return header, records, body


def rewrite_file(src_lgp: Path, maps: dict, out_path: Path) -> dict:
    raw = src_lgp.read_bytes()
    bom = b""
    if raw.startswith(b"\xef\xbb\xbf"):
        bom = raw[:3]
        data = raw[3:]
    else:
        data = raw
    text = data.decode("utf-8")

    header, records, body = iter_records_raw(text)
    # Preserve inter-record gaps by walking body again
    out_parts = [header]
    depth = 0
    in_q = False
    j = 0
    rec_i = 0
    gap_start = 0
    while j < len(body):
        ch = body[j]
        if in_q:
            if ch == '"':
                if j + 1 < len(body) and body[j + 1] == '"':
                    j += 2
                    continue
                in_q = False
            j += 1
            continue
        if ch == '"':
            in_q = True
            j += 1
            continue
        if ch == "{":
            if depth == 0:
                # gap before this record
                if j > gap_start:
                    out_parts.append(body[gap_start:j])
                buf_start = j
            depth += 1
            j += 1
            continue
        if ch == "}":
            depth -= 1
            j += 1
            if depth == 0:
                end = j
                if end < len(body) and body[end] == ",":
                    end += 1
                original = body[buf_start:end]
                out_parts.append(renumber_record(original, maps))
                rec_i += 1
                gap_start = end
            continue
        j += 1
    if gap_start < len(body):
        out_parts.append(body[gap_start:])

    # Replace header GUID/version with destination dictionary
    # header is first 3 lines of SRC — replace line2 with dst guid, keep version
    dst = read_lgf(DST_LGF)
    # rebuild header
    # parse header lines
    hl = []
    rest = header
    for _ in range(3):
        if rest.startswith("\r\n"):
            hl.append("")
            rest = rest[2:]
            continue
        idx_n = rest.find("\n")
        idx_r = rest.find("\r\n")
        if idx_r != -1 and (idx_n == -1 or idx_r <= idx_n):
            hl.append(rest[:idx_r])
            rest = rest[idx_r + 2 :]
        elif idx_n != -1:
            hl.append(rest[:idx_n])
            rest = rest[idx_n + 1 :]
        else:
            hl.append(rest)
            rest = ""
            break
    # hl[0]=version, hl[1]=guid, hl[2]='' (empty line content before its break — messy)

    # Simpler header rewrite: take dst version/guid from lgf
    ver = dst["version"]
    guid = dst["guid"]
    # detect header newline style from original header
    nl = "\r\n" if "\r\n" in header[:80] else "\n"
    new_header = ver + nl + guid + nl + nl

    # out_parts[0] was old header — replace
    out_parts[0] = new_header
    # If original had gap after header already in body start, we may duplicate blank —
    # iter puts header including trailing blank; body starts at first record.
    # Good.

    out_text = "".join(out_parts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bom + out_text.encode("utf-8"))

    # stats
    lf_only = out_text.count("\n") - out_text.count("\r\n")
    return {
        "records": rec_i,
        "lf_only": lf_only,
        "crlf": out_text.count("\r\n"),
        "size": out_path.stat().st_size,
    }


def main() -> int:
    src = read_lgf(SRC_DIR / "1Cv8.lgf")
    dst = read_lgf(DST_LGF)
    result = build_maps(src, dst)
    maps = result["maps"]
    print("maps built, added", result["added"], "need_remap", result["need_remap"])

    # copy lgf as-is from Desktop\2 (already fixed commas/uuid)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lgf_out = OUT_DIR / "1Cv8.lgf"
    lgf_out.write_bytes(DST_LGF.read_bytes())
    print("copied lgf", lgf_out.stat().st_size)

    # keep existing 24 from desktop 2 (skipped merge)
    p24_src = Path(r"C:\Users\mamak\OneDrive\Desktop\2\20260824000000.lgp")
    if p24_src.exists():
        (OUT_DIR / "20260824000000.lgp").write_bytes(p24_src.read_bytes())
        print("copied 24", p24_src.stat().st_size)

    for name in ["20260819000000.lgp", "20260820000000.lgp"]:
        stats = rewrite_file(SRC_DIR / name, maps, OUT_DIR / name)
        print(name, stats)
        # verify lf_only restored
        raw = (OUT_DIR / name).read_bytes()
        body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
        crlf = body.count(b"\r\n")
        lf = body.count(b"\n")
        lf_only = lf - crlf
        print("  verify crlf", crlf, "lf_only", lf_only)
    print("OUT", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
