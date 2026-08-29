"""Phase 2 merge-quality helpers mirroring Module.bsl (no 1C runtime).

LGP record tokens are 0-based (Infostart 1-based − 1):
  0 date YYYYMMDDHHMMSS, 1 transaction status (N/U/C/R), 2 tx id,
  3 user, 4 computer, 5 app, 6 connection, 7 event, 8 level, 9 comment,
  10 metadata, … 16 session.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

TX_NONE = "N"
TX_UNFINISHED = "U"
TX_COMMITTED = "C"
TX_ROLLED_BACK = "R"
OPEN_TX = frozenset({TX_UNFINISHED})

IDX_DATE = 0
IDX_TX_STATUS = 1
IDX_USER = 3
IDX_COMPUTER = 4
IDX_APP = 5
IDX_CONNECTION = 6
IDX_EVENT = 7
IDX_LEVEL = 8
IDX_COMMENT = 9
IDX_SESSION = 16

HEADER_MARKER = "1CV8LOG"
DATE_RE = re.compile(r"^\d{14}$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


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


def iter_records(body: str) -> Iterable[str]:
    """Yield top-level `{...}` record texts (without trailing comma)."""
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
                rec = "".join(buf).strip()
                if rec:
                    yield rec
                buf = []
        elif depth == 0:
            # skip whitespace/commas between records
            pass
        else:
            buf.append(ch)
        i += 1


def split_header_body(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        return text, ""
    # version, guid, optional blank, then body
    idx = 2
    if idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    header = "".join(lines[:idx])
    body = "".join(lines[idx:])
    return header, body


def record_tokens(record: str) -> list[str]:
    s = record.strip()
    if s.endswith(","):
        s = s[:-1].rstrip()
    if not (s.startswith("{") and s.endswith("}")):
        return []
    return tokenize(s[1:-1])


def day_from_date_token(token: str) -> str:
    t = token.strip()
    if DATE_RE.match(t):
        return t[:8]
    return ""


def day_from_lgp_filename(name: str) -> str:
    stem = Path(name).stem
    if len(stem) >= 8 and stem[:8].isdigit():
        return stem[:8]
    return ""


def fingerprint(tokens: list[str]) -> str:
    def get(i: int) -> str:
        return tokens[i].strip() if i < len(tokens) else ""

    parts = [
        get(IDX_DATE),
        get(IDX_USER),
        get(IDX_COMPUTER),
        get(IDX_APP),
        get(IDX_CONNECTION),
        get(IDX_EVENT),
        get(IDX_LEVEL),
        get(IDX_COMMENT),
        get(IDX_SESSION),
    ]
    return "|".join(parts)


def is_event_record(tokens: list[str]) -> bool:
    return bool(tokens) and bool(DATE_RE.match(tokens[0].strip()))


def is_dict_record(tokens: list[str]) -> bool:
    if not tokens:
        return False
    first = tokens[0].strip()
    if not first.isdigit():
        return False
    typ = int(first)
    if typ < 1 or typ > 20:
        return False
    # lgf row: {type, uuid_or_name, ...} — not a 14-digit date
    return not DATE_RE.match(first)


@dataclass
class ArchiveDetectResult:
    is_archive: bool
    has_dict_rows: bool
    has_event_rows: bool
    message: str = ""


def detect_archive_format(text: str) -> ArchiveDetectResult:
    """lgf+lgp packed in one file: both dictionary rows and event rows after one header."""
    if HEADER_MARKER not in text[:64]:
        return ArchiveDetectResult(False, False, False, "no 1CV8LOG marker")
    _, body = split_header_body(text)
    has_dict = False
    has_event = False
    for rec in iter_records(body):
        tokens = record_tokens(rec)
        if is_event_record(tokens):
            has_event = True
        elif is_dict_record(tokens):
            has_dict = True
        if has_dict and has_event:
            return ArchiveDetectResult(
                True,
                True,
                True,
                "Обнаружен архивный формат (словарь lgf и записи lgp в одном файле). "
                "Обработка только читает/предупреждает — запись архива не поддерживается.",
            )
    return ArchiveDetectResult(False, has_dict, has_event)


@dataclass
class TxBoundary:
    open_at_end: bool
    last_status: str = ""
    first_status: str = ""
    open_at_start: bool = False
    warnings: list[str] = field(default_factory=list)


def scan_transaction_boundary(text: str) -> TxBoundary:
    _, body = split_header_body(text)
    statuses: list[str] = []
    depth_open = 0
    for rec in iter_records(body):
        tokens = record_tokens(rec)
        if not is_event_record(tokens) or len(tokens) <= IDX_TX_STATUS:
            continue
        st = tokens[IDX_TX_STATUS].strip().upper()
        statuses.append(st)
        if st == TX_UNFINISHED:
            depth_open += 1
        elif st in (TX_COMMITTED, TX_ROLLED_BACK):
            depth_open = max(0, depth_open - 1)
        # N does not change depth
    result = TxBoundary(
        open_at_end=depth_open > 0,
        last_status=statuses[-1] if statuses else "",
        first_status=statuses[0] if statuses else "",
        open_at_start=bool(statuses) and statuses[0] == TX_UNFINISHED,
    )
    if result.open_at_end:
        result.warnings.append(
            "В конце файла есть незакрытая транзакция (статус U без пары C/R). "
            "При склейке через границу файлов пара begin/commit может разорваться."
        )
    return result


def merge_warn_transactions(dest_text: str, src_text: str) -> list[str]:
    dest = scan_transaction_boundary(dest_text)
    src = scan_transaction_boundary(src_text)
    warnings: list[str] = []
    warnings.extend(dest.warnings)
    if dest.open_at_end and src.first_status and src.first_status != TX_UNFINISHED:
        warnings.append(
            "Приёмник заканчивается незакрытой транзакцией, а источник начинается "
            f"со статуса «{src.first_status}» — проверьте целостность транзакций после merge."
        )
    if src.open_at_end:
        warnings.append(
            "Источник заканчивается незакрытой транзакцией — после дописывания "
            "в приёмнике останется открытая транзакция до появления C/R."
        )
    return warnings


@dataclass
class DedupStats:
    written: int = 0
    skipped: int = 0


def merge_records_dedup(
    dest_body_records: list[str],
    src_records: list[str],
    *,
    dedup: bool,
) -> tuple[list[str], DedupStats]:
    seen: set[str] = set()
    out: list[str] = []
    stats = DedupStats()
    for rec in dest_body_records:
        tokens = record_tokens(rec)
        if is_event_record(tokens):
            seen.add(fingerprint(tokens))
        out.append(rec)
    for rec in src_records:
        tokens = record_tokens(rec)
        if not is_event_record(tokens):
            out.append(rec)
            stats.written += 1
            continue
        fp = fingerprint(tokens)
        if dedup and fp in seen:
            stats.skipped += 1
            continue
        seen.add(fp)
        out.append(rec)
        stats.written += 1
    return out, stats


def split_by_day(
    records: list[str],
    *,
    protect_transactions: bool = True,
) -> dict[str, list[str]]:
    """Bucket event records by YYYYMMDD. Open TX stays on begin-day until C/R."""
    buckets: dict[str, list[str]] = defaultdict(list)
    sticky_day = ""
    open_depth = 0
    for rec in records:
        tokens = record_tokens(rec)
        if not is_event_record(tokens):
            continue
        day = day_from_date_token(tokens[IDX_DATE])
        if not day:
            continue
        st = tokens[IDX_TX_STATUS].strip().upper() if len(tokens) > IDX_TX_STATUS else TX_NONE
        if protect_transactions and open_depth > 0 and sticky_day:
            target = sticky_day
        else:
            target = day
        buckets[target].append(rec)
        if protect_transactions:
            if st == TX_UNFINISHED:
                if open_depth == 0:
                    sticky_day = day
                open_depth += 1
            elif st in (TX_COMMITTED, TX_ROLLED_BACK):
                open_depth = max(0, open_depth - 1)
                if open_depth == 0:
                    sticky_day = ""
    return dict(buckets)


def make_lgp(version: str, guid: str, records: list[str], crlf: bool = True) -> str:
    nl = "\r\n" if crlf else "\n"
    parts = [version, guid, ""]
    for i, rec in enumerate(records):
        r = rec.strip()
        if not r.endswith(",") and i < len(records) - 1:
            r = r + ","
        if i == len(records) - 1 and r.endswith(","):
            r = r[:-1]
        parts.append(r)
    return nl.join(parts) + nl


def write_golden_fixtures(root: Path) -> list[Path]:
    """Create anonymized synthetic .lgp under tests/fixtures/golden/."""
    out_dir = root / "tests" / "fixtures" / "golden"
    out_dir.mkdir(parents=True, exist_ok=True)
    ver = "1CV8LOG(ver 2.0)"
    guid_a = "11111111-e311-4ee2-8582-7a2a46a59363"
    guid_b = "22222222-e311-4ee2-8582-7a2a46a59363"

    # Minimal event row template (enough tokens for fingerprint + tx)
    def ev(dt: str, tx: str, user: str, event: str, comment: str = '""') -> str:
        return (
            f"{{{dt},{tx},"
            f"{{0,0}},{user},1,1,1,{event},I,{comment},0,"
            f'{{"U"}},"",0,0,0,1,0,'
            f"{{0}}}}"
        )

    files: list[Path] = []

    p = out_dir / "day_a.lgp"
    p.write_text(
        make_lgp(
            ver,
            guid_a,
            [
                ev("20260820010101", "N", "1", "1", '"login"'),
                ev("20260820010202", "U", "1", "2", '"tx-begin"'),
                ev("20260820010303", "C", "1", "2", '"tx-end"'),
            ],
        ),
        encoding="utf-8-sig",
    )
    files.append(p)

    p = out_dir / "day_b_overlap.lgp"
    p.write_text(
        make_lgp(
            ver,
            guid_b,
            [
                ev("20260820010101", "N", "1", "1", '"login"'),  # duplicate of day_a
                ev("20260820010404", "N", "2", "3", '"other"'),
            ],
        ),
        encoding="utf-8-sig",
    )
    files.append(p)

    p = out_dir / "multiday.lgp"
    p.write_text(
        make_lgp(
            ver,
            guid_a,
            [
                ev("20260820010101", "N", "1", "1"),
                ev("20260821010101", "N", "1", "1"),
                ev("20260822010101", "U", "1", "2", '"span"'),
                ev("20260823010101", "C", "1", "2", '"span-end"'),  # after midnight, sticky
            ],
        ),
        encoding="utf-8-sig",
    )
    files.append(p)

    p = out_dir / "open_tx_tail.lgp"
    p.write_text(
        make_lgp(
            ver,
            guid_a,
            [
                ev("20260820010101", "N", "1", "1"),
                ev("20260820010202", "U", "1", "2", '"open"'),
            ],
        ),
        encoding="utf-8-sig",
    )
    files.append(p)

    p = out_dir / "archive_packed.lgp"
    # dictionary row + event row under one header
    body_recs = [
        '{1,aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee,"",1}',
        '{4,"_$Session$_.Start",1}',
        ev("20260820010101", "N", "1", "1"),
    ]
    p.write_text(make_lgp(ver, guid_a, body_recs), encoding="utf-8-sig")
    files.append(p)

    p = out_dir / "emptyish.lgp"
    p.write_text(make_lgp(ver, guid_a, []), encoding="utf-8-sig")
    files.append(p)

    p = out_dir / "renumber_src.lgp"
    p.write_text(
        make_lgp(
            ver,
            guid_a,
            [ev("20260824000001", "N", "9", "9", '"src"')],
        ),
        encoding="utf-8-sig",
    )
    files.append(p)

    p = out_dir / "renumber_dst.lgp"
    p.write_text(
        make_lgp(
            ver,
            guid_b,
            [ev("20260824000002", "N", "1", "1", '"dst"')],
        ),
        encoding="utf-8-sig",
    )
    files.append(p)

    return files
