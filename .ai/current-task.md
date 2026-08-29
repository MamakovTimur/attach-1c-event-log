# Текущая задача: Фаза 2 — Качество merge

**Статус:** выполнено (29.08.2026). Версия **1.3.21**.

Полный план: `.ai/roadmap-2026-08.md`.

## Чеклист Фазы 2

| # | Задача | Статус |
|---|--------|--------|
| 1 | Дедупликация опциональная (флаг, default OFF) + тесты | ✅ |
| 2 | Предупреждение/защита транзакций в dry-run + sticky day при split | ✅ |
| 3 | Golden/synthetic fixtures + Python-тесты | ✅ |
| 4 | Split по дню (MVP: «Разбивать источник по дням») | ✅ |
| 5 | Архивный формат read-only detection | ✅ |
| 6 | Версия 1.3.21: ObjectModule, `НомерВерсииОбработки()`, README, knowledge | ✅ |
| 7 | Form.xml: реквизиты/флаги | ✅ |
| 8 | syntaxcheck + duplicate names + unittest + smoke | ✅ (см. verification) |
| 9 | Пересборка EPF | ✅ |

## Изменённые файлы

- `Forms/Форма/Ext/Form.xml` — флаги дедупликации и разбивки по дням
- `Forms/Форма/Ext/Form/Module.bsl` — качество склейки Фазы 2
- `Ext/ObjectModule.bsl` — версия 1.3.21
- `tests/lgp_merge_quality.py`, `tests/test_merge_quality.py`, `tests/fixtures/golden/`
- `README.md`, `.ai/*`, `.gitignore`

## Следующий шаг

Фаза 3 — автоматизация (`/C`, OneScript, exit codes).
