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


def test_server_attach_plan_is_frozen_at_initialization() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "ИнициализироватьПрисоединениеНаСервере")
    for field in (
        "ФайлыЖурнала",
        "КаталогИсточника",
        "КаталогПриемника",
        "ОпцииСклейки",
        "ПроверятьЦелостность",
    ):
        assert f'Состояние.Вставить("{field}"' in body


def test_batches_and_final_check_use_only_frozen_plan() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    batch = _method_body(text, "ОбработатьПакетПрисоединенияНаСервере")
    assert "ФайлыЖурналаСнимок = Состояние.ФайлыЖурнала" in batch
    assert "ОпцииСклейки = Состояние.ОпцииСклейки" in batch
    assert "УдалитьИндексыЖурналаНаСервереКонтекста(Состояние.КаталогПриемника)" in batch
    assert "Если Состояние.ПроверятьЦелостность Тогда" in batch
    assert "ОпцииСклейкиИзРеквизитовФормыНаСервере()" not in batch
    assert "ФайлыЖурнала[" not in batch

    final_check = _method_body(
        text, "ЗавершитьКонтрольЦелостностиПослеПрисоединенияНаСервере"
    )
    assert "Для Каждого СтрокаФайла Из Состояние.ФайлыЖурнала Цикл" in final_check
    assert "Для Каждого СтрокаФайла Из ФайлыЖурнала Цикл" not in final_check


def test_temporary_state_is_replaced_without_accumulation() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "СохранитьСостояниеПрисоединенияВоВременноеХранилище")
    put_at = body.index("НовыйАдрес = ПоместитьВоВременноеХранилище")
    assign_at = body.index("АдресСостоянияПрисоединения = НовыйАдрес")
    delete_old_at = body.index("УдалитьИзВременногоХранилища(ПредыдущийАдрес)", assign_at)
    assert put_at < assign_at < delete_old_at

    client_loop = _method_body(text, "ПродолжитьПрисоединениеНаСервереПакетами")
    exception_at = client_loop.index("Исключение")
    assert (
        "СохранитьСостояниеПрисоединенияВоВременноеХранилище(Неопределено)"
        in client_loop[exception_at:]
    )


if __name__ == "__main__":
    test_server_attach_plan_is_frozen_at_initialization()
    test_batches_and_final_check_use_only_frozen_plan()
    test_temporary_state_is_replaced_without_accumulation()
