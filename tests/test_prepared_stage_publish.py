from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = (
    ROOT
    / "ПрисоединениеЖурналаРегистрации"
    / "Forms"
    / "Форма"
    / "Ext"
    / "Form"
    / "Module.bsl"
)


def _method_body(text: str, name: str) -> str:
    pattern = (
        rf"(?ms)^\s*(?:Процедура|Функция)\s+{re.escape(name)}\s*\([^)]*\)\s*\n"
        rf"(.*?)(?=^\s*(?:КонецПроцедуры|КонецФункции)\s*$)"
    )
    match = re.search(pattern, text)
    assert match is not None, f"method not found: {name}"
    return match.group(1)


def test_stage_is_created_beside_destination() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "ПолучитьПутьПодготовленногоФайлаРядом")
    assert 'Приемник + ".stage_" + Метка' in body
    assert "ПолучитьИмяВременногоФайла" not in body


def test_prepared_publish_preserves_previous_restore_protocol() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "ОпубликоватьПодготовленныйФайл")
    assert "ПереместитьФайл(Приемник, ПутьПредыдущего)" in body
    assert "ПереместитьФайл(ПутьПодготовленного, Приемник)" in body
    assert "Не Опубликовано" in body
    assert "ПереместитьФайл(ПутьПредыдущего, Приемник)" in body
    assert "КопироватьФайл(" not in body


def test_large_result_builders_publish_stage_without_second_copy() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    methods = (
        "ОбъединитьLgpБезПеренумерации",
        "ПрисоединитьФайлLgp",
        "СкопироватьLgpСЗаголовкомПриемника",
        "ОбъединитьLgpСПоточнойПерекодировкой",
    )
    for name in methods:
        body = _method_body(text, name)
        assert "ПолучитьПутьПодготовленногоФайлаРядом" in body, name
        assert "ОпубликоватьПодготовленныйФайл" in body, name
        assert "КопироватьФайлСЗаменой(ВременныйФайл" not in body, name
        assert "КопироватьФайлСЗаменой(ПутьПодготовленного" not in body, name


if __name__ == "__main__":
    test_stage_is_created_beside_destination()
    test_prepared_publish_preserves_previous_restore_protocol()
    test_large_result_builders_publish_stage_without_second_copy()
