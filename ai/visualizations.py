from __future__ import annotations

import math
import re
from typing import Any


_SAFE_ID = re.compile(r"[^a-zA-Z0-9_-]+")
_SAFE_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_SUBTYPE_LABELS = {
    "long": "long",
    "shorts": "shorts",
    "livestream": "livestream",
}


def _number(value: Any, *, integer: bool = False) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return int(parsed) if integer else parsed


def _text(value: Any, *, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _safe_id(value: str) -> str:
    return _SAFE_ID.sub("-", value).strip("-")[:100] or "visualization"


def _change(current: int, baseline: int) -> dict[str, Any]:
    rate = (current - baseline) / baseline if baseline else None
    return {
        "change": current - baseline,
        "change_rate": round(rate, 6) if rate is not None else None,
        "decline_over_30_percent": bool(
            baseline and current < baseline * 0.7
        ),
    }


def _canonical_subtype(value: Any) -> str | None:
    normalized = _text(value, limit=40).casefold()
    if normalized in {"long", "long video", "长视频"}:
        return "long"
    if normalized in {"livestream", "live stream", "live", "直播"}:
        return "livestream"
    if normalized in {
        "short",
        "shorts",
        "short video",
        "ytb shorts",
        "tiktok",
        "短视频",
    }:
        return "shorts"
    return None


def _subtype_totals(rows: Any) -> dict[str, dict[str, int]]:
    totals = {
        subtype: {"post_count": 0, "views": 0}
        for subtype in _SUBTYPE_LABELS
    }
    if not isinstance(rows, list):
        return totals
    for row in rows:
        if not isinstance(row, dict):
            continue
        subtype = _canonical_subtype(row.get("subtype"))
        if subtype is None:
            continue
        totals[subtype]["post_count"] += int(_number(row.get("post_count"), integer=True) or 0)
        totals[subtype]["views"] += int(_number(row.get("views"), integer=True) or 0)
    return totals


def _warning(category: str, metric_label: str, rate: float | None) -> dict[str, str] | None:
    if rate is None or rate >= -0.3:
        return None
    return {
        "level": "danger",
        "message": f"{category}{metric_label}下降 {abs(rate):.1%}，超过 30% 警戒线。",
    }


def _chart(
    *,
    chart_id: str,
    title: str,
    baseline_month: str,
    current_month: str,
    value_format: str,
    rows: list[dict[str, Any]],
    creator: dict[str, Any],
    metric_label: str,
) -> dict[str, Any]:
    warnings = [
        item
        for row in rows
        if (
            item := _warning(
                str(row["category"]),
                metric_label,
                row.get("change_rate"),
            )
        )
    ]
    return {
        "schema_version": 1,
        "id": _safe_id(chart_id),
        "kind": "grouped_bar",
        "title": title,
        "subtitle": f"{baseline_month} vs {current_month}",
        "category_key": "category",
        "value_format": value_format,
        "series": [
            {"key": "baseline", "label": baseline_month, "color": "#64748b"},
            {"key": "current", "label": current_month, "color": "#0f9b9b"},
        ],
        "data": rows,
        "warnings": warnings,
        "source": {
            "tool": "compare_creator_months",
            "database_backed": True,
            "creator_id": _number(creator.get("creator_id"), integer=True),
            "creator_name": _text(creator.get("koc_name"), limit=80),
            "periods": [baseline_month, current_month],
        },
    }


def build_tool_visualizations(
    tool_name: str,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build charts only from trusted database tool results, never model text."""
    if tool_name != "compare_creator_months" or result.get("status") != "ok":
        return []

    current_month = _text(result.get("current_month"), limit=7)
    baseline_month = _text(result.get("baseline_month"), limit=7)
    creator = result.get("creator") if isinstance(result.get("creator"), dict) else {}
    creator_name = _text(creator.get("koc_name"), limit=80) or "达人"
    current = result.get("current") if isinstance(result.get("current"), dict) else {}
    baseline = result.get("baseline") if isinstance(result.get("baseline"), dict) else {}
    if not current_month or not baseline_month:
        return []

    total_post_current = int(_number(current.get("post_count"), integer=True) or 0)
    total_post_baseline = int(_number(baseline.get("post_count"), integer=True) or 0)
    total_views_current = int(_number(current.get("views"), integer=True) or 0)
    total_views_baseline = int(_number(baseline.get("views"), integer=True) or 0)

    post_row = {
        "category": "投稿数量",
        "baseline": total_post_baseline,
        "current": total_post_current,
        **_change(total_post_current, total_post_baseline),
    }
    views_row = {
        "category": "总播放量",
        "baseline": total_views_baseline,
        "current": total_views_current,
        **_change(total_views_current, total_views_baseline),
    }

    current_types = _subtype_totals(current.get("by_subtype"))
    baseline_types = _subtype_totals(baseline.get("by_subtype"))
    subtype_post_rows = []
    subtype_view_rows = []
    for subtype, label in _SUBTYPE_LABELS.items():
        current_posts = current_types[subtype]["post_count"]
        baseline_posts = baseline_types[subtype]["post_count"]
        current_views = current_types[subtype]["views"]
        baseline_views = baseline_types[subtype]["views"]
        subtype_post_rows.append(
            {
                "category": label,
                "baseline": baseline_posts,
                "current": current_posts,
                **_change(current_posts, baseline_posts),
            }
        )
        subtype_view_rows.append(
            {
                "category": label,
                "baseline": baseline_views,
                "current": current_views,
                **_change(current_views, baseline_views),
            }
        )

    prefix = f"creator-{creator.get('creator_id', 'unknown')}-{baseline_month}-{current_month}"
    return [
        _chart(
            chart_id=f"{prefix}-total-posts",
            title=f"{creator_name} 投稿数量对比",
            baseline_month=baseline_month,
            current_month=current_month,
            value_format="integer",
            rows=[post_row],
            creator=creator,
            metric_label="",
        ),
        _chart(
            chart_id=f"{prefix}-total-views",
            title=f"{creator_name} 总播放量对比",
            baseline_month=baseline_month,
            current_month=current_month,
            value_format="integer",
            rows=[views_row],
            creator=creator,
            metric_label="",
        ),
        _chart(
            chart_id=f"{prefix}-subtype-posts",
            title=f"{creator_name} 分类型投稿数量",
            baseline_month=baseline_month,
            current_month=current_month,
            value_format="integer",
            rows=subtype_post_rows,
            creator=creator,
            metric_label="投稿数",
        ),
        _chart(
            chart_id=f"{prefix}-subtype-views",
            title=f"{creator_name} 分类型播放量",
            baseline_month=baseline_month,
            current_month=current_month,
            value_format="integer",
            rows=subtype_view_rows,
            creator=creator,
            metric_label="播放量",
        ),
    ]


def sanitize_visualizations(value: Any) -> list[dict[str, Any]]:
    """Whitelist persisted visualization payloads before returning them to browsers."""
    if not isinstance(value, (list, tuple)):
        return []
    sanitized: list[dict[str, Any]] = []
    for raw_chart in list(value)[:8]:
        if not isinstance(raw_chart, dict) or raw_chart.get("kind") != "grouped_bar":
            continue
        series = []
        for raw_series in raw_chart.get("series", [])[:4]:
            if not isinstance(raw_series, dict):
                continue
            key = _text(raw_series.get("key"), limit=30)
            if key not in {"baseline", "current"}:
                continue
            series.append(
                {
                    "key": key,
                    "label": _text(raw_series.get("label"), limit=30),
                    "color": (
                        color
                        if _SAFE_COLOR.fullmatch(
                            color := _text(raw_series.get("color"), limit=20)
                        )
                        else ("#64748b" if key == "baseline" else "#0f9b9b")
                    ),
                }
            )
        data = []
        for raw_row in raw_chart.get("data", [])[:20]:
            if not isinstance(raw_row, dict):
                continue
            baseline = _number(raw_row.get("baseline"), integer=True)
            current = _number(raw_row.get("current"), integer=True)
            if baseline is None or current is None:
                continue
            calculated_change = _change(current, baseline)
            data.append(
                {
                    "category": _text(raw_row.get("category"), limit=60),
                    "baseline": baseline,
                    "current": current,
                    **calculated_change,
                }
            )
        source = raw_chart.get("source") if isinstance(raw_chart.get("source"), dict) else {}
        if source.get("tool") != "compare_creator_months" or not source.get("database_backed"):
            continue
        warnings = []
        for raw_warning in raw_chart.get("warnings", [])[:20]:
            if not isinstance(raw_warning, dict):
                continue
            warnings.append(
                {
                    "level": "danger",
                    "message": _text(raw_warning.get("message"), limit=180),
                }
            )
        if len(series) != 2 or not data:
            continue
        sanitized.append(
            {
                "schema_version": 1,
                "id": _safe_id(_text(raw_chart.get("id"), limit=100)),
                "kind": "grouped_bar",
                "title": _text(raw_chart.get("title"), limit=120),
                "subtitle": _text(raw_chart.get("subtitle"), limit=80),
                "category_key": "category",
                "value_format": "integer",
                "series": series,
                "data": data,
                "warnings": warnings,
                "source": {
                    "tool": "compare_creator_months",
                    "database_backed": True,
                    "creator_id": _number(source.get("creator_id"), integer=True),
                    "creator_name": _text(source.get("creator_name"), limit=80),
                    "periods": [
                        _text(item, limit=7)
                        for item in source.get("periods", [])[:2]
                    ],
                },
            }
        )
    return sanitized
