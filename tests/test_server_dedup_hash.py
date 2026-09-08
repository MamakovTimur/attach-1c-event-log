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


def test_server_dedup_retains_compact_sha256_key() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "ОтпечатокЗаписиLgpИзТокенов")
    server = body.split("#Если Сервер Тогда", 1)[1].split("#Иначе", 1)[0]
    assert "ХешированиеДанных(ХешФункция.SHA256)" in server
    assert "Хеширование.Добавить(КаноническийТекст)" in server
    assert "Base64Строка(Хеширование.ХешСумма)" in server
    assert "Токены.Количество()" in server
    assert "ОбщаяДлинаПолей" in server


def test_client_dedup_keeps_legacy_compatible_key() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "ОтпечатокЗаписиLgpИзТокенов")
    client = body.split("#Иначе", 1)[1].split("#КонецЕсли", 1)[0]
    assert "Возврат КаноническийТекст" in client
    assert "ХешированиеДанных" not in client


def test_canonical_serialization_remains_length_prefixed() -> None:
    text = MODULE.read_text(encoding="utf-8-sig")
    body = _method_body(text, "ОтпечатокЗаписиLgpИзТокенов")
    assert 'Формат(ДлинаПоля, "ЧГ=0") + ":" + ЗначениеПоля' in body
    assert 'СтрСоединить(Части, "|")' in body


if __name__ == "__main__":
    test_server_dedup_retains_compact_sha256_key()
    test_client_dedup_keeps_legacy_compatible_key()
    test_canonical_serialization_remains_length_prefixed()
