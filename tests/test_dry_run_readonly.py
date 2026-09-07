# Dry-run (analyze) must be read-only: no rename lockcheck in analysis protocols.
# Attach still uses ФайлЗаблокированДляЗаписиБезКэша (ПереместитьФайл / .lockcheck_*).

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ПрисоединениеЖурналаРегистрации" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"

ANALYZE_PROCS = (
    "ЗаписатьПротоколАнализа",
    "ЗаписатьПротоколАнализаНаСервереКонтекста",
)


def _procedure_body(text: str, name: str) -> str:
    pattern = rf"(?ms)^\s*Процедура\s+{re.escape(name)}\s*\([^)]*\)\s*\n(.*?)(?=^\s*(?:Процедура|Функция)\s+|\Z)"
    match = re.search(pattern, text)
    assert match is not None, f"procedure not found: {name}"
    return match.group(1)


def test_analyze_protocol_does_not_call_lock_protocol() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    for name in ANALYZE_PROCS:
        body = _procedure_body(text, name)
        assert "ЗаписатьПротоколБлокировок" not in body, (
            f"{name}: must not call ЗаписатьПротоколБлокировок* (dry-run is read-only)"
        )
        assert ".lockcheck_" not in body, (
            f"{name}: must not mention .lockcheck_ (rename probe is attach-only)"
        )


def test_attach_lockcheck_helper_still_present() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    assert "Функция ФайлЗаблокированДляЗаписиБезКэша(" in text
    assert ".lockcheck_" in text


def main() -> int:
    test_analyze_protocol_does_not_call_lock_protocol()
    test_attach_lockcheck_helper_still_present()
    print("OK: dry-run analysis is read-only (no lockcheck)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
