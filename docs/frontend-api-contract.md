# 前端 API 契约（第一阶段：只读）

本文档只定义契约，不引入任何代码、框架或依赖。字段名与业务规则均对齐现有
`core/`、`database/`、`services/` 中的真实实现，未来实现 FastAPI 层时应直接
复用这些模块，禁止重新定义/重新计算同名字段。

适用范围：本阶段仅开放只读接口。写接口（达人编辑、合同周期、Excel 导入、
粉丝更新、报酬保存）见文末「第二阶段」章节，本阶段不得实现。

---

## 0. 通用约定

### 0.1 认证方式

- 沿用现有 [ui/auth.py](../ui/auth.py) 的"团队共享密码"模型，登录后签发
  HttpOnly session cookie（详见第 9 节，含本地/生产环境差异）。
- 所有 `/api/*` 接口（除 `/api/health`、`/api/auth/login`）都要求携带该 cookie。

### 0.2 通用响应包裹

成功响应统一包裹：

```json
{
  "data": { ... } | [ ... ],
  "meta": { "request_id": "string" }
}
```

列表接口在 `meta` 中额外包含分页信息（见 0.4）。

### 0.3 错误响应格式（全局统一）

```json
{
  "error": {
    "code": "STRING_ERROR_CODE",
    "message": "面向用户的可读信息（中文）",
    "field_errors": [
      { "field": "字段名", "message": "该字段的具体问题" }
    ],
    "request_id": "string"
  }
}
```

`field_errors` 仅在 422 时出现，其余错误省略该字段（或返回空数组）。

| HTTP 状态 | code | 触发场景 |
|---|---|---|
| 401 | `UNAUTHENTICATED` | 未登录 / session cookie 缺失或已过期 |
| 403 | `FORBIDDEN` | 已登录但访问了本阶段未开放的写操作，或团队密码已被撤销 |
| 404 | `NOT_FOUND` | 路径中的资源 id（如 creator id）不存在 |
| 422 | `VALIDATION_ERROR` | 查询参数/请求体格式非法（如分页参数越界、日期格式错误、枚举值非法、周期参数互斥冲突） |
| 500 | `INTERNAL_ERROR` | 未预期的服务端异常（数据库连接失败等），`message` 固定为通用文案，不回传异常堆栈 |

### 0.4 分页规则（适用于所有列表接口）

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `page` | int | 1 | 从 1 开始 |
| `page_size` | int | 20 | 最大 100，超过按 422 处理 |

响应 `meta` 追加：

```json
"meta": {
  "request_id": "string",
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 137,
    "total_pages": 7
  }
}
```

### 0.5 排序规则

统一使用 `sort` 参数，格式为 `字段名` 或 `-字段名`（`-` 前缀表示降序）。
每个接口下方单独列出该接口允许的 `sort` 取值白名单；传入非白名单字段返回 422。

### 0.6 筛选与搜索规则

- 搜索统一使用 `q` 参数，语义等价于现有
  [database/koc_repository.py:1371](../database/koc_repository.py:1371) 中
  `search` 对 `user_id`/`koc_name` 的 `LIKE %q%` 模糊匹配。
- 多值筛选统一使用重复 query key，如
  `?creator_key=abc&creator_key=def`（对齐
  [database/koc_repository.py:1236](../database/koc_repository.py:1236) 的
  `contract_types: Iterable[...]` 语义）。

### 0.7 合同类型：禁止固定 enum

`contract_type` / `contract_types` **不是**固定枚举值。现有
[models/enums.py:13](../models/enums.py:13) 中的 `ContractType`（`YTB` /
`YTB_SHORTS` / `TT` / `APRIL_YTB` / `APRIL_TT` / `MAY_YTB` / `MAY_TT`）只是
历史上出现过的样例，运营会持续新增新的合同类型字符串（对齐
[database/koc_repository.py:2596](../database/koc_repository.py:2596)
`list_contract_type_options()` 直接从 `creator_contract` 表读取真实存在值，
而非从代码里的枚举读取）。

因此本契约中所有涉及 `contract_type` 的查询参数/返回字段，类型一律标注为
**string**（数据库中的原始字符串），前端必须通过下方 `GET
/api/meta/contract-types` 动态获取可选项列表，**不得在前端硬编码合同类型
选项**。

---

## 1. `GET /api/health`

无需认证。用于探活。

**请求参数**：无。

**返回**：

```json
{
  "data": {
    "status": "ok",
    "database": "postgres" | "sqlite"
  }
}
```

- `database` 字段对齐 [app.py:32](../app.py:32) 中
  `is_postgres_target(settings.database_path)` 的判定结果，仅暴露"是否为
  Postgres"这一布尔语义翻译，**不暴露连接串本身**。

**错误码**：仅 500（数据库不可达时）。

---

## 2. `POST /api/auth/login`

**请求参数（JSON body）**：

```json
{ "password": "string" }
```

**返回（200）**：

```json
{ "data": { "authenticated": true } }
```

同时通过 `Set-Cookie` 响应头下发 session cookie（见第 9 节），响应体本身不
包含 token。

**错误**：

| 状态 | code | 场景 |
|---|---|---|
| 401 | `INVALID_CREDENTIALS` | 密码不匹配，对齐 [ui/auth.py:35](../ui/auth.py:35) `password_matches()` 的比较逻辑（`hmac.compare_digest`，防时序攻击，后端实现必须沿用同样的常量时间比较） |
| 422 | `VALIDATION_ERROR` | `password` 缺失或为空字符串 |

**限流建议**（供实现参考，非本阶段强制）：同一 IP/来源连续失败次数超过阈值
后临时锁定，避免密码暴力破解——现有 Streamlit 版本无此限制，属于安全加固项。

---

## 3. `POST /api/auth/logout`

**请求参数**：无（依赖 cookie 识别当前 session）。

**返回（200）**：

```json
{ "data": { "authenticated": false } }
```

行为对齐 [ui/auth.py:88](../ui/auth.py:88) `render_logout()`：清除服务端
session 状态，并在响应中下发过期的 Set-Cookie 使浏览器端 cookie 失效。

**错误**：401（未登录时调用，视为幂等操作也可返回 200，两种设计均可接受，
建议返回 200 以简化前端逻辑）。

---

## 4. `GET /api/creators`

对齐 [database/koc_repository.py:1230](../database/koc_repository.py:1230)
`KOCRepository.list()`。

**查询参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `q` | string | 模糊搜索 `user_id` / `koc_name` |
| `creator_category` | enum | `LONG_TERM` \| `COMMENTARY` \| `GRASSROOT`（见 [models/enums.py:7](../models/enums.py:7)，此枚举是代码内固定分类，与合同类型不同，可以保留固定值） |
| `contract_type` | **string，可重复** | 数据库中真实存在的合同类型字符串，取值来自 `GET /api/meta/contract-types`，**不是固定 enum** |
| `follower_sync_status` | enum，可重复 | `NEVER` \| `SUCCESS` \| `FAILED` \| `MANUAL` |
| `follower_source` | enum，可重复 | `YOUTUBE_API` \| `TIKTOK_API` \| `TIKTOK_BROWSER` \| `MANUAL` |
| `settlement_eligible` | bool | 是否结算达标 |
| `active` | enum：`"all"` \| `"true"` \| `"false"` | **默认值为 `"all"`**：`"all"` 返回全部达人（启用+停用）；`"true"` 仅返回启用达人；`"false"` 仅返回停用达人。注意默认值与 [database/koc_repository.py:1230](../database/koc_repository.py:1230) `list()` 方法本身"未传参数时只查 active"的默认行为不同——API 层显式选择以 `"all"` 为默认，实现时需在调用 repository 前将 `"all"` 翻译为 `active=None, include_inactive=True`，不能直接透传参数缺省值 |
| `page`, `page_size` | int | 见 0.4 |
| `sort` | string | 允许值：`updated_at`, `-updated_at`, `koc_name`, `-koc_name`, `id`, `-id`（默认 `-updated_at`，对齐现有 `ORDER BY active DESC, updated_at DESC, id DESC`） |

**返回 `data`（数组，元素字段对齐 [models/koc.py:77](../models/koc.py:77)
`KOCRecord`）**：

```json
{
  "id": 1,
  "user_id": "string",
  "koc_name": "string",
  "creator_category": "LONG_TERM | COMMENTARY | GRASSROOT | null",
  "contract_types": ["string", "string"],
  "contract_start_date": "2026-01-01",
  "contract_end_date": "2026-12-31",
  "homepage_url": "string | null",
  "follower_count": 12000,
  "youtube_user_id": "string | null",
  "youtube_homepage_url": "string | null",
  "youtube_follower_count": 5000,
  "tiktok_user_id": "string | null",
  "tiktok_homepage_url": "string | null",
  "tiktok_follower_count": 7000,
  "follower_raw_display_value": "12.3万 | null",
  "follower_source": "YOUTUBE_API | TIKTOK_API | TIKTOK_BROWSER | MANUAL | null",
  "follower_count_is_estimated": false,
  "follower_count_updated_at": "2026-08-01T00:00:00",
  "follower_sync_status": "NEVER | SUCCESS | FAILED | MANUAL",
  "settlement_eligible": true,
  "active": true,
  "note": "string | null",
  "created_at": "2026-01-01T00:00:00",
  "updated_at": "2026-08-01T00:00:00"
}
```

`contract_types` 数组元素类型为 **string**（不是 enum），值来自
`creator_contract.contract_type` 原始数据。

字段 `follower_error_code`、`follower_sync_error`、`follower_source_url`、
`follower_profile_url` 属于运维排障字段，**列表接口不返回**，仅在详情接口
（第 5 节）中返回。

**错误**：401、422（非法枚举值 / `page_size` 超限）。

---

## 5. `GET /api/creators/{id}`

**路径参数**：`id`（int，对应 `koc_master.id`，即 [models/koc.py:78](../models/koc.py:78) `KOCRecord.id`）。

**返回 `data`**：第 4 节所有字段，另加：

```json
{
  "follower_error_code": "string | null",
  "follower_sync_error": "string | null",
  "follower_source_url": "string | null",
  "follower_profile_url": "string | null",
  "contract_periods": [
    {
      "id": 1,
      "effective_date": "2026-01-01",
      "creator_category": "LONG_TERM | null",
      "contract_types": ["string"],
      "contract_start_date": "2026-01-01",
      "contract_end_date": "2026-06-30",
      "created_at": "2026-01-01T00:00:00",
      "updated_at": "2026-01-01T00:00:00"
    }
  ]
}
```

- `contract_periods` 对齐
  [database/koc_repository.py:475](../database/koc_repository.py:475)
  `list_contract_periods()` 与
  [models/koc.py:45](../models/koc.py:45) `CreatorContractPeriod`。
- `contract_periods[].contract_types` 同样为 string 数组，不是固定 enum。

**错误**：401、404（`id` 不存在，对齐
[database/koc_repository.py:2063](../database/koc_repository.py:2063)
`get()` 返回 `None` 时）。

---

## 6. `GET /api/meta/contract-types`

**新增接口。** 返回数据库中当前真实存在的合同类型字符串，供前端筛选器/
下拉框动态渲染，**前端不得硬编码合同类型选项**。

对齐 [database/koc_repository.py:2596](../database/koc_repository.py:2596)
`KOCRepository.list_contract_type_options()`。

**请求参数**：无。

**返回 `data`**：

```json
{
  "contract_types": ["YTB", "TT", "YTB shorts", "..."]
}
```

- 顺序对齐 `list_contract_type_options()` 的返回顺序（按合同类型首次出现的
  `id` 升序，即"首次导入顺序"），前端下拉框应保持该顺序，不做本地重新排序，
  除非产品明确要求按字母序展示。

**错误**：401、500。

---

## 7. `GET /api/dashboard/filter-options`

**新增接口。** 返回当前看板数据中实际可用的筛选维度取值，供前端筛选器动态
渲染，**前端不得写死平台/内容类型/月份等选项**。

**请求参数**：无（返回全量可用选项，不做时间范围过滤；若数据量增长导致性能
问题，可在未来版本增加 `since` 参数做增量查询，本阶段不做该优化）。

**返回 `data`**：

```json
{
  "creators": [
    { "creator_key": "string", "creator_label": "string" }
  ],
  "creator_categories": ["LONG_TERM", "COMMENTARY", "GRASSROOT"],
  "source_platforms": ["YouTube", "TikTok"],
  "content_types": ["long", "livestream", "YTB shorts", "tiktok", "未标注"],
  "available_months": ["2026-06", "2026-07", "2026-08"],
  "available_weeks": [
    { "week_start": "2026-07-28", "week_end": "2026-08-03" }
  ]
}
```

- `creators`：对齐 `CREATOR_SUMMARY_COLUMNS` 中 `creator_key` /
  `creator_label`（[core/dashboard_processor.py:87](../core/dashboard_processor.py:87)）在当前投稿数据中出现过的去重列表。
- `content_types`：真实取值对齐
  [core/dashboard_processor.py:129](../core/dashboard_processor.py:129)
  `_content_type_series()` 的实际输出（`long` / `livestream` / `YTB shorts`
  / `tiktok` / `未标注`），**不是固定 enum**，未来若该函数逻辑变化，本接口
  返回值必须随之同步，前端只读取接口返回值。
- `available_weeks`：按投稿数据 `publish_date` 覆盖范围，以 ISO 周
  （周一至周日）切片列出确实存在数据的周区间，供 `period_mode=week` 时的
  下拉框使用。

**错误**：401、500。

---

## 8. Dashboard 系列接口的通用查询参数

`GET /api/dashboard/summary`、`GET /api/dashboard/posts` 的 query 参数，以及
`POST /api/dashboard/comparison` 的 JSON body 字段，共享以下通用规则（后者
以 body 字段形式表达同一套语义，见第 11 节）。

### 8.1 统计周期参数（三选一，互斥）

| `period_mode` | 必须同时提供 | 说明 |
|---|---|---|
| `month` | `period_month`（`YYYY-MM`） | 对齐现有按月看板逻辑 |
| `week` | `week_start`（`YYYY-MM-DD`，必须是周一） | 周区间为 `week_start` 起 7 天，值必须出现在 `GET /api/dashboard/filter-options` 返回的 `available_weeks` 中 |
| `custom` | `start_date` + `end_date`（均为 `YYYY-MM-DD`，`end_date >= start_date`） | 自定义区间 |

**互斥规则**：`period_mode` 必填；若请求中同时携带了非本模式所需的周期参数
（例如 `period_mode=month` 却同时传了 `week_start`），返回 422
`VALIDATION_ERROR`，`field_errors` 指出冲突字段。若 `period_mode` 对应的必需
参数缺失，同样返回 422。

### 8.2 通用筛选参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `creator_key` | string，可重复 | 限定达人，取值来自 `filter-options.creators[].creator_key` |
| `creator_category` | enum，可重复 | `LONG_TERM` \| `COMMENTARY` \| `GRASSROOT` |
| `source_platform` | string，可重复 | 取值来自 `filter-options.source_platforms` |
| `content_type` | string，可重复 | 取值来自 `filter-options.content_types`，**不是固定 enum** |
| `include_cross_industry` | bool，默认 `false` | `false` 时排除
  [core/cross_industry.py](../core/cross_industry.py) 判定为跨行业互斥的投稿
  （即 `is_cross_industry=true` 的记录），对齐现有报酬计算前置过滤口径；
  `true` 时返回全部投稿供审计对比用途 |
| `traffic_boost_mode` | enum，**默认 `saved_setting`** | 三个取值见下表，本参数只影响返回的 `views` 口径，**不会写入任何数据库设置**（见下方强约束） |

`traffic_boost_mode` 取值说明：

| 取值 | 含义 |
|---|---|
| `saved_setting`（默认） | 读取数据库中当前已保存的流量加成开关，对齐 [database/dashboard_repository.py:414](../database/dashboard_repository.py:414) `get_traffic_boost_enabled(period_month)`（存储于 `dashboard_traffic_boost_setting` 表）。开关为开时 `views = boosted_views`，为关时 `views = original_views`。**这是与当前 Streamlit 看板和实时结算口径保持一致的唯一取值**，前端默认展示必须使用该模式 |
| `original` | 忽略数据库开关，强制 `views = original_views` |
| `boosted_preview` | 忽略数据库开关，强制 `views = boosted_views`。**仅用于只读预览**（例如"如果开启加成会是什么样子"的对比视图），**不会保存、不会修改** `dashboard_traffic_boost_setting` 任何记录 |

**强约束**：第一阶段所有只读接口（包括本参数）**禁止**修改
`dashboard_traffic_boost_setting` 表。无论传入哪个 `traffic_boost_mode`，
接口都只是"选择用哪种口径渲染这次请求的返回结果"，不产生任何写操作。保存
每月流量加成开关（即调用
[database/dashboard_repository.py:427](../database/dashboard_repository.py:427)
`save_traffic_boost_enabled()`）属于第二阶段写接口，本阶段不实现、不暴露
对应的 POST/PUT 端点。

### 8.3 播放量字段口径（必须严格区分，前端不得自行计算加成）

四个原始/派生字段 + 一个"当前口径"字段：

| 字段 | 含义 | 来源 |
|---|---|---|
| `view` | 源文件原始播放量，未做任何清洗 | 原始导入数据的 `view` 列 |
| `original_views` | 标准化后的原始播放量（清洗、转整数、下限裁剪为 0） | 对齐 [core/traffic_boost.py:20](../core/traffic_boost.py:20) `_base_views()` |
| `traffic_boost_views` | 流量加成**增加的**播放量（即 `boosted_views - original_views`），非加成期间恒为 0 | 对齐 [core/traffic_boost.py](../core/traffic_boost.py) `JULY_TRAFFIC_BOOST_RATE = 0.05` 及 `july_traffic_boost_eligible()` 判定 |
| `boosted_views` | 加成后播放量（`original_views + traffic_boost_views`） | 同上 |
| `views` | **当前请求实际用于展示/统计的播放量**：`traffic_boost_mode=saved_setting`（默认）时按数据库已保存开关取 `original_views` 或 `boosted_views`；`traffic_boost_mode=original` 时固定等于 `original_views`；`traffic_boost_mode=boosted_preview` 时固定等于 `boosted_views`（仅预览，不落库） | 由请求参数 `traffic_boost_mode` 决定，服务端计算，前端只读取该字段用于图表/列表展示，禁止自行计算加成 |

**强约束**：前端渲染播放量相关图表/列表时，一律使用 `views` 字段，
**禁止**在前端用 `original_views * 1.05` 或任何形式自行重算加成——加成规则
（生效日期、比例、判定条件）属于 [core/traffic_boost.py](../core/traffic_boost.py)
的业务规则，未来可能变化或叠加新的限时规则，前端硬编码等于制造下一次对不上
账的风险点。

---

## 9. `GET /api/dashboard/summary`

对齐 [core/dashboard_processor.py](../core/dashboard_processor.py) 中
`CREATOR_SUMMARY_COLUMNS`（[core/dashboard_processor.py:87](../core/dashboard_processor.py:87)）。

**查询参数**：第 8.1、8.2 节通用参数，另加：

| 参数 | 类型 | 说明 |
|---|---|---|
| `q` | string，可选 | 按 `creator_label` / `user_id` 模糊搜索 |
| `page`, `page_size`, `sort` | 见 0.4/0.5；`sort` 允许值：`total_views`, `-total_views`, `engagement_rate`, `-engagement_rate`, `koc_name`, `-koc_name`（默认 `-total_views`） |

**返回 `data`（数组，每项对应一个 `creator_key`）**：

```json
{
  "creator_key": "string",
  "user_id": "string",
  "creator_label": "string",
  "creator_category": "LONG_TERM | COMMENTARY | GRASSROOT | null",
  "contract_types": ["string"],
  "follower_count": 12000,
  "source_platforms": ["YouTube", "TikTok"],
  "post_count": 24,
  "view": 950000,
  "original_views": 1000000,
  "traffic_boost_views": 50000,
  "boosted_views": 1050000,
  "total_views": 1000000,
  "average_views": 41666,
  "max_views": 200000,
  "total_likes": 5000,
  "total_comments": 300,
  "total_reposts": 120,
  "total_collects": 90,
  "total_interactions": 5510,
  "engagement_rate": 0.0055,
  "earliest_date": "2026-07-01",
  "latest_date": "2026-07-31"
}
```

- `total_views` 沿用 `CREATOR_SUMMARY_COLUMNS` 原字段名，其值口径与
  `views`（第 8.3 节）一致，即随 `traffic_boost_mode` 变化；本接口按聚合语义
  使用 `total_views` 而非 `views` 命名，避免与单条投稿字段混淆。

`source_files` 字段（存在于 `CREATOR_SUMMARY_COLUMNS`）属于导入批次追溯用途，
**不对前端暴露**，仅供内部审计。

**错误**：401、422（周期参数缺失/冲突、非法枚举值）。

---

## 10. `GET /api/dashboard/posts`

对齐 `DASHBOARD_DETAIL_COLUMNS`
（[core/dashboard_processor.py:20](../core/dashboard_processor.py:20)）。

**查询参数**：第 8.1、8.2 节通用参数，另加：

| 参数 | 类型 | 说明 |
|---|---|---|
| `q` | string，可选 | 按 `title` 模糊搜索 |
| `page`, `page_size`, `sort` | 见 0.4/0.5；`sort` 允许值：`publish_date`, `-publish_date`, `views`, `-views`（默认 `-publish_date`） |

**返回 `data`（数组）**：

```json
{
  "creator_key": "string",
  "user_id": "string",
  "koc_name": "string",
  "creator_category": "LONG_TERM | COMMENTARY | GRASSROOT | null",
  "contract_types": ["string"],
  "source_platform": "YouTube | TikTok",
  "content_type": "string",
  "subtype": "string",
  "title": "string",
  "url": "string",
  "publish_date": "2026-07-15",
  "view": 47500,
  "original_views": 50000,
  "traffic_boost_views": 2500,
  "boosted_views": 52500,
  "views": 52500,
  "likes": 2000,
  "comment": 100,
  "reposted": 30,
  "collect": 40,
  "matched": true,
  "profile_status": "MATCHED | UNMATCHED | HISTORY_MISSING",
  "is_cross_industry": false,
  "compensation_eligible": true,
  "cross_industry_reason": "string | null"
}
```

- `profile_status` 三个取值对齐
  [core/dashboard_processor.py:63](../core/dashboard_processor.py:63)
  `PROFILE_STATUS_MATCHED` / `PROFILE_STATUS_UNMATCHED` /
  `PROFILE_STATUS_HISTORY_MISSING`。
- 播放量五个字段定义与强约束见第 8.3 节，前端展示一律使用 `views`。

**错误**：401、422（周期参数缺失/冲突、`sort` 非白名单）。

---

## 11. `POST /api/dashboard/comparison`

用于跨周期对比视图，聚合自
[database/dashboard_repository.py](../database/dashboard_repository.py) 的
月度导入批次数据与 `summary` 同源的聚合逻辑，播放量口径同第 8.3 节。

本接口为**只读查询**，使用 `POST` 仅因为参数结构（`periods` 数组 + 多个可
重复筛选字段）无法用 GET query string 干净表达；不产生任何写操作，语义等
价于 `GET`（幂等、可安全重试），因此不落入第二阶段"写接口"范畴。

**请求 body（JSON）**：

```json
{
  "periods": [
    { "period_mode": "month", "period_month": "2026-06" },
    { "period_mode": "month", "period_month": "2026-07" }
  ],
  "dimension": "creator",
  "metric": "total_views",
  "creator_key": [],
  "creator_category": [],
  "source_platform": [],
  "content_type": [],
  "include_cross_industry": false,
  "traffic_boost_mode": "saved_setting"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `periods` | array，必填，至少 2 个元素 | 每个元素为 `{ "period_mode": "month\|week\|custom", ... }`，其余字段规则同第 8.1 节（`period_month` / `week_start` / `start_date`+`end_date`，与 `period_mode` 一一对应，三选一，同一元素内不得混用） |
| `dimension` | enum，必填 | `platform` \| `content_type` \| `creator_category` \| `creator`，见下方维度说明 |
| `metric` | enum，可选，默认 `total_views` | `total_views` \| `post_count` \| `engagement_rate` |
| `creator_key` | array\<string\>，可选，默认 `[]`（不筛选） | 同第 8.2 节，可重复 |
| `creator_category` | array\<string\>，可选，默认 `[]` | 同第 8.2 节，可重复 |
| `source_platform` | array\<string\>，可选，默认 `[]` | 同第 8.2 节，可重复 |
| `content_type` | array\<string\>，可选，默认 `[]` | 同第 8.2 节，可重复，取值动态（第 0.7 节） |
| `include_cross_industry` | bool，可选，默认 `false` | 同第 8.2 节 |
| `traffic_boost_mode` | enum，可选，默认 `"saved_setting"` | 取值与语义完全同第 8.2 节（`saved_setting` / `original` / `boosted_preview`），同样**不修改** `dashboard_traffic_boost_setting` |

**四种对比维度**：

- `dimension=platform`：按 `source_platform`（`YouTube` / `TikTok`）分组对比。
- `dimension=content_type`：按 `content_type`（取值见
  `filter-options.content_types`）分组对比。
- `dimension=creator_category`：按 `creator_category`（`LONG_TERM` /
  `COMMENTARY` / `GRASSROOT`）分组对比。
- `dimension=creator`：按单个达人对比，且**必须**在 `points` 中额外拆分出
  `long`（YTB 长视频/长包）、`livestream`（直播）、`shorts`（YTB shorts）、
  `tiktok`（TikTok 短视频）四个子维度各自的播放量与投稿数变化，取值对齐
  `content_type` 的真实字符串（第 7 节 `filter-options.content_types`）。

**返回 `data`**：

```json
{
  "dimension": "creator",
  "metric": "total_views",
  "series": [
    {
      "group_key": "string",
      "group_label": "string",
      "points": [
        { "period_label": "2026-06", "value": 800000, "post_count": 10 },
        { "period_label": "2026-07", "value": 1000000, "post_count": 12 }
      ],
      "change_rate": 0.25,
      "warning": false,
      "breakdown": {
        "long": {
          "points": [
            { "period_label": "2026-06", "value": 500000, "post_count": 4 },
            { "period_label": "2026-07", "value": 400000, "post_count": 3 }
          ],
          "change_rate": -0.2,
          "warning": false
        },
        "livestream": { "points": [], "change_rate": null, "warning": false },
        "shorts": { "points": [], "change_rate": null, "warning": false },
        "tiktok": { "points": [], "change_rate": null, "warning": false }
      }
    }
  ]
}
```

- `breakdown` 键固定为 `long` / `livestream` / `shorts` / `tiktok` 四个，
  仅在 `dimension=creator` 时返回；其余三种维度不返回 `breakdown` 字段。
- `change_rate` = `(最新期 value - 最早期 value) / 最早期 value`，最早期为 0
  时返回 `null`（避免除零，前端需处理该 `null`）。
- `warning`：当 `change_rate` 存在且 `change_rate <= -0.3`（即下降超过
  30%）时为 `true`，用于前端高亮预警；`change_rate` 为 `null` 时 `warning`
  固定为 `false`（无法判断升降，不误报预警）。`breakdown` 内每个子维度同样
  独立计算各自的 `warning`。

**错误**：401、422（`periods` 少于 2 个、单个 period 内部字段冲突/缺失、
`dimension` 或 `metric` 非白名单、body 非合法 JSON）。

---

## 12. `GET /api/dashboard/rankings`

**新增接口。** 支持多种榜单口径，聚合自
[core/dashboard_processor.py](../core/dashboard_processor.py) 的投稿明细，
播放量口径同第 8.3 节。

**查询参数**：第 8.1、8.2 节通用参数，另加：

| 参数 | 类型 | 说明 |
|---|---|---|
| `ranking_type` | enum，必填 | 见下表 |

| `ranking_type` | 含义 | 排名依据 | 榜单长度 | 额外筛选 |
|---|---|---|---|---|
| `creator_views_top10` | 达人播放量 Top 10 | 周期内 `total_views` 降序 | 10 | 无 |
| `creator_posts_top10` | 达人投稿数 Top 10 | 周期内 `post_count` 降序 | 10 | 无 |
| `creator_ytb_top30` | YTB 达人 Top 30 | `total_views` 降序 | 30 | 仅统计 `source_platform=YouTube` 的投稿数据 |
| `creator_tt_top30` | TT 达人 Top 30 | `total_views` 降序 | 30 | 仅统计 `source_platform=TikTok` 的投稿数据 |
| `video_ytb_top20` | YTB 视频播放量 Top 20 | 单条投稿 `views` 降序 | 20 | 仅 `source_platform=YouTube` |
| `video_tt_top20` | TT 视频播放量 Top 20 | 单条投稿 `views` 降序 | 20 | 仅 `source_platform=TikTok` |

**返回 `data`（`creator_*` 系列，元素字段同第 9 节 summary 精简版）**：

```json
{
  "ranking_type": "creator_views_top10",
  "items": [
    {
      "rank": 1,
      "creator_key": "string",
      "creator_label": "string",
      "creator_category": "LONG_TERM | COMMENTARY | GRASSROOT | null",
      "total_views": 1000000,
      "post_count": 12
    }
  ]
}
```

**返回 `data`（`video_*` 系列，元素字段同第 10 节 posts 精简版）**：

```json
{
  "ranking_type": "video_ytb_top20",
  "items": [
    {
      "rank": 1,
      "creator_key": "string",
      "creator_label": "string",
      "title": "string",
      "url": "string",
      "publish_date": "2026-07-15",
      "views": 500000
    }
  ]
}
```

榜单接口不分页（长度固定为对应 `ranking_type` 的榜单长度，若实际数据不足则
返回不足该长度的数组，不补空）。

**错误**：401、422（`ranking_type` 非白名单、周期参数缺失/冲突）。

---

## 13. `GET /api/dashboard/import-batches`

**新增接口。** 返回月度完整导入批次记录及"按月替换"造成的覆盖历史，供审计
追溯，对齐
[database/dashboard_repository.py:354](../database/dashboard_repository.py:354)
`list_import_batches()`。

**查询参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `limit` | int，可选，默认 30 | 对齐 `list_import_batches(limit=30)` 的默认值；最大 200，超过按 422 处理 |

**返回 `data`（数组，按批次 id 降序，即最新的在前）**：

```json
{
  "batch_id": 1,
  "mode": "REPLACE_MONTHS | APPEND_OR_UPDATE",
  "period_months": ["2026-07"],
  "source_files": ["7月投稿数据.xlsx"],
  "input_count": 320,
  "saved_count": 300,
  "removed_count": 20,
  "created_at": "2026-08-01T09:00:00"
}
```

- `mode` 两个取值对齐 `dashboard_import_batch.mode` 原始存储值
  `REPLACE_MONTHS`（按月份完整替换，会产生 `removed_count > 0`）与
  `APPEND_OR_UPDATE`（追加/更新，不删除已有记录）。
- `removed_count` 特指"按月份替换"模式下被覆盖移除的旧记录条数，是审计该
  批次是否发生过数据覆盖的关键字段，前端应在 UI 中对 `removed_count > 0` 的
  批次做明显标注。

**错误**：401、422（`limit` 超限）。

---

## 14. Session / Cookie 方案

1. 登录成功后，后端生成一个随机 session id（不是团队密码本身、不是 JWT
   编码的密码），存储于服务端 session store（阶段一可用内存或 Redis，字典
   结构：`session_id -> {issued_at, expires_at}`）。
2. Cookie 属性按部署环境区分，**不是固定写死**：

   | 属性 | 本地开发 | 生产环境 |
   |---|---|---|
   | `HttpOnly` | `true` | `true`（两者都必须开启，禁止 JS 读取，防 XSS 窃取） |
   | `Secure` | `false`（本地通常是 `http://localhost`，强制 `Secure` 会导致浏览器拒绝写入 cookie） | `true`（必须仅 HTTPS 传输） |
   | `SameSite` | `Lax`（前后端同源/同站点开发时足够） | 同站点部署（推荐，见下）用 `Lax`；若前后端跨站点部署，必须改为 `None`（且此时 `Secure` 必须为 `true`，否则浏览器拒绝该 cookie） |
   | `Max-Age` | `28800`（8 小时） | `28800`（8 小时），与团队协作的一个工作日时长对齐 |

   示例（生产环境、同站点部署）：

   ```
   Set-Cookie: koc_session=<random_session_id>;
     HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=28800
   ```

3. `POST /api/auth/logout` 或过期时，服务端删除对应 session 记录，并下发
   `Set-Cookie: koc_session=; Max-Age=0` 使浏览器端立即失效。
4. 由于是"团队共享一个密码"而非"每用户一个账号"（对齐
   [ui/auth.py:43](../ui/auth.py:43) `require_team_authentication()`
   的现状），本阶段 session 中不携带用户身份信息，仅代表"已通过团队密码
   验证"这一布尔状态；如未来需要审计到人，需先在业务上引入多用户账号体系，
   不在本阶段契约范围内。

### 14.1 部署拓扑与 CORS

**优先方案（推荐）：同站点反向代理。** 将 Next.js 与 FastAPI 部署在同一个
站点下，前端通过 `/api/*` 路径经反向代理（Nginx / Next.js rewrites /
Vercel/自建网关）转发到后端服务，浏览器视角下前后端同源。此时：

- Cookie 用 `SameSite=Lax` 即可，无需 CORS 配置，无需 `credentials:
  include`（同源请求自动带 cookie）。
- 这是默认推荐路径，能规避跨站 cookie 的一整类问题，优先采用。

**备选方案：前后端不同站点（跨域）部署。** 若因基础设施限制无法做到同站点，
则必须同时满足以下三项，缺一不可：

1. 后端 CORS 配置：
   - `Access-Control-Allow-Origin` 精确指定前端域名（不能用 `*`，因为要
     配合 credentials）。
   - `Access-Control-Allow-Credentials: true`。
2. 前端所有请求必须显式带上 `credentials: 'include'`（或等价的
   `withCredentials: true`），否则浏览器不会附带 cookie。
3. Cookie 必须设置 `SameSite=None; Secure`（`None` 允许跨站携带，但浏览器
   强制要求同时有 `Secure`，纯 HTTP 环境下无法使用跨站 cookie 方案）。

跨域方案的运维与安全成本显著高于同站点反向代理（需要额外维护 CORS 白名单、
更容易受 CSRF 影响、本地开发与生产环境行为不一致），**没有明确基础设施
限制时应优先选择同站点反向代理方案**。

---

## 15. 前端缓存策略

| 接口 | 可缓存 | 缓存建议 | 失效时机 |
|---|---|---|---|
| `GET /api/health` | 否 | 每次请求实时探活 | — |
| `GET /api/meta/contract-types` | 是 | 5 分钟 | "达人编辑"/"合同周期"写接口（第二阶段）成功后失效 |
| `GET /api/dashboard/filter-options` | 是 | 5 分钟 | "Excel 导入"写接口成功后失效 |
| `GET /api/creators` | 是 | 60 秒 stale-while-revalidate | 任意"达人编辑"写接口（第二阶段）成功后立即失效该列表相关缓存 |
| `GET /api/creators/{id}` | 是 | 60 秒 | 对应 `id` 的"达人编辑"/"合同周期"写接口成功后失效 |
| `GET /api/dashboard/summary` | 是 | 按周期缓存 5 分钟；覆盖"当前进行中周期"（当月/当周）的请求缩短为 60 秒（因为数据可能仍在导入中） | "Excel 导入"写接口成功后，失效该周期对应缓存 |
| `GET /api/dashboard/posts` | 是 | 同 `summary`：历史周期 5 分钟，当前进行中周期 60 秒 | 同上，按周期精确失效 |
| `POST /api/dashboard/comparison` | 是（按 body 内容做 key，含 `periods`/筛选/`traffic_boost_mode`） | 5 分钟（多为历史周期对比，变化频率低） | 任一涉及周期的数据被"Excel 导入"或"报酬保存"覆盖后失效；若 `traffic_boost_mode=saved_setting`，还需在"保存流量加成开关"（第二阶段）成功后失效 |
| `GET /api/dashboard/rankings` | 是 | 同 `summary`：历史周期 5 分钟，当前进行中周期 60 秒 | 同上 |
| `GET /api/dashboard/import-batches` | 否（或 10 秒极短缓存） | 该接口本身就是"最新导入了什么"的审计入口，不宜久缓存 | 任意"Excel 导入"写接口成功后立即失效 |

原则：只要某接口的数据来源存在对应的写接口（第二阶段），该接口就不能设置
"永不过期"的强缓存，必须绑定到具体写操作的成功回调上做主动失效
（cache invalidation by mutation），而不是单纯依赖 TTL 兜底。

---

## 16. 前端不可接触的敏感信息

前端（Next.js 侧）在任何情况下都不得获取、缓存、打印或经由网络暴露以下内容：

- `DATABASE_URL`（Supabase/Postgres 连接串，含用户名密码），当前仅存在于
  `.env` 与运行时环境变量，经 [config/settings.py:136](../config/settings.py:136)
  加载，**不得**通过任何 API 响应字段回传，包括 `/api/health` 也只返回
  `"postgres" | "sqlite"` 的布尔翻译，不返回主机名/端口/库名。
- Supabase 项目密码 / API Key / Service Role Key（若未来引入 Supabase 客户端
  SDK，也只能在服务端使用，不得下发到浏览器端）。
- AI Key（`DEEPSEEK_API_KEY` / `OPENAI_API_KEY`，见
  [config/settings.py:141](../config/settings.py:141)、
  [config/settings.py:148](../config/settings.py:148)），AI 相关接口未来
  只能由后端代理调用大模型，前端只能拿到问答结果，不得拿到 key 本身。
- 团队密码明文（`TEAM_PASSWORD`）本身不通过任何响应回传，登录接口只返回
  `authenticated: true/false`。

任何新增接口在设计返回字段时，都必须先检查是否间接泄露上述内容（例如错误
信息的堆栈、健康检查的详细连接信息等），若不确定应默认不返回。

---

## 17. 第二阶段才允许新增的写接口（本阶段禁止实现）

以下操作在本阶段**只做契约占位说明，不设计具体字段，不实现**：

1. **达人编辑**：对应 [database/koc_repository.py:2289](../database/koc_repository.py:2289)
   `update()` / [database/koc_repository.py:2095](../database/koc_repository.py:2095)
   `create()` / [database/koc_repository.py:2580](../database/koc_repository.py:2580)
   `set_active()`。
2. **合同周期**：对应 `create_contract_change`
   （[database/koc_repository.py:760](../database/koc_repository.py:760)）、
   `correct_contract_period`
   （[database/koc_repository.py:876](../database/koc_repository.py:876)）、
   `delete_authoritative_contract_period`
   （[database/koc_repository.py:970](../database/koc_repository.py:970)）、
   `revert_contract_revision`
   （[database/koc_repository.py:621](../database/koc_repository.py:621)）。
3. **Excel 导入**：对应 [ui/data_processing.py](../ui/data_processing.py) 与
   [core/multi_file_processor.py](../core/multi_file_processor.py) 的批量导入
   流程，以及 [database/dashboard_repository.py:279](../database/dashboard_repository.py:279)
   `save_monthly_import()`。
4. **粉丝更新**：对应 [services/follower_service.py](../services/follower_service.py)
   编排的 TikTok/YouTube 抓取，以及
   [database/koc_repository.py:2660](../database/koc_repository.py:2660)
   `apply_follower_success()` / `apply_follower_failure()`。
5. **报酬保存**：对应 `create_compensation_draft` /
   `update_compensation_draft` / `lock_compensation_version`
   （[database/dashboard_repository.py:667](../database/dashboard_repository.py:667)
   起）及其长期合同、解说两套并行版本
   （`create_long_term_compensation_draft`、
   `create_commentary_compensation_draft`）。
6. **保存流量加成开关**：对应
   [database/dashboard_repository.py:427](../database/dashboard_repository.py:427)
   `save_traffic_boost_enabled(period_month, enabled)`，写入
   `dashboard_traffic_boost_setting` 表。第一阶段所有接口的
   `traffic_boost_mode`（`saved_setting` / `original` / `boosted_preview`，
   见第 8.2 节、第 11 节）**只读取**该表，任何取值都不得触发写入；按月开启/
   关闭流量加成必须等本条写接口在第二阶段单独设计、验证后才能实现。

这六类写接口必须等第一阶段只读接口在生产环境验证数据一致性后，才能单独立项
设计契约，且每一类都要求与 [core/grassroot_compensation.py](../core/grassroot_compensation.py)、
[core/commentary_compensation.py](../core/commentary_compensation.py)、
[core/long_term_compensation.py](../core/long_term_compensation.py) 中的阶梯
计算规则做逐字段回归比对后再上线。

---

## 18. 报酬结算只读 API（第一阶段严格只读）

本章新增草根 / 长包 / 解说三条赛道的月度结算**只读**接口，以及月份枚举、历史
版本、指定主题申报的只读查询。所有接口均遵循第 0 章通用约定与第 14 章 Session
方案，且**严格只读**：不写入任何表，不触发任何结算保存 / 锁定 / 汇率保存 /
流量加成开关（这些属于第 17 章第二阶段写接口）。

### 18.0 贯穿全章的强制规则

1. **禁止在 API 层重算阶梯。** 所有结算数字必须由现有 core 函数产出，API 层
   只做序列化与筛选、分页、排序：
   - 草根：[core/grassroot_compensation.py:1104](../core/grassroot_compensation.py:1104)
     `calculate_grassroot_compensation()`（**当前函数**，按投稿逐条解析生效合同
     版本并做合同期内过滤；不得调用其 `_legacy_*` 版本）。
   - 长包：[core/long_term_compensation.py:358](../core/long_term_compensation.py:358)
     `calculate_long_term_compensation()`。
   - 解说：[core/commentary_compensation.py:479](../core/commentary_compensation.py:479)
     `calculate_commentary_compensation()`。

2. **`mode` 必须是三态，不是二元的“预览/冻结”。** 每个明细接口用 `version_id`
   查询参数区分，返回的 `meta.mode` 取以下三值之一：
   - **不传 `version_id` → `mode: "preview"`（当前预览）**：实时调用上述 core
     函数，输入=达人库当前状态 + 看板当前投稿 + 当月已保存汇率/活动数/流量加成
     开关/指定主题申报。预览会随达人库和看板数据变化。
   - **传 `version_id` 且该版本 `status == "DRAFT"` → `mode: "saved_draft"`
     （已保存草稿）**：直接反序列化该版本保存时的 `details`/`summary` 快照，
     **不重算**；但该版本在写侧（第二阶段接口，本章不实现）仍可被覆盖/重新
     生成，因此不是最终定稿。
   - **传 `version_id` 且该版本 `status == "LOCKED"` → `mode: "frozen"`
     （已锁定/官方定稿）**：同样读取保存时的 `details`/`summary` 快照、**不重算**，
     且该版本已锁定、不可再被写侧覆盖，代表最终结算结果。
   - `saved_draft` 与 `frozen` 在“读取快照、不重算”这一点上完全相同，唯一区别
     是版本本身是否已锁定（对应 `status` 字段）；两者读取的都是保存当时的合同、
     粉丝数、投稿、播放量、汇率、流量加成与异业状态，**不随当前达人库变化**
     （对齐 [ui/compensation.py:543](../ui/compensation.py:543)
     `_result_from_version()` 的行为——版本只回放 `version.details`，不再调用
     core）。

3. **预览按“结算月份对应的有效合同周期”计算，绝不简单读取达人最新合同。**
   这一点由 core 当前函数保证，API 不得绕过：
   - 草根 `calculate_grassroot_compensation` 通过 `_profile_creators_from_dashboard`
     按合同期建立每个结算单元，并用 `_within_contract_period` 仅保留发布日期落在
     `[contract_start_date, contract_end_date]` 内的投稿；投稿存在但都不在合同期内
     → `结算状态 = 合同期限外`。
   - 长包/解说通过“月末生效档案快照”（`_profile_at_month_end` / 逐条
     `_row_within_contract`）取结算月生效的合同、粉丝、类别，而非最新快照。
   - 因此 API **必须把结算月份（`period_month`）透传给 core**，由 core 解析生效
     合同，API 不得自行按“最新合同”组织数据。
   - **预览（`mode: "preview"`）不得传入
     [dashboard_repository.py:541](../database/dashboard_repository.py:541)
     `get_grassroot_contract_snapshots()` 返回的 `contract_type_snapshots`
     覆盖参数**，让 `calculate_grassroot_compensation` 按 `period_month` +
     投稿发布日期自行解析生效合同（与 UI 现状一致）。
   - **`saved_draft`/`frozen` 不重新解析合同**：直接读取该版本 `details` 快照中
     已经落盘的合同字段，不调用任何合同解析函数。

4. **三赛道严格按达人库合作类别筛选，互不混入。** 与
   [ui/compensation.py:89](../ui/compensation.py:89) 一致，草根只取
   `CreatorCategory.GRASSROOT`、长包只取 `LONG_TERM`、解说只取 `COMMENTARY`
   的达人库记录，作为对应 core 函数的 `creator_records` 输入。跨赛道（异业外的
   “非合同赛道活动”）逻辑仅存在于草根内部（`跨赛道*` 字段），不是把长包/解说
   的达人混进草根。

5. **流量加成与异业排除必须与现有结算逻辑一致，API 不得自定义口径。**
   - 异业：三条赛道的 core 入口都先调用
     [core/cross_industry.py:199](../core/cross_industry.py:199)
     `exclude_cross_industry_posts()` 丢弃 `is_cross_industry` 命中的投稿，异业
     投稿不进入任何结算金额。
   - 流量加成：仅草根与长包支持，且只在 7 月窗口有效——预览时是否加成 =
     `is_july_traffic_boost_month(月)` 且
     [database/dashboard_repository.py:414](../database/dashboard_repository.py:414)
     `get_traffic_boost_enabled(period_month)` 为真；其它月份恒为 `False`。CPM 的
     分母始终使用**无加成**原始播放量（列 `CPM计算播放量（无加成）`）。解说
     结算不涉及流量加成参数。
   - `traffic_boost_mode` 请求参数（见第 8.2 节）在本章**不适用**：结算预览严格
     使用“当月已保存的流量加成开关”这一唯一口径，API 只读该开关、不接受前端切换、
     更不写入。
   - **长包“每月活动数”同理只读**：预览严格使用
     [database/dashboard_repository.py:461](../database/dashboard_repository.py:461)
     `get_long_term_activity_counts(period_month)` 的持久化值作为 `event_counts`
     传给 core，**本阶段只读接口不接受前端传入临时活动数**（写入活动数属于
     第二阶段范围）。

6. **币种、服务费、手续费、舍入——所有金额字段的统一口径。** 基准币种为**日元
   （JPY）**；美元字段由汇率 `jpy_to_usd_rate` 派生。常量见
   [core/grassroot_compensation.py:17](../core/grassroot_compensation.py:17)
   （`USD_HANDLING_FEE = 15.0` 美元、`SERVICE_FEE_MULTIPLIER = 1.15`），长包与
   解说均 `import` 复用同一常量。派生关系：

   ```
   creator_usd = 总金额_jpy * jpy_to_usd_rate + 15.0        # 博主应收（美元）：含 15$ 手续费，不含服务费
   youdao_usd  = creator_usd * 1.15                          # 有道应收（美元）（包含服务费）
   creator_jpy = int(round(creator_usd / jpy_to_usd_rate))   # 博主应收（日元）(包含15$手续费)
   youdao_jpy  = int(round(youdao_usd  / jpy_to_usd_rate))   # 有道应收（日元）（包含服务费）
   CPM         = youdao_usd / 无加成播放量 * 1000            # 播放量为 0 时为 null
   ```

   **未达标（金额为 0）特例（强制）**：当 `总金额（日元）`/结算基准金额为 `0`
   （例如 `结算状态 = 未达标`）时，**不叠加 15$ 手续费、不乘以 1.15 服务费**——
   `creator_receivable_jpy`/`youdao_receivable_jpy`/`creator_receivable_usd`/
   `youdao_receivable_usd` 全部为 `0`（对齐三个 core 模块各自的
   “金额为 0 → 应收全 0”分支，例如
   [core/long_term_compensation.py](../core/long_term_compensation.py)
   的 `_no_payment_row` 与
   [core/commentary_compensation.py:586](../core/commentary_compensation.py:586)
   的 `else: creator_usd = youdao_usd = 0.0` 分支）。API 层不得在 0 基数上自行
   叠加手续费/服务费。`CPM` 仍按 core 原样输出（播放量为 0 时为 `null`）。

   **舍入与展示分工**：API **只透传 core 的原始未舍入数值**，不在 API 层做二次
   舍入/格式化。前端渲染时对 USD 与 CPM 保留 2 位小数、JPY 取整显示；任何汇总/
   求和计算必须使用**原始未格式化的数值**参与运算，禁止用前端已格式化（四舍五入）
   后的数字重新相加。

   | 口径 | 规则 |
   |---|---|
   | 基准币种 | 阶梯奖励表、投稿数奖励、`总金额（日元）`/`解说含税总额（日元）` 均为 **JPY** |
   | 美元字段 | `博主应收（美元）`、`有道应收（美元）（包含服务费）` 由汇率派生 |
   | 手续费（15$） | 只加在“博主应收”侧（字段名含 `包含15$手续费`），美元/日元两版都含 |
   | 服务费（×1.15） | 只加在“有道应收”侧（字段名含 `包含服务费`）；博主应收**不含**服务费 |
   | 舍入 | 两个“应收（日元）”用 `int(round(...))`（Python 四舍五入后取整）；**美元金额与 CPM 为未舍入 float**；聚合汇总为 `int()/float()` 求和 |
   | 无 CNY/RMB | 现有 core 中不存在任何人民币字段，API 不得臆造 |

   所有金额字段在响应里必须**自带币种与含费标注**（见各接口字段表的“含义/含费”
   列），前端不得二次乘汇率或二次加服务费。

7. **认证与只读。** 所有接口要求有效 `koc_session` cookie（第 0.1、第 14 章），
   未登录/过期 → `401 UNAUTHENTICATED`。本阶段这些接口**只读**，不接受任何写
   语义参数。

8. **敏感信息（第 16 章）在本章同样适用**：不回传 `DATABASE_URL`、团队密码、
   AI Key；`500 INTERNAL_ERROR` 只返回通用文案，绝不回传数据库异常/堆栈/SQL。

### 18.0.1 统一错误码

沿用第 0.3 节格式，本章可能出现：

| HTTP | `code` | 触发场景 |
|---|---|---|
| 401 | `UNAUTHENTICATED` | 缺失/过期 session cookie |
| 404 | `NOT_FOUND` | `version_id` 在该 `period_month`+`category` 下不存在 |
| 422 | `VALIDATION_ERROR` | `period_month` 非 `YYYY-MM`；`category` 非法；`page_size` 超限；**预览模式**下当月汇率未保存（见下） |
| 500 | `INTERNAL_ERROR` | 服务端异常，仅返回通用文案 |

- **当月汇率未保存（仅影响预览，定案）**：`mode: "preview"` 依赖
  [database/dashboard_repository.py:386](../database/dashboard_repository.py:386)
  `get_jpy_to_usd_rate(period_month)`；若返回 `None`，core 无法计算美元/应收。
  **本接口必须返回 `422 VALIDATION_ERROR`**，`field_errors` 内含
  `{"jpy_to_usd_rate": "该月尚未保存 JPY→USD 汇率"}`，**不得返回 `200` 且金额
  字段缺失/为 `null`**。`saved_draft`/`frozen` 读取的是版本保存时落盘的汇率与
  金额快照，**不受当前月份是否已保存汇率影响**，不会触发本错误。

### 18.0.2 分页与排序

- **明细类接口**（`grassroot` / `long-term` / `commentary`）为列表，套用第 0.4 节
  分页（`page` 默认 1，`page_size` 默认 20、上限 100）与第 0.5 节排序
  （`sort=field` / `sort=-field`，各接口给出白名单）。默认排序统一为
  `-total_amount_jpy`（金额降序），金额相同再按 `creator_key` 升序稳定排序。
  支持第 0.6 节 `q`（匹配 `creator_key` / `creator_name`）与 `settlement_status`
  精确筛选（可重复多值）。
- **枚举类接口**（`periods` / `versions` / `theme-submissions`）数据量小，本阶段
  **定案不分页**、按固定顺序返回（`periods` 按月份降序；`versions` 按
  `version_no` 降序，对齐 DB `ORDER BY version_no DESC`；`theme-submissions`
  已按 `period_month` 限定范围，按 `creator_id, theme_code` 升序，对齐 DB
  查询）。团队现有数据量下无需分页。

---

### 18.1 `GET /api/compensation/periods`

返回“存在结算数据或投稿数据”的可选结算月份，供前端月份下拉框使用。

**查询参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `category` | string，可选 | `GRASSROOT` / `LONG_TERM` / `COMMENTARY`；传入后只返回该赛道相关月份，省略则返回全部 |

**数据来源**：
- 有投稿的月份：**必须**取投稿实际 `publish_date` 归月去重（对齐
  [ui/compensation.py:51](../ui/compensation.py:51) `_settlement_month_options()`）。
  **不得**使用文件名或 `dashboard_import_batch` 声明的导入周期月份替代投稿实际
  发布日期——若投稿发布月与导入声明月不一致，一律以投稿 `publish_date` 归月
  为准（此为定案，替代原 18.7 第 1 项待确认内容）。
- 有结算版本的月份：三张
  `grassroot_compensation_version` / `long_term_compensation_version` /
  `commentary_compensation_version` 表中出现过的 `period_month`。

**返回 `data`（数组，按 `period_month` 降序）**：

```json
{
  "data": [
    {
      "period_month": "2026-07",
      "has_posts": true,
      "traffic_boost_applicable": true,
      "traffic_boost_enabled": true,
      "versions": {
        "grassroot": {"count": 2, "has_locked": true},
        "long_term": {"count": 1, "has_locked": false},
        "commentary": {"count": 0, "has_locked": false}
      }
    },
    {
      "period_month": "2026-06",
      "has_posts": true,
      "traffic_boost_applicable": false,
      "traffic_boost_enabled": false,
      "versions": {
        "grassroot": {"count": 1, "has_locked": true},
        "long_term": {"count": 0, "has_locked": false},
        "commentary": {"count": 1, "has_locked": true}
      }
    }
  ],
  "meta": {"request_id": "..."}
}
```

**字段来源映射**：

| 字段 | 来源 |
|---|---|
| `period_month` | 投稿 `publish_date` 归月（`_settlement_month_options`）∪ 版本表 `period_month` |
| `has_posts` | 该月是否存在投稿 |
| `traffic_boost_applicable` | `is_july_traffic_boost_month(月)`（core/traffic_boost） |
| `traffic_boost_enabled` | [dashboard_repository.py:414](../database/dashboard_repository.py:414) `get_traffic_boost_enabled()`；非 7 月恒 `false` |
| `versions.*.count` / `has_locked` | `list_compensation_versions` / `list_long_term_compensation_versions` / `list_commentary_compensation_versions` 的条数与是否含 `status == "LOCKED"` |

**错误**：401、422（`category` 非法）。

---

### 18.2 `GET /api/compensation/grassroot`

草根达人月度结算明细。

**查询参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `period_month` | string，必填 | `YYYY-MM` |
| `version_id` | int，可选 | 省略=当前预览；传入=读取该冻结版本快照 |
| `settlement_status` | string，可重复，可选 | 精确筛选 `结算状态` |
| `q` | string，可选 | 匹配 `creator_key` / `creator_name` |
| `page` / `page_size` | int，可选 | 见 0.4 |
| `sort` | string，可选 | 白名单：`total_amount_jpy`、`billable_views`、`all_video_views`、`cpm`、`creator_key`；默认 `-total_amount_jpy` |

**当前预览计算口径**（对齐 [ui/compensation.py:502](../ui/compensation.py:502)）：
`calculate_grassroot_compensation(_month_data(data, 月), 达人库全量记录, jpy_to_usd_rate=当月汇率, traffic_boost_enabled=当月开关)`。`_month_data` =
先 `exclude_cross_industry_posts` 再按月过滤。

**返回 `data`（数组，每达人一行）+ `meta`**：

```json
{
  "data": [
    {
      "creator_key": "koc_001",
      "creator_name": "示例达人",
      "contract_types": ["6月YTB"],
      "settlement_status": "可结算",
      "rank": "A+",
      "settlement_subtype": "long+livestream",
      "followers": 120000,
      "youtube_followers": 120000,
      "tiktok_followers": null,
      "billable_post_count": 12,
      "billable_views": 3500000,
      "contract_billable_views": 3200000,
      "all_video_views": 4100000,
      "cpm_views_no_boost": 4100000,
      "cross_lane": {
        "types": "tiktok",
        "post_count": 2,
        "original_views": 300000,
        "boosted_views": 315000,
        "rank": "C",
        "rank_reward_jpy": 120000,
        "post_reward_jpy": 0,
        "amount_jpy": 120000,
        "urls": ["https://..."]
      },
      "rewards_jpy": {
        "short_rank": 0,
        "long_livestream_rank": 800000,
        "short_post": 0,
        "long_livestream_post": 50000
      },
      "total_amount_jpy": 970000,
      "creator_receivable_jpy": 972239,
      "youdao_receivable_jpy": 1118075,
      "creator_receivable_usd": 6514.0,
      "youdao_receivable_usd": 7490.1,
      "cpm": 1.83
    }
  ],
  "meta": {
    "request_id": "...",
    "mode": "preview",
    "period_month": "2026-07",
    "jpy_to_usd_rate": 0.0067,
    "traffic_boost_enabled": true,
    "version": null,
    "currency": {
      "base": "JPY",
      "usd_fields": ["creator_receivable_usd", "youdao_receivable_usd", "cpm"],
      "handling_fee_usd": 15.0,
      "service_fee_multiplier": 1.15,
      "rounding": "receivable_jpy=int(round); usd/cpm=unrounded float; zero-amount rows skip fee/multiplier entirely"
    },
    "summary": {
      "total_amount_jpy": 970000,
      "creator_receivable_jpy": 972239,
      "youdao_receivable_jpy": 1118075,
      "creator_receivable_usd": 6514.0,
      "youdao_receivable_usd": 7490.1,
      "settled_views": 3500000,
      "total_video_views": 4100000,
      "overall_cpm": 1.83
    },
    "pagination": {"page": 1, "page_size": 20, "total_items": 1, "total_pages": 1}
  }
}
```

`creator_receivable_usd`/`youdao_receivable_usd`/`creator_receivable_jpy`/
`youdao_receivable_jpy`/`cpm` 在上例中按 18.0 第 6 条公式由
`total_amount_jpy=970000`、`jpy_to_usd_rate=0.0067` 精确推导而来
（`creator_usd = 970000*0.0067+15 = 6514.0`；`youdao_usd = 6514.0*1.15 = 7490.1`；
下同），示例数值可直接复算校验，不是任意占位数。若某达人 `结算状态 = 未达标`
（`total_amount_jpy = 0`），则该行 `creator_receivable_jpy`/`youdao_receivable_jpy`/
`creator_receivable_usd`/`youdao_receivable_usd` 全部为 `0`（不叠加 15$ 手续费、
不乘以 1.15 服务费），`cpm` 按 core 原样输出。

`saved_draft`/`frozen` 时 `mode` 相应为 `"saved_draft"` / `"frozen"`，`version` 填
`{"version_id": 12, "version_no": 2, "status": "LOCKED", "created_at": "...", "updated_at": "...", "locked_at": "..."}`（`status` 为 `DRAFT` 时对应
`mode: "saved_draft"`、`locked_at` 为 `null`），`data` 直接来自
`version.details` 快照，不重算。

**前端展示口径**：草根结算页面**可以在 UI 上隐藏 `total_amount_jpy`**（该字段
仅作为日元基准金额/审计口径保留），前端主展示金额为 `creator_receivable_usd`
的汇总值（对应 `meta.summary.creator_receivable_usd`）。API 仍必须返回
`total_amount_jpy` 供审计/对账使用，不得因前端隐藏而在响应中省略该字段。

**字段来源映射**（列名对齐
[core/grassroot_compensation.py:46](../core/grassroot_compensation.py:46)
`COMPENSATION_COLUMNS`）：

| JSON 字段 | 现有列 / 来源 | 含义/含费 |
|---|---|---|
| `creator_key` | `user_id` | |
| `creator_name` | `达人` | |
| `contract_types` | `合同类型`（按 `、` 拆分为数组，遵循 0.7 动态字符串） | |
| `settlement_status` | `结算状态` | 取值：可结算/未达标/待补充粉丝数/合同类型待确认/合同期限外/历史资料缺失 |
| `rank` | `rank` | 可为 `无等级` |
| `settlement_subtype` | `计费 subtype` | |
| `followers`/`youtube_followers`/`tiktok_followers` | `粉丝数`/`YouTube粉丝数`/`TikTok粉丝数` | |
| `billable_post_count` | `投稿数` | 计费投稿数（含跨赛道计费投稿） |
| `billable_views` | `计费播放量` | 计费播放量（含跨赛道计费播放） |
| `contract_billable_views` | `合同内计费播放量` | |
| `all_video_views` | `全部视频类型播放量` | 全部视频播放量 |
| `cpm_views_no_boost` | `CPM计算播放量（无加成）` | CPM 分母（无加成） |
| `cross_lane.*` | `跨赛道类型/活动投稿数/原始播放量/加成后播放量/rank/rank金额/投稿数奖励/结算金额/视频链接` | 跨赛道（仅草根、7 月流量加成启用时非空） |
| `rewards_jpy.*` | `short rank金额`/`long+livestreamrank金额`/`short 投稿数奖励`/`long+livestream投稿数奖励` | JPY |
| `total_amount_jpy` | `总金额（日元）` | JPY |
| `creator_receivable_jpy` | `博主应收（日元）(包含15$手续费)` | JPY，含 15$ 手续费，不含服务费 |
| `youdao_receivable_jpy` | `有道应收（日元）（包含服务费）` | JPY，含服务费 |
| `creator_receivable_usd` | `博主应收（美元）` | USD，含 15$ 手续费 |
| `youdao_receivable_usd` | `有道应收（美元）（包含服务费）` | USD，含服务费 |
| `cpm` | `CPM` | USD/千次；无加成播放量为 0 时 `null` |
| `meta.summary.*` | `GrassrootCompensationResult` 的 `total_amount_jpy`/`creator_receivable_jpy`/`youdao_receivable_jpy`/`creator_receivable_usd`/`youdao_receivable_usd`/`settled_views`/`total_video_views`/`overall_cpm` | |

**错误**：401、404（`version_id` 不存在）、422（`period_month`/`page_size`/汇率未保存）。

---

### 18.3 `GET /api/compensation/long-term`

长包达人月度结算明细，含“手动活动数”对应结果。

**查询参数**：同 18.2（`period_month` 必填、`version_id`、`settlement_status`、
`q`、分页、`sort`）。`sort` 白名单：`total_amount_jpy`、`monthly_new_post_views`、
`cpm`、`creator_key`。

**当前预览口径**：`calculate_long_term_compensation(月投稿, 长包达人记录,
jpy_to_usd_rate=当月汇率, event_counts=当月活动数, period_start=月首,
period_end=月末, traffic_boost_enabled=当月开关)`。`event_counts` 来自
[dashboard_repository.py:461](../database/dashboard_repository.py:461)
`get_long_term_activity_counts(period_month)`（键为达人库 `record.id`，缺失即
未填 → `结算状态 = 待填写活动数`）。

**返回 `data` 行示例**：

```json
{
  "record_id": 88,
  "creator_key": "koc_long_01",
  "creator_name": "长包达人",
  "contract_types": ["长包"],
  "contract_start_date": "2026-01-01",
  "contract_end_date": "2026-12-31",
  "settlement_status": "可结算",
  "rank": "B+",
  "followers": 240000,
  "youtube_post_count": 8,
  "monthly_new_post_views": 1800000,
  "cpm_views_no_boost": 1750000,
  "monthly_activity_count": 3,
  "activity_threshold": 2,
  "rank_reward_jpy": 500000,
  "expected_cpm_jpy": 250,
  "total_amount_jpy": 500000,
  "creator_receivable_jpy": 502239,
  "youdao_receivable_jpy": 577575,
  "creator_receivable_usd": 3365.0,
  "youdao_receivable_usd": 3869.75,
  "cpm": 2.21
}
```

`creator_receivable_*`/`youdao_receivable_*`/`cpm` 同样由 18.0 第 6 条公式对
`total_amount_jpy=500000`、`jpy_to_usd_rate=0.0067` 精确推导（`creator_usd =
500000*0.0067+15 = 3365.0`；`youdao_usd = 3365.0*1.15 = 3869.75`），可直接复算。
若 `结算状态 = 未达标`（`total_amount_jpy = 0`），四个应收字段全部为 `0`，不叠加
手续费/服务费。

`meta` 与 18.2 结构一致（`mode` 为 `preview`/`saved_draft`/`frozen` 三态之一，
以及 `version`/`jpy_to_usd_rate`/`traffic_boost_enabled`/`currency`/`summary`/
`pagination`——`pagination` 统一使用 `total_items`/`total_pages`，见 0.4），
`summary` 字段来自 `LongTermCompensationResult`。

**字段来源映射**（列名对齐
[core/long_term_compensation.py:29](../core/long_term_compensation.py:29)
`LONG_TERM_COMPENSATION_COLUMNS`）：

| JSON 字段 | 现有列 | 含义/含费 |
|---|---|---|
| `record_id` | `记录ID` | |
| `creator_key` / `creator_name` | `user_id` / `达人` | |
| `contract_types` | `合同类型` | 长包 |
| `contract_start_date` / `contract_end_date` | `合同开始日期` / `合同截止日期` | 结算月生效合同 |
| `settlement_status` | `结算状态` | 可结算/未达标/待补充粉丝数/待填写活动数/合同期限外/历史资料缺失 |
| `rank` | `rank` | |
| `followers` | `粉丝数` | |
| `youtube_post_count` | `YouTube 投稿数` | |
| `monthly_new_post_views` | `月度新投稿播放量` | 全部（含加成，若启用） |
| `cpm_views_no_boost` | `CPM计算播放量（无加成）` | CPM 分母 |
| `monthly_activity_count` | `每月活动数` | **手动活动数**（来自 `event_counts`，可为 `null`） |
| `activity_threshold` | `活动数门槛` | 命中档位所需活动数 |
| `rank_reward_jpy` | `rank金额` | JPY |
| `expected_cpm_jpy` | `预计 CPM（日元）` | JPY |
| `total_amount_jpy` | `总金额（日元）` | JPY |
| `creator_receivable_jpy` | `博主应收（日元）(包含15$手续费)` | 含 15$ 手续费 |
| `youdao_receivable_jpy` | `有道应收（日元）（包含服务费）` | 含服务费 |
| `creator_receivable_usd` | `博主应收（美元）` | 含 15$ 手续费 |
| `youdao_receivable_usd` | `有道应收（美元）（包含服务费）` | 含服务费 |
| `cpm` | `CPM` | 可 `null` |

**手动活动数规则**：`每月活动数` 为空 → `待填写活动数`（不计费）；有值但低于所在
档位 `event_threshold` 时该档位被跳过（可能降级或落到 `无等级`/`未达标`），命中
档位的门槛写回 `activity_threshold`。

**错误**：401、404、422（含汇率未保存）。

---

### 18.4 `GET /api/compensation/commentary`

解说达人月度结算明细：长/短视频等级、并用奖金、指定主题件数与金额、全部播放量、
CPM。

**查询参数**：同 18.2；`sort` 白名单：`total_amount_jpy`（=`解说含税总额（日元）`）、
`all_paid_views`、`cpm`、`creator_key`。

**当前预览口径**（对齐 [ui/compensation.py:1422](../ui/compensation.py:1422)）：
`calculate_commentary_compensation(月投稿, 达人库全量记录, period_month=月,
jpy_to_usd_rate=当月汇率, profile_history=达人档案历史,
theme_submissions=list_commentary_theme_submissions(月),
theme_definitions=list_commentary_theme_definitions(月))`。解说不涉及流量加成
参数，**`meta` 中不返回 `traffic_boost_enabled` 字段（整体省略，不返回 `false`）**，
避免前端误以为解说存在可切换的流量加成开关。

**返回 `data` 行示例**：

```json
{
  "creator_id": 501,
  "creator_key": "koc_cm_01",
  "creator_name": "解说达人",
  "contract_types": ["YTB长+TT短"],
  "settlement_status": "可结算",
  "youtube_uid": "yt_501",
  "youtube_followers": 300000,
  "tiktok_uid": "tt_501",
  "tiktok_followers": 150000,
  "short_platform": "TikTok",
  "long_views": 2200000,
  "long_view_rank": "A",
  "long_follower_cap_rank": "A+",
  "long_final_rank": "A",
  "long_reward_jpy": 600000,
  "short_views": 900000,
  "short_view_rank": "B",
  "short_follower_cap_rank": "-",
  "short_final_rank": "B",
  "short_reward_jpy": 200000,
  "combined_bonus_rank": "A/B",
  "combined_bonus_jpy": 100000,
  "designated_theme_count": 2,
  "designated_theme_reward_jpy": 30000,
  "all_paid_views": 3100000,
  "total_jpy_tax_incl": 930000,
  "creator_receivable_jpy": 932239,
  "youdao_receivable_jpy": 1072075,
  "creator_receivable_usd": 6246.0,
  "youdao_receivable_usd": 7182.9,
  "cpm": 2.32
}
```

`creator_receivable_*`/`youdao_receivable_*`/`cpm` 由 18.0 第 6 条公式对
`total_jpy_tax_incl=930000`、`jpy_to_usd_rate=0.0067` 精确推导（`creator_usd =
930000*0.0067+15 = 6246.0`；`youdao_usd = 6246.0*1.15 = 7182.9`），可直接复算。
若 `结算状态 = 未达标`（`total_jpy_tax_incl = 0`），四个应收字段全部为 `0`，
不叠加手续费/服务费。

`meta` 结构同上（`mode` 三态、`pagination` 统一 `total_items`/`total_pages`，
且不含 `traffic_boost_enabled`）；`summary` 来自 `CommentaryCompensationResult`
（`total_amount_jpy`=解说含税总额之和、两组应收、`settled_views`=长+短、
`total_video_views`=全部已付费内容播放量、`overall_cpm`）。

**字段来源映射**（列名对齐
[core/commentary_compensation.py:60](../core/commentary_compensation.py:60)
`COMMENTARY_COLUMNS`）：

| JSON 字段 | 现有列 | 含义/含费 |
|---|---|---|
| `creator_id` | `creator_id` | 达人库 `record.id` |
| `creator_key` / `creator_name` | `UID` / `达人` | |
| `contract_types` | `合同类型` | |
| `settlement_status` | `结算状态` | 可结算/待补充粉丝数/未达标 |
| `youtube_uid`/`youtube_followers`/`tiktok_uid`/`tiktok_followers` | `YouTube UID`/`YouTube粉丝数`/`TikTok UID`/`TikTok粉丝数` | |
| `short_platform` | `短视频平台` | `TikTok` 或 `YouTube` |
| `long_views` | `长视频播放量` | **计费长视频播放量（已排除指定主题已通过视频）** |
| `long_view_rank`/`long_follower_cap_rank`/`long_final_rank` | `长视频播放等级`/`长视频粉丝上限等级`/`长视频最终等级` | 长视频等级 |
| `long_reward_jpy` | `长视频报酬（日元）` | JPY |
| `short_views` | `短视频播放量` | 计费短视频播放量（同上排除） |
| `short_view_rank`/`short_follower_cap_rank`/`short_final_rank` | `短视频播放等级`/`短视频粉丝上限等级`/`短视频最终等级` | 短视频等级 |
| `short_reward_jpy` | `短视频报酬（日元）` | JPY |
| `combined_bonus_rank` | `并用奖金等级` | 可为 `不适用` |
| `combined_bonus_jpy` | `并用奖金（日元）` | 并用奖金，JPY |
| `designated_theme_count` | `指定主题件数` | 指定主题件数 |
| `designated_theme_reward_jpy` | `指定主题报酬（日元）` | 指定主题金额，JPY（每件 15,000） |
| `all_paid_views` | `全部已付费内容播放量` | 全部播放量（= 长+短计费播放量） |
| `total_jpy_tax_incl` | `解说含税总额（日元）` | JPY，含税 |
| `creator_receivable_jpy`/`youdao_receivable_jpy` | `博主应收（日元）(包含15$手续费)`/`有道应收（日元）（包含服务费）` | 分别含手续费/含服务费 |
| `creator_receivable_usd`/`youdao_receivable_usd` | `博主应收（美元）`/`有道应收（美元）（包含服务费）` | |
| `cpm` | `CPM` | 基于 `有道应收（美元）` / 全部已付费内容播放量 ×1000，可 `null` |

**指定主题排除规则（强制）**：审核状态为 `APPROVED` 且满足主题规则（链接数
LONG=1/SHORT=3）的指定主题申报**在当月投稿数据中实际匹配到的链接**不计入解说
长/短视频计费播放量（这些 URL 由 `_settlement_content_views` 的
`excluded_theme_urls` 过滤掉），但**无论链接是否在当月投稿数据中实际匹配到**，
只要申报满足上述条件，都计入 `指定主题件数` 与 `指定主题报酬（日元）`（即
“是否有资格计费”与“是否有播放量被实际排除”是两件独立的事，详见 18.6 的
`theme_reward_eligible`/`matched_post_urls`/`billing_excluded_url_count`/
`billing_excluded` 四字段）。因此输出中**不存在**`指定主题视频播放量` 列，API
不得自行把这些播放量加回 `long_views`/`short_views`。

**错误**：401、404、422（含汇率未保存）。

---

### 18.5 `GET /api/compensation/versions`

返回指定月份、指定结算类别的历史结算版本列表（不含逐行明细，明细通过 18.2–18.4
带 `version_id` 获取）。

**查询参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `period_month` | string，必填 | `YYYY-MM` |
| `category` | string，必填 | `GRASSROOT` / `LONG_TERM` / `COMMENTARY` |

**数据来源**：按 `category` 分别调用
[dashboard_repository.py:655](../database/dashboard_repository.py:655)
`list_compensation_versions()`（草根）、
[:764](../database/dashboard_repository.py:764)
`list_long_term_compensation_versions()`、
[:1118](../database/dashboard_repository.py:1118)
`list_commentary_compensation_versions()`，三者均返回同一 `CompensationVersion`
数据类，按 `version_no` 降序。

**返回 `data`（数组，`version_no` 降序）**：

```json
{
  "data": [
    {
      "version_id": 12,
      "version_no": 2,
      "status": "LOCKED",
      "schema_version": 1,
      "jpy_to_usd_rate": 0.0067,
      "note": null,
      "created_at": "2026-08-01T09:00:00",
      "updated_at": "2026-08-02T10:30:00",
      "locked_at": "2026-08-02T10:30:00",
      "summary": {
        "total_amount_jpy": 970000,
        "creator_receivable_jpy": 972239,
        "youdao_receivable_jpy": 1118075,
        "creator_receivable_usd": 6514.0,
        "youdao_receivable_usd": 7490.1,
        "settled_views": 3500000,
        "total_video_views": 4100000,
        "overall_cpm": 1.83
      }
    },
    {
      "version_id": 8,
      "version_no": 1,
      "status": "DRAFT",
      "schema_version": 1,
      "jpy_to_usd_rate": 0.0067,
      "note": "初稿",
      "created_at": "2026-07-31T18:00:00",
      "updated_at": "2026-07-31T18:00:00",
      "locked_at": null,
      "summary": { "...": "..." }
    },
    {
      "version_id": 3,
      "version_no": null,
      "status": "LOCKED",
      "schema_version": null,
      "jpy_to_usd_rate": 0.0065,
      "note": "历史遗留版本（无 schema_version）",
      "created_at": "2026-03-31T18:00:00",
      "updated_at": "2026-03-31T18:00:00",
      "locked_at": "2026-03-31T18:00:00",
      "summary": { "...": "..." }
    }
  ],
  "meta": {"request_id": "...", "period_month": "2026-07", "category": "GRASSROOT"}
}
```

**字段来源映射**（数据类
[database/dashboard_repository.py:30](../database/dashboard_repository.py:30)
`CompensationVersion`）：

| JSON 字段 | 数据类字段 |
|---|---|
| `version_id` | `id` |
| `version_no` | `version_no` |
| `status` | `status`（`DRAFT` / `LOCKED`；对应明细接口 `mode` 分别为 `saved_draft` / `frozen`） |
| `schema_version` | **新增**：保存该版本时记录的 schema 版本号（整数，从本契约生效起的新保存版本开始写入）；历史遗留版本无此值时为 `null`，视为 legacy |
| `jpy_to_usd_rate` | `jpy_to_usd_rate` |
| `note` | `note` |
| `created_at` / `updated_at` / `locked_at` | 同名字段 |
| `summary` | `summary`（保存当时写入的汇总 dict，键随 core 的 summary 结构） |

**历史版本 schema 漂移处理（legacy 规则，定案）**：`schema_version` 为 `null`
（或早于当前值）的版本一律视为 **legacy**：读取时只做“列名映射 + 缺失字段
补 `null`”，**不得重新计算**其历史金额、合同、播放量或等级——即使这些值按当前
core 逻辑本应不同。前端必须容忍旧版本缺少新增字段（例如尚未引入
`theme_reward_eligible` 等字段的旧版本，读取 18.4/18.6 时相应字段返回 `null`
或整体缺省）。新保存的版本（第二阶段写接口范围）应写入当前 `schema_version`。

**快照语义**：`summary` 与（经 18.2–18.4 读取的）`details` 均为**保存当时**的
快照，无论 `status` 是 `DRAFT` 还是 `LOCKED`，读取时都不重算、不随当前达人库/
看板变化；仅 `LOCKED`（对应 `mode: "frozen"`）代表不可再变更的官方定稿。

**错误**：401、422（`category` / `period_month` 非法）。

---

### 18.6 `GET /api/compensation/commentary/theme-submissions`

只读返回已保存的解说“指定主题”申报：主题、链接、审核状态与计费排除状态。

**查询参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `period_month` | string，必填 | `YYYY-MM` |
| `creator_id` | int，可重复，可选 | 按达人过滤 |
| `review_status` | string，可重复，可选 | `PENDING` / `APPROVED` / `REJECTED` |

**数据来源**：
[dashboard_repository.py:1002](../database/dashboard_repository.py:1002)
`list_commentary_theme_submissions(period_month)`（已保存申报，原样只读）；主题
名称/是否启用/每人上限来自
[:974](../database/dashboard_repository.py:974)
`list_commentary_theme_definitions(period_month)`。

**返回 `data`（数组，`creator_id, theme_code` 升序）**：

```json
{
  "data": [
    {
      "id": 3001,
      "period_month": "2026-07",
      "creator_id": 501,
      "theme_code": "SUMMER_A",
      "theme_name": "夏季主题A",
      "content_format": "LONG",
      "urls": ["https://youtube.example/watch?v=abc"],
      "submitted_date": "2026-07-20",
      "review_status": "APPROVED",
      "note": null,
      "theme_reward_eligible": true,
      "matched_post_urls": ["https://youtube.example/watch?v=abc"],
      "billing_excluded_url_count": 1,
      "billing_excluded": true
    },
    {
      "id": 3002,
      "period_month": "2026-07",
      "creator_id": 502,
      "theme_code": "SUMMER_B",
      "theme_name": "夏季主题B",
      "content_format": "SHORT",
      "urls": ["https://...1", "https://...2", "https://...3"],
      "submitted_date": "2026-07-21",
      "review_status": "PENDING",
      "note": "待复核",
      "theme_reward_eligible": false,
      "matched_post_urls": [],
      "billing_excluded_url_count": 0,
      "billing_excluded": false
    },
    {
      "id": 3003,
      "period_month": "2026-07",
      "creator_id": 503,
      "theme_code": "SUMMER_A",
      "theme_name": "夏季主题A",
      "content_format": "LONG",
      "urls": ["https://youtube.example/watch?v=xyz"],
      "submitted_date": "2026-07-22",
      "review_status": "APPROVED",
      "note": null,
      "theme_reward_eligible": true,
      "matched_post_urls": [],
      "billing_excluded_url_count": 0,
      "billing_excluded": false
    }
  ],
  "meta": {"request_id": "...", "period_month": "2026-07"}
}
```

第三条示例（`id: 3003`）说明关键语义：审核状态为 `APPROVED` 且满足主题规则的
申报，即使其链接**未**出现在当月投稿数据中（`matched_post_urls` 为空），依旧
`theme_reward_eligible: true`（计入指定主题件数与奖励）；但因为没有实际匹配到
的投稿，也就没有播放量可从计费播放量中排除，`billing_excluded_url_count: 0`、
`billing_excluded: false`。

**字段来源映射**：

| JSON 字段 | 来源 |
|---|---|
| `id`/`period_month`/`creator_id`/`theme_code`/`content_format`/`urls`/`submitted_date`/`review_status`/`note` | `list_commentary_theme_submissions()` 原样返回的 dict |
| `theme_name` | `list_commentary_theme_definitions()[theme_code]["theme_name"]` |
| `theme_reward_eligible` | **派生**：复用 `_valid_theme_submissions`（[core/commentary_compensation.py:294](../core/commentary_compensation.py:294)）的判定——`review_status == "APPROVED"` 且该主题 `enabled` 且链接数符合规则（LONG=1 / SHORT=3）即为 `true`，**与链接是否在当月投稿中被实际匹配无关** |
| `matched_post_urls` | **派生**：对 `urls` 中每条链接复用 core 的 URL 归一化（`_video_url_key`/`normalize_video_url`，[core/cross_industry.py](../core/cross_industry.py)）与当月投稿数据比对，返回实际命中的链接子集 |
| `billing_excluded_url_count` | **派生**：`len(matched_post_urls)`——即当月投稿数据中因该申报被排除出计费播放量的链接数 |
| `billing_excluded` | **派生**：`billing_excluded_url_count > 0` |

- `content_format` 取值 `LONG` / `SHORT`；`review_status` 存储层允许
  `PENDING` / `APPROVED` / `REJECTED`（写入校验见
  [dashboard_repository.py:1039](../database/dashboard_repository.py:1039)
  `replace_commentary_theme_submissions()`，本阶段不实现）。
- 数据库无持久化“计费排除”字段，`theme_reward_eligible`/`matched_post_urls`/
  `billing_excluded_url_count`/`billing_excluded` 均为**只读派生量**，必须复用
  core 既有的 `_valid_theme_submissions` 判定与 URL 归一化逻辑，**API 层不得
  另写一套独立判断**；也不得据此反推结算金额——真正的排除发生在 core 结算
  （18.4 的 `calculate_commentary_compensation`）内部，本接口只是把同一判定
  逻辑复用后暴露给前端展示。

**错误**：401、422（`period_month` / `review_status` 非法）。

---

### 18.7 设计决策汇总（已定案，不再是待确认事项）

原 18.7 列出的 10 项待确认内容，均已由产品/团队给出明确决策，具体落实见本章
对应位置，此处仅作汇总索引，供后续实现核对：

1. **`periods` 月份口径**：严格取投稿 `publish_date` 归月，不使用文件名/导入
   声明月份替代——见 18.1。
2. **预览缺汇率**：`mode: "preview"` 且当月汇率未保存时，一律返回
   `422 VALIDATION_ERROR`，不返回 `200`；历史 `saved_draft`/`frozen` 版本不受
   影响——见 18.0.1。
3. **草根合同快照**：预览不传 `contract_type_snapshots`，由 core 按
   `period_month` + 投稿日期自行解析生效合同；已保存版本直接读快照、不重新
   解析——见 18.0 第 3 条。
4. **长包活动数**：只读 `get_long_term_activity_counts(period_month)` 的持久化
   值，本阶段只读接口不接受前端传入临时活动数——见 18.0 第 5 条、18.3。
5. **指定主题计费排除**：拆分为
   `theme_reward_eligible`/`matched_post_urls`/`billing_excluded_url_count`/
   `billing_excluded` 四字段，复用 core 的 `_valid_theme_submissions` 与 URL
   归一化逻辑——见 18.6。
6. **历史版本 schema 漂移**：新增 `schema_version` 字段；无版本号的旧版本视为
   legacy，只做列名映射与缺失字段补 `null`，不重算——见 18.5。
7. **金额舍入呈现**：API 只透传 core 原始未舍入值；前端展示时 USD/CPM 保留 2
   位小数、JPY 取整；聚合计算一律使用原始值——见 18.0 第 6 条。
8. **枚举类接口分页**：`periods`/`versions`/`theme-submissions` 本阶段定案不
   分页——见 18.0.2。
9. **达人多类别**：三条赛道各自严格按 `CreatorCategory` 独立取数，跨类别达人
   可分别出现在各赛道结果中，金额互不合并——见 18.0 第 4 条。
10. **解说 `traffic_boost_enabled`**：在解说接口的 `meta` 中整体省略该字段，
    不返回 `false`——见 18.4。
