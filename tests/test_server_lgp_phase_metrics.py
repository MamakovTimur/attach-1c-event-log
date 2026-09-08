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


def _module_text() -> str:
    return MODULE.read_text(encoding="utf-8-sig")


def _method_body(text: str, name: str) -> str:
    pattern = (
        rf"(?ms)^\s*(?:Процедура|Функция)\s+{re.escape(name)}\s*\([^)]*\)\s*"
        rf"(?:Экспорт\s*)?\n"
        rf"(.*?)(?=^\s*(?:КонецПроцедуры|КонецФункции)\s*$)"
    )
    match = re.search(pattern, text)
    assert match is not None, f"method not found: {name}"
    return match.group(1)


def test_phase_metrics_are_allocated_only_on_server_for_debug() -> None:
    body = _method_body(_module_text(), "НовыеМетрикиФазLgp")
    server = body.split("#Если Сервер Тогда", 1)[1].split("#Иначе", 1)[0]
    client = body.split("#Иначе", 1)[1].split("#КонецЕсли", 1)[0]
    assert "СведенияОтладки = Неопределено" in server
    assert "ТекущаяУниверсальнаяДатаВМиллисекундах()" in server
    assert "Возврат Неопределено" in client


def test_debug_log_exposes_all_lgp_phase_metrics() -> None:
    body = _method_body(_module_text(), "СтрокиОтладкиОперацииФайла")
    for metric in (
        "lgp_read_prepare_ms",
        "lgp_transform_ms",
        "lgp_publish_ms",
        "lgp_total_ms",
    ):
        assert f'"[METRIC] {metric}="' in body


def test_atomic_publication_owns_publish_timer() -> None:
    body = _method_body(_module_text(), "ОпубликоватьПодготовленныйФайл")
    assert 'НачатьИзмерениеФазыLgp(МетрикиФаз)' in body
    assert 'ЗавершитьИзмерениеФазыLgp(МетрикиФаз, "ПубликацияМс"' in body


def test_size_only_metrics_do_not_require_record_counts() -> None:
    text = _module_text()
    formatter = _method_body(text, "СтрокаМетрикLgp")
    fallback = formatter.split('Если Не Метрики.Свойство("Записей") Тогда', 1)[1].split("КонецЕсли;", 1)[0]
    assert "Возврат" in fallback
    assert "Метрики.Байт" in fallback
    assert "Метрики.Записей" not in fallback
    operation = _method_body(text, "СтрокиОтладкиОперацииФайла")
    comparison = operation.split("И МетрикиПосле.Записей <", 1)[0].rsplit("Если", 1)[1]
    assert 'МетрикиИсточника.Свойство("Записей")' in comparison
    assert 'МетрикиПосле.Свойство("Записей")' in comparison


def test_split_by_day_aggregates_child_phases_without_child_total() -> None:
    body = _method_body(_module_text(), "ДобавитьВложенныеМетрикиФазLgp")
    assert "ВложенныеФазы.ЧтениеПодготовкаМс" in body
    assert "ВложенныеФазы.ПреобразованиеЗаписейМс" in body
    assert "ВложенныеФазы.ПубликацияМс" in body
    assert "ВложенныеФазы.ВсегоМс" not in body


if __name__ == "__main__":
    test_phase_metrics_are_allocated_only_on_server_for_debug()
    test_debug_log_exposes_all_lgp_phase_metrics()
    test_atomic_publication_owns_publish_timer()
    test_size_only_metrics_do_not_require_record_counts()
    test_split_by_day_aggregates_child_phases_without_child_total()
