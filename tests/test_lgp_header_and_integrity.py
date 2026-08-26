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


def rewrite_header(src: str, version: str, guid: str) -> str:
    lines = src.splitlines()
    body = lines[2:] if len(lines) >= 2 else []
    return "\n".join([version, guid, *body]) + ("\n" if src.endswith("\n") else "")


def test_limit_open_bracket_is_not_corruption() -> None:
    # Large-ish synthetic body with unclosed brace inside sample window
    header = "1CV8LOGVERSION=8.3\nsource-guid\n"
    body = "{" + ("x" * (SAMPLE_LIMIT + 100))
    result = check_lgp_sample(header + body, "source-guid", "1CV8LOGVERSION=8.3")
    assert result["hit_limit"] is True
    assert result["eof"] is False
    assert "truncated at eof" not in result["issues"]
    assert result["ok"] is True


def test_eof_open_bracket_is_corruption() -> None:
    text = "1CV8LOGVERSION=8.3\nsource-guid\n{not-closed\n"
    result = check_lgp_sample(text, "source-guid", "1CV8LOGVERSION=8.3")
    assert result["eof"] is True
    assert "truncated at eof" in result["issues"]
    assert result["ok"] is False


def test_guid_mismatch_detected() -> None:
    text = "1CV8LOGVERSION=8.3\nsource-guid\n{1,2},\n"
    result = check_lgp_sample(text, "dest-guid", "1CV8LOGVERSION=8.3")
    assert "guid mismatch" in result["issues"]
    assert result["ok"] is False


def test_header_rewrite_on_copy() -> None:
    src = "1CV8LOGVERSION=8.3\nsource-guid\n{1,2},\n{3,4},\n"
    out = rewrite_header(src, "1CV8LOGVERSION=8.3", "dest-guid")
    lines = out.splitlines()
    assert lines[0] == "1CV8LOGVERSION=8.3"
    assert lines[1] == "dest-guid"
    assert lines[2:] == ["{1,2},", "{3,4},"]
    # After rewrite, sample against dest dict is clean
    result = check_lgp_sample(out, "dest-guid", "1CV8LOGVERSION=8.3")
    assert result["ok"] is True


def main() -> int:
    test_limit_open_bracket_is_not_corruption()
    test_eof_open_bracket_is_corruption()
    test_guid_mismatch_detected()
    test_header_rewrite_on_copy()
    # Also keep a tiny on-disk rewrite check
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "a.lgp"
        p.write_text("1CV8LOGVERSION=8.3\nold\n{1},\n", encoding="utf-8")
        rewritten = rewrite_header(p.read_text(encoding="utf-8"), "1CV8LOGVERSION=8.3", "new")
        Path(tmp, "b.lgp").write_text(rewritten, encoding="utf-8")
        assert Path(tmp, "b.lgp").read_text(encoding="utf-8").splitlines()[1] == "new"
    print("OK: lgp header + integrity rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
