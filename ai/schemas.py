from __future__ import annotations

from typing import Any


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


OPENAI_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_creators",
        "description": "按达人名、UID、合作类别或合同类型搜索达人库。",
        "parameters": _object_schema(
            {
                "search": {"type": ["string", "null"]},
                "creator_category": {
                    "type": ["string", "null"],
                    "enum": ["LONG_TERM", "COMMENTARY", "GRASSROOT", None],
                },
                "contract_type": {"type": ["string", "null"]},
                "active_only": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_creator_profile",
        "description": "读取单个达人的当前达人库资料、平台 UID、粉丝数和合同。",
        "parameters": _object_schema({"query": {"type": "string"}}),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_creator_contract_history",
        "description": "读取单个达人的合同周期和合同修订记录。",
        "parameters": _object_schema(
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_creator_monthly_performance",
        "description": "按月读取单个达人的投稿量、播放量和视频类型明细。",
        "parameters": _object_schema(
            {
                "query": {"type": "string"},
                "period_month": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                "include_cross_industry": {"type": "boolean"},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "compare_creator_months",
        "description": "比较单个达人两个月的投稿数和各视频类型播放量变化。",
        "parameters": _object_schema(
            {
                "query": {"type": "string"},
                "current_month": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                "baseline_month": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                "include_cross_industry": {"type": "boolean"},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_compensation_breakdown",
        "description": "读取已保存的草根、长包或解说结算版本，绝不重新计算。",
        "parameters": _object_schema(
            {
                "query": {"type": "string"},
                "period_month": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                "settlement_type": {
                    "type": "string",
                    "enum": ["auto", "grassroot", "long_term", "commentary"],
                },
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_top_videos",
        "description": "读取指定月份按播放量排序的视频，支持 YouTube、TikTok 或全部平台。",
        "parameters": _object_schema(
            {
                "period_month": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                "platform": {"type": "string", "enum": ["YouTube", "TikTok", "all"]},
                "creator_query": {"type": ["string", "null"]},
                "include_cross_industry": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "audit_month_data",
        "description": "审计指定月份的投稿、匹配、日期、URL、异业排除和导入批次情况。",
        "parameters": _object_schema(
            {"period_month": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"}}
        ),
        "strict": True,
    },
]
