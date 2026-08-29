# Fixtures для smoke-тестов и golden Phase 2

Минимальные каталоги журнала регистрации (старый формат `lgf`/`lgp`) для `smoke_analyze.py` без зависимости от Desktop.

| Каталог | Назначение |
| --- | --- |
| `jr_src` | Источник (старый кластер) |
| `jr_dst` | Приёмник (новый кластер, другой GUID журнала) |
| `golden/` | Синтетические анонимизированные `.lgp` для дедупа, транзакций, split по дням, архива |

Пересоздать jr_*:

```powershell
python tests/bootstrap_fixtures.py
```

Golden создаются тестом `test_merge_quality.py` (или `python -c "from tests.lgp_merge_quality import write_golden_fixtures; write_golden_fixtures('.')"`).
