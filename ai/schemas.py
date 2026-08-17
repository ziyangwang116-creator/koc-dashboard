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
        "name": "read_project_file",
        "description": "读取项目内允许访问的代码文件指定行号，供 Agent 分析后生成修改。",
        "parameters": _object_schema(
            {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            }
        ),
        "strict": True,
    },
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
    {
        "type": "function",
        "name": "get_operational_summary",
        "description": "Return a database-backed monthly operations summary including posts, views, platform/type breakdown, top creators, and data-quality counts. Do not invent values.",
        "parameters": _object_schema(
            {
                "period_month": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                "include_cross_industry": {"type": "boolean"},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "update_creator_profile",
        "description": "请求修改达人资料或平台粉丝数。该工具只生成待确认操作，用户确认后才写入数据库。合同类型变化必须使用 create_contract_change。",
        "parameters": _object_schema(
            {
                "query": {"type": "string"},
                "koc_name": {"type": ["string", "null"]},
                "homepage_url": {"type": ["string", "null"]},
                "youtube_homepage_url": {"type": ["string", "null"]},
                "tiktok_homepage_url": {"type": ["string", "null"]},
                "follower_count": {"type": ["integer", "null"], "minimum": 0},
                "youtube_follower_count": {"type": ["integer", "null"], "minimum": 0},
                "tiktok_follower_count": {"type": ["integer", "null"], "minimum": 0},
                "note": {"type": ["string", "null"]},
                "active": {"type": ["boolean", "null"]},
                "settlement_eligible": {"type": ["boolean", "null"]},
                "expected_updated_at": {"type": ["string", "null"]},
                "reason": {"type": ["string", "null"]},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "create_contract_change",
        "description": "请求新增达人合同周期变更。会保留历史快照，用户确认后才写入数据库。合同填写错误应使用现有达人库纠错流程，不要把纠错当成变更。",
        "parameters": _object_schema(
            {
                "query": {"type": "string"},
                "effective_date": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                "contract_types": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "contract_end_date": {"type": ["string", "null"], "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                "creator_category": {"type": ["string", "null"], "enum": ["LONG_TERM", "COMMENTARY", "GRASSROOT", None]},
                "reason": {"type": "string"},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "save_exchange_rate",
        "description": "请求保存指定月份日元兑美元汇率。用户确认后才写入数据库，并使该月份未锁定结算缓存失效。",
        "parameters": _object_schema(
            {
                "period_month": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                "jpy_to_usd_rate": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "modify_project_file",
        "description": "请求对项目内代码文件做一次受控文本替换。必须先读取文件；禁止密钥、数据库、数据目录和部署凭据。用户确认后才写入当前运行环境，不自动提交或部署。",
        "parameters": _object_schema(
            {
                "path": {"type": "string"},
                "old_text": {"type": "string", "minLength": 1},
                "new_text": {"type": "string"},
                "expected_sha256": {"type": ["string", "null"]},
                "max_replacements": {"type": "integer", "minimum": 1, "maximum": 10},
                "reason": {"type": "string"},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_git_status",
        "description": "读取当前项目 Git 分支和改动文件，不执行提交、推送或部署。",
        "parameters": _object_schema({}),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_follower_update_job",
        "description": "查询 Agent 发起的 YouTube/TikTok 批量粉丝更新任务进度和结果。",
        "parameters": _object_schema(
            {
                "job_id": {"type": "string"},
                "include_results": {"type": "boolean"},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "import_posts_from_preview",
        "description": "请求导入 Agent 页面已上传并预览的 Excel，可选择按月份完整替换或补充导入/更新，必须由用户确认后执行。",
        "parameters": _object_schema(
            {
                "preview_token": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["replace_months", "append_or_update"],
                },
                "reason": {"type": "string"},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "rollback_post_import",
        "description": "请求回滚一个可安全回滚的按月份完整替换投稿批次。必须提供原因并由用户确认。",
        "parameters": _object_schema(
            {
                "batch_id": {"type": "integer", "minimum": 1},
                "reason": {"type": "string", "minLength": 1},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "start_follower_batch_update",
        "description": "请求批量自动更新 YouTube、TikTok 或两个平台的达人粉丝数。YouTube 仅使用主页链接。用户确认后启动后台任务。",
        "parameters": _object_schema(
            {
                "platform": {"type": "string", "enum": ["YouTube", "TikTok", "both"]},
                "reason": {"type": "string"},
            }
        ),
        "strict": True,
    },
    {
        "type": "function",
        "name": "publish_project_changes",
        "description": "请求将明确列出的项目文件提交到 Git，可选择推送并触发部署。不会暂存未列出的文件，必须由用户确认。",
        "parameters": _object_schema(
            {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 50,
                },
                "commit_message": {"type": "string", "minLength": 5, "maxLength": 120},
                "push": {"type": "boolean"},
                "deploy": {"type": "boolean"},
            }
        ),
        "strict": True,
    },
]
