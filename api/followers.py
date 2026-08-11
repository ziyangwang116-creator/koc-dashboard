from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from database.koc_repository import KOCRepository
from followers.base import FollowerFetchResult
from followers.manual_provider import ManualProvider
from models.enums import FollowerSource, FollowerSyncStatus, OperatorMode
from services.follower_service import FollowerService, FollowerUpdateOutcome

from api.dashboard_support import validation_error

# In-process job registry (per 19.4.3: "the concrete background execution
# mechanism -- in-process thread pool, separate worker process, or a task
# queue -- is left to the implementation phase; this module only needs to
# honour the three endpoints' request/response shapes and status machine").
# No external task queue infra exists in this project, so a daemon thread per
# job plus a lock-guarded in-memory dict is the simplest option that still
# lets the create-job endpoint return immediately (202) while a client polls
# for progress across separate requests.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _not_found_error(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": message}})


class JobStore:
    """Thread-safe in-memory registry for async follower batch-update jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, total: int) -> str:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "PENDING",
                "total": total,
                "processed": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "youtube_success": 0,
                "youtube_failed": 0,
                "tiktok_success": 0,
                "tiktok_failed": 0,
                "created_at": _now(),
                "started_at": None,
                "finished_at": None,
                "rows": [],
            }
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            snapshot = dict(job)
            snapshot["rows"] = list(job["rows"])
            return snapshot

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job["status"] == "PENDING":
                job["status"] = "RUNNING"
                job["started_at"] = _now()

    def record_row(
        self,
        job_id: str,
        row: dict[str, Any],
        *,
        status: str,
        platform: str | None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["processed"] += 1
            job["rows"].append(row)
            if status == "成功":
                job["success"] += 1
                if platform == "YouTube":
                    job["youtube_success"] += 1
                elif platform == "TikTok":
                    job["tiktok_success"] += 1
            elif status == "跳过":
                job["skipped"] += 1
            else:
                job["failed"] += 1
                if platform == "YouTube":
                    job["youtube_failed"] += 1
                elif platform == "TikTok":
                    job["tiktok_failed"] += 1

    def mark_succeeded(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["status"] = "SUCCEEDED"
                job["finished_at"] = _now()

    def mark_failed(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["status"] = "FAILED"
                job["finished_at"] = _now()


def _missing_tiktok_uid_result(record) -> FollowerFetchResult:
    return FollowerFetchResult(
        False,
        None,
        "TikTok",
        _now(),
        "MISSING_TIKTOK_USER_ID",
        "该达人缺失 tiktok_user_id，无法发起 TikTok 抓取。",
        source=FollowerSource.MANUAL,
        profile_url=record.homepage_for_platform("TikTok"),
    )


def _run_job(
    job_id: str,
    job_store: JobStore,
    service: FollowerService,
    record_ids: list[int],
    required_platform: str | None,
    platform_by_record: dict[int, str | None] | None,
    pre_rows: list[tuple[dict[str, Any], str, str | None]] | None = None,
) -> None:
    """Background worker for one batch-update job.

    Every per-creator error (fetch exception, missing tiktok_user_id, record
    not found, etc.) is isolated by `FollowerService.update_many()` itself --
    it records a failed/skipped row for that creator and keeps going. This
    wrapper only needs to guard against something unexpected blowing up
    *outside* that per-record loop (e.g. a DB connection error while writing
    progress), in which case the job itself -- not any single creator's
    result -- is marked FAILED.
    """
    job_store.mark_running(job_id)
    try:
        if pre_rows:
            for row, status, platform in pre_rows:
                job_store.record_row(job_id, row, status=status, platform=platform)
        if record_ids:
            def _progress_callback(
                completed: int,
                total: int,
                record,
                outcome: FollowerUpdateOutcome,
            ) -> None:
                job_store.record_row(
                    job_id,
                    FollowerService._detail_row(outcome),
                    status=outcome.status,
                    platform=outcome.result.platform,
                )

            service.update_many(
                record_ids,
                required_platform=required_platform,
                platform_by_record=platform_by_record,
                progress_callback=_progress_callback,
            )
        job_store.mark_succeeded(job_id)
    except Exception:  # noqa: BLE001 - job-level crash boundary, never a per-record failure
        job_store.mark_failed(job_id)


def build_followers_router(
    *,
    database_path,
    require_session: Callable,
    session_context: Callable | None = None,
    service_factory: Callable[[], FollowerService] | None = None,
    youtube_api_key: str | None = None,
    tiktok_browser_data_dir=None,
    tiktok_persistent_headless: bool = False,
) -> APIRouter:
    """Wrap `services.follower_service.FollowerService` as HTTP endpoints.

    Per 19.4: this module does not reimplement platform identification,
    scraping, or success/failure persistence -- it only calls the existing
    `update_one`/`update_many`/`tiktok_contract_records`/`has_youtube_contract`
    methods and exposes their results over HTTP (plus a manual-input endpoint
    and an async job wrapper around `update_many`, per this phase's scope).
    """
    router = APIRouter(dependencies=[require_session])
    job_store = JobStore()

    def _repository() -> KOCRepository:
        return KOCRepository(database_path)

    def _service() -> FollowerService:
        if service_factory is not None:
            return service_factory()
        return FollowerService(
            _repository(),
            youtube_api_key=youtube_api_key,
            tiktok_browser_data_dir=tiktok_browser_data_dir,
            tiktok_persistent_headless=tiktok_persistent_headless,
        )

    def _operator_name(ctx: Any) -> str | None:
        return ctx.get("operator_name") if isinstance(ctx, dict) else None

    # ------------------------------------------------------------------
    # Manual single-creator follower-count input (operator-typed values,
    # not fetched from an external platform). Reuses
    # `followers.manual_provider.ManualProvider.from_value()` for parsing/
    # validation and the same `apply_follower_success`/`apply_follower_failure`
    # persistence used by the automatic fetch paths, so the two input modes
    # share one audit trail and one set of stored-value invariants.
    # ------------------------------------------------------------------
    @router.post("/api/followers/{creator_id}/manual-update")
    def manual_update(
        creator_id: int,
        payload: dict = Body(...),
        ctx: dict = session_context,
    ) -> JSONResponse:
        youtube_value = payload.get("youtube_follower_count")
        tiktok_value = payload.get("tiktok_follower_count")
        if youtube_value in (None, "") and tiktok_value in (None, ""):
            raise validation_error(
                "必须至少提供 youtube_follower_count 或 tiktok_follower_count 之一。"
            )

        repository = _repository()
        record = repository.get(creator_id)
        if record is None:
            raise _not_found_error("未找到要更新粉丝数的达人。")

        operator_name = _operator_name(ctx)
        provider = ManualProvider()
        results: dict[str, Any] = {}

        for platform, field, raw_value in (
            ("YouTube", "youtube_follower_count", youtube_value),
            ("TikTok", "tiktok_follower_count", tiktok_value),
        ):
            if raw_value in (None, ""):
                continue
            profile_url = record.homepage_for_platform(platform)
            fetch_result = provider.from_value(
                raw_value, profile_url=profile_url, settlement_confirmed=True
            )
            if fetch_result.success:
                fetch_result = replace(fetch_result, platform=platform)
                record = repository.apply_follower_success(
                    record.id,
                    fetch_result,
                    sync_status=FollowerSyncStatus.MANUAL,
                    operator_mode=OperatorMode.MANUAL,
                    operator_name=operator_name,
                )
                results[field] = {
                    "status": "成功",
                    "follower_count": fetch_result.follower_count,
                    "error_code": None,
                    "message": "更新成功",
                }
            else:
                record = repository.apply_follower_failure(
                    record.id,
                    fetch_result,
                    operator_mode=OperatorMode.MANUAL,
                    operator_name=operator_name,
                )
                results[field] = {
                    "status": "失败",
                    "follower_count": None,
                    "error_code": fetch_result.error_code,
                    "message": fetch_result.error_message,
                }

        return JSONResponse(
            status_code=200,
            content={"data": {"record_id": record.id, "results": results}},
        )

    # ------------------------------------------------------------------
    # 19.4.3 async batch-update job: create / poll progress / read results.
    # ------------------------------------------------------------------
    @router.post("/api/followers/batch-update-jobs", status_code=202)
    def create_batch_job(payload: dict = Body(...)) -> JSONResponse:
        record_ids_raw = payload.get("record_ids")
        if not isinstance(record_ids_raw, list) or not record_ids_raw:
            raise validation_error("record_ids 是必填字段，且不能为空数组。", "record_ids")
        try:
            record_ids = [int(value) for value in record_ids_raw]
        except (TypeError, ValueError) as exc:
            raise validation_error("record_ids 必须是整数数组。", "record_ids") from exc

        required_platform = payload.get("required_platform")
        platform_by_record_raw = payload.get("platform_by_record") or {}
        if not isinstance(platform_by_record_raw, dict):
            raise validation_error("platform_by_record 须为对象。", "platform_by_record")
        platform_by_record = (
            {int(key): value for key, value in platform_by_record_raw.items()}
            if platform_by_record_raw
            else None
        )

        service = _service()
        job_id = job_store.create(total=len(record_ids))
        threading.Thread(
            target=_run_job,
            args=(job_id, job_store, service, record_ids, required_platform, platform_by_record),
            daemon=True,
        ).start()

        job = job_store.get(job_id)
        return JSONResponse(
            status_code=202,
            content={
                "data": {
                    "job_id": job["job_id"],
                    "status": job["status"],
                    "total": job["total"],
                    "created_at": job["created_at"],
                }
            },
        )

    @router.get("/api/followers/batch-update-jobs/{job_id}")
    def get_batch_job(job_id: str) -> dict:
        job = job_store.get(job_id)
        if job is None:
            raise _not_found_error("未找到该批量更新任务。")
        return {
            "data": {
                "job_id": job["job_id"],
                "status": job["status"],
                "total": job["total"],
                "processed": job["processed"],
                "success": job["success"],
                "failed": job["failed"],
                "skipped": job["skipped"],
                "youtube_success": job["youtube_success"],
                "youtube_failed": job["youtube_failed"],
                "tiktok_success": job["tiktok_success"],
                "tiktok_failed": job["tiktok_failed"],
                "started_at": job["started_at"],
                "finished_at": job["finished_at"],
            }
        }

    @router.get("/api/followers/batch-update-jobs/{job_id}/results")
    def get_batch_job_results(job_id: str) -> dict:
        job = job_store.get(job_id)
        if job is None:
            raise _not_found_error("未找到该批量更新任务。")
        return {"data": {"job_id": job["job_id"], "rows": job["rows"]}}

    # ------------------------------------------------------------------
    # 19.4.4 all-tiktok / all-youtube convenience jobs.
    #
    # TikTok candidacy is the exact same dynamic substring match already used
    # by `FollowerService.has_tiktok_contract()`/`tiktok_contract_records()`
    # (which in turn reads `record.contract_types` -- the creator's currently
    # effective contract set from `creator_contract`, replaced in full on
    # every contract change, per `KOCRepository._contract_map()`). No
    # whitelist is introduced here; any future contract-type string
    # containing "tt" (case/space-insensitive) is automatically included.
    # ------------------------------------------------------------------
    @router.post("/api/followers/batch-update-jobs/all-tiktok", status_code=202)
    def create_all_tiktok_job() -> JSONResponse:
        service = _service()
        candidates = service.tiktok_contract_records()

        eligible_ids: list[int] = []
        pre_rows: list[tuple[dict[str, Any], str, str | None]] = []
        for record in candidates:
            if str(record.tiktok_user_id or "").strip():
                eligible_ids.append(record.id)
                continue
            # A TikTok-candidate creator missing tiktok_user_id must never
            # abort/fail the whole batch -- record an isolated skip for this
            # creator only and continue with the rest (per 19.4.4).
            result = _missing_tiktok_uid_result(record)
            service.repository.record_follower_attempt(record.id, result)
            outcome = FollowerUpdateOutcome(
                record.id, record.user_id, record.koc_name, "跳过", result
            )
            pre_rows.append((FollowerService._detail_row(outcome), "跳过", "TikTok"))

        job_id = job_store.create(total=len(candidates))
        threading.Thread(
            target=_run_job,
            args=(job_id, job_store, service, eligible_ids, "TikTok", None, pre_rows),
            daemon=True,
        ).start()

        job = job_store.get(job_id)
        return JSONResponse(
            status_code=202,
            content={
                "data": {
                    "job_id": job["job_id"],
                    "status": job["status"],
                    "total": job["total"],
                    "created_at": job["created_at"],
                }
            },
        )

    @router.post("/api/followers/batch-update-jobs/all-youtube", status_code=202)
    def create_all_youtube_job() -> JSONResponse:
        service = _service()
        candidates = [
            record
            for record in service.repository.list(active=True)
            if service.has_youtube_contract(record)
        ]
        ids = [record.id for record in candidates]

        job_id = job_store.create(total=len(ids))
        threading.Thread(
            target=_run_job,
            args=(job_id, job_store, service, ids, "YouTube", None, None),
            daemon=True,
        ).start()

        job = job_store.get(job_id)
        return JSONResponse(
            status_code=202,
            content={
                "data": {
                    "job_id": job["job_id"],
                    "status": job["status"],
                    "total": job["total"],
                    "created_at": job["created_at"],
                }
            },
        )

    return router
