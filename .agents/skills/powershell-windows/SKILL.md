---
name: powershell-windows
description: >-
  PowerShell 5.1 rules for this Windows repo: quoting, no &&, LASTEXITCODE,
  Start-Sleep. Use when running shell, git, python tests, or Designer CLI.
---

# PowerShell (Windows)

- Разделитель команд: `;`, не `&&` (PS 5.1). Зависимые native-команды проверяй `$LASTEXITCODE`.
- Пути с пробелами и кириллицей — **в двойных кавычках**.
- Пауза: `Start-Sleep -Seconds N`, не `timeout`.
- Тесты: `python tests/check_duplicate_method_names.py` из корня репозитория.
- Не предлагать bash-only конструкции (`export`, heredoc `$(cat <<'EOF')` без обёртки). Для `git commit` на Windows:

```powershell
git commit -m "сообщение"
```

Многострочное сообщение:

```powershell
git commit -m @"
Первая строка.

Вторая строка.
"@
```
