# Verification hotfix 1.3.22

**Дата:** 30.08.2026  
**Цель:** форма внешней обработки снова открывается в 1С.

## Симптом

```
Ошибка инициализации модуля: ...Форма.Форма.Форма
{...(2342,48)}: Неопознанный оператор
		РазмерБайт = РазмерБайт + Новый Файл(ПутьLgf)<<?>>.Размер();
[ОшибкаКомпиляцииВстроенногоЯзыка]
```

## Причина

В BSL нельзя вызывать метод сразу на результате конструктора `Новый Файл(...)` в одном выражении.

## Исправления в Module.bsl

| Место | Было | Стало |
|---|---|---|
| `РазмерФайловЖРВКаталоге` (~2342) | `РазмерБайт + Новый Файл(ПутьLgf).Размер()` | `ФайлLgf = Новый Файл(...); РазмерБайт + ФайлLgf.Размер()` |
| `ДописатьЗаписиLgpИзФайлаПострочно` (~3757) | `Новый Файл(ПутьИсточника).Размер()` | `ФайлИсточникаРазмер = Новый Файл(...); ...Размер()` |

ObjectModule: только версия → `1.3.22`.

## Доказательства

### Grep: нет цепочек `Новый ...).`

```
pattern: Новый\s+\w+\([^)]*\)\s*\.
path: ПрисоединениеЖурналаРегистрации/
result: No matches found
```

### `tests/check_no_new_chained_calls.py`

```
OK: no chained Новый in Module.bsl
OK: no chained Новый in ObjectModule.bsl
PASS: check_no_new_chained_calls
exit=0
```

### `tests/check_duplicate_method_names.py`

```
OK: 247 unique declarations in Module.bsl
exit=0
```

### syntaxcheck MCP (ObjectModule + Module q1–q4)

```
ObjectModule.bsl: errors=0
Module_q1: errors=0
Module_q2: errors=0
Module_q3: errors=0
Module_q4: errors=0
TOTAL errors=0
```

### unittest + smoke

```
Ran 13 tests ... OK
SMOKE OK: analyze
```

### Designer / EPF

- Команда: `1cv8 DESIGNER /LoadExternalDataProcessorOrReportFromFiles`
- `designer_load.log`: «Загрузка завершена» (~1719 мс), без фатальных ошибок
- Файл: `ПрисоединениеЖурналаРегистрации.epf`, размер ~48033 байт, время сборки 30.08.2026

### Версия синхронна

- `ObjectModule.bsl` → `"1.3.22"`
- `НомерВерсииОбработки()` → `"1.3.22"`
- README / `.ai/project-knowledge.md` / `.ai/current-task.md`

## Релиз

- URL: https://github.com/MamakovTimur/attach-1c-event-log/releases/tag/v1.3.22
- Asset: **ПрисоединениеЖурналаРегистрации.epf** (не `default.epf`)
- Tag: `v1.3.22`

## Вердикт

**PASS** — hotfix готов к открытию формы в 1С.
