# Fixtures для smoke-тестов и golden Phase 2

Минимальные каталоги журнала регистрации (старый формат `lgf`/`lgp`) для `smoke_analyze.py` без зависимости от Desktop.

| Каталог | Назначение |
| --- | --- |
| `jr_src` | Источник (старый журнал) |
| `jr_dst` | Приёмник (текущий журнал, другой GUID) |
| `golden/` | Синтетические анонимизированные `.lgp` для дедупа, транзакций, split по дням, архива |

Пересоздать jr_*:

```powershell
python tests/bootstrap_fixtures.py
```

**Golden — неизменяемые байты в git.** Тесты их не перезаписывают. Сознательно пересоздать:

```powershell
python -c "from pathlib import Path; import sys; sys.path.insert(0, 'tests'); from lgp_merge_quality import write_golden_fixtures; write_golden_fixtures(Path('.'))"
```

Запись идёт через `write_bytes` (UTF-8 BOM + явный CRLF), без text-mode перевода строк ОС.

Единый прогон всех Python-проверок:

```powershell
python tests/run_all.py
```
