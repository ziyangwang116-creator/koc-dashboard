from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from database.dashboard_repository import DashboardRepository
from database.koc_repository import DuplicateUserIDError, KOCRepository, KOCRepositoryError
from models.enums import CreatorCategory, FollowerSource, FollowerSyncStatus
from services.follower_service import FollowerService

from api.idempotency import IdempotencyCache
from api.serializers import (
    serialize_contract_revision,
    serialize_creator_detail,
    serialize_creator_summary,
)

ACTIVE_VALUES = {"all", "true", "false"}
PLATFORM_VALUES = {"all", "youtube", "tiktok"}
SORT_WHITELIST = {"updated_at", "-updated_at", "koc_name", "-koc_name", "id", "-id"}
MAX_PAGE_SIZE = 100

# Fields a client may never set directly; always server-controlled from the
# session (see 19.6.7 audit convention).
_SERVER_CONTROLLED_FIELDS = {"operator_name", "session_id"}


def _validation_error(message: str, field: str | None = None) -> HTTPException:
    error: dict = {"code": "VALIDATION_ERROR", "message": message}
    if field is not None:
        error["field_errors"] = [{"field": field, "message": message}]
    return HTTPException(status_code=422, detail={"error": error})


def _not_found_error(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": message}})


def _conflict_error(message: str, code: str = "CONFLICT") -> HTTPException:
    return HTTPException(status_code=409, detail={"error": {"code": code, "message": message}})


_NOT_FOUND_MARKERS = (
    "Creator not found.",
    "未找到",
    "已刷新",
    "无法读取",
)
_CONFLICT_MARKERS = ("重叠", "已有合同周期", "只能撤销")


def _map_repository_error(exc: KOCRepositoryError) -> HTTPException:
    message = str(exc)
    if isinstance(exc, DuplicateUserIDError):
        return _conflict_error(message)
    if any(marker in message for marker in _NOT_FOUND_MARKERS):
        return _not_found_error(message)
    if any(marker in message for marker in _CONFLICT_MARKERS):
        return _conflict_error(message)
    return _validation_error(message)


def _annotate_revisions(revisions: list) -> list[dict]:
    """Flag each revision with its revert eligibility, per revert_contract_revision()'s
    "only the latest un-reverted, non-REVERT revision can be reverted" rule
    (see database/koc_repository.py revert_contract_revision)."""
    latest_revertable_id = max(
        (
            revision.id
            for revision in revisions
            if revision.operation_type != "REVERT" and revision.reverted_at is None
        ),
        default=None,
    )
    annotated: list[dict] = []
    for revision in revisions:
        if revision.operation_type == "REVERT":
            revertable, status = False, "REVERT_RECORD"
        elif revision.reverted_at is not None:
            revertable, status = False, "REVERTED"
        elif revision.id == latest_revertable_id:
            revertable, status = True, "REVERTABLE"
        else:
            revertable, status = False, "SUPERSEDED"
        annotated.append(
            serialize_contract_revision(revision, revertable=revertable, status=status)
        )
    return annotated


def _clean_body_contract_types(payload: dict, field: str = "contract_types") -> list[str]:
    values = payload.get(field) or []
    if not isinstance(values, list):
        raise _validation_error(f"{field} 必须是字符串数组。", field)
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    return list(dict.fromkeys(cleaned))


def _strip_server_controlled(payload: dict) -> dict:
    """Never let client-supplied operator_name/session_id reach the repository."""
    return {k: v for k, v in payload.items() if k not in _SERVER_CONTROLLED_FIELDS}


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


def build_creators_router(
    *,
    database_path,
    require_session: Callable,
    session_context: Callable | None = None,
) -> APIRouter:
    router = APIRouter(dependencies=[require_session])
    idempotency_cache = IdempotencyCache()

    def _repository() -> KOCRepository:
        return KOCRepository(database_path)

    def _invalidate_compensation(reason: str, from_date: str | None = None) -> None:
        from_month = str(from_date)[:7] if from_date else None
        DashboardRepository(database_path).invalidate_compensation_calculation_cache(
            from_period_month=from_month,
            reason=reason,
        )

    def _detail_payload(repository: KOCRepository, record_id: int) -> dict:
        record = repository.get(record_id)
        if record is None:
            raise RuntimeError("Creator disappeared unexpectedly after write.")
        periods = repository.list_contract_periods(record_id)
        return serialize_creator_detail(record, periods)

    def _run_idempotent(
        *,
        operation: str,
        ctx: dict,
        idempotency_key: str | None,
        payload: dict,
        execute: Callable[[], tuple[int, dict]],
    ) -> JSONResponse:
        session_id = ctx.get("session_id", "")
        if idempotency_key:
            body_hash = IdempotencyCache.hash_body(payload)
            cached = idempotency_cache.lookup(operation, session_id, idempotency_key)
            if cached is not None:
                if cached.body_hash != body_hash:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "error": {
                                "code": "IDEMPOTENCY_KEY_REUSED",
                                "message": "该幂等键已用于不同的请求内容，请更换新的 Idempotency-Key。",
                            }
                        },
                    )
                return JSONResponse(status_code=cached.status_code, content=cached.body)
            status_code, body = execute()
            idempotency_cache.store(
                operation,
                session_id,
                idempotency_key,
                body_hash=body_hash,
                status_code=status_code,
                body=body,
            )
            return JSONResponse(status_code=status_code, content=body)
        status_code, body = execute()
        return JSONResponse(status_code=status_code, content=body)

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
        platform: str = Query(default="all"),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
        sort: str = Query(default="-updated_at"),
    ) -> dict:
        if active not in ACTIVE_VALUES:
            raise _validation_error(f"无效的 active 取值：{active}", "active")
        if platform not in PLATFORM_VALUES:
            raise _validation_error(f"无效的 platform 取值：{platform}", "platform")
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

        if platform == "youtube":
            records = [
                record
                for record in records
                if FollowerService.has_youtube_contract(record)
            ]
        elif platform == "tiktok":
            records = [
                record
                for record in records
                if FollowerService.has_tiktok_contract(record)
            ]

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

    @router.get("/api/creators/{creator_id}/contract-revisions")
    def list_contract_revisions(creator_id: int) -> dict:
        repository = _repository()
        record = repository.get(creator_id)
        if record is None:
            raise _not_found_error(f"未找到 id={creator_id} 的达人。")
        revisions = repository.list_contract_revisions(creator_id, limit=2_000)
        return {"data": _annotate_revisions(revisions)}

    # -------------------------------------------------------------------
    # Write endpoints (19.1) — API layer only validates input and calls the
    # existing repository methods; no business rules are reimplemented here.
    # -------------------------------------------------------------------

    @router.post("/api/creators", status_code=201)
    def create_creator(
        payload: dict = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ctx: dict = session_context,
    ) -> JSONResponse:
        clean = _strip_server_controlled(payload)
        repository = _repository()

        def execute() -> tuple[int, dict]:
            try:
                repository.create(
                    user_id=clean.get("user_id"),
                    koc_name=clean.get("koc_name"),
                    creator_category=clean.get("creator_category"),
                    contract_types=clean.get("contract_types"),
                    homepage_url=clean.get("homepage_url"),
                    follower_count=clean.get("follower_count"),
                    youtube_user_id=clean.get("youtube_user_id"),
                    youtube_homepage_url=clean.get("youtube_homepage_url"),
                    youtube_follower_count=clean.get("youtube_follower_count"),
                    tiktok_user_id=clean.get("tiktok_user_id"),
                    tiktok_homepage_url=clean.get("tiktok_homepage_url"),
                    tiktok_follower_count=clean.get("tiktok_follower_count"),
                    active=bool(clean.get("active", True)),
                    note=clean.get("note"),
                    effective_date=clean.get("effective_date"),
                    contract_start_date=clean.get("contract_start_date"),
                    contract_end_date=clean.get("contract_end_date"),
                )
            except DuplicateUserIDError as exc:
                raise _conflict_error(str(exc)) from exc
            except KOCRepositoryError as exc:
                raise _map_repository_error(exc) from exc
            new_record = repository.get_by_user_id(clean.get("user_id"))
            if new_record is None:
                raise RuntimeError("Creator disappeared after create.")
            _invalidate_compensation("达人资料已新增", clean.get("effective_date"))
            return 201, {"data": _detail_payload(repository, new_record.id)}

        return _run_idempotent(
            operation="create_creator",
            ctx=ctx,
            idempotency_key=idempotency_key,
            payload=clean,
            execute=execute,
        )

    @router.put("/api/creators/{creator_id}")
    def update_creator(
        creator_id: int,
        payload: dict = Body(...),
        if_unmodified_since: str | None = Header(default=None, alias="If-Unmodified-Since"),
        ctx: dict = session_context,
    ) -> JSONResponse:
        clean = _strip_server_controlled(payload)
        repository = _repository()
        current = repository.get(creator_id)
        if current is None:
            raise _not_found_error(f"未找到 id={creator_id} 的达人。")
        if if_unmodified_since and if_unmodified_since != current.updated_at:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "CONFLICT",
                        "message": "该达人资料已被修改，请刷新后重试。",
                        "field_errors": {"updated_at": current.updated_at},
                    }
                },
            )

        requested_contracts = clean.get("contract_types")
        if requested_contracts is None:
            requested_contracts_clean = list(current.contract_types)
        else:
            requested_contracts_clean = _clean_body_contract_types(clean)
        current_category_value = (
            current.creator_category.value if current.creator_category else None
        )
        requested_category = clean.get("creator_category", current_category_value)
        if requested_contracts_clean != list(current.contract_types) or (
            requested_category or None
        ) != current_category_value:
            raise _validation_error(
                "合同类型变化请使用“新增合同变更”接口。", "contract_types"
            )

        try:
            repository.update(
                creator_id,
                user_id=clean.get("user_id", current.user_id),
                koc_name=clean.get("koc_name", current.koc_name),
                creator_category=requested_category,
                contract_types=requested_contracts_clean,
                homepage_url=clean.get("homepage_url", current.homepage_url),
                follower_count=clean.get("follower_count", current.follower_count),
                youtube_user_id=clean.get(
                    "youtube_user_id", current.youtube_user_id
                ),
                youtube_homepage_url=clean.get(
                    "youtube_homepage_url", current.youtube_homepage_url
                ),
                youtube_follower_count=clean.get(
                    "youtube_follower_count", current.youtube_follower_count
                ),
                tiktok_user_id=clean.get("tiktok_user_id", current.tiktok_user_id),
                tiktok_homepage_url=clean.get(
                    "tiktok_homepage_url", current.tiktok_homepage_url
                ),
                tiktok_follower_count=clean.get(
                    "tiktok_follower_count", current.tiktok_follower_count
                ),
                active=bool(clean.get("active", current.active)),
                note=clean.get("note", current.note),
                manual_follower_update=bool(clean.get("manual_follower_update", False)),
                manual_settlement_eligible=clean.get("manual_settlement_eligible"),
            )
        except DuplicateUserIDError as exc:
            raise _conflict_error(str(exc)) from exc
        except KOCRepositoryError as exc:
            raise _map_repository_error(exc) from exc

        _invalidate_compensation("达人资料或粉丝数已更新")

        return JSONResponse(status_code=200, content={"data": _detail_payload(repository, creator_id)})

    @router.patch("/api/creators/{creator_id}/active")
    def set_creator_active(
        creator_id: int,
        payload: dict = Body(...),
        ctx: dict = session_context,
    ) -> JSONResponse:
        if "active" not in payload:
            raise _validation_error("active 是必填字段。", "active")
        repository = _repository()
        try:
            repository.set_active(creator_id, bool(payload.get("active")))
        except KOCRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        _invalidate_compensation("达人启用状态已更新")
        return JSONResponse(status_code=200, content={"data": _detail_payload(repository, creator_id)})

    @router.post("/api/creators/{creator_id}/contract-changes", status_code=201)
    def create_contract_change(
        creator_id: int,
        payload: dict = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ctx: dict = session_context,
    ) -> JSONResponse:
        clean = _strip_server_controlled(payload)
        repository = _repository()
        if not clean.get("effective_date"):
            raise _validation_error("effective_date 是必填字段。", "effective_date")
        contract_types = _clean_body_contract_types(clean)
        if not contract_types:
            raise _validation_error("contract_types 不能为空。", "contract_types")

        def execute() -> tuple[int, dict]:
            try:
                repository.create_contract_change(
                    creator_id,
                    effective_date=clean.get("effective_date"),
                    contract_types=contract_types,
                    contract_end_date=clean.get("contract_end_date"),
                    creator_category=clean.get("creator_category"),
                    reason=clean.get("reason"),
                )
            except KOCRepositoryError as exc:
                raise _map_repository_error(exc) from exc
            _invalidate_compensation("合同类型或合同周期已更新", clean.get("effective_date"))
            return 201, {"data": _detail_payload(repository, creator_id)}

        return _run_idempotent(
            operation="contract_change",
            ctx=ctx,
            idempotency_key=idempotency_key,
            payload={"creator_id": creator_id, **clean},
            execute=execute,
        )

    @router.post("/api/creators/{creator_id}/contract-corrections")
    def create_contract_correction(
        creator_id: int,
        payload: dict = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ctx: dict = session_context,
    ) -> JSONResponse:
        clean = _strip_server_controlled(payload)
        repository = _repository()
        current = repository.get(creator_id)
        if current is None:
            raise _not_found_error(f"未找到 id={creator_id} 的达人。")
        source_effective_date = clean.get("source_effective_date")
        if not source_effective_date:
            raise _validation_error(
                "source_effective_date 是必填字段。", "source_effective_date"
            )
        contract_types = _clean_body_contract_types(clean)
        if not contract_types:
            raise _validation_error("contract_types 不能为空。", "contract_types")
        start = clean.get("contract_start_date")
        end = clean.get("contract_end_date")
        if not start or not end:
            raise _validation_error(
                "contract_start_date 和 contract_end_date 均为必填字段。",
                "contract_start_date",
            )
        if str(end) < str(start):
            raise _validation_error("合同截止日期不能早于开始日期。", "contract_end_date")

        expected_updated_at = clean.get("expected_updated_at")

        periods = repository.list_contract_periods(creator_id)
        matching = next(
            (
                p
                for p in periods
                if p.contract_start_date is not None
                and p.contract_start_date.isoformat() == str(source_effective_date)
            ),
            None,
        )
        if matching is not None:
            no_change = (
                list(matching.contract_types) == contract_types
                and matching.contract_start_date.isoformat() == str(start)
                and matching.contract_end_date.isoformat() == str(end)
            )
            if no_change:
                body = _detail_payload(repository, creator_id)
                body["no_change"] = True
                return JSONResponse(status_code=200, content={"data": body})

        if (
            expected_updated_at
            and expected_updated_at != current.updated_at
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "REVISION_EXPIRED",
                        "message": "该达人数据已被修改，请刷新后重试。",
                        "field_errors": {"updated_at": current.updated_at},
                    }
                },
            )

        def execute() -> tuple[int, dict]:
            try:
                repository.correct_contract_period(
                    creator_id,
                    source_effective_date=source_effective_date,
                    contract_types=contract_types,
                    contract_start_date=start,
                    contract_end_date=end,
                    reason=clean.get("reason"),
                )
            except KOCRepositoryError as exc:
                raise _map_repository_error(exc) from exc
            _invalidate_compensation(
                "合同类型或合同周期已更正",
                min(str(source_effective_date), str(start)),
            )
            return 200, {"data": _detail_payload(repository, creator_id)}

        return _run_idempotent(
            operation="contract_correction",
            ctx=ctx,
            idempotency_key=idempotency_key,
            payload={"creator_id": creator_id, **clean},
            execute=execute,
        )

    @router.delete("/api/creators/{creator_id}/contract-periods/{source_effective_date}")
    def delete_contract_period(
        creator_id: int,
        source_effective_date: str,
        payload: dict = Body(default={}),
        ctx: dict = session_context,
    ) -> JSONResponse:
        clean = _strip_server_controlled(payload or {})
        repository = _repository()
        try:
            repository.delete_authoritative_contract_period(
                creator_id,
                source_effective_date=source_effective_date,
                reason=clean.get("reason"),
            )
        except KOCRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        _invalidate_compensation("合同周期已删除", source_effective_date)
        return JSONResponse(status_code=200, content={"data": _detail_payload(repository, creator_id)})

    @router.post("/api/creators/{creator_id}/contract-revisions/{revision_id}/revert")
    def revert_contract_revision(
        creator_id: int,
        revision_id: int,
        payload: dict = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ctx: dict = session_context,
    ) -> JSONResponse:
        clean = _strip_server_controlled(payload)
        reason = (clean.get("reason") or "").strip()
        if not reason:
            raise _validation_error("reason 是必填字段，长度须为 1-500 个字符。", "reason")
        if len(reason) > 500:
            raise _validation_error("reason 长度不能超过 500 个字符。", "reason")

        repository = _repository()

        def execute() -> tuple[int, dict]:
            try:
                repository.revert_contract_revision(revision_id, reason=reason)
            except KOCRepositoryError as exc:
                raise _map_repository_error(exc) from exc
            _invalidate_compensation("合同历史修订已撤销")
            return 200, {"data": _detail_payload(repository, creator_id)}

        return _run_idempotent(
            operation="contract_revert",
            ctx=ctx,
            idempotency_key=idempotency_key,
            payload={"creator_id": creator_id, "revision_id": revision_id, **clean},
            execute=execute,
        )

    return router
