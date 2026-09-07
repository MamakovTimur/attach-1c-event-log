---
name: mcp-1c-epf
description: >-
  Dispatcher for OneRPA MCP allowed in this standalone EPF (docs, templates,
  syntaxcheck, Напарник, SSL registration only). Use proactively before writing
  or reviewing BSL, checking platform API, or validating syntax. Never call
  code-metadata or graph-metadata servers.
---

# MCP для этой EPF

Индекс code/graph metadata — **чужая БП КОРП**. Не вызывать их инструменты.

Перед вызовом убедись, что сервер есть в схеме инструментов текущей сессии. Имена namespace часто с префиксом `user-`.

## Каталог

| Сервер | Когда | Инструменты |
|---|---|---|
| `1C-docs-mcp` | API платформы, события формы, файлы, кодировки | `docsearch` (описание), `docinfo` (точное имя) |
| `1c-templates-mcp` | перед новой нетривиальной процедурой | `templatesearch`, запрос **по-русски** |
| `1c-syntax-checker-mcp` | после каждой правки BSL | `syntaxcheck`: `code` = весь модуль, `file_name` = `Module.bsl` или `ObjectModule.bsl` (имя, не путь) |
| `1c-code-check-mcp` | логика/стиль | `check_1c_code`, `review_1c_code` — только `code` |
| `1c-ssl-mcp` | только регистрация доп. обработки | `ssl_search` про `СведенияОВнешнейОбработке` |

## Запрещено

- Весь `1c-code-metadata-mcp` и `1c-graph-metadata-mcp`
- `remember` / `recall` (общая память с Techno1CAccMCP)
- `files` у Напарника (монтирована чужая выгрузка)
- `rewrite_1c_code` / `modify_1c_code`, пока пользователь явно не попросил черновик; правку всё равно вносить в файлы репозитория самому

## Порядок на задаче BSL

1. `Grep`/`Read` локальных модулей — как уже сделано в обработке.
2. При сомнении в методе платформы — `docsearch` (`detail_level=compact`, `max_items=3`), затем `docinfo`.
3. `templatesearch`, если пишешь новый кусок (диалог выбора каталога, чтение/запись текста, работа с файлами). Шаблон — старт, не слепое копирование из конфигурации.
4. Правка файла на диске.
5. `syntaxcheck` по полному тексту модуля.
6. `python tests/check_duplicate_method_names.py` если трогали модуль формы.

`syntaxcheck` не видит дубли имён `&НаКлиенте`/`&НаСервере` как ошибку формы — тест обязателен.
