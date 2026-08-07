from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, HTTPException, Query

from database.koc_repository import KOCRepository
from models.enums import CreatorCategory, FollowerSource, FollowerSyncStatus

from api.serializers import serialize_creator_detail, serialize_creator_summary

ACTIVE_VALUES = {"all", "true", "false"}
SORT_WHITELIST = {"updated_at", "-updated_at", "koc_name", "-koc_name", "id", "-id"}
MAX_PAGE_SIZE = 100


def _validation_error(message: str, field: str | None = None) -> HTTPException:
    error: dict = {"code": "VALIDATION_ERROR", "message": message}
    if field is not None:
        error["field_errors"] = [{"field": field, "message": message}]
    return HTTPException(status_code=422, detail={"error": error})


def _not_found_error(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": message}})


def _parse_enum_list(values: list[str] | None, enum_cls, field: str):
    if not values:
        return None
    parsed = []
    for value in values:
        try:
            parsed.append(enum_cls(value))
        except ValueError as exc:
            raise _validation_error(f"无效的 {field} 取值：{value}", field) from exc
    return parsed


def build_creators_router(*, database_path, require_session: Callable) -> APIRouter:
    router = APIRouter(dependencies=[require_session])

    def _repository() -> KOCRepository:
        return KOCRepository(database_path)

    @router.get("/api/meta/contract-types")
    def list_contract_types() -> dict:
        repository = _repository()
        return {"data": {"contract_types": repository.list_contract_type_options()}}

    @router.get("/api/creators")
    def list_creators(
        q: str = "",
        creator_category: str | None = Query(default=None),
        contract_type: list[str] | None = Query(default=None),
        follower_sync_status: list[str] | None = Query(default=None),
        follower_source: list[str] | None = Query(default=None),
        settlement_eligible: bool | None = Query(default=None),
        active: str = Query(default="all"),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
        sort: str = Query(default="-updated_at"),
    ) -> dict:
        if active not in ACTIVE_VALUES:
            raise _validation_error(f"无效的 active 取值：{active}", "active")
        if sort not in SORT_WHITELIST:
            raise _validation_error(f"无效的 sort 取值：{sort}", "sort")
        if page < 1:
            raise _validation_error("page 必须大于等于 1。", "page")
        if page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise _validation_error(f"page_size 必须在 1 到 {MAX_PAGE_SIZE} 之间。", "page_size")

        parsed_creator_category = None
        if creator_category is not None:
            try:
                parsed_creator_category = CreatorCategory(creator_category)
            except ValueError as exc:
                raise _validation_error(
                    f"无效的 creator_category 取值：{creator_category}", "creator_category"
                ) from exc

        parsed_follower_sync_statuses = _parse_enum_list(
            follower_sync_status, FollowerSyncStatus, "follower_sync_status"
        )
        parsed_follower_sources = _parse_enum_list(
            follower_source, FollowerSource, "follower_source"
        )

        if active == "all":
            active_kwargs = {"active": None, "include_inactive": True}
        elif active == "true":
            active_kwargs = {"active": True}
        else:
            active_kwargs = {"active": False}

        repository = _repository()
        records = repository.list(
            search=q,
            creator_category=parsed_creator_category,
            contract_types=contract_type,
            follower_sync_statuses=parsed_follower_sync_statuses,
            follower_sources=parsed_follower_sources,
            settlement_eligible=settlement_eligible,
            **active_kwargs,
        )

        reverse = sort.startswith("-")
        sort_field = sort[1:] if reverse else sort
        records = sorted(records, key=lambda record: getattr(record, sort_field), reverse=reverse)

        total_items = len(records)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        start = (page - 1) * page_size
        page_records = records[start : start + page_size]

        return {
            "data": [serialize_creator_summary(record) for record in page_records],
            "meta": {
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_items": total_items,
                    "total_pages": total_pages,
                }
            },
        }

    @router.get("/api/creators/{creator_id}")
    def get_creator(creator_id: int) -> dict:
        repository = _repository()
        record = repository.get(creator_id)
        if record is None:
            raise _not_found_error(f"未找到 id={creator_id} 的达人。")
        contract_periods = repository.list_contract_periods(creator_id)
        return {"data": serialize_creator_detail(record, contract_periods)}

    return router
