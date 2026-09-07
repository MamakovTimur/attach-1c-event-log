#!/usr/bin/env python3
"""Reproducible performance benchmark for the Python event-log engine.

The benchmark creates disposable synthetic journals and runs the real
``tools/attach_event_log.py`` command.  It measures wall-clock time,
throughput and peak resident memory of the child process.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "tools" / "attach_event_log.py"
MIB = 1024 * 1024
FREE_SPACE_MARGIN = 64 * MIB
SOURCE_GUID = "aaaaaaaa-e311-4ee2-8582-7a2a46a59363"
DESTINATION_GUID = "bbbbbbbb-e311-4ee2-8582-7a2a46a59363"
PERIOD_NAME = "20260101000000.lgp"


def _write_lgf(path: Path, guid: str, *, remap_destination: bool) -> None:
    if remap_destination:
        rows = [
            '{1,11111111-1111-1111-1111-111111111111,"User",5},',
            '{2,"OTHER-PC",2},',
            '{3,"App",1},',
            '{4,"OtherEvent",3}',
        ]
    else:
        rows = [
            '{1,11111111-1111-1111-1111-111111111111,"User",1},',
            '{2,"PC",1},',
            '{3,"App",1},',
            '{4,"Event",1}',
        ]
    text = f"1CV8LOG(ver 2.0)\r\n{guid}\r\n\r\n" + "\r\n".join(rows) + "\r\n"
    path.write_bytes(("\ufeff" + text).encode("utf-8"))


def _record(number: int) -> bytes:
    seconds = number % 86400
    hour, seconds = divmod(seconds, 3600)
    minute, second = divmod(seconds, 60)
    timestamp = f"20260101{hour:02d}{minute:02d}{second:02d}"
    payload = (
        f'{{{timestamp},N,{{0,0}},1,1,1,1,1,I,"",0,'
        f'{{"U"}},"benchmark-{number:010d}",0,0,0,1,0,{{0}}}}'
    )
    return payload.encode("utf-8")


def write_synthetic_lgp(path: Path, guid: str, target_bytes: int) -> int:
    """Write at least target_bytes without retaining records in memory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ("\ufeff1CV8LOG(ver 2.0)\r\n" + guid + "\r\n\r\n").encode("utf-8")
    count = 0
    with path.open("wb") as stream:
        stream.write(header)
        buffer = bytearray()
        while stream.tell() + len(buffer) < target_bytes:
            if count:
                buffer.extend(b",\r\n")
            buffer.extend(_record(count))
            count += 1
            if len(buffer) >= MIB:
                stream.write(buffer)
                buffer.clear()
        stream.write(buffer)
        stream.write(b"\r\n")
    return count


def create_case(root: Path, size_mib: float, scenario: str) -> dict[str, Any]:
    remap = scenario == "remap"
    source = root / "src"
    destination = root / "dst"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    source_guid = SOURCE_GUID
    destination_guid = DESTINATION_GUID if remap else SOURCE_GUID
    _write_lgf(source / "1Cv8.lgf", source_guid, remap_destination=False)
    _write_lgf(
        destination / "1Cv8.lgf",
        destination_guid,
        remap_destination=remap,
    )
    requested = max(1, int(size_mib * MIB))
    records = write_synthetic_lgp(source / PERIOD_NAME, source_guid, requested)
    actual = (source / PERIOD_NAME).stat().st_size
    return {
        "source": source,
        "destination": destination,
        "input_bytes": actual,
        "records": records,
    }


def _rss_bytes_windows(pid: int) -> int | None:
    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    query = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(query, False, pid)
    if not handle:
        return None
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        return int(counters.WorkingSetSize) if ok else None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def process_rss_bytes(pid: int) -> int | None:
    if os.name == "nt":
        return _rss_bytes_windows(pid)
    status = Path(f"/proc/{pid}/status")
    try:
        for line in status.read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def run_engine(mode: str, case: dict[str, Any]) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ENGINE),
        "--mode",
        mode,
        "--src",
        str(case["source"]),
        "--dst",
        str(case["destination"]),
    ]
    if mode == "attach":
        command.extend(["--conflict", "merge", "--files", PERIOD_NAME])
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    output_lines: list[str] = []

    def drain_output() -> None:
        assert process.stdout is not None
        output_lines.extend(process.stdout)

    reader = threading.Thread(target=drain_output, daemon=True)
    reader.start()
    peak_rss = 0
    while process.poll() is None:
        rss = process_rss_bytes(process.pid)
        if rss is not None:
            peak_rss = max(peak_rss, rss)
        time.sleep(0.02)
    reader.join()
    if process.stdout is not None:
        process.stdout.close()
    output = "".join(output_lines)
    elapsed = time.perf_counter() - started
    if process.returncode != 0:
        raise RuntimeError(
            f"engine failed with exit code {process.returncode}:\n{output}"
        )
    input_mib = case["input_bytes"] / MIB
    throughput = input_mib / elapsed if mode == "attach" and elapsed else None
    return {
        "mode": mode,
        "elapsed_seconds": round(elapsed, 6),
        "throughput_mib_s": round(throughput, 3) if throughput is not None else None,
        "peak_rss_mib": round(peak_rss / MIB, 3) if peak_rss else None,
    }


def parse_sizes(value: str) -> list[float]:
    try:
        sizes = [float(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("sizes must be comma-separated numbers") from exc
    if not sizes or any(size <= 0 for size in sizes):
        raise argparse.ArgumentTypeError("every size must be greater than zero")
    return sizes


def estimate_benchmark_disk_bytes(
    sizes: list[float],
    scenarios: list[str],
    modes: list[str],
    repeat: int,
) -> int:
    """Estimate retained input/output data for all generated benchmark cases."""
    total = 0
    writes_output = "attach" in modes
    for size in sizes:
        source_bytes = max(1, int(size * MIB))
        for scenario in scenarios:
            multiplier = 1
            if writes_output:
                multiplier += 2 if scenario == "remap" else 1
            total += source_bytes * multiplier * repeat
    return total + FREE_SPACE_MARGIN


def benchmark(
    sizes: list[float],
    scenarios: list[str],
    modes: list[str],
    repeat: int,
    work_dir: Path | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    parent = work_dir or Path(tempfile.mkdtemp(prefix="event-log-benchmark-"))
    parent.mkdir(parents=True, exist_ok=True)
    remove_parent = work_dir is None
    try:
        required = estimate_benchmark_disk_bytes(
            sizes, scenarios, modes, repeat
        )
        free = shutil.disk_usage(parent).free
        if free < required:
            raise RuntimeError(
                "not enough free space for benchmark: "
                f"{free / MIB:.1f} MiB available, {required / MIB:.1f} MiB required"
            )
        for size in sizes:
            for scenario in scenarios:
                for iteration in range(1, repeat + 1):
                    case_root = parent / f"{size:g}MiB-{scenario}-{iteration}"
                    if case_root.exists():
                        shutil.rmtree(case_root)
                    case = create_case(case_root, size, scenario)
                    base = {
                        "size_mib": round(case["input_bytes"] / MIB, 3),
                        "input_bytes": case["input_bytes"],
                        "records": case["records"],
                        "scenario": scenario,
                        "iteration": iteration,
                    }
                    for mode in modes:
                        result = {**base, **run_engine(mode, case)}
                        results.append(result)
                        speed = result["throughput_mib_s"]
                        speed_text = f"{speed:.1f} MiB/s" if speed is not None else "n/a"
                        print(
                            f"{size:g} MiB | {scenario:8s} | {mode:7s} | "
                            f"{result['elapsed_seconds']:.3f} s | "
                            f"{speed_text} | "
                            f"peak RSS {result['peak_rss_mib']} MiB"
                        )
        return results
    finally:
        if remove_parent:
            shutil.rmtree(parent, ignore_errors=True)


def build_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    engine_hash = hashlib.sha256(ENGINE.read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "engine": str(ENGINE.relative_to(ROOT)),
            "engine_sha256": engine_hash,
        },
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate synthetic LGP files and benchmark the Python engine"
    )
    parser.add_argument(
        "--sizes-mib",
        type=parse_sizes,
        default=parse_sizes("100"),
        help="Comma-separated input sizes; for example 100,1024,10240",
    )
    parser.add_argument(
        "--scenario",
        choices=("no-remap", "remap", "both"),
        default="both",
    )
    parser.add_argument(
        "--mode", choices=("analyze", "attach", "both"), default="both"
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--json-out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repeat < 1:
        raise SystemExit("--repeat must be greater than zero")
    scenarios = ["no-remap", "remap"] if args.scenario == "both" else [args.scenario]
    modes = ["analyze", "attach"] if args.mode == "both" else [args.mode]
    results = benchmark(args.sizes_mib, scenarios, modes, args.repeat, args.work_dir)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(build_report(results), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
