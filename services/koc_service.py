from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from database.koc_repository import KOCImportResult, KOCRepository
from models.koc import CreatorContractRevision, CreatorProfileSnapshot, KOCRecord


class KOCService:
    def __init__(self, repository: KOCRepository) -> None:
        self.repository = repository

    @staticmethod
    def _comparable_follower_count(value: Any) -> int | None:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return None
        text = str(value).strip().replace(",", "")
        try:
            numeric = float(text)
        except (TypeError, ValueError):
            return None
        return int(numeric) if numeric.is_integer() else None

    def create_creator(self, **values: Any) -> KOCRecord:
        return self.repository.create(**values)

    def update_creator(self, record_id: int, **values: Any) -> KOCRecord:
        current = self.repository.get(record_id)
        if current is None:
            raise ValueError("未找到要修改的达人记录。")
        follower_changed = (
            self._comparable_follower_count(values.get("follower_count"))
            != current.follower_count
        )
        if "youtube_follower_count" in values:
            follower_changed = follower_changed or (
                self._comparable_follower_count(values.get("youtube_follower_count"))
                != current.youtube_follower_count
            )
        if "tiktok_follower_count" in values:
            follower_changed = follower_changed or (
                self._comparable_follower_count(values.get("tiktok_follower_count"))
                != current.tiktok_follower_count
            )
        manual_settlement_eligible = values.pop(
            "manual_settlement_eligible", None
        )
        settlement_changed = (
            manual_settlement_eligible is not None
            and bool(manual_settlement_eligible) != current.settlement_eligible
        )
        return self.repository.update(
            record_id,
            **values,
            manual_follower_update=follower_changed,
            manual_settlement_eligible=(
                bool(manual_settlement_eligible)
                if follower_changed or settlement_changed
                else None
            ),
        )

    def update_follower_count_manually(
        self,
        record_id: int,
        follower_count: Any,
    ) -> KOCRecord:
        """Record an explicit manual follower refresh, even when the value is unchanged."""
        current = self.repository.get(record_id)
        if current is None:
            raise ValueError("未找到要更新粉丝数的达人。")
        return self.repository.update(
            record_id,
            user_id=current.user_id,
            koc_name=current.koc_name,
            creator_category=current.creator_category,
            contract_types=current.contract_types,
            homepage_url=current.homepage_url,
            follower_count=follower_count,
            active=current.active,
            note=current.note,
            manual_follower_update=True,
            manual_settlement_eligible=current.settlement_eligible,
        )

    def save_contract_history_version(
        self,
        record_id: int,
        **values: Any,
    ) -> CreatorProfileSnapshot:
        return self.repository.save_contract_history_version(record_id, **values)

    def update_contract_period(
        self,
        record_id: int,
        **values: Any,
    ) -> KOCRecord:
        return self.repository.update_contract_period(record_id, **values)

    def create_contract_change(self, record_id: int, **values: Any) -> KOCRecord:
        return self.repository.create_contract_change(record_id, **values)

    def correct_contract_period(self, record_id: int, **values: Any) -> KOCRecord:
        return self.repository.correct_contract_period(record_id, **values)

    def list_contract_revisions(
        self,
        record_id: int | None = None,
        *,
        limit: int = 200,
    ) -> list[CreatorContractRevision]:
        return self.repository.list_contract_revisions(record_id, limit=limit)

    def revert_contract_revision(self, revision_id: int) -> KOCRecord:
        return self.repository.revert_contract_revision(revision_id)

    def delete_contract_period(
        self,
        record_id: int,
        **values: Any,
    ) -> KOCRecord:
        return self.repository.delete_contract_period(record_id, **values)

    def import_creators(
        self,
        dataframe: pd.DataFrame,
        *,
        strategy: str = "add_only",
        effective_date: date | str | None = None,
    ) -> KOCImportResult:
        return self.repository.import_dataframe(  # type: ignore[arg-type]
            dataframe,
            strategy=strategy,
            effective_date=effective_date,
        )
