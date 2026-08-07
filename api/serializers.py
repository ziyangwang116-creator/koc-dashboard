from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from models.koc import CreatorContractPeriod, KOCRecord


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _date_str(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def serialize_creator_summary(record: KOCRecord) -> dict:
    return {
        "id": record.id,
        "user_id": record.user_id,
        "koc_name": record.koc_name,
        "creator_category": _enum_value(record.creator_category),
        "contract_types": list(record.contract_types),
        "contract_start_date": _date_str(record.contract_start_date),
        "contract_end_date": _date_str(record.contract_end_date),
        "homepage_url": record.homepage_url,
        "follower_count": record.follower_count,
        "youtube_user_id": record.youtube_user_id,
        "youtube_homepage_url": record.youtube_homepage_url,
        "youtube_follower_count": record.youtube_follower_count,
        "tiktok_user_id": record.tiktok_user_id,
        "tiktok_homepage_url": record.tiktok_homepage_url,
        "tiktok_follower_count": record.tiktok_follower_count,
        "follower_raw_display_value": record.follower_raw_display_value,
        "follower_source": _enum_value(record.follower_source),
        "follower_count_is_estimated": record.follower_count_is_estimated,
        "follower_count_updated_at": record.follower_count_updated_at,
        "follower_sync_status": _enum_value(record.follower_sync_status),
        "settlement_eligible": record.settlement_eligible,
        "active": record.active,
        "note": record.note,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def serialize_contract_period(period: CreatorContractPeriod) -> dict:
    return {
        "id": period.id,
        "effective_date": _date_str(period.effective_date),
        "creator_category": _enum_value(period.creator_category),
        "contract_types": list(period.contract_types),
        "contract_start_date": _date_str(period.contract_start_date),
        "contract_end_date": _date_str(period.contract_end_date),
        "created_at": period.created_at,
        "updated_at": period.updated_at,
    }


def serialize_creator_detail(
    record: KOCRecord, contract_periods: list[CreatorContractPeriod]
) -> dict:
    detail = serialize_creator_summary(record)
    detail["follower_source_url"] = record.follower_source_url
    detail["follower_profile_url"] = record.follower_profile_url
    detail["follower_error_code"] = record.follower_error_code
    detail["follower_sync_error"] = record.follower_sync_error
    detail["contract_periods"] = [
        serialize_contract_period(period) for period in contract_periods
    ]
    return detail
