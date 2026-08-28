# Присоединение журнала регистрации — правила агента

Автономная **внешняя обработка** (выгрузка EPF в XML/BSL). Это не конфигурация и не расширение. Источник правды — файлы в этом репозитории, не индекс OneRPA.

Читай `.ai/project-knowledge.md` в начале сессии. Общайся с пользователем **по-русски**.

## Жёсткие запреты

Не вызывай инструменты серверов `1c-code-metadata-mcp` и `1c-graph-metadata-mcp` (в сессии они часто видны как `user-1c-code-metadata-mcp` / `user-1c-graph-metadata-mcp`). Их индекс — чужая типовая БП КОРП.

Не используй `remember` / `recall`, RSV/EDT (`edit_metadata`, `write_module_source`), `1c-explorer`, `1c-metadata-manager`, команды ИБ (`/update1cbase`, `/loadfrom1cbase`).

Поиск по обработке: `Grep` / `Glob` / `Read` по диску. Не «ориентируйся» через codesearch/graph.

Правка `.bsl` / `Form.xml` / корневого XML — обычными файловыми инструментами Cursor. Это выгрузка EPF, не EDT.

## Разрешённый MCP

Диспетчер: skill `mcp-1c-epf`. Кратко:

| Задача | Инструмент |
|---|---|
| Справка платформы | `docsearch` / `docinfo` |
| Шаблон BSL | `templatesearch` (запрос по-русски) |
| Синтаксис после правки | `syntaxcheck` с текстом модуля, `file_name` = `Module.bsl` или `ObjectModule.bsl` |
| Ревью BSL | `check_1c_code` / `review_1c_code` — только аргумент `code`, не `files` |
| Регистрация в БСП | `ssl_search` только для `СведенияОВнешнейОбработке` |

Платформа **8.3.10+**: не вводить `Асинх`/`Ждать`. Диалоги — `ОписаниеОповещения`, как в текущем модуле формы.

## Скиллы и субагенты

- Любая правка BSL — skill `epf-bsl`.
- Сборка `.epf` — skill `epf-build`.
- Shell на Windows — skill `powershell-windows`.
- Нетривиальный BSL (новая процедура, клиент/сервер, формат lgf/lgp) — субагент `1c-developer`.
- После записи BSL — `1c-code-reviewer`.
- Ошибка, форма не открывается, падает тест — `1c-error-fixer`.
- Однострочник / опечатка — родитель сам, без конвейера.

Если тип субагента недоступен в `Task` — родитель выполняет тот же чеклист из файла агента, не пропускает проверки.

## Проверка после правки BSL

1. `syntaxcheck` по полному тексту затронутого модуля.
2. `python tests/check_duplicate_method_names.py`
3. Релевантные тесты: `tests/test_lgp_header_and_integrity.py`, `tests/smoke_analyze.py`.
4. Не оставлять одно имя у `&НаКлиенте` и `&НаСервере`.
