#!/usr/bin/env python3
"""Single entry for all fast Python checks (no 1C runtime).

Runs:
  1) mechanical BSL guards
  2) unittest discovery (TestCase methods)
  3) module-level test_* functions missed by discovery
  4) smoke_analyze on committed fixtures

After a green run, golden fixtures under tests/fixtures/golden must be unchanged.
"""

from __future__ import annotations

import importlib.util
import inspect
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
GOLDEN = TESTS / "fixtures" / "golden"

GUARDS = (
    "check_duplicate_method_names.py",
    "check_bsl_block_balance.py",
    "check_no_new_chained_calls.py",
    "check_no_form_attrs_in_nocontext.py",
    "audit_module_calls.py",
)


def _run_script(rel: str) -> int:
    path = TESTS / rel
    print(f"=== guard: {rel} ===")
    proc = subprocess.run([sys.executable, str(path)], cwd=str(ROOT))
    return int(proc.returncode)


def _load_module(path: Path):
    name = f"epf_tests_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_unittest_discovery() -> tuple[int, int]:
    print("=== unittest discover test_*.py ===")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    loader = unittest.TestLoader()
    suite = loader.discover(str(TESTS), pattern="test_*.py", top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    failed = len(result.failures) + len(result.errors)
    return (1 if failed else 0), result.testsRun


def _module_level_tests(path: Path) -> list:
    mod = _load_module(path)
    found = []
    for name, obj in inspect.getmembers(mod, inspect.isfunction):
        if not name.startswith("test_"):
            continue
        if obj.__module__ != mod.__name__:
            continue
        found.append((name, obj))
    return found


def _run_toplevel_test_functions() -> tuple[int, int]:
    print("=== module-level test_* (outside TestCase) ===")
    ran = 0
    failed = 0
    for path in sorted(TESTS.glob("test_*.py")):
        # Skip if the file is only TestCase-based with no free functions —
        # still safe to scan.
        try:
            tests = _module_level_tests(path)
        except Exception as exc:  # noqa: BLE001 — report and fail the run
            print(f"FAIL load {path.name}: {exc}")
            failed += 1
            continue
        if not tests:
            continue
        print(f"-- {path.name}: {len(tests)} function(s)")
        for name, fn in tests:
            ran += 1
            try:
                fn()
                print(f"  ok {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  FAIL {name}: {exc}")
    return (1 if failed else 0), ran


def _snapshot_golden() -> dict[str, bytes]:
    if not GOLDEN.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(GOLDEN.glob("*.lgp"))}


def _run_smoke() -> int:
    print("=== smoke_analyze.py ===")
    proc = subprocess.run([sys.executable, str(TESTS / "smoke_analyze.py")], cwd=str(ROOT))
    return int(proc.returncode)


def main() -> int:
    before = _snapshot_golden()
    rc = 0
    counts: list[str] = []

    for guard in GUARDS:
        code = _run_script(guard)
        if code != 0:
            rc = 1

    code, n_case = _run_unittest_discovery()
    counts.append(f"TestCase methods run~={n_case}")
    if code != 0:
        rc = 1

    code, n_fn = _run_toplevel_test_functions()
    counts.append(f"module-level test_*={n_fn}")
    if code != 0:
        rc = 1

    if _run_smoke() != 0:
        rc = 1

    after = _snapshot_golden()
    if before != after:
        print("FAIL: golden fixtures changed during the run (must stay immutable)")
        for name in sorted(set(before) | set(after)):
            if before.get(name) != after.get(name):
                print(f"  changed: {name}")
        rc = 1
    else:
        print(f"OK: golden fixtures unchanged ({len(before)} files)")

    print("Summary:", "; ".join(counts), flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
