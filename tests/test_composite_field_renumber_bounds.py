# Regression: ПеренумероватьСоставноеПоле must use 0-based loops.
# Old BSL loop `Для Индекс = 1 По Части.Количество()` crashes on {"U"} (len=1).

from __future__ import annotations


def tokenize(text: str) -> list[str]:
    """Mirror of Module.bsl Токенизировать for bracket bodies."""
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    in_quotes = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quotes:
            current.append(ch)
            if ch == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    current.append('"')
                    i += 2
                    continue
                in_quotes = False
            i += 1
            continue
        if ch == '"':
            in_quotes = True
            current.append(ch)
        elif ch == "{":
            depth += 1
            current.append(ch)
        elif ch == "}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            tokens.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current or text:
        tokens.append("".join(current).strip())
    return tokens


def body_of_bracket(value: str) -> str:
    value = value.strip()
    assert value.startswith("{") and value.endswith("}")
    return value[1:-1]


def renumber_composite_old_1based(parts: list[str]) -> list[str]:
    """Simulates broken BSL: Для Индекс = 1 По Части.Количество()."""
    result = list(parts)
    for index in range(1, len(parts) + 1):
        result[index] = result[index]  # noqa: B018 — access is the bug
    return result


def renumber_composite_new_0based(parts: list[str]) -> list[str]:
    """Simulates fixed BSL: Для Индекс = 0 По Части.ВГраница()."""
    result = list(parts)
    for index in range(len(parts)):  # 0 .. ВГраница inclusive
        result[index] = result[index]
    return result


def record_field_accessible(token_count: int, field_index_0based: int, use_safe_check: bool) -> bool:
    """
    Old check: КоличествоТокенов < ИндексПоля  → still accesses when equal.
    New check: ИндексПоля > ВГраница() (= count-1).
    """
    if use_safe_check:
        vgranica = token_count - 1
        return field_index_0based <= vgranica
    return not (token_count < field_index_0based)


def test_tokenize_singleton_u() -> None:
    parts = tokenize(body_of_bracket('{"U"}'))
    assert parts == ['"U"']
    assert len(parts) == 1


def test_tokenize_two_numbers() -> None:
    parts = tokenize(body_of_bracket("{1,2}"))
    assert parts == ["1", "2"]
    assert len(parts) == 2


def test_old_loop_crashes_on_singleton() -> None:
    parts = tokenize(body_of_bracket('{"U"}'))
    raised = False
    try:
        renumber_composite_old_1based(parts)
    except IndexError:
        raised = True
    assert raised, "old 1-based loop must IndexError on len=1"


def test_new_loop_ok_on_singleton() -> None:
    parts = tokenize(body_of_bracket('{"U"}'))
    result = renumber_composite_new_0based(parts)
    assert result == ['"U"']


def test_both_loops_ok_on_two_parts() -> None:
    parts = tokenize(body_of_bracket("{1,2}"))
    assert renumber_composite_new_0based(parts) == ["1", "2"]
    # Old loop still crashes: range(1, 3) accesses [1] and [2], [2] OOB
    raised = False
    try:
        renumber_composite_old_1based(parts)
    except IndexError:
        raised = True
    assert raised, "old loop also OOB on len=2 (accesses [2])"


def test_record_bounds_equal_index_is_oob_with_old_check() -> None:
    # 12 tokens → indices 0..11; field 11 is valid; field 12 is not
    assert record_field_accessible(12, 11, use_safe_check=False) is True
    assert record_field_accessible(12, 12, use_safe_check=False) is True  # bug: allows OOB
    assert record_field_accessible(12, 11, use_safe_check=True) is True
    assert record_field_accessible(12, 12, use_safe_check=True) is False


if __name__ == "__main__":
    test_tokenize_singleton_u()
    test_tokenize_two_numbers()
    test_old_loop_crashes_on_singleton()
    test_new_loop_ok_on_singleton()
    test_both_loops_ok_on_two_parts()
    test_record_bounds_equal_index_is_oob_with_old_check()
    print("OK")
