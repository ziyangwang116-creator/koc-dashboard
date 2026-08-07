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
