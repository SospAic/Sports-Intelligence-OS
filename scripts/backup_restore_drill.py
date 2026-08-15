"""Run a non-destructive Compose backup and isolated restore drill.

The drill never removes application volumes. It creates a uniquely named
temporary PostgreSQL database, restores the dump there, validates a query, then
drops only that temporary database. Docker must be available; otherwise the
script exits with the original command error.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


def run(command: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, input=input_bytes, capture_output=True, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix="sio-backup-drill-"))
    output.mkdir(parents=True, exist_ok=True)
    compose = ["docker", "compose"]
    db_user = os.environ.get("POSTGRES_USER", "sio")
    db_name = os.environ.get("POSTGRES_DB", "sports_intelligence")
    restore_db = f"sio_restore_drill_{os.getpid()}"
    dump_path = output / "postgres.dump"
    media_path = output / "media.tar.gz"
    redis_path = output / "redis.rdb"

    try:
        dump = run(
            compose
            + [
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "-U",
                db_user,
                "-d",
                db_name,
            ]
        )
        dump_path.write_bytes(dump.stdout)

        media = run(compose + ["exec", "-T", "api", "tar", "-C", "/workspace/media", "-czf", "-", "."])
        media_path.write_bytes(media.stdout)

        run(compose + ["exec", "-T", "redis", "redis-cli", "--rdb", "/tmp/sio-restore-drill.rdb"])
        run(compose + ["cp", "redis:/tmp/sio-restore-drill.rdb", str(redis_path)])

        run(compose + ["exec", "-T", "postgres", "dropdb", "--if-exists", "-U", db_user, restore_db])
        run(compose + ["exec", "-T", "postgres", "createdb", "-U", db_user, restore_db])
        run(
            compose
            + [
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "-U",
                db_user,
                "-d",
                restore_db,
            ],
            input_bytes=dump_path.read_bytes(),
        )
        check = run(
            compose
            + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-At",
                "-U",
                db_user,
                "-d",
                restore_db,
                "-c",
                "SELECT current_database()",
            ]
        )
        if check.stdout.decode().strip() != restore_db:
            raise RuntimeError("restored database identity check failed")
    finally:
        subprocess.run(
            compose + ["exec", "-T", "postgres", "dropdb", "--if-exists", "-U", db_user, restore_db],
            check=False,
            capture_output=True,
        )

    manifest = []
    for path in (dump_path, media_path, redis_path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.append(f"{path.name}\t{path.stat().st_size}\t{digest}")
    (output / "SHA256SUMS").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(f"Backup and isolated restore drill passed: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
