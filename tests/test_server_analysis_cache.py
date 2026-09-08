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
        rf"(?ms)^\s*(?:Процедура|Функция)\s+{re.escape(name)}\s*\([^)]*\)\s*"
        rf"(?:Экспорт\s*)?\n"
        rf"(.*?)(?=^\s*(?:КонецПроцедуры|КонецФункции)\s*$)"
    )
    match = re.search(pattern, text)
    assert match is not None, f"method not found: {name}"
    return match.group(1)


def test_lgf_fingerprint_is_fail_closed_and_cross_platform_safe() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "ОтпечатокLgfДляКэшаАнализа")
    assert "Не ФайлLgf.Существует() Или Не ФайлLgf.ЭтоФайл()" in body
    assert "ФайлLgf.ПолноеИмя" in body
    assert "ФайлLgf.Размер()" in body
    assert "ФайлLgf.ПолучитьВремяИзменения()" in body
    assert "ХешированиеДанных(ХешФункция.SHA256)" in body
    assert "ДобавитьФайл(ФайлLgf.ПолноеИмя)" in body
    assert "ХешСодержимого" in body
    assert "ВРег(" not in body, "case-sensitive server paths must not be folded"


def test_server_cache_checks_both_lgf_fingerprints() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    compare = _method_body(text, "ОтпечаткиLgfСовпадают")
    for field in ("Путь", "Размер", "ВремяИзменения", "ХешСодержимого"):
        assert f"Первый.{field} = Второй.{field}" in compare

    get_cached = _method_body(text, "ПолучитьСохраненныйКэшАнализаНаСервере")
    assert "ДанныеКэша.ОтпечатокИсточника" in get_cached
    assert "ДанныеКэша.ОтпечатокПриемника" in get_cached
    assert "Возврат Неопределено" in get_cached


def test_cache_hit_precedes_dictionary_read_and_map_build() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "ПолучитьДанныеАнализаДляПрисоединенияНаСервере")
    hit_at = body.index("Если ДанныеАнализа <> Неопределено Тогда")
    read_at = body.index("СловарьИсточника = ПрочитатьСловарьLgf")
    map_at = body.index("РезультатКарт = ПостроитьКартыПеренумерации")
    assert hit_at < read_at < map_at

    dry_run = _method_body(text, "ВыполнитьАнализНаСервереКонтекста")
    assert "ПолучитьДанныеАнализаДляПрисоединенияНаСервере(" in dry_run
    assert "ПрочитатьСловарьLgf(" not in dry_run
    assert "ПостроитьКартыПеренумерации(" not in dry_run


def test_cache_address_replacement_is_bounded() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    save = _method_body(text, "СохранитьКэшАнализаНаСервере")
    put_at = save.index("НовыйАдрес = ПоместитьВоВременноеХранилище")
    assign_at = save.index("КэшКлючАнализа = НовыйАдрес")
    cleanup_at = save.index("ОчиститьКэшАнализаНаСервере(ПредыдущийАдрес)")
    assert put_at < assign_at < cleanup_at

    reset = _method_body(text, "СброситьПланАнализа")
    assert "ОчиститьКэшАнализаНаСервере(ПредыдущийАдресКэша)" in reset


if __name__ == "__main__":
    test_lgf_fingerprint_is_fail_closed_and_cross_platform_safe()
    test_server_cache_checks_both_lgf_fingerprints()
    test_cache_hit_precedes_dictionary_read_and_map_build()
    test_cache_address_replacement_is_bounded()
