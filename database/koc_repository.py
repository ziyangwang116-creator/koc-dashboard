from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import pandas as pd

from core.koc_import import KOCImportFormatError, normalize_import_columns
from core.user_id import normalize_user_id
from database.db import INTEGRITY_ERRORS, connect, init_db, normalize_database_target
from followers.base import FollowerFetchResult
from models.enums import (
    ContractType,
    CreatorCategory,
    FollowerSource,
    FollowerSyncStatus,
    OperatorMode,
    parse_contract_type,
    parse_creator_category,
)
from models.contracts import (
    contract_texts_for_category,
    derive_creator_categories,
    normalize_contract_text,
)
from models.koc import (
    CreatorContractPeriod,
    CreatorContractRevision,
    CreatorProfileSnapshot,
    KOC_EXPORT_COLUMNS,
    KOCRecord,
)


ImportStrategy = Literal["add_only", "update_existing"]
_UNSET = object()


class KOCRepositoryError(ValueError):
    """A repository validation error safe to show in the UI."""


class DuplicateUserIDError(KOCRepositoryError):
    pass


class KOCImportResult:
    def __init__(
        self,
        *,
        added_count: int,
        updated_count: int,
        skipped_count: int,
        failed_count: int,
        details: pd.DataFrame,
        contract_count: int = 0,
    ) -> None:
        self.added_count = added_count
        self.updated_count = updated_count
        self.skipped_count = skipped_count
        self.failed_count = failed_count
        self.contract_count = contract_count
        self.details = details


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class KOCRepository:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = normalize_database_target(database_path)
        init_db(self.database_path)

    @staticmethod
    def _clean_required(value: Any, field_label: str) -> str:
        if value is None or pd.isna(value):
            raise KOCRepositoryError(f"{field_label}不能为空。")
        text = str(value).strip()
        if not text:
            raise KOCRepositoryError(f"{field_label}不能为空。")
        return text

    @staticmethod
    def _clean_user_id(value: Any) -> str:
        normalized = normalize_user_id(value)
        if normalized is None:
            raise KOCRepositoryError("user_id 不能为空。")
        return normalized

    @staticmethod
    def _clean_optional_user_id(value: Any) -> str | None:
        if value is None or pd.isna(value) or not str(value).strip():
            return None
        normalized = normalize_user_id(value)
        if normalized is None:
            raise KOCRepositoryError("平台 UID 格式无效。")
        return normalized

    @staticmethod
    def _clean_optional(value: Any) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _clean_homepage_url(cls, value: Any) -> str | None:
        cleaned = cls._clean_optional(value)
        if cleaned is None:
            return None
        parsed = urlparse(cleaned)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            raise KOCRepositoryError("达人主页链接必须是完整的 http 或 https URL。")
        return cleaned

    @staticmethod
    def _clean_follower_count(value: Any) -> int | None:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return None
        if isinstance(value, bool):
            raise KOCRepositoryError("粉丝数必须是大于或等于 0 的整数。")
        text = str(value).strip().replace(",", "")
        try:
            numeric = float(text)
        except (TypeError, ValueError) as exc:
            raise KOCRepositoryError("粉丝数必须是大于或等于 0 的整数。") from exc
        if not numeric.is_integer() or numeric < 0:
            raise KOCRepositoryError("粉丝数必须是大于或等于 0 的整数。")
        return int(numeric)

    @staticmethod
    def _clean_active(value: Any, *, default: bool = True) -> bool:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return default
        if isinstance(value, str):
            return value.strip().casefold() not in {"0", "false", "否", "停用"}
        return bool(value)

    @staticmethod
    def _clean_category(value: Any) -> CreatorCategory | None:
        try:
            return parse_creator_category(value)
        except ValueError as exc:
            raise KOCRepositoryError("合作类别不是允许的枚举值。") from exc

    @staticmethod
    def _clean_contract(value: Any) -> ContractType | None:
        try:
            return parse_contract_type(value)
        except ValueError as exc:
            raise KOCRepositoryError("合同类型不是允许的枚举值。") from exc

    @staticmethod
    def _clean_follower_sync_status(value: Any) -> FollowerSyncStatus:
        try:
            if isinstance(value, FollowerSyncStatus):
                return value
            return FollowerSyncStatus(str(value).strip().upper())
        except ValueError as exc:
            raise KOCRepositoryError("粉丝数更新状态不是允许的枚举值。") from exc

    @staticmethod
    def _clean_follower_source(value: Any) -> FollowerSource:
        try:
            if isinstance(value, FollowerSource):
                return value
            return FollowerSource(str(value).strip().upper())
        except ValueError as exc:
            raise KOCRepositoryError("粉丝来源不是允许的枚举值。") from exc

    @staticmethod
    def _validate_category_contract(
        category: CreatorCategory | None,
        contract: ContractType | None,
    ) -> None:
        if contract is not None and category is not CreatorCategory.GRASSROOT:
            raise KOCRepositoryError("只有草根达人可以选择当前合同类型。")

    @staticmethod
    def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
        """Read a SQLite row value while remaining compatible with older schemas."""
        return row[key] if key in row.keys() else default

    @staticmethod
    def _clean_contract_text(value: Any) -> str | None:
        return normalize_contract_text(value)

    @staticmethod
    def _clean_effective_date(value: date | str | None) -> date:
        if value is None:
            return date.today()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value).strip())
        except ValueError as exc:
            raise KOCRepositoryError("生效日期必须使用 YYYY-MM-DD 格式。") from exc

    @staticmethod
    def _stored_contract_date(value: Any) -> date | None:
        """Read an optional persisted ISO date without failing on legacy rows."""
        if value is None or pd.isna(value):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    @classmethod
    def _clean_contract_date(cls, value: Any, field_label: str) -> date | None:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return None
        parsed = cls._stored_contract_date(value)
        if parsed is None:
            raise KOCRepositoryError(
                f"{field_label}必须使用 YYYY-MM-DD 格式。"
            )
        return parsed

    @staticmethod
    def _contract_period_defaults(
        category: CreatorCategory | None,
        contract_types: Iterable[str],
        *,
        year: int,
    ) -> tuple[date, date]:
        """Return the default May-based term for the creator's contract family."""
        categories = derive_creator_categories(contract_types, fallback=category)
        if CreatorCategory.LONG_TERM in categories:
            return date(year, 5, 1), date(year, 12, 31)
        if CreatorCategory.COMMENTARY in categories:
            return date(year, 5, 1), date(year, 8, 31)
        return date(year, 5, 1), date(year, 10, 31)

    @classmethod
    def _resolve_contract_period(
        cls,
        *,
        category: CreatorCategory | None,
        contract_types: Iterable[str],
        effective_date: date,
        current: KOCRecord | None = None,
        contract_start_date: Any = None,
        contract_end_date: Any = None,
        reset_for_contract_change: bool = False,
    ) -> tuple[date, date]:
        """Apply explicit dates, defaults, and version-effective contract changes."""
        explicit_start = cls._clean_contract_date(
            contract_start_date, "合同开始日期"
        )
        explicit_end = cls._clean_contract_date(
            contract_end_date, "合同截止日期"
        )
        default_start, default_end = cls._contract_period_defaults(
            category, contract_types, year=effective_date.year
        )

        if current is None:
            start = explicit_start or default_start
            end = explicit_end or default_end
        elif reset_for_contract_change:
            # A new contract version applies from its profile effective date.
            start = explicit_start or effective_date
            end = explicit_end or default_end
        else:
            start = explicit_start or current.contract_start_date or default_start
            end = explicit_end or current.contract_end_date or default_end

        if end < start:
            raise KOCRepositoryError("合同截止日期不能早于合同开始日期。")
        return start, end

    @staticmethod
    def _contract_map(
        connection: sqlite3.Connection,
        creator_ids: Iterable[int],
    ) -> dict[int, tuple[str, ...]]:
        ids = list(dict.fromkeys(int(value) for value in creator_ids))
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        rows = connection.execute(
            f"""
            SELECT creator_id, contract_type
            FROM creator_contract
            WHERE creator_id IN ({placeholders})
            ORDER BY id
            """,
            ids,
        ).fetchall()
        grouped: dict[int, list[str]] = {creator_id: [] for creator_id in ids}
        for row in rows:
            contract_type = normalize_contract_text(row["contract_type"])
            if contract_type is not None:
                grouped[int(row["creator_id"])].append(contract_type)
        return {key: tuple(values) for key, values in grouped.items()}

    def _save_profile_snapshot(
        self,
        connection: sqlite3.Connection,
        record_id: int,
        effective_date: date | str | None,
    ) -> None:
        effective = self._clean_effective_date(effective_date).isoformat()
        row = connection.execute(
            """
            SELECT id, user_id, koc_name, creator_category, homepage_url,
                   contract_start_date, contract_end_date, follower_count,
                   youtube_user_id, youtube_homepage_url,
                   youtube_follower_count, tiktok_user_id,
                   tiktok_homepage_url, tiktok_follower_count, active
            FROM koc_master WHERE id = ?
            """,
            (record_id,),
        ).fetchone()
        if row is None:
            raise KOCRepositoryError("达人记录不存在，无法保存资料快照。")
        connection.execute(
            """
            INSERT INTO creator_profile_history (
                creator_id, effective_date, user_id, koc_name,
                creator_category, contract_types_json, contract_start_date,
                contract_end_date, homepage_url, follower_count,
                youtube_user_id, youtube_homepage_url, youtube_follower_count,
                tiktok_user_id, tiktok_homepage_url, tiktok_follower_count,
                active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(creator_id, effective_date) DO UPDATE SET
                user_id = excluded.user_id,
                koc_name = excluded.koc_name,
                creator_category = excluded.creator_category,
                contract_types_json = excluded.contract_types_json,
                contract_start_date = excluded.contract_start_date,
                contract_end_date = excluded.contract_end_date,
                homepage_url = excluded.homepage_url,
                follower_count = excluded.follower_count,
                youtube_user_id = excluded.youtube_user_id,
                youtube_homepage_url = excluded.youtube_homepage_url,
                youtube_follower_count = excluded.youtube_follower_count,
                tiktok_user_id = excluded.tiktok_user_id,
                tiktok_homepage_url = excluded.tiktok_homepage_url,
                tiktok_follower_count = excluded.tiktok_follower_count,
                active = excluded.active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                record_id,
                effective,
                str(row["user_id"]),
                str(row["koc_name"]),
                None,
                "[]",
                None,
                None,
                row["homepage_url"],
                row["follower_count"],
                row["youtube_user_id"],
                row["youtube_homepage_url"],
                row["youtube_follower_count"],
                row["tiktok_user_id"],
                row["tiktok_homepage_url"],
                row["tiktok_follower_count"],
                int(row["active"]),
            ),
        )

    def _ensure_pre_contract_change_history(
        self,
        connection: sqlite3.Connection,
        current: KOCRecord,
        effective_date: date,
    ) -> None:
        """Preserve the current profile before a later contract version replaces it."""
        baseline = current.contract_start_date
        if baseline is None:
            baseline, _ = self._contract_period_defaults(
                current.creator_category,
                current.contract_types,
                year=effective_date.year,
            )
        if baseline >= effective_date:
            return

        previous = connection.execute(
            """
            SELECT effective_date, contract_end_date
            FROM creator_profile_history
            WHERE creator_id = ? AND effective_date < ?
            ORDER BY effective_date DESC
            LIMIT 1
            """,
            (current.id, effective_date.isoformat()),
        ).fetchone()
        if previous is None:
            self._save_profile_snapshot(connection, current.id, baseline)
            previous = connection.execute(
                """
                SELECT effective_date, contract_end_date
                FROM creator_profile_history
                WHERE creator_id = ? AND effective_date < ?
                ORDER BY effective_date DESC
                LIMIT 1
                """,
                (current.id, effective_date.isoformat()),
            ).fetchone()
        if previous is None:
            return

        previous_end = self._stored_contract_date(previous["contract_end_date"])
        closed_end = effective_date - timedelta(days=1)
        if previous_end is None or previous_end > closed_end:
            connection.execute(
                """
                UPDATE creator_profile_history
                SET contract_end_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE creator_id = ? AND effective_date = ?
                """,
                (closed_end.isoformat(), current.id, previous["effective_date"]),
            )

    @staticmethod
    def _profile_history_contracts(value: Any) -> tuple[str, ...]:
        """Read stored contract JSON while tolerating older or malformed rows."""
        try:
            values = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            values = []
        if not isinstance(values, list):
            return ()
        return tuple(
            dict.fromkeys(
                contract
                for item in values
                if (contract := normalize_contract_text(item)) is not None
            )
        )

    @classmethod
    def _contract_period_record(cls, row: sqlite3.Row) -> CreatorContractPeriod:
        category = row["creator_category"]
        start = cls._stored_contract_date(row["start_date"])
        end = cls._stored_contract_date(row["end_date"])
        if start is None or end is None:
            raise RuntimeError("Invalid creator contract period dates.")
        return CreatorContractPeriod(
            id=int(row["id"]),
            creator_id=int(row["creator_id"]),
            effective_date=start,
            creator_category=(CreatorCategory(str(category)) if category else None),
            contract_types=cls._profile_history_contracts(
                row["contract_types_json"]
            ),
            contract_start_date=start,
            contract_end_date=end,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list_contract_periods(
        self,
        record_id: int | None = None,
    ) -> list[CreatorContractPeriod]:
        query = """
            SELECT id, creator_id, creator_category, contract_types_json,
                   start_date, end_date, created_at, updated_at
            FROM creator_contract_period
        """
        parameters: tuple[object, ...] = ()
        if record_id is not None:
            query += " WHERE creator_id = ?"
            parameters = (record_id,)
        query += " ORDER BY creator_id, start_date"
        with connect(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._contract_period_record(row) for row in rows]

    @classmethod
    def _contract_period_payload(
        cls,
        connection: sqlite3.Connection,
        record_id: int,
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            """
            SELECT creator_category, contract_types_json, start_date, end_date
            FROM creator_contract_period
            WHERE creator_id = ?
            ORDER BY start_date, id
            """,
            (record_id,),
        ).fetchall()
        return [
            {
                "creator_category": row["creator_category"],
                "contract_types": list(
                    cls._profile_history_contracts(row["contract_types_json"])
                ),
                "start_date": str(row["start_date"]),
                "end_date": str(row["end_date"]),
            }
            for row in rows
        ]

    @staticmethod
    def _insert_contract_revision(
        connection: sqlite3.Connection,
        *,
        record_id: int,
        operation_type: str,
        before_periods: list[dict[str, object]],
        after_periods: list[dict[str, object]],
        affected_start_date: date | None,
        affected_end_date: date | None,
        reason: str | None,
        reverted_revision_id: int | None = None,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO creator_contract_revision (
                creator_id, operation_type, before_json, after_json,
                affected_start_date, affected_end_date, reason,
                reverted_revision_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                operation_type,
                json.dumps(before_periods, ensure_ascii=False),
                json.dumps(after_periods, ensure_ascii=False),
                affected_start_date.isoformat() if affected_start_date else None,
                affected_end_date.isoformat() if affected_end_date else None,
                reason.strip() if reason and reason.strip() else None,
                reverted_revision_id,
            ),
        )
        return int(cursor.lastrowid)

    def list_contract_revisions(
        self,
        record_id: int | None = None,
        *,
        limit: int = 200,
    ) -> list[CreatorContractRevision]:
        query = "SELECT * FROM creator_contract_revision"
        parameters: list[object] = []
        if record_id is not None:
            query += " WHERE creator_id = ?"
            parameters.append(record_id)
        query += " ORDER BY id DESC LIMIT ?"
        parameters.append(max(1, int(limit)))
        with connect(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        revisions: list[CreatorContractRevision] = []
        for row in rows:
            try:
                before = json.loads(str(row["before_json"]))
                after = json.loads(str(row["after_json"]))
            except json.JSONDecodeError:
                before, after = [], []
            revisions.append(
                CreatorContractRevision(
                    id=int(row["id"]),
                    creator_id=int(row["creator_id"]),
                    operation_type=str(row["operation_type"]),
                    before_periods=tuple(before if isinstance(before, list) else []),
                    after_periods=tuple(after if isinstance(after, list) else []),
                    affected_start_date=self._stored_contract_date(
                        row["affected_start_date"]
                    ),
                    affected_end_date=self._stored_contract_date(
                        row["affected_end_date"]
                    ),
                    reason=row["reason"],
                    reverted_revision_id=(
                        int(row["reverted_revision_id"])
                        if row["reverted_revision_id"] is not None
                        else None
                    ),
                    reverted_at=row["reverted_at"],
                    created_at=str(row["created_at"]),
                )
            )
        return revisions

    def contract_revisions_for_month(self, period_month: str) -> list[CreatorContractRevision]:
        try:
            month_start = date.fromisoformat(f"{period_month}-01")
        except ValueError as exc:
            raise KOCRepositoryError("月份格式必须为 YYYY-MM。") from exc
        next_month = (
            date(month_start.year + 1, 1, 1)
            if month_start.month == 12
            else date(month_start.year, month_start.month + 1, 1)
        )
        month_end = next_month - timedelta(days=1)
        return [
            revision
            for revision in self.list_contract_revisions(limit=2_000)
            if revision.affected_start_date is not None
            and revision.affected_end_date is not None
            and revision.affected_start_date <= month_end
            and revision.affected_end_date >= month_start
        ]

    def revert_contract_revision(self, revision_id: int, *, reason: str | None = None) -> KOCRecord:
        cleaned_reason = (reason or "").strip() or None
        if reason is not None and cleaned_reason is None:
            raise KOCRepositoryError("撤销原因不能为空。")
        if cleaned_reason is not None and len(cleaned_reason) > 500:
            raise KOCRepositoryError("撤销原因不能超过 500 个字符。")
        with connect(self.database_path) as connection:
            target = connection.execute(
                "SELECT * FROM creator_contract_revision WHERE id = ?",
                (revision_id,),
            ).fetchone()
            if target is None:
                raise KOCRepositoryError("未找到要撤销的合同修改记录。")
            if str(target["operation_type"]) == "REVERT":
                raise KOCRepositoryError("撤销记录不能再次撤销。")
            if target["reverted_at"] is not None:
                raise KOCRepositoryError("该合同修改已经撤销。")
            record_id = int(target["creator_id"])
            latest = connection.execute(
                """
                SELECT id FROM creator_contract_revision
                WHERE creator_id = ? AND operation_type != 'REVERT'
                  AND reverted_at IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (record_id,),
            ).fetchone()
            if latest is None or int(latest["id"]) != revision_id:
                raise KOCRepositoryError("只能撤销该达人最近一次未撤销的合同修改。")
            try:
                restored_periods = json.loads(str(target["before_json"]))
            except json.JSONDecodeError as exc:
                raise KOCRepositoryError("合同修改记录无法读取，不能撤销。") from exc
            if not isinstance(restored_periods, list) or not restored_periods:
                raise KOCRepositoryError("撤销后不能让达人失去全部合同周期。")
            current_periods = self._contract_period_payload(connection, record_id)
            connection.execute(
                "DELETE FROM creator_contract_period WHERE creator_id = ?",
                (record_id,),
            )
            for period in restored_periods:
                connection.execute(
                    """
                    INSERT INTO creator_contract_period (
                        creator_id, creator_category, contract_types_json,
                        start_date, end_date
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        period.get("creator_category"),
                        json.dumps(period.get("contract_types", []), ensure_ascii=False),
                        period.get("start_date"),
                        period.get("end_date"),
                    ),
                )
            self._sync_master_contract_period(connection, record_id)
            revert_id = self._insert_contract_revision(
                connection,
                record_id=record_id,
                operation_type="REVERT",
                before_periods=current_periods,
                after_periods=restored_periods,
                affected_start_date=self._stored_contract_date(
                    target["affected_start_date"]
                ),
                affected_end_date=self._stored_contract_date(
                    target["affected_end_date"]
                ),
                reason=cleaned_reason or f"撤销合同修改 #{revision_id}",
                reverted_revision_id=revision_id,
            )
            connection.execute(
                """
                UPDATE creator_contract_revision
                SET reverted_revision_id = ?, reverted_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (revert_id, revision_id),
            )
        updated = self.get(record_id)
        if updated is None:
            raise RuntimeError("Creator disappeared after contract revision revert.")
        return updated

    @staticmethod
    def _period_for_date(
        periods: Iterable[CreatorContractPeriod],
        target: date,
    ) -> CreatorContractPeriod | None:
        matches = [
            period
            for period in periods
            if period.contract_start_date <= target <= period.contract_end_date
        ]
        return max(matches, key=lambda period: period.contract_start_date, default=None)

    def _sync_master_contract_period(
        self,
        connection: sqlite3.Connection,
        record_id: int,
    ) -> None:
        latest = connection.execute(
            """
            SELECT creator_category, contract_types_json, start_date, end_date
            FROM creator_contract_period
            WHERE creator_id = ?
            ORDER BY start_date DESC, id DESC
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if latest is None:
            return
        contracts = self._profile_history_contracts(latest["contract_types_json"])
        now = _utc_now()
        connection.execute(
            """
            UPDATE koc_master
            SET creator_category = ?, contract_start_date = ?,
                contract_end_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                latest["creator_category"],
                latest["start_date"],
                latest["end_date"],
                now,
                record_id,
            ),
        )
        connection.execute(
            "DELETE FROM creator_contract WHERE creator_id = ?",
            (record_id,),
        )
        for contract in contracts:
            connection.execute(
                """
                INSERT INTO creator_contract (creator_id, contract_type, updated_at)
                VALUES (?, ?, ?)
                """,
                (record_id, contract, now),
            )

    def create_contract_change(
        self,
        record_id: int,
        *,
        effective_date: date | str,
        contract_types: Iterable[Any],
        contract_end_date: date | str | None = None,
        creator_category: Any = None,
        reason: str | None = None,
    ) -> KOCRecord:
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("Creator not found.")
        effective = self._clean_effective_date(effective_date)
        contracts = tuple(
            dict.fromkeys(
                contract
                for value in contract_types
                if (contract := self._clean_contract_text(value)) is not None
            )
        )
        if not contracts:
            raise KOCRepositoryError("\u5408\u540c\u7c7b\u578b\u4e0d\u80fd\u4e3a\u7a7a\u3002")
        parsed_category = self._clean_category(creator_category)
        categories = derive_creator_categories(
            contracts,
            fallback=parsed_category or current.creator_category,
        )
        category = categories[0] if categories else parsed_category or current.creator_category
        _, default_end = self._contract_period_defaults(
            category, contracts, year=effective.year
        )
        end = self._clean_contract_date(
            contract_end_date, "contract_end_date"
        ) or default_end
        if end < effective:
            raise KOCRepositoryError(
                "\u5408\u540c\u622a\u6b62\u65e5\u671f\u4e0d\u80fd\u65e9\u4e8e\u751f\u6548\u65e5\u671f\u3002"
            )

        with connect(self.database_path) as connection:
            before_periods = self._contract_period_payload(connection, record_id)
            existing = connection.execute(
                """
                SELECT id FROM creator_contract_period
                WHERE creator_id = ? AND start_date = ?
                """,
                (record_id, effective.isoformat()),
            ).fetchone()
            if existing is not None:
                raise KOCRepositoryError(
                    "\u8be5\u6708\u5df2\u6709\u5408\u540c\u5468\u671f\uff0c\u8bf7\u4f7f\u7528\u201c\u7ea0\u6b63\u586b\u5199\u9519\u8bef\u201d\u3002"
                )
            next_row = connection.execute(
                """
                SELECT start_date FROM creator_contract_period
                WHERE creator_id = ? AND start_date > ?
                ORDER BY start_date LIMIT 1
                """,
                (record_id, effective.isoformat()),
            ).fetchone()
            if next_row is not None:
                end = min(
                    end,
                    date.fromisoformat(str(next_row["start_date"]))
                    - timedelta(days=1),
                )
            previous = connection.execute(
                """
                SELECT id, end_date FROM creator_contract_period
                WHERE creator_id = ? AND start_date < ?
                ORDER BY start_date DESC LIMIT 1
                """,
                (record_id, effective.isoformat()),
            ).fetchone()
            if previous is not None and str(previous["end_date"]) >= effective.isoformat():
                connection.execute(
                    """
                    UPDATE creator_contract_period
                    SET end_date = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    ((effective - timedelta(days=1)).isoformat(), int(previous["id"])),
                )
            connection.execute(
                """
                INSERT INTO creator_contract_period (
                    creator_id, creator_category, contract_types_json,
                    start_date, end_date
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    category.value if category else None,
                    json.dumps(list(contracts), ensure_ascii=False),
                    effective.isoformat(),
                    end.isoformat(),
                ),
            )
            self._sync_master_contract_period(connection, record_id)
            after_periods = self._contract_period_payload(connection, record_id)
            self._insert_contract_revision(
                connection,
                record_id=record_id,
                operation_type="CHANGE",
                before_periods=before_periods,
                after_periods=after_periods,
                affected_start_date=effective,
                affected_end_date=end,
                reason=reason,
            )
        updated = self.get(record_id)
        if updated is None:
            raise RuntimeError("Creator disappeared after contract change.")
        return updated

    def correct_contract_period(
        self,
        record_id: int,
        *,
        source_effective_date: date | str,
        contract_types: Iterable[Any],
        contract_start_date: date | str,
        contract_end_date: date | str,
        reason: str | None = None,
    ) -> KOCRecord:
        source = self._clean_effective_date(source_effective_date)
        start = self._clean_contract_date(contract_start_date, "contract_start_date")
        end = self._clean_contract_date(contract_end_date, "contract_end_date")
        if start is None or end is None:
            raise KOCRepositoryError("\u5408\u540c\u5468\u671f\u5fc5\u987b\u586b\u5199\u5f00\u59cb\u548c\u622a\u6b62\u65e5\u671f\u3002")
        if end < start:
            raise KOCRepositoryError("\u5408\u540c\u622a\u6b62\u65e5\u671f\u4e0d\u80fd\u65e9\u4e8e\u5f00\u59cb\u65e5\u671f\u3002")
        contracts = tuple(
            dict.fromkeys(
                contract
                for value in contract_types
                if (contract := self._clean_contract_text(value)) is not None
            )
        )
        if not contracts:
            raise KOCRepositoryError("\u5408\u540c\u7c7b\u578b\u4e0d\u80fd\u4e3a\u7a7a\u3002")
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("Creator not found.")
        categories = derive_creator_categories(
            contracts, fallback=current.creator_category
        )
        category = categories[0] if categories else current.creator_category
        with connect(self.database_path) as connection:
            before_periods = self._contract_period_payload(connection, record_id)
            period = connection.execute(
                """
                SELECT id, start_date, end_date FROM creator_contract_period
                WHERE creator_id = ? AND start_date = ?
                """,
                (record_id, source.isoformat()),
            ).fetchone()
            if period is None:
                raise KOCRepositoryError(
                    "\u5408\u540c\u5468\u671f\u5df2\u5237\u65b0\uff0c\u8bf7\u91cd\u65b0\u6253\u5f00\u540e\u518d\u4fdd\u5b58\u3002"
                )
            overlap = connection.execute(
                """
                SELECT id FROM creator_contract_period
                WHERE creator_id = ? AND id != ?
                  AND start_date <= ? AND end_date >= ?
                LIMIT 1
                """,
                (record_id, int(period["id"]), end.isoformat(), start.isoformat()),
            ).fetchone()
            if overlap is not None:
                raise KOCRepositoryError(
                    "\u4fee\u6b63\u540e\u7684\u5408\u540c\u5468\u671f\u4e0e\u5176\u4ed6\u5468\u671f\u91cd\u53e0\u3002"
                )
            connection.execute(
                """
                UPDATE creator_contract_period
                SET creator_category = ?, contract_types_json = ?,
                    start_date = ?, end_date = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    category.value if category else None,
                    json.dumps(list(contracts), ensure_ascii=False),
                    start.isoformat(),
                    end.isoformat(),
                    int(period["id"]),
                ),
            )
            self._sync_master_contract_period(connection, record_id)
            after_periods = self._contract_period_payload(connection, record_id)
            previous_start = date.fromisoformat(str(period["start_date"]))
            previous_end = date.fromisoformat(str(period["end_date"]))
            self._insert_contract_revision(
                connection,
                record_id=record_id,
                operation_type="CORRECTION",
                before_periods=before_periods,
                after_periods=after_periods,
                affected_start_date=min(previous_start, start),
                affected_end_date=max(previous_end, end),
                reason=reason,
            )
        updated = self.get(record_id)
        if updated is None:
            raise RuntimeError("Creator disappeared after contract correction.")
        return updated

    def delete_authoritative_contract_period(
        self,
        record_id: int,
        *,
        source_effective_date: date | str,
        reason: str | None = None,
    ) -> KOCRecord:
        source = self._clean_effective_date(source_effective_date)
        with connect(self.database_path) as connection:
            before_periods = self._contract_period_payload(connection, record_id)
            rows = connection.execute(
                """
                SELECT id, start_date, end_date
                FROM creator_contract_period
                WHERE creator_id = ?
                ORDER BY start_date
                """,
                (record_id,),
            ).fetchall()
            if len(rows) <= 1:
                raise KOCRepositoryError(
                    "\u6bcf\u4f4d\u8fbe\u4eba\u81f3\u5c11\u9700\u8981\u4fdd\u7559\u4e00\u6bb5\u5408\u540c\u5468\u671f\u3002"
                )
            index = next(
                (
                    idx
                    for idx, row in enumerate(rows)
                    if str(row["start_date"]) == source.isoformat()
                ),
                None,
            )
            if index is None:
                raise KOCRepositoryError(
                    "\u5408\u540c\u5468\u671f\u5df2\u5237\u65b0\uff0c\u8bf7\u91cd\u65b0\u6253\u5f00\u540e\u518d\u5220\u9664\u3002"
                )
            target = rows[index]
            affected_start = date.fromisoformat(str(target["start_date"]))
            affected_end = date.fromisoformat(str(target["end_date"]))
            connection.execute(
                "DELETE FROM creator_contract_period WHERE id = ?",
                (int(target["id"]),),
            )
            if index > 0:
                previous = rows[index - 1]
                replacement_end = affected_end
                if index + 1 < len(rows):
                    next_row = rows[index + 1]
                    next_start = date.fromisoformat(str(next_row["start_date"]))
                    replacement_end = next_start - timedelta(days=1)
                connection.execute(
                    """
                    UPDATE creator_contract_period
                    SET end_date = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        replacement_end.isoformat(),
                        int(previous["id"]),
                    ),
                )
            self._sync_master_contract_period(connection, record_id)
            after_periods = self._contract_period_payload(connection, record_id)
            self._insert_contract_revision(
                connection,
                record_id=record_id,
                operation_type="DELETE",
                before_periods=before_periods,
                after_periods=after_periods,
                affected_start_date=affected_start,
                affected_end_date=affected_end,
                reason=reason,
            )
        updated = self.get(record_id)
        if updated is None:
            raise RuntimeError("Creator disappeared after contract-period deletion.")
        return updated

    def _update_profile_contract_group(
        self,
        connection: sqlite3.Connection,
        *,
        record_id: int,
        source_contracts: tuple[str, ...],
        source_start_date: date | None,
        target_contracts: tuple[str, ...],
        target_category: CreatorCategory | None,
        target_start_date: date,
        target_end_date: date,
        effective_on_or_after: date | None = None,
    ) -> tuple[date, ...]:
        """Update every profile-only snapshot belonging to one contract period."""
        rows = connection.execute(
            """
            SELECT effective_date, contract_types_json, contract_start_date
            FROM creator_profile_history
            WHERE creator_id = ?
            ORDER BY effective_date
            """,
            (record_id,),
        ).fetchall()
        matched_dates: list[date] = []
        for row in rows:
            effective = date.fromisoformat(str(row["effective_date"]))
            if effective_on_or_after is not None and effective < effective_on_or_after:
                continue
            if self._profile_history_contracts(row["contract_types_json"]) != source_contracts:
                continue
            if self._stored_contract_date(row["contract_start_date"]) != source_start_date:
                continue
            matched_dates.append(effective)
        if not matched_dates:
            return ()

        target_json = json.dumps(list(target_contracts), ensure_ascii=False)
        for effective in matched_dates:
            connection.execute(
                """
                UPDATE creator_profile_history
                SET creator_category = ?, contract_types_json = ?,
                    contract_start_date = ?, contract_end_date = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE creator_id = ? AND effective_date = ?
                """,
                (
                    target_category.value if target_category else None,
                    target_json,
                    target_start_date.isoformat(),
                    target_end_date.isoformat(),
                    record_id,
                    effective.isoformat(),
                ),
            )
        return tuple(matched_dates)

    @classmethod
    def _record(
        cls,
        row: sqlite3.Row,
        contract_types: Iterable[str] = (),
    ) -> KOCRecord:
        creator_category = cls._row_value(row, "creator_category")
        follower_count = cls._row_value(row, "follower_count")
        follower_source = cls._row_value(row, "follower_source")
        follower_sync_status = cls._row_value(
            row,
            "follower_sync_status",
            FollowerSyncStatus.NEVER.value,
        )

        return KOCRecord(
            id=int(cls._row_value(row, "id")),
            user_id=str(cls._row_value(row, "user_id", "")),
            koc_name=str(cls._row_value(row, "koc_name", "")),
            creator_category=(
                CreatorCategory(creator_category)
                if creator_category is not None
                else None
            ),
            contract_types=tuple(contract_types),
            contract_start_date=cls._stored_contract_date(
                cls._row_value(row, "contract_start_date")
            ),
            contract_end_date=cls._stored_contract_date(
                cls._row_value(row, "contract_end_date")
            ),
            homepage_url=cls._row_value(row, "homepage_url"),
            follower_count=(
                int(follower_count)
                if follower_count is not None
                else None
            ),
            youtube_user_id=cls._row_value(row, "youtube_user_id"),
            youtube_homepage_url=cls._row_value(row, "youtube_homepage_url"),
            youtube_follower_count=(
                int(cls._row_value(row, "youtube_follower_count"))
                if cls._row_value(row, "youtube_follower_count") is not None
                else None
            ),
            tiktok_user_id=cls._row_value(row, "tiktok_user_id"),
            tiktok_homepage_url=cls._row_value(row, "tiktok_homepage_url"),
            tiktok_follower_count=(
                int(cls._row_value(row, "tiktok_follower_count"))
                if cls._row_value(row, "tiktok_follower_count") is not None
                else None
            ),
            follower_raw_display_value=cls._row_value(
                row, "follower_raw_display_value"
            ),
            follower_source=(
                FollowerSource(follower_source)
                if follower_source is not None
                else None
            ),
            follower_source_url=cls._row_value(row, "follower_source_url"),
            follower_profile_url=cls._row_value(row, "follower_profile_url"),
            follower_count_is_estimated=(
                bool(cls._row_value(row, "follower_count_is_estimated"))
                if cls._row_value(row, "follower_count_is_estimated") is not None
                else None
            ),
            follower_count_updated_at=cls._row_value(
                row, "follower_count_updated_at"
            ),
            follower_sync_status=FollowerSyncStatus(follower_sync_status),
            follower_error_code=cls._row_value(row, "follower_error_code"),
            follower_sync_error=cls._row_value(row, "follower_sync_error"),
            settlement_eligible=bool(
                cls._row_value(row, "settlement_eligible", 0)
            ),
            active=bool(cls._row_value(row, "active", 1)),
            note=cls._row_value(row, "note"),
            created_at=str(cls._row_value(row, "created_at", "")),
            updated_at=str(cls._row_value(row, "updated_at", "")),
        )

    @staticmethod
    def _insert_follower_audit(
        connection: sqlite3.Connection,
        *,
        user_id: str,
        koc_name: str,
        old_follower_count: int | None,
        new_follower_count: int | None,
        raw_display_value: str | None,
        source: FollowerSource | None,
        source_url: str | None,
        fetched_at: str,
        is_estimated: bool,
        settlement_eligible: bool,
        sync_status: str,
        error_code: str | None,
        operator_mode: OperatorMode,
    ) -> None:
        connection.execute(
            """
            INSERT INTO follower_update_audit (
                user_id, koc_name, old_follower_count, new_follower_count,
                raw_display_value, source, source_url, fetched_at,
                is_estimated, settlement_eligible, sync_status, error_code,
                operator_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                koc_name,
                old_follower_count,
                new_follower_count,
                raw_display_value,
                source.value if source else None,
                source_url,
                fetched_at,
                int(is_estimated),
                int(settlement_eligible),
                sync_status,
                error_code,
                operator_mode.value,
            ),
        )


    def list(
        self,
        search: str = "",
        *,
        creator_category: CreatorCategory | str | None = None,
        contract_type: ContractType | str | None = None,
        contract_types: Iterable[ContractType | str | None] | None = None,
        follower_sync_statuses: Iterable[FollowerSyncStatus | str] | None = None,
        follower_sources: Iterable[FollowerSource | str | None] | None = None,
        settlement_eligible: bool | None = None,
        requires_manual_confirmation: bool | None = None,
        active: bool | None = None,
        include_inactive: bool | None = None,
    ) -> list[KOCRecord]:
        query = "SELECT koc_master.* FROM koc_master"
        clauses: list[str] = []
        parameters: list[Any] = []
        if include_inactive is False and active is None:
            active = True
        if active is not None:
            clauses.append("active = ?")
            parameters.append(int(active))
        category = self._clean_category(creator_category)
        if category is not None:
            if category is CreatorCategory.GRASSROOT:
                clauses.append(
                    "(creator_category = ? OR EXISTS ("
                    "SELECT 1 FROM creator_contract category_contract "
                    "WHERE category_contract.creator_id = koc_master.id AND ("
                    "LOWER(REPLACE(category_contract.contract_type, ' ', '')) LIKE '%ytb%' "
                    "OR LOWER(REPLACE(category_contract.contract_type, ' ', '')) LIKE '%tt%' "
                    "OR LOWER(category_contract.contract_type) LIKE '%tiktok%'"
                    ")))"
                )
                parameters.append(category.value)
            else:
                category_contracts = contract_texts_for_category(category)
                placeholders = ", ".join("?" for _ in category_contracts)
                clauses.append(
                    "(creator_category = ? OR EXISTS ("
                    "SELECT 1 FROM creator_contract category_contract "
                    "WHERE category_contract.creator_id = koc_master.id "
                    f"AND LOWER(TRIM(category_contract.contract_type)) IN ({placeholders})"
                    "))"
                )
                parameters.append(category.value)
                parameters.extend(category_contracts)
        if contract_type is not None and contract_types is not None:
            raise KOCRepositoryError(
                "contract_type 和 contract_types 不能同时使用。"
            )
        if contract_type is not None:
            selected_contracts: list[ContractType | str | None] = [contract_type]
        elif contract_types is None:
            selected_contracts = []
        elif isinstance(contract_types, (str, ContractType)):
            selected_contracts = [contract_types]
        else:
            selected_contracts = list(contract_types)

        if selected_contracts:
            include_unset = any(
                value is None or str(value).strip() == ""
                for value in selected_contracts
            )
            normalized_contracts = [
                self._clean_contract_text(value)
                for value in selected_contracts
                if value is not None and str(value).strip() != ""
            ]
            contract_clauses: list[str] = []
            if normalized_contracts:
                placeholders = ", ".join("?" for _ in normalized_contracts)
                contract_clauses.append(
                    "EXISTS (SELECT 1 FROM creator_contract selected_contract "
                    "WHERE selected_contract.creator_id = koc_master.id "
                    f"AND selected_contract.contract_type IN ({placeholders}))"
                )
                parameters.extend(
                    contract for contract in normalized_contracts if contract is not None
                )
            if include_unset:
                contract_clauses.append(
                    "NOT EXISTS (SELECT 1 FROM creator_contract any_contract "
                    "WHERE any_contract.creator_id = koc_master.id "
                    "AND any_contract.contract_type IS NOT NULL "
                    "AND TRIM(any_contract.contract_type) != '')"
                )
            clauses.append("(" + " OR ".join(contract_clauses) + ")")

        if follower_sync_statuses is None:
            selected_statuses: list[FollowerSyncStatus | str] = []
        elif isinstance(follower_sync_statuses, (str, FollowerSyncStatus)):
            selected_statuses = [follower_sync_statuses]
        else:
            selected_statuses = list(follower_sync_statuses)
        if selected_statuses:
            normalized_statuses = [
                self._clean_follower_sync_status(value)
                for value in selected_statuses
            ]
            placeholders = ", ".join("?" for _ in normalized_statuses)
            clauses.append(f"follower_sync_status IN ({placeholders})")
            parameters.extend(status.value for status in normalized_statuses)
        if follower_sources is None:
            selected_sources: list[FollowerSource | str | None] = []
        elif isinstance(follower_sources, (str, FollowerSource)):
            selected_sources = [follower_sources]
        else:
            selected_sources = list(follower_sources)
        if selected_sources:
            include_unset_source = any(
                value is None or str(value).strip() == ""
                for value in selected_sources
            )
            normalized_sources = [
                self._clean_follower_source(value)
                for value in selected_sources
                if value is not None and str(value).strip() != ""
            ]
            source_clauses: list[str] = []
            if normalized_sources:
                placeholders = ", ".join("?" for _ in normalized_sources)
                source_clauses.append(f"follower_source IN ({placeholders})")
                parameters.extend(source.value for source in normalized_sources)
            if include_unset_source:
                source_clauses.append(
                    "(follower_source IS NULL OR TRIM(follower_source) = '')"
                )
            clauses.append("(" + " OR ".join(source_clauses) + ")")
        if settlement_eligible is not None:
            clauses.append("settlement_eligible = ?")
            parameters.append(int(settlement_eligible))
        if requires_manual_confirmation is True:
            clauses.append(
                "(follower_count IS NOT NULL AND settlement_eligible = 0)"
            )
        elif requires_manual_confirmation is False:
            clauses.append(
                "(follower_count IS NULL OR settlement_eligible = 1)"
            )
        cleaned_search = search.strip()
        if cleaned_search:
            clauses.append("(user_id LIKE ? OR koc_name LIKE ?)")
            pattern = f"%{cleaned_search}%"
            parameters.extend([pattern, pattern])
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY active DESC, updated_at DESC, id DESC"
        with connect(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
            contract_map = self._contract_map(
                connection, (int(row["id"]) for row in rows)
            )
        return [
            self._record(row, contract_map.get(int(row["id"]), ()))
            for row in rows
        ]

    def list_profile_history(self) -> list[CreatorProfileSnapshot]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT creator_id, effective_date, user_id, koc_name,
                       creator_category, contract_types_json, contract_start_date,
                       contract_end_date, homepage_url, follower_count,
                       youtube_user_id, youtube_homepage_url,
                       youtube_follower_count, tiktok_user_id,
                       tiktok_homepage_url, tiktok_follower_count, active
                FROM creator_profile_history
                ORDER BY creator_id, effective_date
                """
            ).fetchall()
        base_snapshots: list[CreatorProfileSnapshot] = []
        for row in rows:
            try:
                contracts = json.loads(str(row["contract_types_json"]))
            except json.JSONDecodeError:
                contracts = []
            if not isinstance(contracts, list):
                contracts = []
            category = row["creator_category"]
            base_snapshots.append(
                CreatorProfileSnapshot(
                    creator_id=int(row["creator_id"]),
                    effective_date=date.fromisoformat(str(row["effective_date"])),
                    user_id=str(row["user_id"]),
                    koc_name=str(row["koc_name"]),
                    creator_category=(CreatorCategory(str(category)) if category else None),
                    contract_types=tuple(
                        str(value).strip() for value in contracts if str(value).strip()
                    ),
                    contract_start_date=self._stored_contract_date(
                        row["contract_start_date"]
                    ),
                    contract_end_date=self._stored_contract_date(
                        row["contract_end_date"]
                    ),
                    homepage_url=row["homepage_url"],
                    follower_count=(
                        int(row["follower_count"])
                        if row["follower_count"] is not None
                        else None
                    ),
                    youtube_user_id=row["youtube_user_id"],
                    youtube_homepage_url=row["youtube_homepage_url"],
                    youtube_follower_count=(
                        int(row["youtube_follower_count"])
                        if row["youtube_follower_count"] is not None
                        else None
                    ),
                    tiktok_user_id=row["tiktok_user_id"],
                    tiktok_homepage_url=row["tiktok_homepage_url"],
                    tiktok_follower_count=(
                        int(row["tiktok_follower_count"])
                        if row["tiktok_follower_count"] is not None
                        else None
                    ),
                    active=bool(row["active"]),
                )
            )

        periods_by_creator: dict[int, list[CreatorContractPeriod]] = {}
        for period in self.list_contract_periods():
            periods_by_creator.setdefault(period.creator_id, []).append(period)
        snapshots_by_creator: dict[int, list[CreatorProfileSnapshot]] = {}
        for snapshot in base_snapshots:
            snapshots_by_creator.setdefault(snapshot.creator_id, []).append(snapshot)

        resolved: list[CreatorProfileSnapshot] = []
        for creator_id, creator_snapshots in snapshots_by_creator.items():
            periods = periods_by_creator.get(creator_id, [])
            effective_dates = {snapshot.effective_date for snapshot in creator_snapshots}
            for snapshot in creator_snapshots:
                period = self._period_for_date(periods, snapshot.effective_date)
                resolved.append(
                    replace(
                        snapshot,
                        creator_category=(
                            period.creator_category
                            if period is not None
                            else snapshot.creator_category
                        ),
                        contract_types=(
                            period.contract_types if period is not None else ()
                        ),
                        contract_start_date=(
                            period.contract_start_date if period is not None else None
                        ),
                        contract_end_date=(
                            period.contract_end_date if period is not None else None
                        ),
                    )
                )

            ordered_snapshots = sorted(
                creator_snapshots, key=lambda item: item.effective_date
            )
            for period in periods:
                if period.effective_date in effective_dates:
                    continue
                prior = [
                    snapshot
                    for snapshot in ordered_snapshots
                    if snapshot.effective_date <= period.effective_date
                ]
                source = prior[-1] if prior else ordered_snapshots[0]
                resolved.append(
                    replace(
                        source,
                        effective_date=period.effective_date,
                        creator_category=period.creator_category,
                        contract_types=period.contract_types,
                        contract_start_date=period.contract_start_date,
                        contract_end_date=period.contract_end_date,
                    )
                )
        return sorted(
            resolved,
            key=lambda snapshot: (snapshot.creator_id, snapshot.effective_date),
        )

    def list_profile_history_for_creator(
        self,
        record_id: int,
    ) -> list[CreatorProfileSnapshot]:
        return [
            snapshot
            for snapshot in self.list_profile_history()
            if snapshot.creator_id == record_id
        ]

    def save_contract_history_version(
        self,
        record_id: int,
        *,
        effective_date: date | str,
        contract_types: Iterable[Any],
        contract_start_date: date | str | None = None,
        contract_end_date: date | str | None = None,
    ) -> CreatorProfileSnapshot:
        """Create or correct one historical contract version without changing master data."""
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("未找到要修正历史合同的达人。")

        effective = self._clean_effective_date(effective_date)
        selected_contracts = tuple(
            dict.fromkeys(
                contract
                for value in contract_types
                if (contract := self._clean_contract_text(value)) is not None
            )
        )
        snapshots = self.list_profile_history_for_creator(record_id)
        existing = next(
            (
                snapshot
                for snapshot in snapshots
                if snapshot.effective_date == effective
            ),
            None,
        )
        preceding = [
            snapshot for snapshot in snapshots if snapshot.effective_date < effective
        ]
        source: KOCRecord | CreatorProfileSnapshot = (
            existing or (preceding[-1] if preceding else current)
        )
        categories = derive_creator_categories(
            selected_contracts,
            fallback=source.creator_category,
        )
        category = categories[0] if categories else source.creator_category
        default_start, default_end = self._contract_period_defaults(
            category,
            selected_contracts,
            year=effective.year,
        )
        start = self._clean_contract_date(
            contract_start_date, "合同开始日期"
        ) or default_start
        end = self._clean_contract_date(
            contract_end_date, "合同截止日期"
        ) or default_end
        if end < start:
            raise KOCRepositoryError("合同截止日期不能早于合同开始日期。")

        existing_period = next(
            (
                period
                for period in self.list_contract_periods(record_id)
                if period.contract_start_date == start
            ),
            None,
        )
        if existing_period is None:
            self.create_contract_change(
                record_id,
                effective_date=start,
                contract_types=selected_contracts,
                contract_end_date=end,
                creator_category=category,
                reason="历史合同补录",
            )
        else:
            self.correct_contract_period(
                record_id,
                source_effective_date=existing_period.contract_start_date,
                contract_types=selected_contracts,
                contract_start_date=start,
                contract_end_date=end,
                reason="历史合同纠错",
            )
        saved = next(
            (
                snapshot
                for snapshot in self.list_profile_history_for_creator(record_id)
                if snapshot.effective_date == start
            ),
            None,
        )
        if saved is None:
            raise RuntimeError("历史合同保存后无法读取。")
        return saved

        with connect(self.database_path) as connection:
            next_row = connection.execute(
                """
                SELECT effective_date
                FROM creator_profile_history
                WHERE creator_id = ? AND effective_date > ?
                ORDER BY effective_date
                LIMIT 1
                """,
                (record_id, effective.isoformat()),
            ).fetchone()
            if next_row is not None:
                next_effective = date.fromisoformat(str(next_row["effective_date"]))
                end = min(end, next_effective - timedelta(days=1))
                if end < start:
                    raise KOCRepositoryError(
                        "该版本的合同期限与下一个版本重叠。"
                    )
            connection.execute(
                """
                INSERT INTO creator_profile_history (
                    creator_id, effective_date, user_id, koc_name,
                    creator_category, contract_types_json, contract_start_date,
                    contract_end_date, homepage_url, follower_count,
                    youtube_user_id, youtube_homepage_url,
                    youtube_follower_count, tiktok_user_id,
                    tiktok_homepage_url, tiktok_follower_count, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(creator_id, effective_date) DO UPDATE SET
                    creator_category = excluded.creator_category,
                    contract_types_json = excluded.contract_types_json,
                    contract_start_date = excluded.contract_start_date,
                    contract_end_date = excluded.contract_end_date,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record_id,
                    effective.isoformat(),
                    source.user_id,
                    source.koc_name,
                    category.value if category else None,
                    json.dumps(list(selected_contracts), ensure_ascii=False),
                    start.isoformat(),
                    end.isoformat(),
                    source.homepage_url,
                    source.follower_count,
                    source.youtube_user_id,
                    source.youtube_homepage_url,
                    source.youtube_follower_count,
                    source.tiktok_user_id,
                    source.tiktok_homepage_url,
                    source.tiktok_follower_count,
                    int(source.active),
                ),
            )
            previous = connection.execute(
                """
                SELECT effective_date, contract_end_date
                FROM creator_profile_history
                WHERE creator_id = ? AND effective_date < ?
                ORDER BY effective_date DESC
                LIMIT 1
                """,
                (record_id, effective.isoformat()),
            ).fetchone()
            if previous is not None:
                previous_end = self._stored_contract_date(previous["contract_end_date"])
                closed_end = effective - timedelta(days=1)
                if previous_end is None or previous_end > closed_end:
                    connection.execute(
                        """
                        UPDATE creator_profile_history
                        SET contract_end_date = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE creator_id = ? AND effective_date = ?
                        """,
                        (
                            closed_end.isoformat(),
                            record_id,
                            previous["effective_date"],
                        ),
                    )

        saved = next(
            (
                snapshot
                for snapshot in self.list_profile_history_for_creator(record_id)
                if snapshot.effective_date == effective
            ),
            None,
        )
        if saved is None:
            raise RuntimeError("历史合同保存后无法读取。")
        return saved

    def update_contract_period(
        self,
        record_id: int,
        *,
        source_effective_date: date | str,
        contract_types: Iterable[Any],
        contract_start_date: date | str,
        contract_end_date: date | str,
        reason: str | None = None,
    ) -> KOCRecord:
        """Edit one visible contract period without exposing profile snapshots."""
        return self.correct_contract_period(
            record_id,
            source_effective_date=source_effective_date,
            contract_types=contract_types,
            contract_start_date=contract_start_date,
            contract_end_date=contract_end_date,
            reason=reason,
        )

        # Legacy profile-history implementation retained below for migration
        # compatibility. Authoritative edits return above.
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("未找到要编辑合同周期的达人。")

        source_effective = self._clean_effective_date(source_effective_date)
        selected_contracts = tuple(
            dict.fromkeys(
                contract
                for value in contract_types
                if (contract := self._clean_contract_text(value)) is not None
            )
        )
        if not selected_contracts:
            raise KOCRepositoryError("合同类型不能为空。")
        start = self._clean_contract_date(contract_start_date, "合同开始日期")
        end = self._clean_contract_date(contract_end_date, "合同截止日期")
        if start is None or end is None:
            raise KOCRepositoryError("合同周期必须填写开始和截止日期。")
        if end < start:
            raise KOCRepositoryError("合同截止日期不能早于合同开始日期。")

        categories = derive_creator_categories(
            selected_contracts,
            fallback=current.creator_category,
        )
        category = categories[0] if categories else current.creator_category
        now = _utc_now()
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT effective_date, creator_category, contract_types_json,
                       contract_start_date, contract_end_date
                FROM creator_profile_history
                WHERE creator_id = ?
                ORDER BY effective_date
                """,
                (record_id,),
            ).fetchall()
            source = next(
                (
                    row
                    for row in rows
                    if str(row["effective_date"]) == source_effective.isoformat()
                ),
                None,
            )
            if source is None:
                raise KOCRepositoryError("合同周期已刷新，请重新打开后再保存。")

            source_contracts = self._profile_history_contracts(
                source["contract_types_json"]
            )
            source_start = self._stored_contract_date(
                source["contract_start_date"]
            )
            group_dates = {
                date.fromisoformat(str(row["effective_date"]))
                for row in rows
                if self._profile_history_contracts(row["contract_types_json"])
                == source_contracts
                and self._stored_contract_date(row["contract_start_date"])
                == source_start
            }
            self._update_profile_contract_group(
                connection,
                record_id=record_id,
                source_contracts=source_contracts,
                source_start_date=source_start,
                target_contracts=selected_contracts,
                target_category=category,
                target_start_date=start,
                target_end_date=end,
            )

            if (
                current.contract_types == source_contracts
                and current.contract_start_date == source_start
            ):
                connection.execute(
                    """
                    UPDATE koc_master
                    SET creator_category = ?, contract_start_date = ?,
                        contract_end_date = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        category.value if category else None,
                        start.isoformat(),
                        end.isoformat(),
                        now,
                        record_id,
                    ),
                )
                connection.execute(
                    "DELETE FROM creator_contract WHERE creator_id = ?",
                    (record_id,),
                )
                for contract in selected_contracts:
                    connection.execute(
                        """
                        INSERT INTO creator_contract (
                            creator_id, contract_type, updated_at
                        ) VALUES (?, ?, ?)
                        """,
                        (record_id, contract, now),
                    )

        updated = self.get(record_id)
        if updated is None:
            raise RuntimeError("合同周期保存后无法读取。")
        return updated

    def delete_contract_period(
        self,
        record_id: int,
        *,
        source_effective_date: date | str,
        reason: str | None = None,
    ) -> KOCRecord:
        """Delete one visible contract period and keep the current master in sync."""
        return self.delete_authoritative_contract_period(
            record_id,
            source_effective_date=source_effective_date,
            reason=reason,
        )

        # Legacy profile-history implementation retained below for migration
        # compatibility. Authoritative deletes return above.
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("未找到要删除合同周期的达人。")

        source_effective = self._clean_effective_date(source_effective_date)
        now = _utc_now()
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT effective_date, creator_category, contract_types_json,
                       contract_start_date, contract_end_date
                FROM creator_profile_history
                WHERE creator_id = ?
                ORDER BY effective_date
                """,
                (record_id,),
            ).fetchall()
            source = next(
                (
                    row
                    for row in rows
                    if str(row["effective_date"]) == source_effective.isoformat()
                ),
                None,
            )
            if source is None:
                raise KOCRepositoryError("合同周期已刷新，请重新打开后再删除。")

            groups: dict[tuple[tuple[str, ...], date], list[sqlite3.Row]] = {}
            for row in rows:
                effective = date.fromisoformat(str(row["effective_date"]))
                contracts = self._profile_history_contracts(
                    row["contract_types_json"]
                )
                start = self._stored_contract_date(row["contract_start_date"])
                groups.setdefault((contracts, start or effective), []).append(row)

            source_contracts = self._profile_history_contracts(
                source["contract_types_json"]
            )
            source_start = (
                self._stored_contract_date(source["contract_start_date"])
                or source_effective
            )
            target_key = (source_contracts, source_start)
            target_rows = groups.get(target_key, [])
            if not target_rows:
                raise KOCRepositoryError("合同周期已刷新，请重新打开后再删除。")
            target_source = min(
                date.fromisoformat(str(row["effective_date"]))
                for row in target_rows
            )
            if target_source != source_effective:
                raise KOCRepositoryError("合同周期已刷新，请重新打开后再删除。")
            if len(groups) <= 1:
                raise KOCRepositoryError(
                    "每位达人至少需要保留一段合同周期，请直接编辑当前周期。"
                )

            entries: list[dict[str, Any]] = []
            for (contracts, start), group_rows in groups.items():
                ordered = sorted(
                    group_rows,
                    key=lambda row: str(row["effective_date"]),
                )
                first = ordered[0]
                latest = ordered[-1]
                raw_category = latest["creator_category"]
                category = (
                    CreatorCategory(str(raw_category))
                    if raw_category is not None
                    else None
                )
                end = self._stored_contract_date(latest["contract_end_date"])
                if end is None:
                    end = self._stored_contract_date(first["contract_end_date"])
                entries.append(
                    {
                        "key": (contracts, start),
                        "contracts": contracts,
                        "category": category,
                        "start": start,
                        "end": end,
                        "source_effective": date.fromisoformat(
                            str(first["effective_date"])
                        ),
                        "dates": tuple(
                            date.fromisoformat(str(row["effective_date"]))
                            for row in ordered
                        ),
                    }
                )
            entries.sort(key=lambda entry: entry["source_effective"])
            target_index = next(
                index
                for index, entry in enumerate(entries)
                if entry["key"] == target_key
                and entry["source_effective"] == source_effective
            )
            target = entries[target_index]
            previous = entries[target_index - 1] if target_index > 0 else None
            following = (
                entries[target_index + 1]
                if target_index + 1 < len(entries)
                else None
            )

            for effective in target["dates"]:
                connection.execute(
                    """
                    DELETE FROM creator_profile_history
                    WHERE creator_id = ? AND effective_date = ?
                    """,
                    (record_id, effective.isoformat()),
                )

            if previous is not None:
                previous_end = previous["end"]
                restored_end = previous_end
                if following is not None:
                    restored_end = following["source_effective"] - timedelta(days=1)
                elif previous_end == source_effective - timedelta(days=1):
                    _, restored_end = self._contract_period_defaults(
                        previous["category"],
                        previous["contracts"],
                        year=previous["start"].year,
                    )
                if restored_end is not None and restored_end < previous["start"]:
                    raise KOCRepositoryError(
                        "删除后相邻合同周期会发生冲突，请先修正周期日期。"
                    )
                if restored_end != previous_end:
                    for effective in previous["dates"]:
                        connection.execute(
                            """
                            UPDATE creator_profile_history
                            SET contract_end_date = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE creator_id = ? AND effective_date = ?
                            """,
                            (
                                restored_end.isoformat()
                                if restored_end is not None
                                else None,
                                record_id,
                                effective.isoformat(),
                            ),
                        )
                    previous["end"] = restored_end

            current_key = (
                current.contract_types,
                current.contract_start_date or source_effective,
            )
            if current_key == target_key:
                replacement = max(
                    (entry for entry in entries if entry is not target),
                    key=lambda entry: entry["source_effective"],
                )
                replacement_end = replacement["end"]
                if replacement_end is None:
                    _, replacement_end = self._contract_period_defaults(
                        replacement["category"],
                        replacement["contracts"],
                        year=replacement["start"].year,
                    )
                connection.execute(
                    """
                    UPDATE koc_master
                    SET creator_category = ?, contract_start_date = ?,
                        contract_end_date = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        (
                            replacement["category"].value
                            if replacement["category"] is not None
                            else None
                        ),
                        replacement["start"].isoformat(),
                        replacement_end.isoformat(),
                        now,
                        record_id,
                    ),
                )
                connection.execute(
                    "DELETE FROM creator_contract WHERE creator_id = ?",
                    (record_id,),
                )
                for contract in replacement["contracts"]:
                    connection.execute(
                        """
                        INSERT INTO creator_contract (
                            creator_id, contract_type, updated_at
                        ) VALUES (?, ?, ?)
                        """,
                        (record_id, contract, now),
                    )

        updated = self.get(record_id)
        if updated is None:
            raise RuntimeError("合同周期删除后无法读取达人资料。")
        return updated

    def get(self, record_id: int) -> KOCRecord | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM koc_master WHERE id = ?", (record_id,)
            ).fetchone()
            contracts = (
                self._contract_map(connection, [record_id]).get(record_id, ())
                if row is not None
                else ()
            )
        return self._record(row, contracts) if row is not None else None

    def get_by_user_id(self, user_id: Any) -> KOCRecord | None:
        cleaned_uid = self._clean_user_id(user_id)
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM koc_master
                WHERE user_id = ? OR youtube_user_id = ? OR tiktok_user_id = ?
                ORDER BY id LIMIT 1
                """,
                (cleaned_uid, cleaned_uid, cleaned_uid),
            ).fetchone()
            contracts = (
                self._contract_map(connection, [int(row["id"])]).get(
                    int(row["id"]), ()
                )
                if row is not None
                else ()
            )
        return self._record(row, contracts) if row is not None else None

    def create(
        self,
        *,
        user_id: Any,
        koc_name: Any,
        creator_category: Any = None,
        contract_type: Any = None,
        contract_types: Iterable[Any] | None = None,
        homepage_url: Any = None,
        follower_count: Any = None,
        youtube_user_id: Any = None,
        youtube_homepage_url: Any = None,
        youtube_follower_count: Any = None,
        tiktok_user_id: Any = None,
        tiktok_homepage_url: Any = None,
        tiktok_follower_count: Any = None,
        active: bool = True,
        note: Any = None,
        effective_date: date | str | None = None,
        contract_start_date: date | str | None = None,
        contract_end_date: date | str | None = None,
    ) -> KOCRecord:
        uid = self._clean_user_id(user_id)
        name = self._clean_required(koc_name, "koc_name")
        category = self._clean_category(creator_category)
        if contract_type is not None and contract_types is not None:
            raise KOCRepositoryError(
                "contract_type 和 contract_types 不能同时使用。"
            )
        if contract_types is None:
            legacy_contract = self._clean_contract(contract_type)
            self._validate_category_contract(category, legacy_contract)
            selected_contracts = (
                [legacy_contract.value] if legacy_contract is not None else []
            )
        else:
            selected_contracts = [
                contract
                for value in contract_types
                if (contract := self._clean_contract_text(value)) is not None
            ]
        selected_contracts = list(dict.fromkeys(selected_contracts))
        effective = self._clean_effective_date(effective_date)
        period_start, period_end = self._resolve_contract_period(
            category=category,
            contract_types=selected_contracts,
            effective_date=effective,
            contract_start_date=contract_start_date,
            contract_end_date=contract_end_date,
        )
        homepage = self._clean_homepage_url(homepage_url)
        followers = self._clean_follower_count(follower_count)
        youtube_uid = self._clean_optional_user_id(youtube_user_id)
        youtube_homepage = self._clean_homepage_url(youtube_homepage_url)
        youtube_followers = self._clean_follower_count(youtube_follower_count)
        tiktok_uid = self._clean_optional_user_id(tiktok_user_id)
        tiktok_homepage = self._clean_homepage_url(tiktok_homepage_url)
        tiktok_followers = self._clean_follower_count(tiktok_follower_count)
        homepage_host = urlparse(homepage).netloc.casefold() if homepage else ""
        if youtube_homepage is None and "youtu" in homepage_host:
            youtube_homepage = homepage
        if youtube_uid is None and "youtu" in homepage_host:
            youtube_uid = uid
        if youtube_followers is None and youtube_homepage == homepage:
            youtube_followers = followers
        if tiktok_homepage is None and "tiktok" in homepage_host:
            tiktok_homepage = homepage
        if tiktok_uid is None and "tiktok" in homepage_host:
            tiktok_uid = uid
        if tiktok_followers is None and tiktok_homepage == homepage:
            tiktok_followers = followers
        cleaned_note = self._clean_optional(note)
        now = _utc_now()
        status = (
            FollowerSyncStatus.MANUAL
            if followers is not None
            else FollowerSyncStatus.NEVER
        )
        follower_updated_at = now if followers is not None else None
        raw_display_value = str(followers) if followers is not None else None
        follower_source = (
            FollowerSource.MANUAL if followers is not None else None
        )
        with connect(self.database_path) as connection:
            aliases = tuple(dict.fromkeys(value for value in (uid, youtube_uid, tiktok_uid) if value))
            placeholders = ",".join("?" for _ in aliases)
            existing = connection.execute(
                f"""
                SELECT id FROM koc_master
                WHERE user_id IN ({placeholders})
                   OR youtube_user_id IN ({placeholders})
                   OR tiktok_user_id IN ({placeholders})
                LIMIT 1
                """,
                (*aliases, *aliases, *aliases),
            ).fetchone()
            if existing is not None:
                raise DuplicateUserIDError("该 UID 已存在，请编辑现有达人记录。")
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO koc_master (
                        user_id, koc_name, creator_category,
                        contract_start_date, contract_end_date,
                        homepage_url, follower_count,
                        youtube_user_id, youtube_homepage_url,
                        youtube_follower_count, tiktok_user_id,
                        tiktok_homepage_url, tiktok_follower_count,
                        follower_count_updated_at,
                        follower_raw_display_value, follower_source,
                        follower_profile_url, follower_count_is_estimated,
                        follower_sync_status, settlement_eligible,
                        active, note, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uid,
                        name,
                        category.value if category else None,
                        period_start.isoformat(),
                        period_end.isoformat(),
                        homepage,
                        followers,
                        youtube_uid,
                        youtube_homepage,
                        youtube_followers,
                        tiktok_uid,
                        tiktok_homepage,
                        tiktok_followers,
                        follower_updated_at,
                        raw_display_value,
                        follower_source.value if follower_source else None,
                        homepage,
                        0 if followers is not None else None,
                        status.value,
                        0,
                        int(active),
                        cleaned_note,
                        now,
                    ),
                )
                record_id = int(cursor.lastrowid)
                for contract in selected_contracts:
                    connection.execute(
                        """
                        INSERT INTO creator_contract (
                            creator_id, contract_type, updated_at
                        ) VALUES (?, ?, ?)
                        """,
                        (record_id, contract, now),
                    )
                connection.execute(
                    """
                    INSERT INTO creator_contract_period (
                        creator_id, creator_category, contract_types_json,
                        start_date, end_date, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        category.value if category else None,
                        json.dumps(selected_contracts, ensure_ascii=False),
                        period_start.isoformat(),
                        period_end.isoformat(),
                        now,
                    ),
                )
                # A first contract is valid from its contract start, even when
                # the creator is entered into the system later in the month.
                self._save_profile_snapshot(connection, record_id, period_start)
                if followers is not None:
                    self._insert_follower_audit(
                        connection,
                        user_id=uid,
                        koc_name=name,
                        old_follower_count=None,
                        new_follower_count=followers,
                        raw_display_value=raw_display_value,
                        source=FollowerSource.MANUAL,
                        source_url=None,
                        fetched_at=now,
                        is_estimated=False,
                        settlement_eligible=False,
                        sync_status=FollowerSyncStatus.MANUAL.value,
                        error_code=None,
                        operator_mode=OperatorMode.MANUAL,
                    )
            except INTEGRITY_ERRORS as exc:
                raise KOCRepositoryError("达人保存失败，请检查输入内容。") from exc
        record = self.get(record_id)
        if record is None:
            raise RuntimeError("达人保存后无法读取。")
        return record

    def update(
        self,
        record_id: int,
        *,
        user_id: Any,
        koc_name: Any,
        creator_category: Any,
        contract_type: Any = None,
        contract_types: Iterable[Any] | None = None,
        homepage_url: Any,
        follower_count: Any,
        active: bool,
        note: Any = None,
        youtube_user_id: Any = _UNSET,
        youtube_homepage_url: Any = _UNSET,
        youtube_follower_count: Any = _UNSET,
        tiktok_user_id: Any = _UNSET,
        tiktok_homepage_url: Any = _UNSET,
        tiktok_follower_count: Any = _UNSET,
        manual_follower_update: bool = False,
        manual_settlement_eligible: bool | None = None,
        effective_date: date | str | None = None,
        contract_start_date: date | str | None = None,
        contract_end_date: date | str | None = None,
    ) -> KOCRecord:
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("未找到要修改的达人记录。")
        uid = self._clean_user_id(user_id)
        name = self._clean_required(koc_name, "koc_name")
        category = self._clean_category(creator_category)
        if contract_type is not None and contract_types is not None:
            raise KOCRepositoryError(
                "contract_type 和 contract_types 不能同时使用。"
            )
        if contract_types is None:
            legacy_contract = self._clean_contract(contract_type)
            self._validate_category_contract(category, legacy_contract)
            selected_contracts = (
                [legacy_contract.value] if legacy_contract is not None else []
            )
        else:
            selected_contracts = [
                contract
                for value in contract_types
                if (contract := self._clean_contract_text(value)) is not None
            ]
        selected_contracts = list(dict.fromkeys(selected_contracts))
        effective = self._clean_effective_date(effective_date)
        contracts_changed = tuple(selected_contracts) != current.contract_types
        category_changed = category != current.creator_category
        reset_for_contract_change = contracts_changed or category_changed
        requested_end = self._clean_contract_date(
            contract_end_date, "合同截止日期"
        )
        # The edit form initially shows the current deadline. When a contract
        # family changes, carrying that untouched value into the new version
        # would incorrectly override the new family's default deadline.
        period_end_input: date | str | None = contract_end_date
        if reset_for_contract_change and requested_end == current.contract_end_date:
            period_end_input = None
        period_start, period_end = self._resolve_contract_period(
            category=category,
            contract_types=selected_contracts,
            effective_date=effective,
            current=current,
            contract_start_date=contract_start_date,
            contract_end_date=period_end_input,
            reset_for_contract_change=reset_for_contract_change,
        )
        homepage = self._clean_homepage_url(homepage_url)
        followers = self._clean_follower_count(follower_count)
        youtube_uid = (
            current.youtube_user_id
            if youtube_user_id is _UNSET
            else self._clean_optional_user_id(youtube_user_id)
        )
        youtube_homepage = (
            current.youtube_homepage_url
            if youtube_homepage_url is _UNSET
            else self._clean_homepage_url(youtube_homepage_url)
        )
        youtube_followers = (
            current.youtube_follower_count
            if youtube_follower_count is _UNSET
            else self._clean_follower_count(youtube_follower_count)
        )
        tiktok_uid = (
            current.tiktok_user_id
            if tiktok_user_id is _UNSET
            else self._clean_optional_user_id(tiktok_user_id)
        )
        tiktok_homepage = (
            current.tiktok_homepage_url
            if tiktok_homepage_url is _UNSET
            else self._clean_homepage_url(tiktok_homepage_url)
        )
        tiktok_followers = (
            current.tiktok_follower_count
            if tiktok_follower_count is _UNSET
            else self._clean_follower_count(tiktok_follower_count)
        )
        cleaned_note = self._clean_optional(note)
        now = _utc_now()
        status = current.follower_sync_status
        follower_updated_at = current.follower_count_updated_at
        sync_error = current.follower_sync_error
        error_code = current.follower_error_code
        raw_display_value = current.follower_raw_display_value
        follower_source = current.follower_source
        follower_source_url = current.follower_source_url
        follower_profile_url = current.follower_profile_url
        is_estimated = current.follower_count_is_estimated
        eligible = current.settlement_eligible
        if manual_follower_update:
            status = FollowerSyncStatus.MANUAL
            follower_updated_at = now
            sync_error = None
            error_code = None
            raw_display_value = str(followers) if followers is not None else None
            follower_source = FollowerSource.MANUAL
            follower_source_url = None
            follower_profile_url = homepage
            is_estimated = False
            eligible = bool(manual_settlement_eligible)
        elif manual_settlement_eligible is not None:
            eligible = bool(manual_settlement_eligible)
        with connect(self.database_path) as connection:
            aliases = tuple(dict.fromkeys(value for value in (uid, youtube_uid, tiktok_uid) if value))
            placeholders = ",".join("?" for _ in aliases)
            duplicate = connection.execute(
                f"""
                SELECT id FROM koc_master
                WHERE id != ? AND (
                    user_id IN ({placeholders})
                    OR youtube_user_id IN ({placeholders})
                    OR tiktok_user_id IN ({placeholders})
                )
                LIMIT 1
                """,
                (record_id, *aliases, *aliases, *aliases),
            ).fetchone()
            if duplicate is not None:
                raise DuplicateUserIDError("该 UID 已存在，请编辑现有达人记录。")
            try:
                if reset_for_contract_change:
                    self._ensure_pre_contract_change_history(
                        connection,
                        current,
                        effective,
                    )
                connection.execute(
                    """
                    UPDATE koc_master SET
                        user_id = ?, koc_name = ?, creator_category = ?,
                        contract_start_date = ?, contract_end_date = ?,
                        homepage_url = ?, follower_count = ?,
                        youtube_user_id = ?, youtube_homepage_url = ?,
                        youtube_follower_count = ?, tiktok_user_id = ?,
                        tiktok_homepage_url = ?, tiktok_follower_count = ?,
                        follower_raw_display_value = ?, follower_source = ?,
                        follower_source_url = ?, follower_profile_url = ?,
                        follower_count_is_estimated = ?,
                        follower_count_updated_at = ?, follower_sync_status = ?,
                        follower_error_code = ?, follower_sync_error = ?,
                        settlement_eligible = ?, active = ?, note = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        uid,
                        name,
                        category.value if category else None,
                        period_start.isoformat(),
                        period_end.isoformat(),
                        homepage,
                        followers,
                        youtube_uid,
                        youtube_homepage,
                        youtube_followers,
                        tiktok_uid,
                        tiktok_homepage,
                        tiktok_followers,
                        raw_display_value,
                        follower_source.value if follower_source else None,
                        follower_source_url,
                        follower_profile_url,
                        int(is_estimated) if is_estimated is not None else None,
                        follower_updated_at,
                        status.value,
                        error_code,
                        sync_error,
                        int(eligible),
                        int(active),
                        cleaned_note,
                        now,
                        record_id,
                    ),
                )
                connection.execute(
                    "DELETE FROM creator_contract WHERE creator_id = ?",
                    (record_id,),
                )
                for contract in selected_contracts:
                    connection.execute(
                        """
                        INSERT INTO creator_contract (
                            creator_id, contract_type, updated_at
                        ) VALUES (?, ?, ?)
                        """,
                        (record_id, contract, now),
                    )
                if reset_for_contract_change:
                    # Follower refreshes can create later profile snapshots.
                    # Once a contract is backdated, those profile-only snapshots
                    # must use the new contract instead of reverting the timeline.
                    self._update_profile_contract_group(
                        connection,
                        record_id=record_id,
                        source_contracts=current.contract_types,
                        source_start_date=current.contract_start_date,
                        target_contracts=tuple(selected_contracts),
                        target_category=category,
                        target_start_date=period_start,
                        target_end_date=period_end,
                        effective_on_or_after=effective,
                    )
                profile_data_changed = any(
                    (
                        uid != current.user_id,
                        name != current.koc_name,
                        homepage != current.homepage_url,
                        followers != current.follower_count,
                        youtube_uid != current.youtube_user_id,
                        youtube_homepage != current.youtube_homepage_url,
                        youtube_followers != current.youtube_follower_count,
                        tiktok_uid != current.tiktok_user_id,
                        tiktok_homepage != current.tiktok_homepage_url,
                        tiktok_followers != current.tiktok_follower_count,
                        eligible != current.settlement_eligible,
                        bool(active) != current.active,
                        cleaned_note != current.note,
                    )
                )
                if not reset_for_contract_change or profile_data_changed:
                    self._save_profile_snapshot(connection, record_id, effective)
                if manual_follower_update:
                    self._insert_follower_audit(
                        connection,
                        user_id=uid,
                        koc_name=name,
                        old_follower_count=current.follower_count,
                        new_follower_count=followers,
                        raw_display_value=raw_display_value,
                        source=FollowerSource.MANUAL,
                        source_url=None,
                        fetched_at=now,
                        is_estimated=False,
                        settlement_eligible=eligible,
                        sync_status=FollowerSyncStatus.MANUAL.value,
                        error_code=None,
                        operator_mode=OperatorMode.MANUAL,
                    )
            except INTEGRITY_ERRORS as exc:
                raise KOCRepositoryError("达人修改失败，请检查输入内容。") from exc
        if reset_for_contract_change:
            self.create_contract_change(
                record_id,
                effective_date=effective,
                contract_types=selected_contracts,
                contract_end_date=period_end,
                creator_category=category,
                reason="兼容保存接口：真实合同变更",
            )
        elif (
            period_start != current.contract_start_date
            or period_end != current.contract_end_date
        ):
            source_start = current.contract_start_date or period_start
            self.correct_contract_period(
                record_id,
                source_effective_date=source_start,
                contract_types=selected_contracts,
                contract_start_date=period_start,
                contract_end_date=period_end,
                reason="兼容保存接口：合同周期纠错",
            )
        record = self.get(record_id)
        if record is None:
            raise RuntimeError("达人修改后无法读取。")
        return record

    def set_active(self, record_id: int, active: bool) -> KOCRecord:
        record = self.get(record_id)
        if record is None:
            raise KOCRepositoryError("未找到要修改的达人记录。")
        return self.update(
            record_id,
            user_id=record.user_id,
            koc_name=record.koc_name,
            creator_category=record.creator_category,
            contract_types=record.contract_types,
            homepage_url=record.homepage_url,
            follower_count=record.follower_count,
            active=active,
            note=record.note,
        )

    def list_contract_type_options(self) -> list[str]:
        """Return exact contract labels in first-import order."""
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT contract_type, MIN(id) AS first_id
                FROM creator_contract
                WHERE contract_type IS NOT NULL AND TRIM(contract_type) != ''
                GROUP BY contract_type
                ORDER BY first_id
                """
            ).fetchall()
        return [str(row["contract_type"]) for row in rows]

    def append_contract(
        self,
        record_id: int,
        contract_type: Any,
        *,
        effective_date: date | str | None = None,
    ) -> bool:
        """Append a new contract relationship and keep history in sync."""
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("未找到要追加合同类型的达人。")
        contract = self._clean_contract_text(contract_type)
        if contract is None:
            return False
        effective = self._clean_effective_date(effective_date)
        updated_contracts = tuple(dict.fromkeys([*current.contract_types, contract]))
        period_start, period_end = self._resolve_contract_period(
            category=current.creator_category,
            contract_types=updated_contracts,
            effective_date=effective,
            current=current if current.contract_types else None,
            reset_for_contract_change=bool(current.contract_types),
        )
        now = _utc_now()
        with connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT 1 FROM creator_contract WHERE creator_id = ? AND contract_type = ?",
                (record_id, contract),
            ).fetchone()
            if existing is not None:
                return False
            connection.execute(
                """
                INSERT INTO creator_contract (
                    creator_id, contract_type, updated_at
                ) VALUES (?, ?, ?)
                """,
                (record_id, contract, now),
            )
            connection.execute(
                """
                UPDATE koc_master
                SET contract_start_date = ?, contract_end_date = ?, updated_at = ?
                WHERE id = ?
                """,
                (period_start.isoformat(), period_end.isoformat(), now, record_id),
            )
            self._save_profile_snapshot(connection, record_id, effective)
        return True

    def apply_follower_success(
        self,
        record_id: int,
        result: FollowerFetchResult,
        *,
        sync_status: FollowerSyncStatus = FollowerSyncStatus.SUCCESS,
        operator_mode: OperatorMode = OperatorMode.AUTOMATIC,
    ) -> KOCRecord:
        if not result.success:
            raise KOCRepositoryError("不能把失败的粉丝查询结果保存为成功。")
        followers = self._clean_follower_count(result.follower_count)
        if followers is None:
            raise KOCRepositoryError("粉丝查询成功时 follower_count 不能为空。")
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("未找到要更新粉丝数的达人。")
        source = result.source or FollowerSource.MANUAL
        fetched_at = result.fetched_at or _utc_now()
        raw_display = (
            str(result.raw_display_value).strip()
            if result.raw_display_value is not None
            else str(followers)
        )
        platform = result.platform
        if platform is None and source is FollowerSource.YOUTUBE_API:
            platform = "YouTube"
        if platform is None and source in {
            FollowerSource.TIKTOK_API,
            FollowerSource.TIKTOK_BROWSER,
        }:
            platform = "TikTok"
        profile_url = result.profile_url or (
            current.homepage_for_platform(platform)
            if platform is not None
            else current.homepage_url
        )
        platform_sql = ""
        platform_values: tuple[Any, ...] = ()
        if platform == "YouTube":
            platform_sql = ", youtube_homepage_url = ?, youtube_follower_count = ?"
            platform_values = (profile_url, followers)
        elif platform == "TikTok":
            platform_sql = ", tiktok_homepage_url = ?, tiktok_follower_count = ?"
            platform_values = (profile_url, followers)
        now = _utc_now()
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                f"""
                UPDATE koc_master SET
                    follower_count = ?, follower_raw_display_value = ?,
                    follower_source = ?, follower_source_url = ?,
                    follower_profile_url = ?, follower_count_is_estimated = ?,
                    follower_count_updated_at = ?, follower_sync_status = ?,
                    follower_error_code = NULL, follower_sync_error = NULL,
                    settlement_eligible = ?, updated_at = ?{platform_sql}
                WHERE id = ?
                """,
                (
                    followers,
                    raw_display,
                    source.value,
                    result.source_url,
                    profile_url,
                    int(result.is_estimated),
                    fetched_at,
                    sync_status.value,
                    int(result.settlement_eligible),
                    now,
                    *platform_values,
                    record_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KOCRepositoryError("未找到要更新粉丝数的达人。")
            fetched_date = datetime.fromisoformat(
                fetched_at.replace("Z", "+00:00")
            ).date()
            self._save_profile_snapshot(connection, record_id, fetched_date)
            self._insert_follower_audit(
                connection,
                user_id=current.user_id,
                koc_name=current.koc_name,
                old_follower_count=(
                    current.followers_for_platform(platform)
                    if platform is not None
                    else current.follower_count
                ),
                new_follower_count=followers,
                raw_display_value=raw_display,
                source=source,
                source_url=result.source_url,
                fetched_at=fetched_at,
                is_estimated=result.is_estimated,
                settlement_eligible=result.settlement_eligible,
                sync_status=sync_status.value,
                error_code=None,
                operator_mode=operator_mode,
            )
        updated = self.get(record_id)
        if updated is None:
            raise RuntimeError("粉丝数更新后无法读取达人。")
        return updated

    def apply_follower_failure(
        self,
        record_id: int,
        result: FollowerFetchResult,
        *,
        operator_mode: OperatorMode = OperatorMode.AUTOMATIC,
    ) -> KOCRecord:
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("未找到要更新粉丝状态的达人。")
        cleaned_error = self._clean_required(
            result.error_message or "粉丝数获取失败。", "错误信息"
        )[:200]
        error_code = (result.error_code or "PROVIDER_ERROR")[:80]
        now = _utc_now()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE koc_master SET follower_sync_status = 'FAILED',
                    follower_error_code = ?, follower_sync_error = ?,
                    updated_at = ? WHERE id = ?
                """,
                (error_code, cleaned_error, now, record_id),
            )
            self._insert_follower_audit(
                connection,
                user_id=current.user_id,
                koc_name=current.koc_name,
                old_follower_count=current.follower_count,
                new_follower_count=current.follower_count,
                raw_display_value=result.raw_display_value,
                source=result.source,
                source_url=result.source_url,
                fetched_at=result.fetched_at or now,
                is_estimated=result.is_estimated,
                settlement_eligible=result.settlement_eligible,
                sync_status=FollowerSyncStatus.FAILED.value,
                error_code=error_code,
                operator_mode=operator_mode,
            )
        updated = self.get(record_id)
        if updated is None:
            raise RuntimeError("粉丝失败状态更新后无法读取达人。")
        return updated

    def record_follower_attempt(
        self,
        record_id: int,
        result: FollowerFetchResult,
        *,
        sync_status: str = "SKIPPED",
        operator_mode: OperatorMode = OperatorMode.AUTOMATIC,
    ) -> None:
        current = self.get(record_id)
        if current is None:
            raise KOCRepositoryError("未找到要记录粉丝审计的达人。")
        with connect(self.database_path) as connection:
            self._insert_follower_audit(
                connection,
                user_id=current.user_id,
                koc_name=current.koc_name,
                old_follower_count=current.follower_count,
                new_follower_count=current.follower_count,
                raw_display_value=result.raw_display_value,
                source=result.source,
                source_url=result.source_url,
                fetched_at=result.fetched_at or _utc_now(),
                is_estimated=result.is_estimated,
                settlement_eligible=result.settlement_eligible,
                sync_status=sync_status,
                error_code=result.error_code,
                operator_mode=operator_mode,
            )

    def list_follower_audit(self, user_id: str | None = None) -> pd.DataFrame:
        query = "SELECT * FROM follower_update_audit"
        parameters: list[Any] = []
        if user_id is not None:
            query += " WHERE user_id = ?"
            parameters.append(self._clean_user_id(user_id))
        query += " ORDER BY id DESC"
        with connect(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return pd.DataFrame([dict(row) for row in rows])

    def mark_follower_success(
        self, record_id: int, follower_count: int, fetched_at: str
    ) -> KOCRecord:
        result = FollowerFetchResult(
            True,
            follower_count,
            None,
            fetched_at,
            raw_display_value=str(follower_count),
            source=FollowerSource.MANUAL,
            settlement_eligible=False,
        )
        return self.apply_follower_success(record_id, result)

    def mark_follower_failure(self, record_id: int, error_message: str) -> KOCRecord:
        result = FollowerFetchResult(
            False,
            None,
            None,
            _utc_now(),
            "PROVIDER_ERROR",
            error_message,
        )
        return self.apply_follower_failure(record_id, result)

    def to_dataframe(self, *, include_inactive: bool = True) -> pd.DataFrame:
        records = self.list(include_inactive=include_inactive)
        rows: list[dict[str, Any]] = []
        for record in records:
            contracts: tuple[str | None, ...] = (
                record.contract_types if record.contract_types else (None,)
            )
            for contract_type in contracts:
                rows.append(
                    {
                        "user_id": record.user_id,
                        "koc_name": record.koc_name,
                        "creator_category": (
                            record.creator_category.value
                            if record.creator_category
                            else None
                        ),
                        "contract_type": contract_type,
                        "contract_start_date": (
                            record.contract_start_date.isoformat()
                            if record.contract_start_date
                            else None
                        ),
                        "contract_end_date": (
                            record.contract_end_date.isoformat()
                            if record.contract_end_date
                            else None
                        ),
                        "homepage_url": record.homepage_url,
                        "follower_count": record.follower_count,
                        "youtube_user_id": record.youtube_user_id,
                        "youtube_homepage_url": record.youtube_homepage_url,
                        "youtube_follower_count": record.youtube_follower_count,
                        "tiktok_user_id": record.tiktok_user_id,
                        "tiktok_homepage_url": record.tiktok_homepage_url,
                        "tiktok_follower_count": record.tiktok_follower_count,
                        "follower_raw_display_value": (
                            record.follower_raw_display_value
                        ),
                        "follower_source": (
                            record.follower_source.value
                            if record.follower_source
                            else None
                        ),
                        "follower_source_url": record.follower_source_url,
                        "follower_count_is_estimated": (
                            record.follower_count_is_estimated
                        ),
                        "follower_count_updated_at": (
                            record.follower_count_updated_at
                        ),
                        "follower_sync_status": (
                            record.follower_sync_status.value
                        ),
                        "settlement_eligible": record.settlement_eligible,
                        "active": record.active,
                        "note": record.note,
                        "created_at": record.created_at,
                        "updated_at": record.updated_at,
                    }
                )
        return pd.DataFrame(
            rows,
            columns=KOC_EXPORT_COLUMNS,
        )

    def import_dataframe(
        self,
        dataframe: pd.DataFrame,
        *,
        strategy: ImportStrategy = "add_only",
        effective_date: date | str | None = None,
    ) -> KOCImportResult:
        try:
            prepared = normalize_import_columns(dataframe)
        except KOCImportFormatError as exc:
            raise KOCRepositoryError(str(exc)) from exc
        missing = [
            column for column in ("user_id", "koc_name") if column not in prepared.columns
        ]
        if missing:
            raise KOCRepositoryError(
                "达人库 Excel 缺少必要字段：" + "、".join(missing) + "。"
            )
        if strategy not in {"add_only", "update_existing"}:
            raise KOCRepositoryError("未知的达人库导入策略。")
        snapshot_date = self._clean_effective_date(effective_date)

        added = updated = skipped = failed = contract_count = 0
        details: list[dict[str, Any]] = []
        for row_number, (_, row) in enumerate(prepared.iterrows(), start=2):
            raw_uid = row.get("user_id")
            try:
                uid = self._clean_user_id(raw_uid)
                name = self._clean_required(row.get("koc_name"), "koc_name")
                contract_type = row.get("contract_type")
                existing = self.get_by_user_id(uid)
                created_now = existing is None
                if existing is None:
                    existing = self.create(
                        user_id=uid,
                        koc_name=name,
                        creator_category=row.get("creator_category"),
                        contract_types=[contract_type],
                        homepage_url=row.get("homepage_url"),
                        follower_count=row.get("follower_count"),
                        youtube_user_id=row.get("youtube_user_id"),
                        youtube_homepage_url=row.get("youtube_homepage_url"),
                        youtube_follower_count=row.get("youtube_follower_count"),
                        tiktok_user_id=row.get("tiktok_user_id"),
                        tiktok_homepage_url=row.get("tiktok_homepage_url"),
                        tiktok_follower_count=row.get("tiktok_follower_count"),
                        active=self._clean_active(row.get("active"), default=True),
                        note=row.get("note"),
                        effective_date=snapshot_date,
                        contract_start_date=row.get("contract_start_date"),
                        contract_end_date=row.get("contract_end_date"),
                    )
                    if self._clean_contract_text(contract_type) is not None:
                        contract_count += 1
                    added += 1
                    status, message = "新增", "达人和合同关系新增成功"
                elif strategy == "add_only":
                    skipped += 1
                    status, message = (
                        "合同新增",
                        "UID 已存在；达人基础资料未覆盖，合同关系已保留",
                    )
                else:
                    def explicit(column: str) -> bool:
                        value = row.get(column)
                        return value is not None and not pd.isna(value) and str(value).strip() != ""

                    follower_explicit = explicit("follower_count")
                    self.update(
                        existing.id,
                        user_id=uid,
                        koc_name=name,
                        creator_category=(
                            row.get("creator_category")
                            if explicit("creator_category")
                            else existing.creator_category
                        ),
                        contract_types=existing.contract_types,
                        homepage_url=(
                            row.get("homepage_url")
                            if explicit("homepage_url")
                            else existing.homepage_url
                        ),
                        follower_count=(
                            row.get("follower_count")
                            if follower_explicit
                            else existing.follower_count
                        ),
                        youtube_user_id=(
                            row.get("youtube_user_id")
                            if explicit("youtube_user_id")
                            else existing.youtube_user_id
                        ),
                        youtube_homepage_url=(
                            row.get("youtube_homepage_url")
                            if explicit("youtube_homepage_url")
                            else existing.youtube_homepage_url
                        ),
                        youtube_follower_count=(
                            row.get("youtube_follower_count")
                            if explicit("youtube_follower_count")
                            else existing.youtube_follower_count
                        ),
                        tiktok_user_id=(
                            row.get("tiktok_user_id")
                            if explicit("tiktok_user_id")
                            else existing.tiktok_user_id
                        ),
                        tiktok_homepage_url=(
                            row.get("tiktok_homepage_url")
                            if explicit("tiktok_homepage_url")
                            else existing.tiktok_homepage_url
                        ),
                        tiktok_follower_count=(
                            row.get("tiktok_follower_count")
                            if explicit("tiktok_follower_count")
                            else existing.tiktok_follower_count
                        ),
                        active=(
                            self._clean_active(row.get("active"), default=existing.active)
                            if explicit("active")
                            else existing.active
                        ),
                        note=row.get("note") if explicit("note") else existing.note,
                        manual_follower_update=follower_explicit,
                        effective_date=snapshot_date,
                        contract_start_date=(
                            row.get("contract_start_date")
                            if explicit("contract_start_date")
                            else None
                        ),
                        contract_end_date=(
                            row.get("contract_end_date")
                            if explicit("contract_end_date")
                            else None
                        ),
                    )
                    updated += 1
                    status, message = "更新", "达人资料更新，合同关系已保留"
                if not created_now and self.append_contract(
                    existing.id,
                    contract_type,
                    effective_date=snapshot_date,
                ):
                    contract_count += 1
            except KOCRepositoryError as exc:
                failed += 1
                uid = normalize_user_id(raw_uid) or ""
                status, message = "失败", str(exc)
            details.append(
                {
                    "row_number": row_number,
                    "user_id": uid,
                    "status": status,
                    "message": message,
                }
            )

        return KOCImportResult(
            added_count=added,
            updated_count=updated,
            skipped_count=skipped,
            failed_count=failed,
            contract_count=contract_count,
            details=pd.DataFrame(
                details, columns=["row_number", "user_id", "status", "message"]
            ),
        )
