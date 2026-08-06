from __future__ import annotations

import math
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from core.dashboard_processor import build_dashboard_result, enrich_dashboard_creator_metadata
from core.traffic_boost import apply_july_traffic_boost
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
    """Whitelisted read-only tools backed by existing repositories."""

    def __init__(self, database_path: Path | str) -> None:
        self.dashboard_repository = DashboardRepository(database_path)
        self.creator_repository = KOCRepository(database_path)
        self._records: list[KOCRecord] | None = None
        self._posts: pd.DataFrame | None = None
        self.handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "search_creators": self.search_creators,
            "get_creator_profile": self.get_creator_profile,
            "get_creator_contract_history": self.get_creator_contract_history,
            "get_creator_monthly_performance": self.get_creator_monthly_performance,
            "compare_creator_months": self.compare_creator_months,
            "get_compensation_breakdown": self.get_compensation_breakdown,
            "get_top_videos": self.get_top_videos,
            "audit_month_data": self.audit_month_data,
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

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = self.handlers.get(name)
        if handler is None:
            raise AIToolError(f"不允许调用工具：{name}", code="UNKNOWN_TOOL")
        return _json_value(handler(**arguments))

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
