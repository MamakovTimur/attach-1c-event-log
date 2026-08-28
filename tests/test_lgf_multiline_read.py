# Regression: lgf dictionary entries may span multiple lines (like lgp records).

from __future__ import annotations

import tempfile
from pathlib import Path

from smoke_analyze import add_lgf_record, iter_lgf_records, read_lgf


SAMPLE = """\
1CV8LOG(ver 2.0)
{00000000-0000-0000-0000-000000000001}
{2,"UserA",1},
{5,
"11111111-1111-1111-1111-111111111111",
"MetaObject",2},
{3,"EventX",3},
"""


def test_iter_lgf_records_multiline() -> None:
    lines = SAMPLE.splitlines()
    records = list(iter_lgf_records(lines))
    assert len(records) == 3
    assert records[0].startswith('{2,"UserA",1}')
    assert "\n" in records[1]
    assert records[2].startswith('{3,"EventX",3')


def test_read_lgf_counts_multiline_entry() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "1Cv8.lgf"
        path.write_text(SAMPLE, encoding="utf-8-sig")
        parsed = read_lgf(path)
    assert parsed["count"] == 3
    assert parsed["by_number"][2][1]["name"] == "UserA"
    assert parsed["by_number"][5][2]["uuid"] == "11111111-1111-1111-1111-111111111111"


def test_single_line_still_works() -> None:
    result = {"by_number": {t: {} for t in range(1, 9)}, "by_key": {t: {} for t in range(1, 9)}, "max_number": {t: 0 for t in range(1, 9)}, "count": 0}
    add_lgf_record(result, '{1,"uuid-here","MetaName",5},')
    assert result["count"] == 1
    assert result["by_number"][1][5]["uuid"] == "uuid-here"


def test_type13_numeric_not_misread_as_type1() -> None:
    """Regression: 0-based tokens — type is tokens[0], not [1].
    Old BSL used Токены[1] and treated {13,1,N} as type=1 (exactly 6 false hits on Desktop\\1).
    """
    result = {"by_number": {t: {} for t in range(1, 9)}, "by_key": {t: {} for t in range(1, 9)}, "max_number": {t: 0 for t in range(1, 9)}, "count": 0}
    for n in range(1, 7):
        add_lgf_record(result, f"{{13,1,{n}}},")
    assert result["count"] == 0


def test_native_last_record_has_no_comma() -> None:
    """Platform native .lgp: all records except the last end with comma."""
    src = Path(r"C:\Users\mamak\OneDrive\Desktop\1\20260819000000.lgp")
    if not src.exists():
        return
    text = src.read_text(encoding="utf-8-sig")
    # reuse smoke-style streaming is overkill — just check file tail
    lines = text.splitlines()
    assert lines[-1].rstrip().endswith("}")
    assert not lines[-1].rstrip().endswith("},")


def test_writer_strips_last_comma() -> None:
    mid = "{20260101000000,N,\n{0,0},1\n},"
    last = "{20260101000001,N,\n{0,0},2\n},"
    assert mid.rstrip().endswith(",")
    # mirror УбратьХвостовуюЗапятуюСПоследнейСтроки
    parts = last.split("\n")
    parts[-1] = parts[-1].rstrip().rstrip(",")
    fixed = "\n".join(parts)
    assert fixed.endswith("}")
    assert not fixed.endswith("},")


if __name__ == "__main__":
    test_iter_lgf_records_multiline()
    test_read_lgf_counts_multiline_entry()
    test_single_line_still_works()
    test_type13_numeric_not_misread_as_type1()
    test_native_last_record_has_no_comma()
    test_writer_strips_last_comma()
    print("OK: test_lgf_multiline_read")
