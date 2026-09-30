from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import subprocess
import os

from app.core.config import settings
from sqlalchemy.engine import make_url


def create_backup(directory: Path | None = None) -> Path:
    target_dir = directory or settings.private_storage_dir.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"latentsig-{stamp}.backup"
    partial = target.with_suffix(target.suffix + ".partial")

    if settings.database_url.startswith("sqlite:"):
        raw_path = settings.database_url.removeprefix("sqlite:///")
        source = Path(raw_path)
        if not source.is_absolute():
            source = Path.cwd() / source
        if not source.is_file():
            raise FileNotFoundError(f"SQLite database does not exist: {source}")
        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(partial)) as dst:
            src.backup(dst)
        with closing(sqlite3.connect(partial)) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite backup failed its integrity check.")
    else:
        executable = shutil.which("pg_dump")
        if not executable:
            raise RuntimeError("Install PostgreSQL client tools to back up a PostgreSQL database.")
        url = make_url(settings.database_url)
        environment = os.environ.copy()
        if url.password:
            environment["PGPASSWORD"] = url.password
        command = [executable, "--format=custom", "--no-owner", "--file", str(partial)]
        for option, value in (("--host", url.host), ("--port", str(url.port) if url.port else None), ("--username", url.username)):
            if value:
                command.extend((option, value))
        command.append(url.database or "")
        subprocess.run(command, env=environment, check=True)
        listing = subprocess.run([shutil.which("pg_restore") or "pg_restore", "--list", str(partial)], check=True, capture_output=True)
        if not listing.stdout:
            raise RuntimeError("PostgreSQL backup archive verification returned no contents.")

    partial.replace(target)
    cutoff = datetime.now(timezone.utc).timestamp() - 14 * 24 * 60 * 60
    for old_backup in target_dir.glob("latentsig-*.backup"):
        if old_backup != target and old_backup.stat().st_mtime < cutoff:
            old_backup.unlink()
    return target


if __name__ == "__main__":
    print(create_backup())
