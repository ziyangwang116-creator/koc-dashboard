"""Batch 2 write endpoints: data import (preview/confirm/rollback) and
cross-industry exclusion marking (19.2).

The API layer here only orchestrates: parse -> preview -> validate ->
confirm -> persist. All business logic (Excel parsing, creator ID/name
matching, post normalization, month-replace, URL normalization/marking)
is reused unchanged from ``core/multi_file_processor.py`` and
``database/dashboard_repository.py`` (which itself delegates URL matching
to ``core/cross_industry.py``).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Body, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from core.file_processor import UploadedExcel
from core.multi_file_processor import MultiFileProcessor
from database.dashboard_repository import DashboardRepository
from exporters.excel_exporter import (
    build_multi_file_download_filename,
    export_multi_file_excel,
)

from api.idempotency import IdempotencyCache

PREVIEW_TTL_SECONDS = 30 * 60


def _json_safe(value: Any) -> Any:
    """Recursively convert pandas/numpy values into plain JSON-serializable types."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return DashboardRepository._json_value(value)


def _validation_error(message: str, field_name: str | None = None) -> HTTPException:
    error: dict = {"code": "VALIDATION_ERROR", "message": message}
    if field_name is not None:
        error["field_errors"] = [{"field": field_name, "message": message}]
    return HTTPException(status_code=422, detail={"error": error})


def _not_found_error(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": message}})


def _conflict_error(message: str, code: str = "CONFLICT") -> HTTPException:
    return HTTPException(status_code=409, detail={"error": {"code": code, "message": message}})


@dataclass
class _PreviewEntry:
    data: pd.DataFrame
    unmatched_rows: list[dict[str, Any]]
    period_months: list[str]
    source_files: list[str]
    input_row_count: int
    matched_row_count: int
    cross_industry_flagged_count: int
    column_warnings: list[str]
    expires_at: float
    confirmed_batch_id: int | None = None
    confirmed_body: dict | None = None


class PreviewStore:
    """Short-lived server-side cache for parsed-but-not-yet-committed imports.

    Mirrors the Idempotency-Key cache's shape (19.6.4): a token references a
    result that lives only in memory for a bounded TTL, avoiding round-
    tripping the entire parsed dataset back to the client for confirmation.
    """

    def __init__(self, ttl_seconds: int = PREVIEW_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._entries: dict[str, _PreviewEntry] = {}

    def create(self, **kwargs: Any) -> str:
        token = uuid.uuid4().hex
        kwargs["expires_at"] = time.time() + self.ttl_seconds
        with self._lock:
            self._entries[token] = _PreviewEntry(**kwargs)
        return token

    def get(self, token: str) -> _PreviewEntry | None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            if time.time() >= entry.expires_at:
                del self._entries[token]
                return None
            return entry

    def confirmation_lock(self) -> threading.RLock:
        """Serialize confirms that share this in-process preview cache."""
        return self._lock


@dataclass
class _StandardizeEntry:
    excel_bytes: bytes
    filename: str
    expires_at: float


class StandardizeStore:
    """Short-lived download storage for read-only standardization results."""

    def __init__(self, ttl_seconds: int = PREVIEW_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, _StandardizeEntry] = {}

    def create(self, *, excel_bytes: bytes, filename: str) -> str:
        token = uuid.uuid4().hex
        self._entries[token] = _StandardizeEntry(
            excel_bytes=excel_bytes,
            filename=filename,
            expires_at=time.time() + self.ttl_seconds,
        )
        return token

    def get(self, token: str) -> _StandardizeEntry | None:
        entry = self._entries.get(token)
        if entry is None:
            return None
        if time.time() >= entry.expires_at:
            del self._entries[token]
            return None
        return entry


def build_imports_router(
    *,
    database_path,
    timezone: str,
    require_session: Callable,
    session_context: Callable | None = None,
    preview_store: PreviewStore | None = None,
) -> APIRouter:
    router = APIRouter(dependencies=[require_session])
    preview_store = preview_store or PreviewStore()
    standardize_store = StandardizeStore()
    idempotency_cache = IdempotencyCache()
    # Simple in-process guard against two concurrent replace_months confirms
    # for overlapping months racing each other (19.2.2 "并发冲突").
    active_replace_periods: set[str] = set()

    def _repository() -> DashboardRepository:
        return DashboardRepository(database_path)

    async def _uploaded_excels(files: list[UploadFile]) -> list[UploadedExcel]:
        if not files:
            raise _validation_error("请至少上传一个 Excel 文件。", "files")
        uploaded: list[UploadedExcel] = []
        for upload in files:
            name = upload.filename or "未命名文件"
            if not name.lower().endswith(".xlsx"):
                raise _validation_error(f"仅支持 .xlsx 文件：{name}", "files")
            content = await upload.read()
            uploaded.append(UploadedExcel(name=name, content=content))
        return uploaded

    @router.post("/api/imports/standardize")
    async def standardize_files(
        files: list[UploadFile] = File(...),
        processing_timezone: str | None = Form(default=None),
        deduplicate_urls: bool = Form(default=False),
    ) -> dict:
        """Run the legacy Rapid Query standardizer without writing business data."""
        uploaded = await _uploaded_excels(files)
        effective_timezone = (processing_timezone or timezone).strip()
        try:
            result = MultiFileProcessor(database_path, effective_timezone).process(
                uploaded,
                deduplicate_urls=deduplicate_urls,
            )
            excel_bytes = export_multi_file_excel(
                result.data,
                result.file_reports,
                result.exceptions,
            )
        except Exception as exc:  # noqa: BLE001 - user-facing processing error
            raise _validation_error(f"整理任务无法完成：{exc}") from exc

        filename = build_multi_file_download_filename(datetime.now())
        token = standardize_store.create(excel_bytes=excel_bytes, filename=filename)
        return _json_safe(
            {
                "data": {
                    "download_token": token,
                    "download_path": f"/api/imports/standardize/{token}/download",
                    "filename": filename,
                    "expires_in_seconds": standardize_store.ttl_seconds,
                    "timezone": effective_timezone,
                    "deduplicate_urls": deduplicate_urls,
                    "overall": asdict(result.overall),
                    "file_reports": result.file_reports.to_dict("records"),
                    "unmatched_uids": result.unmatched_uids.to_dict("records"),
                    "result_preview": result.data.head(100).to_dict("records"),
                    "result_row_count": len(result.data),
                    "exception_preview": result.exceptions.head(200).to_dict("records"),
                    "exception_row_count": len(result.exceptions),
                }
            }
        )

    @router.get("/api/imports/standardize/{download_token}/download")
    def download_standardized_file(download_token: str) -> Response:
        entry = standardize_store.get(download_token)
        if entry is None:
            raise _not_found_error("整理结果已过期，请重新上传并整理。")
        encoded_filename = quote(entry.filename)
        return Response(
            content=entry.excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": (
                    'attachment; filename="koc-standardized.xlsx"; '
                    f"filename*=UTF-8''{encoded_filename}"
                ),
                "Cache-Control": "no-store",
            },
        )

    @router.post("/api/imports/preview")
    async def preview_import(
        files: list[UploadFile] = File(...),
    ) -> dict:
        uploaded = await _uploaded_excels(files)

        try:
            result = MultiFileProcessor(database_path, timezone).process(uploaded)
        except Exception as exc:  # noqa: BLE001 - surfaced as a business validation error
            raise _validation_error(f"文件解析失败：{exc}") from exc

        data = result.data
        repository = _repository()
        annotated = repository.annotate_cross_industry_posts(data)
        cross_industry_flagged_count = (
            int(annotated["is_cross_industry"].fillna(False).astype(bool).sum())
            if not annotated.empty and "is_cross_industry" in annotated
            else 0
        )

        unmatched_rows: list[dict[str, Any]] = []
        date_anomaly_rows: list[dict[str, Any]] = []
        for _, row in result.exceptions.iterrows():
            issue_type = row.get("issue_type")
            if issue_type == "UNMATCHED_USER_ID":
                unmatched_rows.append(
                    _json_safe(
                        {
                            "row_index": None,
                            "raw_uid": row.get("userId"),
                            "raw_name": row.get("koc_name"),
                            "reason": row.get("detail") or "UID 在达人库中不存在",
                            "source_file": row.get("source_file"),
                        }
                    )
                )
            elif issue_type == "INVALID_TIMESTAMP":
                date_anomaly_rows.append(
                    _json_safe(
                        {
                            "raw_uid": row.get("userId"),
                            "koc_name": row.get("koc_name"),
                            "title": row.get("title"),
                            "url": row.get("url"),
                            "reason": row.get("detail") or "发布时间无法解析",
                            "source_file": row.get("source_file"),
                        }
                    )
                )

        input_row_count = len(data)
        matched_row_count = input_row_count - len(unmatched_rows)
        period_months = sorted(
            {
                value.strftime("%Y-%m")
                for value in pd.to_datetime(data.get("publish_date"), errors="coerce").dropna()
            }
        ) if not data.empty else []
        column_warnings = [
            str(row["error_message"])
            for _, row in result.file_reports.iterrows()
            if row.get("status") == "失败" and row.get("error_message")
        ]

        # Diff against currently-stored posts for the same months, so the
        # preview always surfaces additions/updates/removals even when the
        # counts are zero (19.2.1 requires all 4 categories to be present).
        new_rows_by_key: dict[str, dict[str, Any]] = {}
        for record in data.to_dict("records"):
            record_key, _source_file, _publish_date, payload_json = repository._storage_row(record)
            new_rows_by_key[record_key] = json.loads(payload_json)

        existing_by_key: dict[str, dict[str, Any]] = {}
        if period_months:
            existing_posts = repository.load_posts()
            if not existing_posts.empty and "publish_date" in existing_posts:
                existing_months = pd.to_datetime(
                    existing_posts["publish_date"], errors="coerce"
                ).dt.strftime("%Y-%m")
                in_scope = existing_posts.loc[existing_months.isin(period_months)]
                for record in in_scope.to_dict("records"):
                    record_key, _sf, _pd, payload_json = repository._storage_row(record)
                    existing_by_key[record_key] = json.loads(payload_json)

        additions = [v for k, v in new_rows_by_key.items() if k not in existing_by_key]
        updates = [
            v
            for k, v in new_rows_by_key.items()
            if k in existing_by_key and existing_by_key[k] != v
        ]
        removals = [v for k, v in existing_by_key.items() if k not in new_rows_by_key]

        source_files = [str(u.name) for u in uploaded]
        token = preview_store.create(
            data=data,
            unmatched_rows=unmatched_rows,
            period_months=period_months,
            source_files=source_files,
            input_row_count=input_row_count,
            matched_row_count=matched_row_count,
            cross_industry_flagged_count=cross_industry_flagged_count,
            column_warnings=column_warnings,
        )

        return _json_safe(
            {
                "data": {
                    "preview_token": token,
                    "input_row_count": input_row_count,
                    "matched_row_count": matched_row_count,
                    "period_months": period_months,
                    "cross_industry_flagged_count": cross_industry_flagged_count,
                    "column_warnings": column_warnings,
                    "additions": {"count": len(additions), "rows": additions},
                    "updates": {"count": len(updates), "rows": updates},
                    "removals": {"count": len(removals), "rows": removals},
                    "unmatched_creators": {
                        "count": len(unmatched_rows),
                        "rows": unmatched_rows,
                    },
                    "date_anomalies": {
                        "count": len(date_anomaly_rows),
                        "rows": date_anomaly_rows,
                    },
                }
            }
        )

    @router.post("/api/imports/{preview_token}/confirm")
    def confirm_import(
        preview_token: str,
        payload: dict = Body(default={}),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ctx: dict = session_context,
    ) -> JSONResponse:
        if not idempotency_key:
            raise _validation_error(
                "confirm 是高风险操作，必须携带 Idempotency-Key 请求头。", "Idempotency-Key"
            )
        entry = preview_store.get(preview_token)
        if entry is None:
            raise _not_found_error("预览已过期，请重新上传。")

        # Same preview_token can only ever succeed once (19.2.2 idempotency
        # semantics): a repeat confirm of an already-confirmed token returns
        # the first successful result rather than re-running the replace.
        if entry.confirmed_body is not None:
            return JSONResponse(status_code=200, content=entry.confirmed_body)

        mode = str(payload.get("mode") or "replace_months")
        if mode not in {"replace_months", "append_or_update"}:
            raise _validation_error(f"无效的 mode 取值：{mode}", "mode")
        replace_months = mode == "replace_months"

        # Hard block: unmatched creator IDs must never be silently dropped
        # or silently saved — confirmation is refused outright until the
        # creator library is fixed or the import is re-previewed.
        if entry.unmatched_rows:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "存在未匹配的创建者 ID/姓名，无法确认导入，请先补录达人库或修正数据后重新预览。",
                        "field_errors": {"unmatched_rows": entry.unmatched_rows},
                    }
                },
            )

        overlap = active_replace_periods & set(entry.period_months) if replace_months else set()
        if overlap:
            raise _conflict_error(
                f"该月份数据正在被另一次导入替换，请稍后重试：{sorted(overlap)}"
            )

        body_hash_payload = {"preview_token": preview_token, **payload}
        session_id = ctx.get("session_id", "") if ctx else ""
        if idempotency_key:
            body_hash = IdempotencyCache.hash_body(body_hash_payload)
            cached = idempotency_cache.lookup("import_confirm", session_id, idempotency_key)
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

        if replace_months:
            active_replace_periods.update(entry.period_months)
        try:
            repository = _repository()
            source_files = payload.get("source_file_names") or entry.source_files
            file_hashes = {name: "" for name in entry.source_files}
            result = repository.save_monthly_import(
                entry.data,
                replace_months=replace_months,
                source_files=source_files,
                file_hashes=file_hashes,
            )
        finally:
            if replace_months:
                active_replace_periods.difference_update(entry.period_months)

        body = {
            "data": {
                "batch_id": result.batch_id,
                "mode": mode.upper(),
                "period_months": entry.period_months,
                "input_count": result.input_count,
                "saved_count": result.saved_count,
                "removed_count": result.removed_count,
            }
        }
        entry.confirmed_batch_id = result.batch_id
        entry.confirmed_body = body
        if idempotency_key:
            idempotency_cache.store(
                "import_confirm",
                session_id,
                idempotency_key,
                body_hash=IdempotencyCache.hash_body(body_hash_payload),
                status_code=200,
                body=body,
            )
        return JSONResponse(status_code=200, content=body)

    @router.post("/api/dashboard/import-batches/{batch_id}/rollback")
    def rollback_import_batch(
        batch_id: int,
        payload: dict = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ctx: dict = session_context,
    ) -> JSONResponse:
        if not idempotency_key:
            raise _validation_error(
                "rollback 是高风险操作，必须携带 Idempotency-Key 请求头。", "Idempotency-Key"
            )
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise _validation_error("reason 是必填字段，请说明回滚原因。", "reason")

        repository = _repository()

        def execute() -> tuple[int, dict]:
            try:
                result = repository.rollback_import_batch(batch_id)
            except ValueError as exc:
                message = str(exc)
                if "不存在" in message:
                    raise _not_found_error(message) from exc
                if "已经回滚过" in message:
                    raise _conflict_error(message) from exc
                if "无法安全回滚" in message or "不是按月完整替换" in message:
                    raise _validation_error(message) from exc
                raise _conflict_error(message) from exc
            return 200, {"data": result}

        session_id = ctx.get("session_id", "") if ctx else ""
        payload_for_hash = {"batch_id": batch_id, "reason": reason}
        body_hash = IdempotencyCache.hash_body(payload_for_hash)
        cached = idempotency_cache.lookup("import_rollback", session_id, idempotency_key)
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
            "import_rollback",
            session_id,
            idempotency_key,
            body_hash=body_hash,
            status_code=status_code,
            body=body,
        )
        return JSONResponse(status_code=status_code, content=body)

    @router.get("/api/cross-industry-exclusions")
    def list_cross_industry_exclusions() -> dict:
        repository = _repository()
        table = repository.list_cross_industry_exclusions(include_inactive=True)
        return _json_safe({"data": table.to_dict("records")})

    @router.post("/api/cross-industry-exclusions", status_code=201)
    def create_cross_industry_exclusions(payload: dict = Body(...)) -> dict:
        urls = payload.get("urls")
        if not urls or not isinstance(urls, list):
            raise _validation_error("urls 必须是非空字符串数组。", "urls")
        cleaned_urls = [str(url).strip() for url in urls if str(url).strip()]
        if not cleaned_urls:
            raise _validation_error("urls 必须是非空字符串数组。", "urls")
        repository = _repository()
        table = repository.save_cross_industry_exclusions(
            cleaned_urls, reason=payload.get("reason")
        )
        return _json_safe({"data": table.to_dict("records")})

    @router.delete("/api/cross-industry-exclusions/{exclusion_id}")
    def delete_cross_industry_exclusion(exclusion_id: int) -> dict:
        repository = _repository()
        deactivated = repository.deactivate_cross_industry_exclusions([exclusion_id])
        return {"data": {"deactivated": deactivated}}

    return router
