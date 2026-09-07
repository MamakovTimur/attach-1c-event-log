# Contract: zero-append merge must not publish a temp .lgp that only gained a trailing comma.
# Guards Module.bsl: ДописатьЗаписиLgpИзФайла returns a count; ПрисоединитьФайлLgp skips
# КопироватьФайлСЗаменой when merge added 0; ОбъединитьLgpБезПеренумерации skips empty body.

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ПрисоединениеЖурналаРегистрации" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"


def _procedure_or_function_body(text: str, name: str) -> str:
    pattern = (
        rf"(?ms)^\s*(?:Процедура|Функция)\s+{re.escape(name)}\s*\([^)]*\)\s*\n"
        rf"(.*?)(?=^\s*(?:Процедура|Функция|КонецПроцедуры|КонецФункции)\s+|\Z)"
    )
    match = re.search(pattern, text)
    assert match is not None, f"procedure/function not found: {name}"
    return match.group(1)


def test_dopisat_returns_count() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    assert re.search(
        r"(?m)^\s*Функция\s+ДописатьЗаписиLgpИзФайла\s*\(",
        text,
    ), "ДописатьЗаписиLgpИзФайла must be a Function returning appended count"
    assert re.search(
        r"(?m)^\s*Функция\s+ДописатьЗаписиLgpИзФайлаПострочно\s*\(",
        text,
    ), "ДописатьЗаписиLgpИзФайлаПострочно must be a Function"
    body = _procedure_or_function_body(text, "ДописатьЗаписиLgpИзФайлаПострочно")
    assert "Возврат СчетчикЗаписей" in body or "Возврат СчётчикЗаписей" in body, (
        "Построчно must return the appended-records counter"
    )


def test_priobiedinit_skips_publish_on_zero_append() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _procedure_or_function_body(text, "ПрисоединитьФайлLgp")
    assert "ДобавленоЗаписей = ДописатьЗаписиLgpИзФайла(" in body, (
        "ПрисоединитьФайлLgp must capture return count from ДописатьЗаписиLgpИзФайла"
    )
    assert "ЭтоДописываниеВСуществующий" in body
    assert re.search(
        r"ЭтоДописываниеВСуществующий\s+И\s+ДобавленоЗаписей\s*=\s*0",
        body,
    ), "must cancel publish when merge added 0 records"
    # When cancelled, must not reach КопироватьФайлСЗаменой for the temp file path
    # after the zero-append branch (guard: УдалитьФайлы then Возврат before publish).
    zero_branch = re.search(
        r"Если\s+ЭтоДописываниеВСуществующий\s+И\s+ДобавленоЗаписей\s*=\s*0\s+Тогда\s*"
        r"(.*?)\s*КонецЕсли",
        body,
        re.DOTALL,
    )
    assert zero_branch is not None
    cancel = zero_branch.group(1)
    assert "УдалитьФайлы(ВременныйФайл)" in cancel
    assert "Возврат" in cancel
    assert "КопироватьФайлСЗаменой" not in cancel


def test_obiedinit_bez_perenumeracii_skips_empty_body() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _procedure_or_function_body(text, "ОбъединитьLgpБезПеренумерации")
    assert "СмещениеТелаLgpВФайле(ПутьИсточника)" in body
    assert re.search(
        r"Размер\(\)\s*<=\s*СмещениеТела",
        body,
    ) or "Размер() <= СмещениеТелаИсточника" in body, (
        "must skip merge when source body is empty"
    )
    assert "Возврат" in body


def main() -> int:
    test_dopisat_returns_count()
    test_priobiedinit_skips_publish_on_zero_append()
    test_obiedinit_bez_perenumeracii_skips_empty_body()
    print("OK: zero-append merge leaves destination untouched (no trailing comma publish)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
