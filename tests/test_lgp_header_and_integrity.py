# Regression for admin-facing integrity rules and header rewrite on copy.
# Mirrors Module.bsl logic without 1C runtime.

from __future__ import annotations

import tempfile
from pathlib import Path


SAMPLE_LIMIT = 2 * 1024 * 1024


def check_lgp_sample(text: str, expected_guid: str, expected_version: str, limit: int = SAMPLE_LIMIT) -> dict:
    lines = text.splitlines()
    version = lines[0].strip() if lines else ""
    guid = lines[1].strip() if len(lines) > 1 else ""
    depth = 0
    in_quotes = False
    buf = ""
    read_bytes = 0
    hit_limit = False
    eof = False
    i = 2
    while True:
        if i >= len(lines):
            eof = True
            break
        line = lines[i]
        i += 1
        read_bytes += len(line) + 2
        for ch in line:
            if in_quotes:
                if ch == '"':
                    in_quotes = False
                buf += ch
                continue
            if ch == '"':
                in_quotes = True
                buf += ch
            elif ch == "{":
                depth += 1
                buf += ch
            elif ch == "}":
                depth -= 1
                buf += ch
            else:
                buf += ch
        if depth == 0 and buf.strip():
            buf = ""
        if read_bytes >= limit:
            hit_limit = True
            break

    issues: list[str] = []
    if "1CV8LOG" not in version:
        issues.append("bad marker")
    if expected_version and version != expected_version:
        issues.append("version mismatch")
    if guid.lower() != expected_guid.lower():
        issues.append("guid mismatch")
    if eof and (depth != 0 or buf.strip()):
        issues.append("truncated at eof")
    # hit_limit + open depth must NOT be an issue
    return {"ok": not issues, "issues": issues, "hit_limit": hit_limit, "eof": eof}


def assert_native_lgp_header(text: str) -> None:
    """Platform layout: version, GUID, blank line, then '{' record."""
    # Keep \r\n if present — splitlines() strips line breaks but keeps content.
    lines = text.splitlines()
    assert len(lines) >= 3, "header too short"
    assert "1CV8LOG" in lines[0]
    assert lines[1].strip() != ""
    assert lines[2] == "", f"expected blank after GUID, got {lines[2]!r}"
    assert any(ln.startswith("{") for ln in lines[3:]), "no record after blank"


def rewrite_header(src: str, version: str, guid: str) -> str:
    """Mirror СкопироватьLgpСЗаголовкомПриемника: always blank after GUID."""
    lines = src.splitlines()
    body = lines[2:] if len(lines) >= 2 else []
    if body and body[0] == "":
        body = body[1:]
    out_lines = [version, guid, "", *body]
    ending = "\n"
    if src.endswith("\r\n"):
        ending = "\r\n"
    elif not src.endswith("\n"):
        ending = ""
    return ending.join(out_lines) + (ending if ending else "")


def ensure_trailing_comma(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return value
    if not stripped.endswith(","):
        return value + ","
    return value


def copy_receiver_with_comma(src: str) -> str:
    """Mirror СкопироватьПриемникСЗапятой: keep blanks; comma on last non-empty."""
    lines = src.splitlines()
    out: list[str] = []
    pending: str | None = None
    pending_blanks = 0
    significant_count = 0

    for line in lines:
        if line.strip() == "":
            if pending is not None:
                pending_blanks += 1
            else:
                out.append(line)
        else:
            if pending is not None:
                out.append(pending)
                out.extend([""] * pending_blanks)
                if significant_count == 2 and pending_blanks == 0 and line.lstrip().startswith("{"):
                    out.append("")
                pending_blanks = 0
            pending = line
            significant_count += 1

    if pending is not None:
        out.append(ensure_trailing_comma(pending))
        out.extend([""] * pending_blanks)

    ending = "\n" if src.endswith("\n") else ""
    return "\n".join(out) + ending


def test_limit_open_bracket_is_not_corruption() -> None:
    # Large-ish synthetic body with unclosed brace inside sample window
    header = "1CV8LOGVERSION=8.3\nsource-guid\n\n"
    body = "{" + ("x" * (SAMPLE_LIMIT + 100))
    result = check_lgp_sample(header + body, "source-guid", "1CV8LOGVERSION=8.3")
    assert result["hit_limit"] is True
    assert result["eof"] is False
    assert "truncated at eof" not in result["issues"]
    assert result["ok"] is True


def test_eof_open_bracket_is_corruption() -> None:
    text = "1CV8LOGVERSION=8.3\nsource-guid\n\n{not-closed\n"
    result = check_lgp_sample(text, "source-guid", "1CV8LOGVERSION=8.3")
    assert result["eof"] is True
    assert "truncated at eof" in result["issues"]
    assert result["ok"] is False


def test_guid_mismatch_detected() -> None:
    text = "1CV8LOGVERSION=8.3\nsource-guid\n\n{1,2},\n"
    result = check_lgp_sample(text, "dest-guid", "1CV8LOGVERSION=8.3")
    assert "guid mismatch" in result["issues"]
    assert result["ok"] is False


def test_header_rewrite_on_copy() -> None:
    src = "1CV8LOGVERSION=8.3\nsource-guid\n\n{1,2},\n{3,4},\n"
    out = rewrite_header(src, "1CV8LOGVERSION=8.3", "dest-guid")
    lines = out.splitlines()
    assert lines[0] == "1CV8LOGVERSION=8.3"
    assert lines[1] == "dest-guid"
    assert lines[2] == ""
    assert lines[3:] == ["{1,2},", "{3,4},"]
    assert_native_lgp_header(out)
    result = check_lgp_sample(out, "dest-guid", "1CV8LOGVERSION=8.3")
    assert result["ok"] is True


def test_header_rewrite_adds_blank_if_source_lacks_it() -> None:
    src = "1CV8LOGVERSION=8.3\nsource-guid\n{1,2},\n"
    out = rewrite_header(src, "1CV8LOGVERSION=8.3", "dest-guid")
    assert_native_lgp_header(out)
    lines = out.splitlines()
    assert lines[2] == ""
    assert lines[3] == "{1,2},"


def test_native_header_crlf_layout() -> None:
    text = "1CV8LOG(ver 2.0)\r\n" "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\r\n" "\r\n" "{1,2},\r\n"
    assert_native_lgp_header(text)


def test_broken_header_without_blank_detected() -> None:
    text = "1CV8LOG(ver 2.0)\r\n" "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\r\n" "{1,2},\r\n"
    try:
        assert_native_lgp_header(text)
    except AssertionError:
        return
    raise AssertionError("expected blank-after-GUID failure")


def test_copy_receiver_preserves_blank_after_guid() -> None:
    src = "1CV8LOGVERSION=8.3\nguid\n\n{1,2}\n{3,4}\n"
    out = copy_receiver_with_comma(src)
    lines = out.splitlines()
    assert lines[0] == "1CV8LOGVERSION=8.3"
    assert lines[1] == "guid"
    assert lines[2] == ""
    assert lines[3] == "{1,2}"
    assert lines[4] == "{3,4},"


def test_copy_receiver_heals_missing_blank() -> None:
    src = "1CV8LOGVERSION=8.3\nguid\n{1,2}\n"
    out = copy_receiver_with_comma(src)
    assert_native_lgp_header(out)
    lines = out.splitlines()
    assert lines[2] == ""
    assert lines[3] == "{1,2},"


def main() -> int:
    test_limit_open_bracket_is_not_corruption()
    test_eof_open_bracket_is_corruption()
    test_guid_mismatch_detected()
    test_header_rewrite_on_copy()
    test_header_rewrite_adds_blank_if_source_lacks_it()
    test_native_header_crlf_layout()
    test_broken_header_without_blank_detected()
    test_copy_receiver_preserves_blank_after_guid()
    test_copy_receiver_heals_missing_blank()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "a.lgp"
        p.write_text("1CV8LOGVERSION=8.3\nold\n\n{1},\n", encoding="utf-8")
        rewritten = rewrite_header(p.read_text(encoding="utf-8"), "1CV8LOGVERSION=8.3", "new")
        Path(tmp, "b.lgp").write_text(rewritten, encoding="utf-8")
        lines = Path(tmp, "b.lgp").read_text(encoding="utf-8").splitlines()
        assert lines[1] == "new"
        assert lines[2] == ""
    print("OK: lgp header + integrity rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
