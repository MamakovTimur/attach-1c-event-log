#!/usr/bin/env python3
"""Real smoke: open EPF in 1C ENTERPRISE and fail on module init/compile errors.

Uses the newest installed 1cv8.exe, file IB `_tmp_ib`, and `/Execute` on
`ПрисоединениеЖурналаРегистрации.epf`. Must pass before giving the EPF to users.

Exit codes:
  0 — no init/compile markers in the platform log
  1 — compile/init error detected (form would not open)
  2 — environment/setup failure (no 1cv8, no epf, IB create failed)
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPF = ROOT / "ПрисоединениеЖурналаРегистрации.epf"
IB = ROOT / "_tmp_ib"
LOG = ROOT / "smoke_open_epf.log"
CREATE_LOG = ROOT / "smoke_open_epf_create_ib.log"

# Hard failure markers from the user's screenshot / platform messages.
FAIL_MARKERS = (
    "Ошибка инициализации модуля",
    "ОшибкаКомпиляцииВстроенногоЯзыка",
    "Переменная не определена",
    "Неопознанный оператор",
)

# Soft hints that the form at least got past compile (best-effort).
OK_HINTS = (
    "Присоединение журнала",
    "ВнешняяОбработка",
)

TIMEOUT_SEC = 45


def find_1cv8() -> Path | None:
    bases = [
        Path(r"C:\Program Files\1cv8"),
        Path(r"C:\Program Files (x86)\1cv8"),
    ]
    found: list[Path] = []
    for base in bases:
        if not base.is_dir():
            continue
        found.extend(base.glob(r"*\bin\1cv8.exe"))
    if not found:
        return None
    # Prefer highest version folder name (8.3.27.2325 > 8.3.27.1936).
    found.sort(key=lambda p: p.parent.parent.name)
    return found[-1]


def ensure_ib(cv8: Path) -> int:
    marker = IB / "1Cv8.1CD"
    if marker.is_file():
        print(f"OK: reuse IB {IB}")
        return 0
    IB.mkdir(parents=True, exist_ok=True)
    create_arg = f'File="{IB}";'
    cmd = [
        str(cv8),
        "CREATEINFOBASE",
        create_arg,
        "/Out",
        str(CREATE_LOG),
    ]
    print("RUN:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), timeout=120)
    if proc.returncode != 0 and not marker.is_file():
        print(f"FAIL: CREATEINFOBASE rc={proc.returncode}, see {CREATE_LOG}", file=sys.stderr)
        return 2
    if not marker.is_file():
        print(f"FAIL: IB not created at {marker}", file=sys.stderr)
        return 2
    print(f"OK: created IB {IB}")
    return 0


def run_execute(cv8: Path) -> tuple[int, str, float]:
    if LOG.is_file():
        LOG.unlink()
    cmd = [
        str(cv8),
        "ENTERPRISE",
        "/F",
        str(IB),
        "/Execute",
        str(EPF),
        "/DisableStartupMessages",
        "/DisableStartupDialogs",
        "/Out",
        str(LOG),
    ]
    print("RUN:", " ".join(cmd))
    print(f"timeout={TIMEOUT_SEC}s (UI may stay open; we only need the log)")
    t0 = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            timeout=TIMEOUT_SEC,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        rc = proc.returncode
        extra = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        # Expected when the form opens and waits for the user.
        timed_out = True
        rc = -9
        out = exc.stdout or b""
        err = exc.stderr or b""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        extra = out + "\n" + err
        print("INFO: process timed out (often OK if form compiled and stayed open)")
        # subprocess.run already kills the child on timeout — do not taskkill /IM.
    elapsed = time.monotonic() - t0
    time.sleep(0.5)
    log_text = ""
    if LOG.is_file():
        log_text = LOG.read_text(encoding="utf-8", errors="replace")
    combined = log_text + "\n" + extra
    if timed_out:
        combined += "\n__SMOKE_TIMED_OUT__\n"
    return rc, combined, elapsed


def main() -> int:
    if not EPF.is_file():
        print(f"FAIL: EPF not found: {EPF}", file=sys.stderr)
        return 2

    cv8 = find_1cv8()
    if cv8 is None:
        print("FAIL: 1cv8.exe not found under Program Files\\1cv8", file=sys.stderr)
        return 2
    print(f"OK: 1cv8={cv8}")

    ib_rc = ensure_ib(cv8)
    if ib_rc != 0:
        return ib_rc

    rc, text, elapsed = run_execute(cv8)
    print(f"platform_rc={rc} elapsed={elapsed:.1f}s")
    print(f"log={LOG} bytes={LOG.stat().st_size if LOG.is_file() else 0}")

    hits = [m for m in FAIL_MARKERS if m in text]
    if hits:
        print("FAIL: form/module compile-init markers in platform output:", file=sys.stderr)
        for m in hits:
            print(f"  - {m}", file=sys.stderr)
        for line in text.splitlines():
            if any(m in line for m in hits):
                print(f"  LOG: {line[:240]}", file=sys.stderr)
        return 1

    if re.search(r"Переменная не определена\s*\(", text):
        print("FAIL: undefined variable while opening EPF", file=sys.stderr)
        return 1

    # Immediate exit with empty log usually means the client never opened the form.
    if "__SMOKE_TIMED_OUT__" not in text and elapsed < 5 and (
        not LOG.is_file() or LOG.stat().st_size == 0
    ):
        print(
            f"FAIL: 1cv8 exited in {elapsed:.1f}s with empty /Out — "
            "form likely failed before logging",
            file=sys.stderr,
        )
        return 1

    print("PASS: smoke_open_epf — no module init/compile errors in log")
    if any(h in text for h in OK_HINTS):
        print("INFO: log contains soft OK hints")
    if "__SMOKE_TIMED_OUT__" in text:
        print("INFO: client stayed up until timeout (good sign for form compile)")
    elif not LOG.is_file() or LOG.stat().st_size == 0:
        print("WARN: empty /Out log — no failure markers found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
