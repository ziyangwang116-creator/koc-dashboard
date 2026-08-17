from __future__ import annotations

import math
import re
import difflib
import hashlib
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import pandas as pd

from core.dashboard_processor import build_dashboard_result, enrich_dashboard_creator_metadata
from core.traffic_boost import apply_july_traffic_boost
from database.ai_repository import AIRepository
from database.dashboard_repository import CompensationVersion, DashboardRepository
from database.koc_repository import KOCRepository
from models.koc import KOCRecord


_PERIOD_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}$")


class AIToolError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_ARGUMENT") -> None:
        super().__init__(message)
        self.code = code


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (AttributeError, ValueError):
            pass
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _validate_period(value: str) -> str:
    period = str(value).strip()
    if not _PERIOD_PATTERN.fullmatch(period):
        raise AIToolError("月份格式必须为 YYYY-MM。")
    try:
        datetime.strptime(period, "%Y-%m")
    except ValueError as exc:
        raise AIToolError("月份不是有效的自然月。") from exc
    return period


def _record_payload(record: KOCRecord) -> dict[str, Any]:
    return {
        "creator_id": record.id,
        "koc_name": record.koc_name,
        "user_id": record.user_id,
        "creator_categories": [item.value for item in record.creator_categories],
        "contract_types": list(record.contract_types),
        "contract_start_date": record.contract_start_date,
        "contract_end_date": record.contract_end_date,
        "active": record.active,
        "homepage_url": record.homepage_url,
        "follower_count": record.follower_count,
        "youtube": {
            "user_id": record.youtube_user_id,
            "homepage_url": record.youtube_homepage_url,
            "follower_count": record.youtube_follower_count,
        },
        "tiktok": {
            "user_id": record.tiktok_user_id,
            "homepage_url": record.tiktok_homepage_url,
            "follower_count": record.tiktok_follower_count,
        },
        "follower_sync_status": record.follower_sync_status.value,
        "settlement_eligible": record.settlement_eligible,
        "updated_at": record.updated_at,
    }


class AIToolRegistry:
    """Whitelisted read tools plus explicitly confirmed write tools."""

    WRITE_TOOL_NAMES = {
        "update_creator_profile",
        "create_contract_change",
        "save_exchange_rate",
        "modify_project_file",
    }

    def __init__(
        self,
        database_path: Path | str,
        *,
        conversation_id: str | None = None,
        session_id: str | None = None,
        operator_name: str = "team",
        project_root: Path | str | None = None,
    ) -> None:
        self.dashboard_repository = DashboardRepository(database_path)
        self.creator_repository = KOCRepository(database_path)
        self.ai_repository = AIRepository(database_path)
        self.conversation_id = conversation_id
        self.session_id = session_id
        self.operator_name = str(operator_name).strip() or "team"
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[1]
        )
        self._records: list[KOCRecord] | None = None
        self._posts: pd.DataFrame | None = None
        self.handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "read_project_file": self.read_project_file,
            "search_creators": self.search_creators,
            "get_creator_profile": self.get_creator_profile,
            "get_creator_contract_history": self.get_creator_contract_history,
            "get_creator_monthly_performance": self.get_creator_monthly_performance,
            "compare_creator_months": self.compare_creator_months,
            "get_compensation_breakdown": self.get_compensation_breakdown,
            "get_top_videos": self.get_top_videos,
            "audit_month_data": self.audit_month_data,
            "get_operational_summary": self.get_operational_summary,
            "update_creator_profile": self.update_creator_profile,
            "create_contract_change": self.create_contract_change,
            "save_exchange_rate": self.save_exchange_rate,
            "modify_project_file": self.modify_project_file,
        }

    @property
    def records(self) -> list[KOCRecord]:
        if self._records is None:
            self._records = self.creator_repository.list(include_inactive=True)
        return self._records

    @property
    def posts(self) -> pd.DataFrame:
        if self._posts is None:
            normalized = build_dashboard_result(
                self.dashboard_repository.load_posts()
            ).data
            enriched = enrich_dashboard_creator_metadata(
                normalized,
                self.records,
                self.creator_repository.list_profile_history(),
            )
            annotated = self.dashboard_repository.annotate_cross_industry_posts(
                enriched
            )
            self._posts = build_dashboard_result(annotated).data
        return self._posts

    @staticmethod
    def _record_search_text(record: KOCRecord) -> str:
        values = [
            record.koc_name,
            record.user_id,
            record.youtube_user_id,
            record.tiktok_user_id,
            *record.contract_types,
            *(item.value for item in record.creator_categories),
        ]
        return " ".join(str(value) for value in values if value).casefold()

    def _resolve_creator(self, query: str) -> KOCRecord:
        cleaned = str(query).strip()
        if not cleaned:
            raise AIToolError("达人查询不能为空。")
        folded = cleaned.casefold()
        exact: list[KOCRecord] = []
        for record in self.records:
            aliases = {
                str(record.id),
                record.koc_name.casefold(),
                record.user_id.casefold(),
                (record.youtube_user_id or "").casefold(),
                (record.tiktok_user_id or "").casefold(),
            }
            if folded in aliases:
                exact.append(record)
        matches = exact or [
            record for record in self.records if folded in self._record_search_text(record)
        ]
        if not matches:
            raise AIToolError(f"未找到达人：{cleaned}", code="NOT_FOUND")
        if len(matches) > 1:
            candidates = "、".join(
                f"{record.koc_name}(ID {record.id})" for record in matches[:10]
            )
            raise AIToolError(
                f"达人查询不唯一，请指定：{candidates}", code="AMBIGUOUS"
            )
        return matches[0]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        allow_writes: bool = False,
    ) -> dict[str, Any]:
        handler = self.handlers.get(name)
        if handler is None:
            raise AIToolError(f"不允许调用工具：{name}", code="UNKNOWN_TOOL")
        if name in self.WRITE_TOOL_NAMES and not allow_writes:
            return self._request_confirmation(name, arguments)
        return _json_value(handler(**arguments))

    def _require_write_context(self) -> None:
        if not self.conversation_id or not self.session_id:
            raise AIToolError(
                "写入工具必须在已认证的 Agent 对话中调用。",
                code="WRITE_CONTEXT_REQUIRED",
            )

    def _request_confirmation(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_write_context()
        preview = self._preview_write(tool_name, arguments)
        action_id = str(uuid4())
        self.ai_repository.create_pending_action(
            action_id=action_id,
            conversation_id=str(self.conversation_id),
            session_id=str(self.session_id),
            tool_name=tool_name,
            arguments=arguments,
            preview=preview,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        return {
            "status": "confirmation_required",
            "action": {
                "action_id": action_id,
                "tool_name": tool_name,
                "preview": preview,
                "expires_in_seconds": 600,
            },
        }

    def _preview_write(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name == "modify_project_file":
            return self._preview_project_file_change(arguments)
        if tool_name == "update_creator_profile":
            record = self._resolve_creator(arguments.get("query", ""))
            changes = {
                key: value
                for key, value in arguments.items()
                if key not in {"query", "expected_updated_at", "reason"}
                and value is not None
            }
            return {
                "kind": "creator_profile_write",
                "creator_id": record.id,
                "creator_name": record.koc_name,
                "changes": changes,
                "expected_updated_at": arguments.get("expected_updated_at") or record.updated_at,
            }
        if tool_name == "create_contract_change":
            record = self._resolve_creator(arguments.get("query", ""))
            contracts = arguments.get("contract_types")
            if not isinstance(contracts, list) or not contracts:
                raise AIToolError("contract_types 不能为空。")
            effective_date = str(arguments.get("effective_date") or "").strip()
            if not effective_date:
                raise AIToolError("effective_date 不能为空。")
            return {
                "kind": "contract_change",
                "creator_id": record.id,
                "creator_name": record.koc_name,
                "effective_date": effective_date,
                "contract_types": [str(item).strip() for item in contracts if str(item).strip()],
                "contract_end_date": arguments.get("contract_end_date"),
                "creator_category": arguments.get("creator_category"),
                "reason": str(arguments.get("reason") or "Agent 请求合同变更"),
            }
        if tool_name == "save_exchange_rate":
            period = _validate_period(arguments.get("period_month", ""))
            rate = float(arguments.get("jpy_to_usd_rate") or 0)
            if rate <= 0 or rate > 1:
                raise AIToolError("日元兑美元汇率必须大于 0 且不超过 1。")
            return {
                "kind": "exchange_rate_write",
                "period_month": period,
                "jpy_to_usd_rate": rate,
            }
        raise AIToolError(f"不允许调用工具：{tool_name}", code="UNKNOWN_TOOL")

    def _safe_project_path(self, raw_path: str) -> Path:
        value = str(raw_path or "").strip().replace("\\", "/")
        if not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
            raise AIToolError("代码文件路径必须是项目内相对路径。", code="PATH_NOT_ALLOWED")
        candidate = (self.project_root / value).resolve()
        try:
            candidate.relative_to(self.project_root)
        except ValueError as exc:
            raise AIToolError("代码文件路径超出项目目录。", code="PATH_NOT_ALLOWED") from exc
        blocked_parts = {".git", ".venv", "node_modules", "data", "outputs", "output"}
        if blocked_parts.intersection(part.casefold() for part in candidate.relative_to(self.project_root).parts):
            raise AIToolError("该目录不允许由 Agent 修改。", code="PATH_NOT_ALLOWED")
        if candidate.name.casefold() in {".env", "secrets.toml", "settings.json"}:
            raise AIToolError("配置密钥文件不允许由 Agent 修改。", code="PATH_NOT_ALLOWED")
        if candidate.suffix.casefold() not in {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".md"}:
            raise AIToolError("Agent 只允许修改代码或文档文件。", code="FILE_TYPE_NOT_ALLOWED")
        return candidate

    def read_project_file(
        self,
        path: str,
        start_line: int,
        end_line: int,
    ) -> dict[str, Any]:
        file_path = self._safe_project_path(path)
        if not file_path.exists() or not file_path.is_file():
            raise AIToolError("代码文件不存在。", code="NOT_FOUND")
        start = max(1, int(start_line))
        end = min(start + 250, max(start, int(end_line)))
        lines = file_path.read_text(encoding="utf-8").splitlines()
        content = "\n".join(lines[start - 1 : end])
        if len(content) > 30_000:
            raise AIToolError("读取内容过大，请缩小行号范围。")
        return {
            "status": "ok",
            "path": str(file_path.relative_to(self.project_root)).replace("\\", "/"),
            "start_line": start,
            "end_line": min(end, len(lines)),
            "content": content,
            "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        }

    def _preview_project_file_change(self, arguments: dict[str, Any]) -> dict[str, Any]:
        file_path = self._safe_project_path(arguments.get("path", ""))
        if not file_path.exists():
            raise AIToolError("代码文件不存在，Agent 不能直接创建新文件。", code="NOT_FOUND")
        old_text = str(arguments.get("old_text") or "")
        new_text = str(arguments.get("new_text") or "")
        if not old_text:
            raise AIToolError("old_text 不能为空。")
        current = file_path.read_text(encoding="utf-8")
        expected_sha256 = str(arguments.get("expected_sha256") or "").strip()
        actual_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if expected_sha256 and expected_sha256 != actual_sha256:
            raise AIToolError("文件已发生变化，请重新读取后再修改。", code="STALE_FILE")
        occurrences = current.count(old_text)
        max_replacements = max(1, min(int(arguments.get("max_replacements") or 1), 10))
        if occurrences == 0:
            raise AIToolError("old_text 在文件中不存在。", code="TEXT_NOT_FOUND")
        if occurrences > max_replacements:
            raise AIToolError("old_text 出现次数超过允许范围，请提供更精确的文本。", code="AMBIGUOUS")
        updated = current.replace(old_text, new_text, max_replacements)
        diff = "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=str(file_path.relative_to(self.project_root)),
                tofile=str(file_path.relative_to(self.project_root)),
                n=3,
            )
        )
        if len(diff) > 40_000:
            raise AIToolError("代码改动预览过大，请拆分为多个小改动。")
        return {
            "kind": "project_file_write",
            "path": str(file_path.relative_to(self.project_root)).replace("\\", "/"),
            "diff": diff,
            "old_sha256": actual_sha256,
            "new_sha256": hashlib.sha256(updated.encode("utf-8")).hexdigest(),
            "replacements": min(occurrences, max_replacements),
            "reason": str(arguments.get("reason") or "Agent 请求代码修改"),
        }

    def update_creator_profile(
        self,
        query: str,
        koc_name: str | None,
        homepage_url: str | None,
        youtube_homepage_url: str | None,
        tiktok_homepage_url: str | None,
        follower_count: int | None,
        youtube_follower_count: int | None,
        tiktok_follower_count: int | None,
        note: str | None,
        active: bool | None,
        settlement_eligible: bool | None,
        expected_updated_at: str | None,
        reason: str | None,
    ) -> dict[str, Any]:
        record = self._resolve_creator(query)
        if expected_updated_at and expected_updated_at != record.updated_at:
            raise AIToolError("达人资料已变化，请重新读取后再提交。", code="STALE_REVISION")
        follower_changed = any(
            value is not None
            for value in (follower_count, youtube_follower_count, tiktok_follower_count)
        )
        updated = self.creator_repository.update(
            record.id,
            user_id=record.user_id,
            koc_name=record.koc_name if koc_name is None else koc_name,
            creator_category=record.creator_category,
            contract_types=record.contract_types,
            homepage_url=record.homepage_url if homepage_url is None else homepage_url,
            follower_count=record.follower_count if follower_count is None else follower_count,
            active=record.active if active is None else active,
            note=record.note if note is None else note,
            youtube_user_id=record.youtube_user_id,
            youtube_homepage_url=(
                record.youtube_homepage_url
                if youtube_homepage_url is None
                else youtube_homepage_url
            ),
            youtube_follower_count=(
                record.youtube_follower_count
                if youtube_follower_count is None
                else youtube_follower_count
            ),
            tiktok_user_id=record.tiktok_user_id,
            tiktok_homepage_url=(
                record.tiktok_homepage_url
                if tiktok_homepage_url is None
                else tiktok_homepage_url
            ),
            tiktok_follower_count=(
                record.tiktok_follower_count
                if tiktok_follower_count is None
                else tiktok_follower_count
            ),
            manual_follower_update=follower_changed,
            manual_settlement_eligible=(
                settlement_eligible
                if settlement_eligible is not None
                else record.settlement_eligible
            ),
        )
        self.dashboard_repository.invalidate_compensation_calculation_cache(
            reason=str(reason or "Agent 更新达人资料")
        )
        self._records = None
        return {
            "status": "ok",
            "creator": _record_payload(updated),
            "written_by": self.operator_name,
        }

    def create_contract_change(
        self,
        query: str,
        effective_date: str,
        contract_types: list[str],
        contract_end_date: str | None,
        creator_category: str | None,
        reason: str,
    ) -> dict[str, Any]:
        record = self._resolve_creator(query)
        updated = self.creator_repository.create_contract_change(
            record.id,
            effective_date=effective_date,
            contract_types=contract_types,
            contract_end_date=contract_end_date,
            creator_category=creator_category,
            reason=reason,
        )
        self.dashboard_repository.invalidate_compensation_calculation_cache(
            from_period_month=str(effective_date)[:7],
            reason=str(reason or "Agent 更新合同周期"),
        )
        self._records = None
        return {
            "status": "ok",
            "creator": _record_payload(updated),
            "written_by": self.operator_name,
        }

    def save_exchange_rate(
        self,
        period_month: str,
        jpy_to_usd_rate: float,
    ) -> dict[str, Any]:
        period = _validate_period(period_month)
        rate = float(jpy_to_usd_rate)
        if rate <= 0 or rate > 1:
            raise AIToolError("日元兑美元汇率必须大于 0 且不超过 1。")
        self.dashboard_repository.save_jpy_to_usd_rate(period, rate)
        return {
            "status": "ok",
            "period_month": period,
            "jpy_to_usd_rate": rate,
            "written_by": self.operator_name,
        }

    def modify_project_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
        expected_sha256: str | None,
        max_replacements: int,
        reason: str,
    ) -> dict[str, Any]:
        file_path = self._safe_project_path(path)
        if not file_path.exists():
            raise AIToolError("代码文件不存在。", code="NOT_FOUND")
        current = file_path.read_text(encoding="utf-8")
        actual_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if expected_sha256 and expected_sha256 != actual_sha256:
            raise AIToolError("文件已发生变化，请重新读取后再修改。", code="STALE_FILE")
        replacements = max(1, min(int(max_replacements or 1), 10))
        if not old_text or current.count(old_text) == 0:
            raise AIToolError("old_text 在文件中不存在。", code="TEXT_NOT_FOUND")
        if current.count(old_text) > replacements:
            raise AIToolError("old_text 出现次数超过允许范围。", code="AMBIGUOUS")
        updated = current.replace(old_text, new_text, replacements)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{file_path.name}.", suffix=".agent-tmp", dir=file_path.parent
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text(updated, encoding="utf-8", newline="")
            temp_path.replace(file_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return {
            "status": "ok",
            "path": str(file_path.relative_to(self.project_root)).replace("\\", "/"),
            "replacements": min(current.count(old_text), replacements),
            "sha256": hashlib.sha256(updated.encode("utf-8")).hexdigest(),
            "reason": reason,
            "written_by": self.operator_name,
            "deployment_note": "代码已写入当前运行环境；是否部署仍需单独执行 Git/部署流程。",
        }

    def search_creators(
        self,
        search: str | None,
        creator_category: str | None,
        contract_type: str | None,
        active_only: bool,
        limit: int,
    ) -> dict[str, Any]:
        query = (search or "").strip().casefold()
        category = (creator_category or "").strip().casefold()
        contract = (contract_type or "").strip().casefold()
        matches = []
        for record in self.records:
            if active_only and not record.active:
                continue
            if query and query not in self._record_search_text(record):
                continue
            if category and category not in {
                item.value.casefold() for item in record.creator_categories
            }:
                continue
            if contract and not any(
                contract in value.casefold() for value in record.contract_types
            ):
                continue
            matches.append(_record_payload(record))
        capped = max(1, min(int(limit), 30))
        return {
            "status": "ok",
            "total_matches": len(matches),
            "returned": min(len(matches), capped),
            "creators": matches[:capped],
        }

    def get_creator_profile(self, query: str) -> dict[str, Any]:
        return {"status": "ok", "creator": _record_payload(self._resolve_creator(query))}

    def get_creator_contract_history(self, query: str, limit: int) -> dict[str, Any]:
        record = self._resolve_creator(query)
        periods = self.creator_repository.list_contract_periods(record.id)
        revisions = self.creator_repository.list_contract_revisions(
            record.id, limit=max(1, min(int(limit), 100))
        )
        return {
            "status": "ok",
            "creator": {"creator_id": record.id, "koc_name": record.koc_name},
            "contract_periods": [
                {
                    "period_id": item.id,
                    "creator_category": (
                        item.creator_category.value if item.creator_category else None
                    ),
                    "contract_types": list(item.contract_types),
                    "start_date": item.contract_start_date,
                    "end_date": item.contract_end_date,
                    "updated_at": item.updated_at,
                }
                for item in periods
            ],
            "revisions": [
                {
                    "revision_id": item.id,
                    "operation_type": item.operation_type,
                    "affected_start_date": item.affected_start_date,
                    "affected_end_date": item.affected_end_date,
                    "reason": item.reason,
                    "reverted_at": item.reverted_at,
                    "created_at": item.created_at,
                }
                for item in revisions
            ],
        }

    def _month_posts(
        self,
        period_month: str,
        *,
        include_cross_industry: bool,
    ) -> pd.DataFrame:
        period = _validate_period(period_month)
        data = self.posts.copy()
        dates = pd.to_datetime(data["publish_date"], errors="coerce")
        scoped = data.loc[dates.dt.strftime("%Y-%m").eq(period)].copy()
        if not include_cross_industry and "compensation_eligible" in scoped:
            scoped = scoped.loc[
                scoped["compensation_eligible"].astype("boolean").fillna(True)
            ].copy()
        boost_enabled = self.dashboard_repository.get_traffic_boost_enabled(period)
        return apply_july_traffic_boost(scoped, enabled=boost_enabled)

    @staticmethod
    def _creator_posts(data: pd.DataFrame, creator_id: int) -> pd.DataFrame:
        ids = pd.to_numeric(data.get("creator_id"), errors="coerce")
        return data.loc[ids.eq(creator_id)].copy()

    @staticmethod
    def _performance_summary(data: pd.DataFrame) -> dict[str, Any]:
        if data.empty:
            return {
                "post_count": 0,
                "views": 0,
                "likes": 0,
                "comments": 0,
                "reposts": 0,
                "by_subtype": [],
                "by_platform": [],
            }
        prepared = data.copy()
        for column in ("views", "likes", "comment", "reposted"):
            prepared[column] = pd.to_numeric(
                prepared.get(column), errors="coerce"
            ).fillna(0)

        def grouped(column: str) -> list[dict[str, Any]]:
            rows = []
            for label, group in prepared.groupby(column, dropna=False, sort=True):
                rows.append(
                    {
                        column: "未分类" if pd.isna(label) else str(label),
                        "post_count": int(len(group)),
                        "views": int(group["views"].sum()),
                    }
                )
            return rows

        return {
            "post_count": int(len(prepared)),
            "views": int(prepared["views"].sum()),
            "likes": int(prepared["likes"].sum()),
            "comments": int(prepared["comment"].sum()),
            "reposts": int(prepared["reposted"].sum()),
            "by_subtype": grouped("subtype"),
            "by_platform": grouped("source_platform"),
        }

    def get_creator_monthly_performance(
        self,
        query: str,
        period_month: str,
        include_cross_industry: bool,
    ) -> dict[str, Any]:
        record = self._resolve_creator(query)
        period = _validate_period(period_month)
        scoped = self._creator_posts(
            self._month_posts(period, include_cross_industry=include_cross_industry),
            record.id,
        )
        return {
            "status": "ok",
            "creator": {"creator_id": record.id, "koc_name": record.koc_name},
            "period_month": period,
            "include_cross_industry": include_cross_industry,
            "traffic_boost_enabled": self.dashboard_repository.get_traffic_boost_enabled(period),
            "performance": self._performance_summary(scoped),
        }

    def compare_creator_months(
        self,
        query: str,
        current_month: str,
        baseline_month: str,
        include_cross_industry: bool,
    ) -> dict[str, Any]:
        record = self._resolve_creator(query)
        current_period = _validate_period(current_month)
        baseline_period = _validate_period(baseline_month)
        current = self._performance_summary(
            self._creator_posts(
                self._month_posts(
                    current_period, include_cross_industry=include_cross_industry
                ),
                record.id,
            )
        )
        baseline = self._performance_summary(
            self._creator_posts(
                self._month_posts(
                    baseline_period, include_cross_industry=include_cross_industry
                ),
                record.id,
            )
        )

        def change(current_value: int, baseline_value: int) -> dict[str, Any]:
            return {
                "absolute": current_value - baseline_value,
                "rate": (
                    round((current_value - baseline_value) / baseline_value, 4)
                    if baseline_value
                    else None
                ),
                "decline_over_30_percent": bool(
                    baseline_value and current_value < baseline_value * 0.7
                ),
            }

        current_types = {row["subtype"]: row for row in current["by_subtype"]}
        baseline_types = {row["subtype"]: row for row in baseline["by_subtype"]}
        subtype_changes = []
        for subtype in sorted(set(current_types) | set(baseline_types)):
            current_row = current_types.get(subtype, {"post_count": 0, "views": 0})
            baseline_row = baseline_types.get(subtype, {"post_count": 0, "views": 0})
            subtype_changes.append(
                {
                    "subtype": subtype,
                    "post_count": change(
                        int(current_row["post_count"]), int(baseline_row["post_count"])
                    ),
                    "views": change(int(current_row["views"]), int(baseline_row["views"])),
                }
            )
        return {
            "status": "ok",
            "creator": {"creator_id": record.id, "koc_name": record.koc_name},
            "current_month": current_period,
            "baseline_month": baseline_period,
            "include_cross_industry": include_cross_industry,
            "current": current,
            "baseline": baseline,
            "overall_change": {
                "post_count": change(current["post_count"], baseline["post_count"]),
                "views": change(current["views"], baseline["views"]),
            },
            "subtype_changes": subtype_changes,
        }

    @staticmethod
    def _selected_version(versions: list[CompensationVersion]) -> CompensationVersion | None:
        if not versions:
            return None
        return next((item for item in versions if item.status == "LOCKED"), versions[0])

    @staticmethod
    def _version_creator_row(
        version: CompensationVersion,
        record: KOCRecord,
    ) -> dict[str, Any] | None:
        details = version.details
        if details.empty:
            return None
        masks: list[pd.Series] = []
        for column in ("creator_id", "记录ID"):
            if column in details:
                masks.append(pd.to_numeric(details[column], errors="coerce").eq(record.id))
        aliases = {
            record.koc_name.casefold(),
            record.user_id.casefold(),
            (record.youtube_user_id or "").casefold(),
            (record.tiktok_user_id or "").casefold(),
        }
        aliases.discard("")
        for column in ("达人", "koc_name", "UID", "user_id"):
            if column in details:
                masks.append(
                    details[column].astype("string").str.strip().str.casefold().isin(aliases)
                )
        if not masks:
            return None
        combined = masks[0].fillna(False)
        for mask in masks[1:]:
            combined = combined | mask.fillna(False)
        matches = details.loc[combined]
        return matches.iloc[0].to_dict() if not matches.empty else None

    def get_compensation_breakdown(
        self,
        query: str,
        period_month: str,
        settlement_type: str,
    ) -> dict[str, Any]:
        record = self._resolve_creator(query)
        period = _validate_period(period_month)
        loaders = {
            "grassroot": self.dashboard_repository.list_compensation_versions,
            "long_term": self.dashboard_repository.list_long_term_compensation_versions,
            "commentary": self.dashboard_repository.list_commentary_compensation_versions,
        }
        selected_types = list(loaders) if settlement_type == "auto" else [settlement_type]
        settlements = []
        for kind in selected_types:
            loader = loaders.get(kind)
            if loader is None:
                raise AIToolError("未知结算类型。")
            version = self._selected_version(loader(period))
            if version is None:
                continue
            row = self._version_creator_row(version, record)
            if row is None:
                continue
            settlements.append(
                {
                    "settlement_type": kind,
                    "version_id": version.id,
                    "version_no": version.version_no,
                    "status": version.status,
                    "jpy_to_usd_rate": version.jpy_to_usd_rate,
                    "locked_at": version.locked_at,
                    "note": version.note,
                    "details": row,
                }
            )
        return {
            "status": "ok" if settlements else "not_found",
            "creator": {"creator_id": record.id, "koc_name": record.koc_name},
            "period_month": period,
            "source": "persisted_compensation_versions_only",
            "settlements": settlements,
        }

    def get_top_videos(
        self,
        period_month: str,
        platform: str,
        creator_query: str | None,
        include_cross_industry: bool,
        limit: int,
    ) -> dict[str, Any]:
        period = _validate_period(period_month)
        scoped = self._month_posts(
            period, include_cross_industry=include_cross_industry
        )
        if platform != "all":
            scoped = scoped.loc[
                scoped["source_platform"].astype("string").str.casefold().eq(
                    platform.casefold()
                )
            ].copy()
        creator = None
        if creator_query and creator_query.strip():
            creator = self._resolve_creator(creator_query)
            scoped = self._creator_posts(scoped, creator.id)
        scoped["views"] = pd.to_numeric(scoped["views"], errors="coerce").fillna(0)
        capped = max(1, min(int(limit), 30))
        top = scoped.sort_values("views", ascending=False, kind="stable").head(capped)
        columns = [
            "creator_id",
            "koc_name",
            "source_platform",
            "subtype",
            "publish_date",
            "title",
            "url",
            "views",
            "original_views",
            "traffic_boost_views",
            "is_cross_industry",
        ]
        return {
            "status": "ok",
            "period_month": period,
            "platform": platform,
            "creator": (
                {"creator_id": creator.id, "koc_name": creator.koc_name}
                if creator
                else None
            ),
            "include_cross_industry": include_cross_industry,
            "traffic_boost_enabled": self.dashboard_repository.get_traffic_boost_enabled(period),
            "videos": top.reindex(columns=columns).to_dict("records"),
        }

    def audit_month_data(self, period_month: str) -> dict[str, Any]:
        period = _validate_period(period_month)
        raw = self.posts.copy()
        dates = pd.to_datetime(raw["publish_date"], errors="coerce")
        scoped = raw.loc[dates.dt.strftime("%Y-%m").eq(period)].copy()
        matched = scoped.get("matched", pd.Series(False, index=scoped.index))
        matched = matched.astype("boolean").fillna(False)
        creator_ids = pd.to_numeric(scoped.get("creator_id"), errors="coerce")
        urls = scoped.get("url", pd.Series("", index=scoped.index)).astype("string").str.strip()
        platform = scoped.get(
            "source_platform", pd.Series("", index=scoped.index)
        ).astype("string").str.casefold()
        duplicate_url_rows = int(
            pd.DataFrame({"platform": platform, "url": urls})
            .loc[urls.ne("")]
            .duplicated(keep=False)
            .sum()
        )
        cross_industry = scoped.get(
            "is_cross_industry", pd.Series(False, index=scoped.index)
        ).astype("boolean").fillna(False)
        batches = self.dashboard_repository.list_import_batches(limit=30)
        if not batches.empty and "数据月份" in batches:
            batches = batches.loc[
                batches["数据月份"].astype("string").str.contains(period, regex=False)
            ]
        unmatched = scoped.loc[~matched]
        return {
            "status": "ok",
            "period_month": period,
            "post_count": int(len(scoped)),
            "matched_post_count": int(matched.sum()),
            "unmatched_post_count": int((~matched).sum()),
            "matched_creator_count": int(creator_ids.dropna().nunique()),
            "missing_publish_date_count_all_data": int(dates.isna().sum()),
            "missing_url_count": int(urls.eq("").sum()),
            "duplicate_platform_url_rows": duplicate_url_rows,
            "cross_industry_post_count": int(cross_industry.sum()),
            "traffic_boost_enabled": self.dashboard_repository.get_traffic_boost_enabled(period),
            "unmatched_uids": sorted(
                set(unmatched.get("user_id", pd.Series(dtype="string")).dropna().astype(str))
            )[:30],
            "import_batches": batches.head(10).to_dict("records"),
        }

    def get_operational_summary(
        self,
        period_month: str,
        include_cross_industry: bool,
    ) -> dict[str, Any]:
        """Return one database-backed monthly operations snapshot for the Agent."""
        period = _validate_period(period_month)
        scoped = self._month_posts(
            period, include_cross_industry=include_cross_industry
        )
        summary = self._performance_summary(scoped)
        creator_ids = pd.to_numeric(
            scoped.get("creator_id", pd.Series(dtype="Int64")), errors="coerce"
        )
        creator_count = int(creator_ids.dropna().nunique())

        if scoped.empty:
            top_creators: list[dict[str, Any]] = []
        else:
            prepared = scoped.copy()
            prepared["views"] = pd.to_numeric(
                prepared.get("views"), errors="coerce"
            ).fillna(0)
            prepared["koc_name"] = prepared.get(
                "koc_name", pd.Series("", index=prepared.index)
            ).astype("string").fillna("")
            grouped = (
                prepared.groupby(["creator_id", "koc_name"], dropna=False)
                .agg(post_count=("creator_id", "size"), views=("views", "sum"))
                .reset_index()
                .sort_values(["views", "post_count"], ascending=False, kind="stable")
                .head(10)
            )
            top_creators = [
                {
                    "creator_id": (
                        int(row.creator_id)
                        if pd.notna(row.creator_id)
                        else None
                    ),
                    "koc_name": str(row.koc_name),
                    "post_count": int(row.post_count),
                    "views": int(row.views),
                }
                for row in grouped.itertuples(index=False)
            ]

        audit = self.audit_month_data(period)
        return {
            "status": "ok",
            "period_month": period,
            "include_cross_industry": include_cross_industry,
            "traffic_boost_enabled": self.dashboard_repository.get_traffic_boost_enabled(period),
            "creator_count": creator_count,
            "summary": summary,
            "top_creators_by_views": top_creators,
            "data_quality": {
                "unmatched_post_count": audit["unmatched_post_count"],
                "missing_url_count": audit["missing_url_count"],
                "duplicate_platform_url_rows": audit["duplicate_platform_url_rows"],
                "cross_industry_post_count": audit["cross_industry_post_count"],
            },
            "source": "database_tool_result",
        }
