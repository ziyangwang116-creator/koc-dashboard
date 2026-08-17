from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from core.cross_industry import (
    annotate_cross_industry_posts,
    normalize_video_url,
)
from database.db import connect, init_db, normalize_database_target


class ThemeSubmissionRevisionExpiredError(ValueError):
    """Raised by replace_commentary_theme_submissions() when the caller's
    expected_revision does not match the server's current revision for that
    month (per 19.3.4 optimistic concurrency)."""


@dataclass(frozen=True)
class DashboardSaveResult:
    input_count: int
    saved_count: int
    total_count: int
    removed_count: int = 0
    batch_id: int | None = None


@dataclass(frozen=True)
class CompensationVersion:
    id: int
    period_month: str
    version_no: int
    status: str
    jpy_to_usd_rate: float
    details: pd.DataFrame
    summary: dict[str, Any]
    note: str | None
    created_at: str
    updated_at: str
    locked_at: str | None
    lock_note: str | None = None
    locked_by: str | None = None


@dataclass(frozen=True)
class CompensationCalculationCache:
    period_month: str
    category: str
    calculation_version: int
    jpy_to_usd_rate: float
    traffic_boost_enabled: bool
    details: pd.DataFrame
    summary: dict[str, Any]
    status: str
    stale_reason: str | None
    calculated_at: str
    invalidated_at: str | None
    updated_at: str


class DashboardRepository:
    """Persist dashboard posts so they remain available after app restarts."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = normalize_database_target(database_path)
        init_db(self.database_path)

    @staticmethod
    def _json_value(value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "item"):
            try:
                value = value.item()
            except (AttributeError, ValueError):
                pass
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        try:
            if bool(pd.isna(value)):
                return None
        except (TypeError, ValueError):
            pass
        return value

    @classmethod
    def _key_text(cls, value: Any) -> str:
        cleaned = cls._json_value(value)
        if cleaned is None:
            return ""
        if isinstance(cleaned, float) and cleaned.is_integer():
            cleaned = int(cleaned)
        return str(cleaned).strip()

    @classmethod
    def _record_key(cls, payload: dict[str, Any]) -> str:
        platform = cls._key_text(payload.get("source_platform")).casefold()
        url = cls._key_text(payload.get("url"))
        if url:
            raw_key = f"url\x1f{platform}\x1f{url}"
        else:
            raw_key = "\x1f".join(
                (
                    "fallback",
                    cls._key_text(payload.get("user_id")),
                    cls._key_text(
                        payload.get("timestamp") or payload.get("publish_date")
                    ),
                    cls._key_text(payload.get("title")),
                    platform,
                )
            )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @classmethod
    def _storage_row(cls, record: dict[str, Any]) -> tuple[str, str, str | None, str]:
        payload = {
            str(column): cls._json_value(value)
            for column, value in record.items()
        }
        record_key = cls._record_key(payload)
        source_file = cls._key_text(payload.get("source_file")) or "未知来源"
        publish_date = cls._key_text(payload.get("publish_date")) or None
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        return record_key, source_file, publish_date, payload_json

    def count_posts(self) -> int:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM dashboard_post"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def load_posts(self) -> pd.DataFrame:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM dashboard_post
                ORDER BY publish_date, source_file, record_key
                """
            ).fetchall()
        payloads = [json.loads(str(row["payload_json"])) for row in rows]
        return pd.DataFrame(payloads)

    def list_cross_industry_exclusions(
        self,
        *,
        include_inactive: bool = False,
    ) -> pd.DataFrame:
        where = "" if include_inactive else "WHERE active = 1"
        with connect(self.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT id, platform, url_key, original_url, normalized_url,
                       reason, active, created_at, updated_at
                FROM dashboard_cross_industry_exclusion
                {where}
                ORDER BY active DESC, updated_at DESC, id DESC
                """
            ).fetchall()
        columns = [
            "id",
            "platform",
            "url_key",
            "original_url",
            "normalized_url",
            "reason",
            "active",
            "created_at",
            "updated_at",
        ]
        return pd.DataFrame([dict(row) for row in rows], columns=columns)

    def save_cross_industry_exclusions(
        self,
        urls: Iterable[str],
        *,
        reason: str | None = None,
    ) -> pd.DataFrame:
        identities = {
            identity.url_key: identity
            for identity in (normalize_video_url(url) for url in urls)
            if identity is not None
        }
        if not identities:
            return self.list_cross_industry_exclusions()
        cleaned_reason = self._key_text(reason) or "异业活动"
        with connect(self.database_path) as connection:
            connection.executemany(
                """
                INSERT INTO dashboard_cross_industry_exclusion (
                    platform, url_key, original_url, normalized_url,
                    reason, active
                ) VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(url_key) DO UPDATE SET
                    platform = excluded.platform,
                    original_url = excluded.original_url,
                    normalized_url = excluded.normalized_url,
                    reason = excluded.reason,
                    active = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [
                    (
                        identity.platform,
                        identity.url_key,
                        identity.original_url,
                        identity.normalized_url,
                        cleaned_reason,
                    )
                    for identity in identities.values()
                ],
            )
        self.invalidate_compensation_calculation_cache(reason="异业排除链接已更新")
        return self.list_cross_industry_exclusions()

    def deactivate_cross_industry_exclusions(self, exclusion_ids: Iterable[int]) -> int:
        ids: list[int] = []
        for value in exclusion_ids:
            try:
                exclusion_id = int(value)
            except (TypeError, ValueError):
                continue
            if exclusion_id > 0 and exclusion_id not in ids:
                ids.append(exclusion_id)
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE dashboard_cross_industry_exclusion
                SET active = 0, updated_at = CURRENT_TIMESTAMP
                """
                f" WHERE id IN ({placeholders}) AND active = 1",
                ids,
            )
        changed = max(cursor.rowcount, 0)
        if changed:
            self.invalidate_compensation_calculation_cache(reason="异业排除链接已更新")
        return changed

    def annotate_cross_industry_posts(self, data: pd.DataFrame) -> pd.DataFrame:
        return annotate_cross_industry_posts(
            data,
            self.list_cross_industry_exclusions(),
        )

    def upsert_posts(self, data: pd.DataFrame) -> DashboardSaveResult:
        if data.empty:
            return DashboardSaveResult(
                input_count=0,
                saved_count=0,
                total_count=self.count_posts(),
            )

        rows_by_key: dict[str, tuple[str, str, str | None, str]] = {}
        for record in data.to_dict("records"):
            storage_row = self._storage_row(record)
            rows_by_key[storage_row[0]] = storage_row

        with connect(self.database_path) as connection:
            connection.executemany(
                """
                INSERT INTO dashboard_post (
                    record_key, source_file, publish_date, payload_json
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(record_key) DO UPDATE SET
                    source_file = excluded.source_file,
                    publish_date = excluded.publish_date,
                    payload_json = excluded.payload_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                list(rows_by_key.values()),
            )
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM dashboard_post"
                ).fetchone()[0]
            )
        result = DashboardSaveResult(
            input_count=len(data),
            saved_count=len(rows_by_key),
            total_count=total,
        )
        self.invalidate_compensation_calculation_cache(
            period_months=self._period_months(data), reason="投稿数据已更新"
        )
        return result

    @staticmethod
    def _period_months(data: pd.DataFrame) -> tuple[str, ...]:
        if data.empty or "publish_date" not in data:
            return ()
        dates = pd.to_datetime(data["publish_date"], errors="coerce").dropna()
        return tuple(sorted({value.strftime("%Y-%m") for value in dates}))

    def save_monthly_import(
        self,
        data: pd.DataFrame,
        *,
        replace_months: bool,
        source_files: Iterable[str],
        file_hashes: dict[str, str],
        file_reports: pd.DataFrame | None = None,
    ) -> DashboardSaveResult:
        """Persist an audited import, optionally replacing all covered months."""
        rows_by_key: dict[str, tuple[str, str, str | None, str]] = {}
        for record in data.to_dict("records"):
            storage_row = self._storage_row(record)
            rows_by_key[storage_row[0]] = storage_row
        periods = self._period_months(data)
        mode = "REPLACE_MONTHS" if replace_months else "APPEND"
        reports = [] if file_reports is None else file_reports.to_dict("records")
        source_file_names = tuple(dict.fromkeys(str(name) for name in source_files))

        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO dashboard_import_batch (
                    mode, period_months_json, source_files_json, file_hashes_json,
                    input_count, saved_count, removed_count, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    mode,
                    json.dumps(periods, ensure_ascii=False),
                    json.dumps(source_file_names, ensure_ascii=False),
                    json.dumps(file_hashes, ensure_ascii=False, sort_keys=True),
                    len(data),
                    len(rows_by_key),
                    json.dumps(reports, ensure_ascii=False, default=str),
                ),
            )
            batch_id = int(cursor.lastrowid)
            removed_count = 0
            if replace_months and periods:
                placeholders = ", ".join("?" for _ in periods)
                # Immutable pre-replace snapshot (19.2.2): capture the full rows
                # that are about to be overwritten, in the SAME transaction as
                # the delete/insert below, so a later rollback can truly restore
                # them (not merely delete the new batch's rows).
                existing_rows = connection.execute(
                    "SELECT record_key, source_file, publish_date, payload_json "
                    "FROM dashboard_post "
                    f"WHERE substr(publish_date, 1, 7) IN ({placeholders})",
                    periods,
                ).fetchall()
                if existing_rows:
                    connection.executemany(
                        """
                        INSERT INTO dashboard_import_batch_snapshot (
                            batch_id, record_key, source_file, publish_date, payload_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                batch_id,
                                row["record_key"],
                                row["source_file"],
                                row["publish_date"],
                                row["payload_json"],
                            )
                            for row in existing_rows
                        ],
                    )
                deleted = connection.execute(
                    "DELETE FROM dashboard_post "
                    f"WHERE substr(publish_date, 1, 7) IN ({placeholders})",
                    periods,
                )
                removed_count = max(deleted.rowcount, 0)
            if rows_by_key:
                connection.executemany(
                    """
                    INSERT INTO dashboard_post (
                        record_key, source_file, publish_date, payload_json, import_batch_id
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(record_key) DO UPDATE SET
                        source_file = excluded.source_file,
                        publish_date = excluded.publish_date,
                        payload_json = excluded.payload_json,
                        import_batch_id = excluded.import_batch_id,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    [(*row, batch_id) for row in rows_by_key.values()],
                )
            connection.execute(
                "UPDATE dashboard_import_batch SET removed_count = ? WHERE id = ?",
                (removed_count, batch_id),
            )
            total = int(connection.execute("SELECT COUNT(*) FROM dashboard_post").fetchone()[0])
        result = DashboardSaveResult(
            input_count=len(data),
            saved_count=len(rows_by_key),
            total_count=total,
            removed_count=removed_count,
            batch_id=batch_id,
        )
        self.invalidate_compensation_calculation_cache(
            period_months=periods, reason="投稿数据已导入或替换"
        )
        return result

    def rollback_import_batch(self, batch_id: int) -> dict[str, int]:
        """True atomic restore of the pre-replace snapshot for one batch (19.2.3).

        Only the most recent REPLACE_MONTHS batch covering a given month may
        be rolled back; a batch that has already been rolled back cannot be
        rolled back again. Restoring deletes the current rows for the
        batch's covered months, then re-inserts the saved snapshot rows —
        never a delete-only operation.
        """
        with connect(self.database_path) as connection:
            batch = connection.execute(
                "SELECT id, mode, period_months_json, rolled_back_at "
                "FROM dashboard_import_batch WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise ValueError(f"导入批次不存在：batch_id={batch_id}。")
            if batch["mode"] != "REPLACE_MONTHS":
                raise ValueError("该批次不是按月完整替换导入，无法回滚。")
            if batch["rolled_back_at"]:
                raise ValueError("该批次已经回滚过，请勿重复操作。")

            periods = json.loads(batch["period_months_json"])
            if periods:
                period_set = set(periods)
                newer_rows = connection.execute(
                    "SELECT id, period_months_json FROM dashboard_import_batch "
                    "WHERE id > ? AND mode = 'REPLACE_MONTHS' ORDER BY id",
                    (batch_id,),
                ).fetchall()
                for row in newer_rows:
                    other_periods = set(json.loads(row["period_months_json"]))
                    if other_periods & period_set:
                        raise ValueError(
                            "存在更新的导入批次（batch_id="
                            f"{int(row['id'])}），无法安全回滚，请联系管理员处理。"
                        )

            snapshot_rows = connection.execute(
                "SELECT record_key, source_file, publish_date, payload_json "
                "FROM dashboard_import_batch_snapshot WHERE batch_id = ?",
                (batch_id,),
            ).fetchall()

            removed_count = 0
            if periods:
                placeholders = ", ".join("?" for _ in periods)
                deleted = connection.execute(
                    "DELETE FROM dashboard_post "
                    f"WHERE substr(publish_date, 1, 7) IN ({placeholders})",
                    periods,
                )
                removed_count = max(deleted.rowcount, 0)

            if snapshot_rows:
                connection.executemany(
                    """
                    INSERT INTO dashboard_post (
                        record_key, source_file, publish_date, payload_json
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(record_key) DO UPDATE SET
                        source_file = excluded.source_file,
                        publish_date = excluded.publish_date,
                        payload_json = excluded.payload_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    [
                        (
                            row["record_key"],
                            row["source_file"],
                            row["publish_date"],
                            row["payload_json"],
                        )
                        for row in snapshot_rows
                    ],
                )

            connection.execute(
                "UPDATE dashboard_import_batch SET rolled_back_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (batch_id,),
            )

        self.invalidate_compensation_calculation_cache(
            period_months=periods, reason="投稿数据已回滚"
        )
        return {
            "batch_id": batch_id,
            "restored_count": len(snapshot_rows),
            "removed_count": removed_count,
        }

    def list_import_batches(self, *, limit: int = 30) -> pd.DataFrame:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, mode, period_months_json, source_files_json,
                       input_count, saved_count, removed_count, created_at
                FROM dashboard_import_batch
                ORDER BY id DESC LIMIT ?
                """,
                (max(int(limit), 1),),
            ).fetchall()
        display_rows: list[dict[str, object]] = []
        for row in rows:
            display_rows.append(
                {
                    "批次": int(row["id"]),
                    "方式": "按月份替换" if row["mode"] == "REPLACE_MONTHS" else "追加/更新",
                    "数据月份": "、".join(json.loads(str(row["period_months_json"]))),
                    "来源文件": "、".join(json.loads(str(row["source_files_json"]))),
                    "导入条数": int(row["input_count"]),
                    "写入条数": int(row["saved_count"]),
                    "替换移除": int(row["removed_count"]),
                    "导入时间": str(row["created_at"]),
                }
            )
        return pd.DataFrame(display_rows)

    def get_import_batch(self, batch_id: int) -> dict[str, Any] | None:
        """Return one import batch for confirmations and audit displays."""
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT id, mode, period_months_json, source_files_json,
                       input_count, saved_count, removed_count, created_at,
                       rolled_back_at
                FROM dashboard_import_batch
                WHERE id = ?
                """,
                (int(batch_id),),
            ).fetchone()
        if row is None:
            return None
        return {
            "batch_id": int(row["id"]),
            "mode": str(row["mode"]),
            "period_months": list(json.loads(str(row["period_months_json"]))),
            "source_files": list(json.loads(str(row["source_files_json"]))),
            "input_count": int(row["input_count"]),
            "saved_count": int(row["saved_count"]),
            "removed_count": int(row["removed_count"]),
            "created_at": str(row["created_at"]),
            "rolled_back_at": row["rolled_back_at"],
        }

    def clear_posts(self) -> int:
        with connect(self.database_path) as connection:
            cursor = connection.execute("DELETE FROM dashboard_post")
        changed = max(cursor.rowcount, 0)
        if changed:
            self.invalidate_compensation_calculation_cache(reason="投稿数据已清空")
        return changed

    def get_jpy_to_usd_rate(self, period_month: str) -> float | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT jpy_to_usd_rate
                FROM grassroot_compensation_setting
                WHERE period_month = ?
                """,
                (period_month,),
            ).fetchone()
        return float(row["jpy_to_usd_rate"]) if row is not None else None

    def save_jpy_to_usd_rate(self, period_month: str, rate: float) -> None:
        if rate <= 0:
            raise ValueError("日元兑美元汇率必须大于 0。")
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO grassroot_compensation_setting (
                    period_month, jpy_to_usd_rate
                ) VALUES (?, ?)
                ON CONFLICT(period_month) DO UPDATE SET
                    jpy_to_usd_rate = excluded.jpy_to_usd_rate,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (period_month, float(rate)),
            )
        self.invalidate_compensation_calculation_cache(
            period_months=[period_month], reason="汇率已更新"
        )

    def get_traffic_boost_enabled(self, period_month: str) -> bool:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT enabled
                FROM dashboard_traffic_boost_setting
                WHERE period_month = ?
                """,
                (period,),
            ).fetchone()
        return bool(row["enabled"]) if row is not None else False

    def save_traffic_boost_enabled(self, period_month: str, enabled: bool) -> None:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO dashboard_traffic_boost_setting (period_month, enabled)
                VALUES (?, ?)
                ON CONFLICT(period_month) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (period, int(enabled)),
            )
        self.invalidate_compensation_calculation_cache(
            period_months=[period],
            categories=["GRASSROOT", "LONG_TERM"],
            reason="流量加成设置已更新",
        )

    @staticmethod
    def _clean_long_term_activity_count(value: Any) -> int | None:
        if value is None:
            return None
        try:
            if bool(pd.isna(value)):
                return None
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        if not text:
            return None
        try:
            numeric = float(text)
        except (TypeError, ValueError) as exc:
            raise ValueError("每月活动数必须为非负整数。") from exc
        if not numeric.is_integer() or numeric < 0:
            raise ValueError("每月活动数必须为非负整数。")
        return int(numeric)

    def get_long_term_activity_counts(self, period_month: str) -> dict[int, int]:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT creator_id, activity_count
                FROM long_term_compensation_activity
                WHERE period_month = ?
                """,
                (period,),
            ).fetchall()
        return {
            int(row["creator_id"]): int(row["activity_count"])
            for row in rows
        }

    def save_long_term_activity_counts(
        self,
        period_month: str,
        activity_counts: Mapping[int, Any],
    ) -> None:
        """Save editable per-creator event counts for one long-term month."""
        period = self._snapshot_period_month(period_month)
        normalized: dict[int, int | None] = {}
        for raw_creator_id, raw_count in activity_counts.items():
            try:
                creator_id = int(raw_creator_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("达人记录不存在。") from exc
            if creator_id <= 0:
                raise ValueError("达人记录不存在。")
            normalized[creator_id] = self._clean_long_term_activity_count(
                raw_count
            )
        with connect(self.database_path) as connection:
            for creator_id, count in normalized.items():
                if count is None:
                    connection.execute(
                        """
                        DELETE FROM long_term_compensation_activity
                        WHERE period_month = ? AND creator_id = ?
                        """,
                        (period, creator_id),
                    )
                    continue
                connection.execute(
                    """
                    INSERT INTO long_term_compensation_activity (
                        period_month, creator_id, activity_count
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(period_month, creator_id) DO UPDATE SET
                        activity_count = excluded.activity_count,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (period, creator_id, count),
                )
        self.invalidate_compensation_calculation_cache(
            period_months=[period],
            categories=["LONG_TERM"],
            reason="长包活动数已更新",
        )

    @staticmethod
    def _snapshot_contract_types(contract_types: Iterable[str]) -> tuple[str, ...]:
        if isinstance(contract_types, str):
            contract_types = (contract_types,)
        return tuple(
            dict.fromkeys(
                text
                for value in contract_types
                if (text := str(value).strip())
            )
        )

    @staticmethod
    def _snapshot_period_month(period_month: str) -> str:
        value = str(period_month).strip()
        try:
            parsed = datetime.strptime(value, "%Y-%m")
        except ValueError as exc:
            raise ValueError("结算月份必须使用 YYYY-MM 格式。") from exc
        if parsed.strftime("%Y-%m") != value:
            raise ValueError("结算月份必须使用 YYYY-MM 格式。")
        return value

    def get_grassroot_contract_snapshots(
        self, period_month: str
    ) -> dict[int, tuple[str, ...]]:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT creator_id, contract_types_json
                FROM grassroot_compensation_contract_snapshot
                WHERE period_month = ?
                """,
                (period,),
            ).fetchall()
        snapshots: dict[int, tuple[str, ...]] = {}
        for row in rows:
            try:
                raw_contracts = json.loads(str(row["contract_types_json"]))
            except json.JSONDecodeError:
                raw_contracts = []
            if not isinstance(raw_contracts, list):
                raw_contracts = []
            snapshots[int(row["creator_id"])] = self._snapshot_contract_types(
                raw_contracts
            )
        return snapshots

    def ensure_grassroot_contract_snapshots(
        self,
        period_month: str,
        creator_contracts: Iterable[tuple[int, Iterable[str]]],
    ) -> dict[int, tuple[str, ...]]:
        period = self._snapshot_period_month(period_month)
        incoming = {
            int(creator_id): self._snapshot_contract_types(contract_types)
            for creator_id, contract_types in creator_contracts
            if int(creator_id) > 0
        }
        existing = self.get_grassroot_contract_snapshots(period)
        missing = [
            (period, creator_id, json.dumps(contract_types, ensure_ascii=False))
            for creator_id, contract_types in incoming.items()
            if creator_id not in existing
        ]
        if missing:
            with connect(self.database_path) as connection:
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO grassroot_compensation_contract_snapshot (
                        period_month, creator_id, contract_types_json
                    ) VALUES (?, ?, ?)
                    """,
                    missing,
                )
        return self.get_grassroot_contract_snapshots(period)

    def save_grassroot_contract_snapshot(
        self,
        period_month: str,
        creator_id: int,
        contract_types: Iterable[str],
    ) -> None:
        period = self._snapshot_period_month(period_month)
        if creator_id <= 0:
            raise ValueError("达人记录不存在。")
        normalized_contracts = self._snapshot_contract_types(contract_types)
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO grassroot_compensation_contract_snapshot (
                    period_month, creator_id, contract_types_json
                ) VALUES (?, ?, ?)
                ON CONFLICT(period_month, creator_id) DO UPDATE SET
                    contract_types_json = excluded.contract_types_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    period,
                    creator_id,
                    json.dumps(normalized_contracts, ensure_ascii=False),
                ),
            )

    @staticmethod
    def _clean_lock_note(lock_note: str | None) -> str | None:
        """Validate lock_note length when provided.

        The API layer (per 19.5.3) treats lock_note as strictly required;
        the repository itself keeps it optional so existing callers (e.g.
        the legacy Streamlit UI) that don't yet pass one keep working.
        """
        if lock_note is None:
            return None
        text = str(lock_note).strip()
        if not (1 <= len(text) <= 500):
            raise ValueError("lock_note 长度须为 1-500 个字符。")
        return text

    @classmethod
    def _version_details_json(cls, details: pd.DataFrame) -> str:
        rows = [
            {
                str(column): cls._json_value(value)
                for column, value in record.items()
            }
            for record in details.to_dict("records")
        ]
        return json.dumps(rows, ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _version_from_row(row: Any) -> CompensationVersion:
        details = pd.read_json(StringIO(str(row["details_json"])), orient="records")
        try:
            summary = json.loads(str(row["summary_json"]))
        except json.JSONDecodeError:
            summary = {}
        return CompensationVersion(
            id=int(row["id"]),
            period_month=str(row["period_month"]),
            version_no=int(row["version_no"]),
            status=str(row["status"]),
            jpy_to_usd_rate=float(row["jpy_to_usd_rate"]),
            details=details,
            summary=summary if isinstance(summary, dict) else {},
            note=row["note"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            locked_at=row["locked_at"],
            lock_note=row["lock_note"] if "lock_note" in row.keys() else None,
            locked_by=row["locked_by"] if "locked_by" in row.keys() else None,
        )

    @staticmethod
    def _calculation_cache_from_row(row: Any) -> CompensationCalculationCache:
        details = pd.read_json(StringIO(str(row["details_json"])), orient="records")
        try:
            summary = json.loads(str(row["summary_json"]))
        except json.JSONDecodeError:
            summary = {}
        return CompensationCalculationCache(
            period_month=str(row["period_month"]),
            category=str(row["category"]),
            calculation_version=int(row["calculation_version"]),
            jpy_to_usd_rate=float(row["jpy_to_usd_rate"]),
            traffic_boost_enabled=bool(row["traffic_boost_enabled"]),
            details=details,
            summary=summary if isinstance(summary, dict) else {},
            status=str(row["status"]),
            stale_reason=row["stale_reason"],
            calculated_at=str(row["calculated_at"]),
            invalidated_at=row["invalidated_at"],
            updated_at=str(row["updated_at"]),
        )

    def get_compensation_calculation_cache(
        self, period_month: str, category: str
    ) -> CompensationCalculationCache | None:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM compensation_calculation_cache "
                "WHERE period_month = ? AND category = ?",
                (period, category),
            ).fetchone()
        return self._calculation_cache_from_row(row) if row is not None else None

    def save_compensation_calculation_cache(
        self,
        period_month: str,
        category: str,
        *,
        jpy_to_usd_rate: float,
        traffic_boost_enabled: bool,
        details: pd.DataFrame,
        summary: dict[str, Any],
    ) -> CompensationCalculationCache:
        period = self._snapshot_period_month(period_month)
        if category not in {"GRASSROOT", "LONG_TERM", "COMMENTARY"}:
            raise ValueError("无效的结算类别。")
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO compensation_calculation_cache (
                    period_month, category, calculation_version,
                    jpy_to_usd_rate, traffic_boost_enabled,
                    details_json, summary_json, status, stale_reason,
                    calculated_at, invalidated_at, updated_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, 'CURRENT', NULL,
                          CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(period_month, category) DO UPDATE SET
                    calculation_version = compensation_calculation_cache.calculation_version + 1,
                    jpy_to_usd_rate = excluded.jpy_to_usd_rate,
                    traffic_boost_enabled = excluded.traffic_boost_enabled,
                    details_json = excluded.details_json,
                    summary_json = excluded.summary_json,
                    status = 'CURRENT', stale_reason = NULL,
                    calculated_at = CURRENT_TIMESTAMP, invalidated_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    period,
                    category,
                    float(jpy_to_usd_rate),
                    int(bool(traffic_boost_enabled)),
                    self._version_details_json(details),
                    json.dumps(summary, ensure_ascii=False, default=str),
                ),
            )
            row = connection.execute(
                "SELECT * FROM compensation_calculation_cache "
                "WHERE period_month = ? AND category = ?",
                (period, category),
            ).fetchone()
        if row is None:
            raise RuntimeError("结算缓存保存后无法读取。")
        return self._calculation_cache_from_row(row)

    def invalidate_compensation_calculation_cache(
        self,
        *,
        period_months: Iterable[str] | None = None,
        categories: Iterable[str] | None = None,
        reason: str,
        from_period_month: str | None = None,
    ) -> int:
        clauses: list[str] = []
        parameters: list[Any] = []
        periods = tuple(dict.fromkeys(period_months or ()))
        category_values = tuple(dict.fromkeys(categories or ()))
        if periods:
            clauses.append("period_month IN (" + ", ".join("?" for _ in periods) + ")")
            parameters.extend(periods)
        if from_period_month:
            clauses.append("period_month >= ?")
            parameters.append(self._snapshot_period_month(from_period_month))
        if category_values:
            clauses.append("category IN (" + ", ".join("?" for _ in category_values) + ")")
            parameters.extend(category_values)
        reason_text = str(reason).strip()[:500] or "相关数据已更新"
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                "UPDATE compensation_calculation_cache SET status = 'STALE', "
                "stale_reason = ?, invalidated_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP"
                + (" WHERE " + " AND ".join(clauses) if clauses else ""),
                [reason_text, *parameters],
            )
        return max(cursor.rowcount, 0)

    def _get_version_by_id(self, table_name: str, version_id: int) -> CompensationVersion | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                f"SELECT * FROM {table_name} WHERE id = ?", (version_id,)
            ).fetchone()
        return self._version_from_row(row) if row is not None else None

    def get_compensation_version(self, version_id: int) -> CompensationVersion | None:
        return self._get_version_by_id("grassroot_compensation_version", version_id)

    def get_long_term_compensation_version(self, version_id: int) -> CompensationVersion | None:
        return self._get_version_by_id("long_term_compensation_version", version_id)

    def get_commentary_compensation_version(self, version_id: int) -> CompensationVersion | None:
        return self._get_version_by_id("commentary_compensation_version", version_id)

    def list_compensation_versions(self, period_month: str) -> list[CompensationVersion]:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM grassroot_compensation_version
                WHERE period_month = ? ORDER BY version_no DESC
                """,
                (period,),
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def create_compensation_draft(
        self,
        period_month: str,
        *,
        jpy_to_usd_rate: float,
        details: pd.DataFrame,
        summary: dict[str, Any],
        note: str | None = None,
    ) -> CompensationVersion:
        period = self._snapshot_period_month(period_month)
        if jpy_to_usd_rate <= 0:
            raise ValueError("日元兑美元汇率必须大于 0。")
        details_json = self._version_details_json(details)
        summary_json = json.dumps(summary, ensure_ascii=False, default=str)
        with connect(self.database_path) as connection:
            version_no = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version_no), 0) + 1 "
                    "FROM grassroot_compensation_version WHERE period_month = ?",
                    (period,),
                ).fetchone()[0]
            )
            cursor = connection.execute(
                """
                INSERT INTO grassroot_compensation_version (
                    period_month, version_no, status, jpy_to_usd_rate,
                    details_json, summary_json, note
                ) VALUES (?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (period, version_no, jpy_to_usd_rate, details_json, summary_json, note),
            )
            row = connection.execute(
                "SELECT * FROM grassroot_compensation_version WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        if row is None:
            raise RuntimeError("结算草稿保存后无法读取。")
        return self._version_from_row(row)

    def update_compensation_draft(
        self,
        version_id: int,
        *,
        jpy_to_usd_rate: float,
        details: pd.DataFrame,
        summary: dict[str, Any],
        note: str | None = None,
    ) -> CompensationVersion:
        if jpy_to_usd_rate <= 0:
            raise ValueError("日元兑美元汇率必须大于 0。")
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE grassroot_compensation_version SET
                    jpy_to_usd_rate = ?, details_json = ?, summary_json = ?,
                    note = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'DRAFT'
                """,
                (
                    jpy_to_usd_rate,
                    self._version_details_json(details),
                    json.dumps(summary, ensure_ascii=False, default=str),
                    note,
                    version_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("只能更新可编辑的结算草稿。")
            row = connection.execute(
                "SELECT * FROM grassroot_compensation_version WHERE id = ?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("结算草稿更新后无法读取。")
        return self._version_from_row(row)

    def lock_compensation_version(
        self,
        version_id: int,
        *,
        lock_note: str | None = None,
        locked_by: str | None = None,
    ) -> CompensationVersion:
        lock_note = self._clean_lock_note(lock_note)
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE grassroot_compensation_version SET
                    status = 'LOCKED', locked_at = CURRENT_TIMESTAMP,
                    lock_note = ?, locked_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'DRAFT'
                """,
                (lock_note, locked_by, version_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("只能锁定可编辑的结算草稿。")
            row = connection.execute(
                "SELECT * FROM grassroot_compensation_version WHERE id = ?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("锁定结算版本后无法读取。")
        return self._version_from_row(row)

    def list_long_term_compensation_versions(
        self,
        period_month: str,
    ) -> list[CompensationVersion]:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM long_term_compensation_version
                WHERE period_month = ? ORDER BY version_no DESC
                """,
                (period,),
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def create_long_term_compensation_draft(
        self,
        period_month: str,
        *,
        jpy_to_usd_rate: float,
        details: pd.DataFrame,
        summary: dict[str, Any],
        note: str | None = None,
    ) -> CompensationVersion:
        period = self._snapshot_period_month(period_month)
        if jpy_to_usd_rate <= 0:
            raise ValueError("日元兑美元汇率必须大于 0。")
        details_json = self._version_details_json(details)
        summary_json = json.dumps(summary, ensure_ascii=False, default=str)
        with connect(self.database_path) as connection:
            version_no = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version_no), 0) + 1 "
                    "FROM long_term_compensation_version WHERE period_month = ?",
                    (period,),
                ).fetchone()[0]
            )
            cursor = connection.execute(
                """
                INSERT INTO long_term_compensation_version (
                    period_month, version_no, status, jpy_to_usd_rate,
                    details_json, summary_json, note
                ) VALUES (?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (period, version_no, jpy_to_usd_rate, details_json, summary_json, note),
            )
            row = connection.execute(
                "SELECT * FROM long_term_compensation_version WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        if row is None:
            raise RuntimeError("长包结算草稿保存后无法读取。")
        return self._version_from_row(row)

    def update_long_term_compensation_draft(
        self,
        version_id: int,
        *,
        jpy_to_usd_rate: float,
        details: pd.DataFrame,
        summary: dict[str, Any],
        note: str | None = None,
    ) -> CompensationVersion:
        if jpy_to_usd_rate <= 0:
            raise ValueError("日元兑美元汇率必须大于 0。")
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE long_term_compensation_version SET
                    jpy_to_usd_rate = ?, details_json = ?, summary_json = ?,
                    note = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'DRAFT'
                """,
                (
                    jpy_to_usd_rate,
                    self._version_details_json(details),
                    json.dumps(summary, ensure_ascii=False, default=str),
                    note,
                    version_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("只能更新可编辑的长包结算草稿。")
            row = connection.execute(
                "SELECT * FROM long_term_compensation_version WHERE id = ?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("长包结算草稿更新后无法读取。")
        return self._version_from_row(row)

    def lock_long_term_compensation_version(
        self,
        version_id: int,
        *,
        lock_note: str | None = None,
        locked_by: str | None = None,
    ) -> CompensationVersion:
        lock_note = self._clean_lock_note(lock_note)
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE long_term_compensation_version SET
                    status = 'LOCKED', locked_at = CURRENT_TIMESTAMP,
                    lock_note = ?, locked_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'DRAFT'
                """,
                (lock_note, locked_by, version_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("只能锁定可编辑的长包结算草稿。")
            row = connection.execute(
                "SELECT * FROM long_term_compensation_version WHERE id = ?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("长包结算版本锁定后无法读取。")
        return self._version_from_row(row)

    def list_commentary_theme_definitions(
        self,
        period_month: str,
    ) -> dict[str, dict[str, Any]]:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT period_month, theme_code, theme_name, description,
                       max_per_creator, reward_jpy, enabled
                FROM commentary_theme_definition
                WHERE period_month = ? ORDER BY theme_code
                """,
                (period,),
            ).fetchall()
        return {
            str(row["theme_code"]): {
                "period_month": str(row["period_month"]),
                "theme_code": str(row["theme_code"]),
                "theme_name": str(row["theme_name"]),
                "description": row["description"],
                "max_per_creator": int(row["max_per_creator"]),
                "reward_jpy": int(row["reward_jpy"]),
                "enabled": bool(row["enabled"]),
            }
            for row in rows
        }

    def list_commentary_theme_submissions(
        self,
        period_month: str,
    ) -> list[dict[str, Any]]:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, period_month, creator_id, theme_code,
                       content_format, urls_json, submitted_date,
                       review_status, note
                FROM commentary_theme_submission
                WHERE period_month = ? ORDER BY creator_id, theme_code
                """,
                (period,),
            ).fetchall()
        submissions: list[dict[str, Any]] = []
        for row in rows:
            try:
                urls = json.loads(str(row["urls_json"]))
            except json.JSONDecodeError:
                urls = []
            submissions.append(
                {
                    "id": int(row["id"]),
                    "period_month": str(row["period_month"]),
                    "creator_id": int(row["creator_id"]),
                    "theme_code": str(row["theme_code"]),
                    "content_format": str(row["content_format"]),
                    "urls": urls if isinstance(urls, list) else [],
                    "submitted_date": row["submitted_date"],
                    "review_status": str(row["review_status"]),
                    "note": row["note"],
                }
            )
        return submissions

    def get_commentary_theme_submissions_revision(self, period_month: str) -> str:
        """Current revision token for the month's full theme-submission list.

        Returns a stable initial token ("rev_0") for months that have never
        had a replace_commentary_theme_submissions() call, so a first-time
        caller can supply expected_revision="rev_0" and proceed uncontested.
        """
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT revision FROM commentary_theme_submission_revision
                WHERE period_month = ?
                """,
                (period,),
            ).fetchone()
        return str(row["revision"]) if row is not None else "rev_0"

    def replace_commentary_theme_submissions(
        self,
        period_month: str,
        rows: Iterable[Mapping[str, Any]],
        *,
        expected_revision: str | None = None,
    ) -> int:
        period = self._snapshot_period_month(period_month)
        allowed_formats = {"LONG", "SHORT"}
        allowed_statuses = {"PENDING", "APPROVED", "REJECTED"}
        definitions = self.list_commentary_theme_definitions(period)
        values: list[tuple[Any, ...]] = []
        seen: set[tuple[int, str]] = set()
        for row in rows:
            creator_id = int(row.get("creator_id") or row.get("达人ID") or 0)
            theme_code = self._key_text(row.get("theme_code") or row.get("主题代码"))
            if creator_id <= 0 or not theme_code:
                continue
            if theme_code not in definitions:
                raise ValueError(f"指定主题不存在：{theme_code}")
            unique_key = (creator_id, theme_code)
            if unique_key in seen:
                raise ValueError("同一达人同一主题每月只能申报一次。")
            seen.add(unique_key)
            content_format = self._key_text(
                row.get("content_format") or row.get("内容形式")
            ).upper()
            review_status = self._key_text(
                row.get("review_status") or row.get("审核状态") or "PENDING"
            ).upper()
            if content_format not in allowed_formats:
                raise ValueError("指定主题内容形式只能选择 LONG 或 SHORT。")
            if review_status not in allowed_statuses:
                raise ValueError("指定主题审核状态无效。")
            raw_urls = row.get("urls", row.get("视频链接", ()))
            if isinstance(raw_urls, str):
                raw_urls = raw_urls.replace("，", "\n").replace(",", "\n").splitlines()
            urls = list(
                dict.fromkeys(
                    self._key_text(value) for value in raw_urls if self._key_text(value)
                )
            )
            expected_count = 1 if content_format == "LONG" else 3
            if len(urls) != expected_count:
                raise ValueError(
                    "LONG 需填写1条链接，SHORT 需填写3条链接（每行一条）。"
                )
            submitted = self._key_text(
                row.get("submitted_date") or row.get("提交日期")
            ) or None
            if submitted:
                submitted = date.fromisoformat(submitted[:10]).isoformat()
            values.append(
                (
                    period,
                    creator_id,
                    theme_code,
                    content_format,
                    json.dumps(urls, ensure_ascii=False),
                    submitted,
                    review_status,
                    self._key_text(row.get("note") or row.get("备注")) or None,
                )
            )
        new_revision = f"rev_{uuid.uuid4().hex}"
        with connect(self.database_path) as connection:
            if expected_revision is not None:
                current_row = connection.execute(
                    """
                    SELECT revision FROM commentary_theme_submission_revision
                    WHERE period_month = ?
                    """,
                    (period,),
                ).fetchone()
                current_revision = (
                    str(current_row["revision"]) if current_row is not None else "rev_0"
                )
                if current_revision != expected_revision:
                    raise ThemeSubmissionRevisionExpiredError(
                        "该月申报列表已被其他会话更新，请刷新后基于最新列表重新提交。"
                    )
            connection.execute(
                "DELETE FROM commentary_theme_submission WHERE period_month = ?",
                (period,),
            )
            if values:
                connection.executemany(
                    """
                    INSERT INTO commentary_theme_submission (
                        period_month, creator_id, theme_code, content_format,
                        urls_json, submitted_date, review_status, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            connection.execute(
                """
                INSERT INTO commentary_theme_submission_revision (
                    period_month, revision
                ) VALUES (?, ?)
                ON CONFLICT(period_month) DO UPDATE SET
                    revision = excluded.revision,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (period, new_revision),
            )
        self.invalidate_compensation_calculation_cache(
            period_months=[period],
            categories=["COMMENTARY"],
            reason="解说指定主题申报已更新",
        )
        return len(values)


    def list_commentary_compensation_versions(
        self,
        period_month: str,
    ) -> list[CompensationVersion]:
        period = self._snapshot_period_month(period_month)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM commentary_compensation_version
                WHERE period_month = ? ORDER BY version_no DESC
                """,
                (period,),
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def create_commentary_compensation_draft(
        self,
        period_month: str,
        *,
        jpy_to_usd_rate: float,
        details: pd.DataFrame,
        summary: dict[str, Any],
        note: str | None = None,
    ) -> CompensationVersion:
        period = self._snapshot_period_month(period_month)
        if jpy_to_usd_rate <= 0:
            raise ValueError("日元兑美元汇率必须大于 0。")
        with connect(self.database_path) as connection:
            version_no = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version_no), 0) + 1 "
                    "FROM commentary_compensation_version WHERE period_month = ?",
                    (period,),
                ).fetchone()[0]
            )
            cursor = connection.execute(
                """
                INSERT INTO commentary_compensation_version (
                    period_month, version_no, status, jpy_to_usd_rate,
                    details_json, summary_json, note
                ) VALUES (?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (
                    period,
                    version_no,
                    jpy_to_usd_rate,
                    self._version_details_json(details),
                    json.dumps(summary, ensure_ascii=False, default=str),
                    note,
                ),
            )
            row = connection.execute(
                "SELECT * FROM commentary_compensation_version WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        if row is None:
            raise RuntimeError("解说结算草稿保存后无法读取。")
        return self._version_from_row(row)

    def update_commentary_compensation_draft(
        self,
        version_id: int,
        *,
        jpy_to_usd_rate: float,
        details: pd.DataFrame,
        summary: dict[str, Any],
        note: str | None = None,
    ) -> CompensationVersion:
        if jpy_to_usd_rate <= 0:
            raise ValueError("日元兑美元汇率必须大于 0。")
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE commentary_compensation_version SET
                    jpy_to_usd_rate = ?, details_json = ?, summary_json = ?,
                    note = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'DRAFT'
                """,
                (
                    jpy_to_usd_rate,
                    self._version_details_json(details),
                    json.dumps(summary, ensure_ascii=False, default=str),
                    note,
                    version_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("只能更新可编辑的解说结算草稿。")
            row = connection.execute(
                "SELECT * FROM commentary_compensation_version WHERE id = ?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("解说结算草稿更新后无法读取。")
        return self._version_from_row(row)

    def lock_commentary_compensation_version(
        self,
        version_id: int,
        *,
        lock_note: str | None = None,
        locked_by: str | None = None,
    ) -> CompensationVersion:
        lock_note = self._clean_lock_note(lock_note)
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE commentary_compensation_version SET
                    status = 'LOCKED', locked_at = CURRENT_TIMESTAMP,
                    lock_note = ?, locked_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'DRAFT'
                """,
                (lock_note, locked_by, version_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("只能锁定可编辑的解说结算草稿。")
            row = connection.execute(
                "SELECT * FROM commentary_compensation_version WHERE id = ?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("解说结算版本锁定后无法读取。")
        return self._version_from_row(row)
