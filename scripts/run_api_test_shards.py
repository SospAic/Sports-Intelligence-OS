"""Run each API test module in an isolated pytest process.

The repository's PostgreSQL fixture intentionally resets a shared database per
test. Module-level processes avoid the long merged-suite lock/WAL contention
while still executing every collected test file and preserving failures.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, default=Path("apps/api"))
    parser.add_argument("--report", type=Path, default=Path("api-test-shards.txt"))
    args = parser.parse_args()
    test_files = sorted((args.workdir / "tests").glob("test_*.py"))
    if not test_files:
        raise SystemExit(f"no API test files found under {args.workdir / 'tests'}")

    results: list[str] = []
    failed = False
    for path in test_files:
        started = time.monotonic()
        relative = path.relative_to(args.workdir).as_posix()
        print(f"\n=== {relative} ===", flush=True)
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", relative, "-q"],
            cwd=args.workdir,
            check=False,
        )
        duration = time.monotonic() - started
        status = "passed" if completed.returncode == 0 else "failed"
        results.append(f"{relative}\t{status}\t{duration:.2f}s")
        if completed.returncode != 0:
            failed = True

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(results) + "\n", encoding="utf-8")
    print(f"\nExecuted {len(test_files)} API test shards; report: {args.report}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
