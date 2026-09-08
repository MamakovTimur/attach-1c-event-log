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


def test_splitter_reuses_one_active_writer() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "РазложитьИсточникLgpПоДнямВоВременныеФайлы")
    assert '"День,Путь,Поток,Запись,ПерваяЗапись"' in body
    assert "Если СостояниеЗаписи.День <> ДеньНазначения Тогда" in body
    assert body.count("ФайловыеПотоки.ОткрытьДляДописывания") == 1
    assert "ДописатьСыройТекстЖурналаUTF8БезBOM(" not in body


def test_splitter_preserves_delimiters_and_reopened_day_state() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "РазложитьИсточникLgpПоДнямВоВременныеФайлы")
    assert "ЭтоПерваяЗаписьДня = ПутьДня = Неопределено" in body
    assert '?(СостояниеЗаписи.ПерваяЗапись, "", "," + Разрыв)' in body
    assert "УбратьХвостовуюЗапятуюВЗаписиLgp(ТекстЗаписи) + Разрыв" in body
    assert "СостояниеЗаписи.ПерваяЗапись = Ложь" in body


def test_normal_close_is_strict_and_failure_cleanup_removes_outputs() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "РазложитьИсточникLgpПоДнямВоВременныеФайлы")
    assert "ЗакрытьСостояниеЗаписиРазбивкиLgp(СостояниеЗаписи);" in body
    assert "ЗакрытьСостояниеЗаписиРазбивкиLgp(СостояниеЗаписи, Истина);" in body
    assert "Для Каждого ПараФайла Из Результат Цикл" in body
    assert "УдалитьФайлы(ПараФайла.Значение)" in body

    close = _method_body(text, "ЗакрытьСостояниеЗаписиРазбивкиLgp")
    assert "Если Не ПодавлятьОшибки" in close
    assert "ВызватьИсключение ТекстОшибкиЗакрытия" in close


if __name__ == "__main__":
    test_splitter_reuses_one_active_writer()
    test_splitter_preserves_delimiters_and_reopened_day_state()
    test_normal_close_is_strict_and_failure_cleanup_removes_outputs()
