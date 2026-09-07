---
name: epf-build
description: >-
  Rebuild ПрисоединениеЖурналаРегистрации.epf from XML/BSL dump via Designer
  /LoadExternalDataProcessorOrReportFromFiles. Use when assembling EPF, after
  BSL/XML changes that must ship in the binary, or when the user asks to
  пересобрать обработку.
---

# Сборка EPF

Исходники: `ПрисоединениеЖурналаРегистрации.xml` + каталог `ПрисоединениеЖурналаРегистрации/`. Бинарник в корне: `ПрисоединениеЖурналаРегистрации.epf` (исключение в `.gitignore`).

Не вызывать `/LoadCfg`, `/UpdateDBCfg`, dump конфигурации. Это не CF.

## Командная строка (предпочтительно)

Временная **файловая** ИБ + Конфигуратор. Путь к `1cv8.exe` уточни у пользователя или найди типичный `C:\Program Files\1cv8\8.3.*\bin\1cv8.exe` — не угадывай версию, если их несколько.

```powershell
$ib = Join-Path $PWD "_tmp_ib"
$epf = Join-Path $PWD "ПрисоединениеЖурналаРегистрации.epf"
$src = Join-Path $PWD "ПрисоединениеЖурналаРегистрации.xml"
New-Item -ItemType Directory -Force -Path $ib | Out-Null
& "C:\Program Files\1cv8\<версия>\bin\1cv8.exe" CREATEINFOBASE "File=""$ib"";" /Out "designer_create.log"
& "C:\Program Files\1cv8\<версия>\bin\1cv8.exe" DESIGNER /F $ib /LoadExternalDataProcessorOrReportFromFiles $src $epf /Out "designer_load.log"
```

`_tmp_ib/` в `.gitignore`. Если ИБ уже есть — не создавать заново.

Успех: в логе нет фатальных ошибок, `.epf` обновлён по времени. Покажи пользователю путь к логу, если Designer вернул ненулевой код.

## Через GUI (если нет 1cv8 в PATH)

Как в README: новая внешняя обработка → **Загрузить из файлов** → каталог с `ПрисоединениеЖурналаРегистрации.xml` → сохранить EPF. Безопасный режим выключен.

## После сборки

Не коммить `.epf`, пока пользователь не попросил релиз. Для проверки достаточно, что файл собрался.
