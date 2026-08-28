# Regression: ПоляСсылокЗаписиLgp must use 0-based indices (Infostart 1-based − 1).
# Wrong 1-based-as-0-based values remapped session (16) instead of aux ports (15).

from __future__ import annotations
from pathlib import Path

EXPECTED_INDICES = [3, 4, 5, 7, 10, 13, 14, 15]
WRONG_LEGACY_INDICES = [4, 5, 6, 8, 11, 14, 15, 16]

MODULE_BSL = (
    Path(__file__).resolve().parents[1]
    / "ПрисоединениеЖурналаРегистрации"
    / "Forms"
    / "Форма"
    / "Ext"
    / "Form"
    / "Module.bsl"
)


def extract_indices_from_bsl(text: str) -> list[int]:
    """Parse ДобавитьПолеСсылкиLgp(..., N, ...) inside ПоляСсылокЗаписиLgp."""
    start = text.find("Функция ПоляСсылокЗаписиLgp()")
    assert start >= 0, "ПоляСсылокЗаписиLgp not found"
    end = text.find("КонецФункции", start)
    body = text[start:end]
    indices: list[int] = []
    needle = "ДобавитьПолеСсылкиLgp(Результат, "
    pos = 0
    while True:
        i = body.find(needle, pos)
        if i < 0:
            break
        j = i + len(needle)
        k = body.find(",", j)
        indices.append(int(body[j:k].strip()))
        pos = k
    return indices


def test_expected_indices_constant() -> None:
    assert EXPECTED_INDICES == [3, 4, 5, 7, 10, 13, 14, 15]
    assert 16 not in EXPECTED_INDICES


def test_module_matches_expected_indices() -> None:
    text = MODULE_BSL.read_text(encoding="utf-8-sig")
    assert extract_indices_from_bsl(text) == EXPECTED_INDICES


def test_legacy_wrong_indices_differ() -> None:
    assert WRONG_LEGACY_INDICES != EXPECTED_INDICES
    assert WRONG_LEGACY_INDICES[-1] == 16  # session was wrongly remapped


if __name__ == "__main__":
    test_expected_indices_constant()
    test_module_matches_expected_indices()
    test_legacy_wrong_indices_differ()
    print("OK")
