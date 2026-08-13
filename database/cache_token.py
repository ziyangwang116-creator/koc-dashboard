from __future__ import annotations

import hashlib
from pathlib import Path

from database.db import connect, is_postgres_target


DatabaseCacheToken = tuple[tuple[str, int, int], ...]


def _file_state(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (str(path.resolve()), -1, -1)
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def dashboard_cache_token(database_path: Path | str) -> DatabaseCacheToken:
    """Return a compact token that changes after dashboard-related writes."""
    if is_postgres_target(database_path):
        digest = hashlib.sha256()
        total_count = 0
        tracked_tables = (
            ("dashboard_post", "updated_at"),
            ("koc_master", "updated_at"),
            ("creator_contract", "updated_at"),
            ("creator_profile_history", "updated_at"),
            ("creator_contract_period", "updated_at"),
            ("dashboard_cross_industry_exclusion", "updated_at"),
            ("dashboard_traffic_boost_setting", "updated_at"),
        )
        revision_query = " UNION ALL ".join(
            f"SELECT '{table_name}' AS table_name, COUNT(*) AS row_count, "
            f"COALESCE(MAX({timestamp_column})::text, '') AS latest_update "
            f"FROM {table_name}"
            for table_name, timestamp_column in tracked_tables
        )
        with connect(database_path) as connection:
            rows = connection.execute(revision_query).fetchall()
        for row in rows:
            table_name = str(row[0])
            count = int(row[1])
            timestamp = str(row[2])
            total_count += count
            digest.update(f"{table_name}:{count}:{timestamp}".encode("utf-8"))
        target_hash = hashlib.sha256(str(database_path).encode("utf-8")).hexdigest()[:16]
        revision = int.from_bytes(digest.digest()[:8], "big", signed=False)
        return ((f"postgres:{target_hash}", total_count, revision),)

    path = Path(database_path)
    return tuple(
        _file_state(candidate)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    )
