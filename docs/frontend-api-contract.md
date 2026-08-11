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
{ "password": "string", "operator_name": "string" }
```

`operator_name` 为**必填**字段，长度限制 2–30 个字符（含首尾）。用于
服务端审计归属（见第 14 节），不参与密码校验本身。

**返回（200）**：

```json
{ "data": { "authenticated": true } }
```

响应体**不回显团队密码**，也**不回显 `operator_name`**（`operator_name`
仅写入服务端 session store 用于审计，不需要在响应中原样返回）。同时通过
`Set-Cookie` 响应头下发 session cookie（见第 14 节），响应体本身不包含
token。

**错误**：

| 状态 | code | 场景 |
|---|---|---|
| 401 | `INVALID_CREDENTIALS` | 密码不匹配，对齐 [ui/auth.py:35](../ui/auth.py:35) `password_matches()` 的比较逻辑（`hmac.compare_digest`，防时序攻击，后端实现必须沿用同样的常量时间比较） |
| 422 | `VALIDATION_ERROR` | `password` 缺失或为空字符串；或 `operator_name` 缺失、为空、或长度不在 2–30 字符范围内 |

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
   结构：`session_id -> {issued_at, expires_at, operator_name}`）。
   `operator_name` 来自登录请求体（见第 2 节），**仅用于服务端审计**：
   - **不得**写入 Cookie（Cookie 只携带随机 `session_id`）；
   - **不得**放入任何 JWT（本方案本身也不使用 JWT 编码 session）；
   - **不得**出现在任何前端可见的日志中（仅允许出现在服务端审计日志/
     数据库审计表中）。
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
   的现状），session 本身仍只代表"已通过团队密码验证"这一布尔状态，
   不构成多用户账号体系；`operator_name` 只是登录时手动填写的操作人
   标注，随 session 存于服务端用于审计归属（见第 2 节、19.6.7），不等同于
   身份认证，且不会以任何形式暴露给前端（Cookie/JWT/前端日志均不包含）。

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

---

## 19. 第二阶段：写入 API 契约

本章为**设计契约**，不引入任何实现代码。凡未特别说明的通用约定（响应包裹、
错误格式、分页、排序、认证、敏感信息隔离）一律沿用第 0、14、16 章；所有写
接口共享的安全规则集中在 19.6，正文各接口不再重复展开，仅在有例外时提及。

**核心原则（贯穿全章，不得违反）**：

1. 写接口只做参数校验、事务编排与序列化，**结算/匹配/排除/阶梯计算逻辑一律
   复用现有 `core/*` 与 `database/*_repository.py` 函数**，契约中不重新定义、
   不重新计算任何业务规则——与第 18 章"禁止在 API 层重算阶梯"的强约束一致。
2. **已锁定（`status = "LOCKED"`）的结算版本永久不可变**，无论后续达人库、
   粉丝数、汇率、投稿、合同如何变化都不会被回溯修改；任何"更正"都必须表现
   为创建一个新的草稿版本（更高 `version_no`），绝不允许对已锁定版本做原地
   UPDATE。
3. **"新增未来变更"与"修正历史录入错误"是两个不同的端点/流程**，绝不合并为
   同一个通用的"编辑合同"接口——即使数据库层它们分别对应
   `create_contract_change()` 与 `correct_contract_period()` 两个已存在的
   repository 方法，也要求前端在 UI 层用不同入口、不同确认文案区分，防止误将
   一次性的录入纠错当成真实发生过的业务变更写入历史。
4. **月度完整导入（按月替换）必须支持"预览 diff → 确认后原子替换"两步流程**，
   确认前的任何校验失败都不得触碰 `dashboard_post` 表；确认后的替换要么整体
   成功、要么整体回滚，不允许部分月份被替换、部分月份保留旧数据的中间态。
5. **后续导入按"当时"有效的达人库合同/UID 规则匹配**，但这只影响"新导入批次
   如何解析达人归属"，绝不会因此改写已经存在的锁定结算版本——锁定版本读取的
   是保存时刻的合同快照（`details_json`），后续导入、合同编辑、达人库变更都
   不会触碰它。

### 19.1 达人库管理（创建 / 编辑 / 启停 / 合同周期）

对应 [database/koc_repository.py:2095](../database/koc_repository.py:2095)
`create()`、[:2289](../database/koc_repository.py:2289) `update()`、
[:2580](../database/koc_repository.py:2580) `set_active()`，以及合同周期四
件套：[:760](../database/koc_repository.py:760) `create_contract_change()`
（新增变更）、[:876](../database/koc_repository.py:876)
`correct_contract_period()`（修正历史错误）、
[:970](../database/koc_repository.py:970)
`delete_authoritative_contract_period()`（删除错误周期）、
[:621](../database/koc_repository.py:621) `revert_contract_revision()`
（撤销/回滚到历史修订）。

#### 19.1.1 `POST /api/creators`（新建达人）

**请求 body**：字段对齐 `create()` 的关键字参数——`user_id`（必填）、
`koc_name`（必填）、`creator_category`、`contract_types`（字符串数组，
0.7 节动态字符串，**不是固定 enum**）、`homepage_url`、`follower_count`、
`youtube_user_id`/`youtube_homepage_url`/`youtube_follower_count`、
`tiktok_user_id`/`tiktok_homepage_url`/`tiktok_follower_count`、`active`
（默认 `true`）、`note`、`effective_date`（默认今天）、
`contract_start_date`/`contract_end_date`（省略则按
`_contract_period_defaults()` 的合同家族默认区间：草根 5/1–10/31、长包
5/1–12/31、解说 5/1–8/31）。

**返回（201）**：`data` 为第 4/5 节 `KOCRecord` 结构（新建即返回详情态，
含 `contract_periods`）。

**错误**：

| 状态 | code | 场景 |
|---|---|---|
| 422 | `VALIDATION_ERROR` | `user_id`/`koc_name` 为空；`homepage_url` 非合法 http(s) URL；`follower_count` 非非负整数；`creator_category`/`contract_types` 非法；`contract_end_date < contract_start_date` |
| 409 | `CONFLICT` | `user_id`/`youtube_user_id`/`tiktok_user_id` 三者中任一与现有达人的这三个字段之一重复（对齐 `DuplicateUserIDError`），`message` 提示"该 UID 已存在，请编辑现有达人记录" |

**事务边界**：`create()` 内部单个 `connect()` 上下文中完成
`koc_master` 插入、`creator_contract` 批量插入、`creator_contract_period`
插入、`creator_profile_history` 快照写入、（如有初始粉丝数）
`follower_update_audit` 写入，五张表在同一事务中提交或整体回滚。

**幂等性**：不提供天然幂等键（`user_id` 唯一约束本身起到"重复请求→409"的
效果，而非"重复请求→返回同一结果"）。若前端需要防止用户重复点击"保存"导致
的重复提交，应携带 `Idempotency-Key` 头（值建议为前端生成的 UUID，绑定到
本次表单提交），服务端在短时间窗口（如 10 分钟）内对相同 Key 返回首次成功
的响应而不二次写入；具体窗口时长与存储方式留待实现阶段定案（见 19.6）。

**并发冲突**：`user_id` 唯一约束天然由数据库层保证，不需要额外的乐观锁；
两个并发请求创建同一 `user_id` 时，后到达的请求应转译数据库层
`IntegrityError` 为 `409 CONFLICT`，而不是 `500`。

**影响范围**：使 `GET /api/creators`、`GET /api/creators/{id}`、
`GET /api/meta/contract-types`（若引入了新合同类型字符串）、
`GET /api/dashboard/filter-options`（`creators` 列表）缓存失效；不影响任何
已存在的结算预览/草稿/锁定版本（新达人在其被创建前的历史结算月份中本就不
应出现）。

#### 19.1.2 `PUT /api/creators/{id}`（编辑达人基础资料）

对应 `update()`。**用途严格限定为"编辑达人当前基础资料"**（姓名、主页、
手动粉丝数、启停、备注、以及在未触发"合同变更/合同纠错"语义时的只读展示
字段同步），**不用于合同周期的新增变更或历史纠错**——那是 19.1.3/19.1.4
两个独立端点的职责。若请求 body 中的 `contract_types`/`creator_category`
相对当前值发生了实质变化（对齐 repository 内部
`contracts_changed`/`category_changed` 判定），前端必须先引导用户走
19.1.3（新合同变更）流程，本端点对此类"隐式合同变更"的请求应返回 422
`VALIDATION_ERROR`（`field_errors` 提示"合同类型变化请使用‘新增合同变更’
接口"），**不得静默接受并当作历史合同处理**。

**请求 body**：同 19.1.1，另加 `manual_follower_update`（bool，标记本次
粉丝数是否为人工修正，对齐 repository 同名参数）、
`manual_settlement_eligible`（可选 bool，人工强制标记结算资格）。

**请求头**：`If-Unmodified-Since` 或 `If-Match`（携带上次读取到的
`updated_at`），用于乐观并发检测（见下）。

**返回（200）**：更新后的 `KOCRecord` 详情态。

**错误**：

| 状态 | code | 场景 |
|---|---|---|
| 404 | `NOT_FOUND` | `id` 不存在 |
| 422 | `VALIDATION_ERROR` | 同 19.1.1 的字段校验；或检测到隐式合同变更 |
| 409 | `CONFLICT` | `user_id` 与其他达人冲突；或 `If-Unmodified-Since`/`If-Match` 携带的 `updated_at` 与当前记录不一致（说明期间被其他会话修改过），响应体 `error.message` 提示"该达人资料已被修改，请刷新后重试"，`error.field_errors` 可附带服务端当前的 `updated_at` 供前端直接刷新缓存 |

**事务边界**：单次 `update()` 调用内对 `koc_master`/`creator_contract`/
`creator_contract_period`/`creator_profile_history` 的必要更新在同一
事务中提交。

**幂等性**：PUT 语义天然幂等（相同 body 重复提交得到相同终态），不强制
要求 `Idempotency-Key`，但仍建议高风险批量编辑场景携带。

**影响范围**：失效该 `id` 对应的 `GET /api/creators/{id}` 与
`GET /api/creators` 列表缓存；若粉丝数变化，还会影响后续新建的结算
**预览**（`mode=preview`）的粉丝数读数，但不影响任何已有的 `saved_draft`/
`frozen` 版本（快照已固化）。

#### 19.1.3 `POST /api/creators/{id}/contract-changes`（新增合同变更——真实业务变化）

对应 [database/koc_repository.py:760](../database/koc_repository.py:760)
`create_contract_change()`。**语义**：达人的合同从某个未来（或当前）生效
日期起，发生了真实的业务变化（例如从 YTB 单合同改为 YTB+TT 双合同、类别
从草根转为长包），这段变化会成为该达人合同历史上真实存在过的一段周期，
不可与"更正之前录错的数据"混淆。

**请求 body**：

```json
{
  "effective_date": "2026-09-01",
  "contract_types": ["YTB", "TT"],
  "contract_end_date": "2026-12-31",
  "creator_category": "GRASSROOT",
  "reason": "9月起新增TT合同"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `effective_date` | string，必填 | `YYYY-MM-DD`，新周期生效日 |
| `contract_types` | array\<string\>，必填，非空 | 动态字符串（0.7 节） |
| `contract_end_date` | string，可选 | 省略则按合同家族默认截止日期 |
| `creator_category` | string，可选 | 省略则按 `contract_types` 自动推导 |
| `reason` | string，可选 | 变更原因备注，写入 `creator_contract_revision.reason`，**前端表单应引导用户填写**（例如"客户方要求新增短视频合作"），便于后续审计区分"新变更"与"纠错" |

**前端确认提示（强制）**：提交前必须展示"这将作为一次真实的合同变更被记录
在该达人的合同历史中，从 {effective_date} 起生效"类文案，与 19.1.4 的纠错
提示在措辞与视觉样式上必须能被用户明显区分（例如变更用"新增"配色，纠错用
"修正"配色），防止操作者选错入口。

**返回（201）**：更新后的 `KOCRecord` 详情态（含新的 `contract_periods`）。

**错误**：

| 状态 | code | 场景 |
|---|---|---|
| 404 | `NOT_FOUND` | `id` 不存在 |
| 422 | `VALIDATION_ERROR` | `contract_types` 为空；`contract_end_date < effective_date` |
| 409 | `CONFLICT` | 该生效日已存在合同周期（`existing is not None`），`error.message` 明确提示"该月已有合同周期，请使用"修正填写错误"（见 19.1.4）而不是本接口，避免用户在该场景下误用新增" |

**事务边界**：单事务内完成 `creator_contract_period` 插入/相邻周期截止日
调整、`_sync_master_contract_period()`（同步 `koc_master`/`creator_contract`
主表）、`creator_contract_revision` 写入（`operation_type='CHANGE'`）。

**幂等性**：`(creator_id, effective_date)` 天然构成去重键——同一生效日的
重复提交会被数据库层唯一性检查转译为 409（见上），因此该组合本身即可作为
`Idempotency-Key` 的语义基础；若前端仍希望使用显式 `Idempotency-Key` 头
防止网络重试导致的双重提交，建议其值绑定 `(creator_id, effective_date,
contract_types 排序后拼接)`。

**并发冲突**：两个并发请求对同一达人、同一生效日创建变更时，后到达者收到
409。

**影响范围**：使该 `id` 的详情/列表缓存失效；使涉及该达人、且结算月份落在
新周期生效日之后的**预览**（`mode=preview`）重新解析合同（草根按
`period_month`+发布日期解析生效合同，长包/解说按月末快照解析，见 18.0 第 3
条）；**不影响任何已存在的 `saved_draft`/`frozen` 版本**——即使这些版本的
结算月份晚于新合同生效日，它们读取的是保存时刻的合同快照，需要人工另行创建
新草稿重算才会体现本次变更。

#### 19.1.4 `POST /api/creators/{id}/contract-corrections`（修正历史录入错误）

对应 [database/koc_repository.py:876](../database/koc_repository.py:876)
`correct_contract_period()`。**语义**：某个已存在的合同周期在最初录入时
就填错了（合同类型、开始/截止日期），需要原地修正为正确值，**不代表业务上
真的发生过变化**——修正后该周期在历史时间线上"从未错过"。

**请求 body**：

```json
{
  "source_effective_date": "2026-05-01",
  "contract_types": ["YTB"],
  "contract_start_date": "2026-05-01",
  "contract_end_date": "2026-10-31",
  "reason": "原录入误填为YTB+TT，实际仅有YTB",
  "expected_updated_at": "2026-08-01T09:00:00Z"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_effective_date` | string，必填 | 定位要修正的现有周期（按其 `start_date` 精确匹配） |
| `contract_types` | array\<string\>，必填 | 修正后的合同类型 |
| `contract_start_date` / `contract_end_date` | string，必填 | 修正后的周期起止（**均必填**，与 19.1.3 不同——纠错要求精确指定完整周期，不依赖默认值推导） |
| `reason` | string，可选 | 纠错原因，写入 revision，前端应提示"请说明这是录入错误而非业务变化" |
| `expected_updated_at` | string，可选（本契约定案新增） | 前端提交时携带上一次读取到的该达人 `updated_at`，用于区分"基于最新数据的重复提交"（见 no_change 规则）与"基于过期数据的修正"（见下方 409） |

**前端确认提示（强制）**：提交前必须展示"这是对已录入历史数据的更正，
不会被视为一次新的业务变更"类文案，且必须与 19.1.3 的提示视觉区分（见
19.1.3）。

**返回（200）**：更新后的 `KOCRecord` 详情态；若命中"内容与当前状态完全
一致"的重复提交判定（见下方幂等性说明），响应体额外带 `no_change: true`。

**错误**：

| 状态 | code | 场景 |
|---|---|---|
| 404 | `NOT_FOUND` | `id` 不存在；或 `source_effective_date` 未命中任何现有周期（`period is None`），`message` 提示"合同周期已刷新，请重新打开后再修正" |
| 422 | `VALIDATION_ERROR` | 起止日期缺失或 `end < start` |
| 409 | `CONFLICT` | 修正后的周期与该达人其他周期发生日期重叠（`overlap is not None`） |
| 409 | `REVISION_EXPIRED` | 携带的 `expected_updated_at` 与该达人当前 `updated_at` 不一致（说明期间已被其他会话修改过），且请求内容与当前状态不同（非 no_change 情形），`message` 提示"该达人数据已被修改，请刷新后重试" |

**事务边界**：单事务内完成目标周期 UPDATE、`_sync_master_contract_period()`
同步、`creator_contract_revision` 写入（`operation_type='CORRECTION'`）。

**幂等性（本契约定案，取代此前"是否需要去重"的开放问题）**：非新增
操作，`source_effective_date` 定位到具体行做 UPDATE，天然幂等（相同
请求重复执行结果一致）；**建议携带 `Idempotency-Key`**（见 19.6.4），
按"操作类型 + `session_id` + `Idempotency-Key` + 请求体哈希"缓存首次
结果，24 小时内相同键的重复提交直接返回首次结果，不再重复写入
`creator_contract_revision`。**若未携带 `Idempotency-Key` 或缓存已过期
而请求确实重复**：当请求内容与该合同周期当前状态完全一致时，服务端
返回 `200` 且响应体带 `no_change=true`，**不创建新的 `CORRECTION`
修订记录**，从根本上消除"审计噪音"问题；若请求基于已过期的旧状态
（例如期间已被其他会话修正过），则按 `expected_updated_at`/等价字段
的乐观并发校验返回 409（见 19.6.3 第 4 类冲突）。

**并发冲突**：`source_effective_date` 定位的周期若已被并发的其他修正/删除
操作改变（找不到匹配行），返回 404 而非静默创建新周期，防止误操作。

**影响范围**：同 19.1.3——失效该达人缓存、影响后续新建预览的合同解析、
不影响已存在的锁定/草稿版本。**与 19.1.3 的关键区别**：本操作绝不会在
`GET /api/compensation/periods` 意义上被展示为"该月新增了一次合同变更"，
而是被视为对现有周期定义的静默修正（前端历史时间线 UI 应把
`operation_type='CORRECTION'` 的修订记录与 `'CHANGE'` 记录用不同图标/颜色
区分展示）。

#### 19.1.5 `DELETE /api/creators/{id}/contract-periods/{source_effective_date}`（删除错误录入的周期）

对应
[database/koc_repository.py:970](../database/koc_repository.py:970)
`delete_authoritative_contract_period()`。用于彻底删除一段因录入失误而
产生、且不应该存在的合同周期（区别于 19.1.4 的"周期该存在但内容录错了"）。

**路径参数**：`source_effective_date`（`YYYY-MM-DD`，定位要删除的周期）。

**请求 body（可选）**：`{ "reason": "string" }`。

**返回（200）**：更新后的 `KOCRecord` 详情态。

**错误**：

| 状态 | code | 场景 |
|---|---|---|
| 404 | `NOT_FOUND` | 周期不存在（已刷新） |
| 422 | `VALIDATION_ERROR` | 该达人当前只剩一段合同周期（`len(rows) <= 1`），"每位达人至少需要保留一段合同周期"——不允许删至零段 |

**事务边界**：单事务内删除目标行、调整相邻周期的截止日期、
`_sync_master_contract_period()`、写入
`creator_contract_revision`（`operation_type='DELETE'`）。

**幂等性**：重复删除同一 `source_effective_date` 第二次会命中"周期不存在"
返回 404（而非 200），前端应将"删除后再次删除返回 404"视为预期行为，不
展示为错误提示，而是提示"该周期已被删除"。

**影响范围**：同 19.1.3/19.1.4；**保留策略（本契约定案）**：删除的周期
数据仍完整保存在 `creator_contract_revision.before_json` 中
（`operation_type='DELETE'` 记录的 `before_json` 就是删除前的完整周期
列表），删除是"从当前有效周期表移除"，不是物理销毁审计痕迹。
**达人合同周期列表（对应 `GET /api/creators/{id}` 的 `contract_periods`
及创建者合同周期管理表格 UI）必须提供一个默认关闭（OFF）的"显示已删除
记录"开关**：开关关闭时按当前行为只展示有效周期；开关打开时额外展示已被
19.1.5 删除的历史周期（只读，取自对应 `DELETE` 修订记录的 `before_json`），
供审计/追溯查看，不提供在该只读视图中直接编辑或恢复的能力（恢复应通过
19.1.3 重新新增一段周期完成，而非"撤销删除"）。

#### 19.1.6 `POST /api/creators/{id}/contract-revisions/{revision_id}/revert`（回滚到历史修订）

对应
[database/koc_repository.py:621](../database/koc_repository.py:621)
`revert_contract_revision()`。

**路径参数**：`revision_id`（`creator_contract_revision.id`）。

**请求 body（本契约定案，取代此前"可选"的表述）**：

```json
{ "reason": "误操作，实际不应新增该合同变更" }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `reason` | string，**必填**，1–500 字符 | 回退原因，写入新生成的 REVERT 修订记录的 `reason` 字段，用于审计追溯；**repository 层
`revert_contract_revision()` 当前签名未接收该字段，实现阶段必须扩展其参数
以接收并落库 `reason`——这是本次已确认的强制需求，不再是"是否扩展"的开放
问题，只是实现顺序上的前置改造项** |

**返回（200）**：更新后的 `KOCRecord` 详情态。

**错误**：

| 状态 | code | 场景 |
|---|---|---|
| 404 | `NOT_FOUND` | `revision_id` 不存在 |
| 422 | `VALIDATION_ERROR` | 目标本身是一条 `REVERT` 记录（不能再次撤销）；或已被撤销过（`reverted_at is not None`）；或 `reason` 缺失/为空/超过 500 字符 |
| 409 | `CONFLICT` | 该 `revision_id` 不是该达人"最近一次未撤销的修改"（`latest is None or int(latest["id"]) != revision_id`）——**只能按栈顺序（后进先出）撤销最近一次修改**，不支持跳跃式撤销任意历史节点，`message` 明确提示"只能撤销该达人最近一次未撤销的合同修改" |

**重要语义（本契约定案，已确认为最终决策，不再是开放问题）**：本操作
**在任何情况下都绝不允许物理删除历史修订记录**，而是**创建一条新的
`operation_type='REVERT'` 修订记录**，把当前周期表恢复为目标修订
`before_json` 记录的状态；原始修订记录本身仍保留在
`creator_contract_revision` 表中（仅打上 `reverted_at`/
`reverted_revision_id` 标记），符合"历史留痕、不物理删除"的整体审计原则，
与 19.1.1–19.1.5 的行为一致。

**事务边界**：单事务内完成目标周期表全量替换（`DELETE` 后按
`before_json` 重新 `INSERT`）、`_sync_master_contract_period()`、写入新的
REVERT 修订记录（含必填的 `reason`）、更新原修订记录的
`reverted_revision_id`/`reverted_at`。

**幂等性**：非幂等——对同一 `revision_id` 第二次调用会因
"已经撤销"（`reverted_at is not None`）返回 422，前端应据此判断"已撤销"
而非重试。

**影响范围**：同 19.1.3；此外，`GET /api/creators/{id}` 返回的
`contract_periods` 与 `GET .../contract-revisions`（若未来提供只读修订
历史查询，见第一阶段第 5 节暂缺此接口，属于后续只读接口补充范围）会立即
反映回滚结果。

#### 19.1.7 `GET /api/creators/{id}/contract-revisions`（只读修订历史，补齐 19.1.5/19.1.6 遗留缺口）

只读接口，复用 `list_contract_revisions()` 已有存储的
`creator_contract_revision` 记录，不引入新的业务写逻辑。返回该达人全部
修订记录（`CHANGE`/`CORRECTION`/`DELETE`/`REVERT`），按 `id` 倒序，每条包含
`before_periods`/`after_periods` 快照、`affected_start_date`/
`affected_end_date`、`reason`、`reverted_revision_id`、`reverted_at`、
`created_at`，并额外附带两个前端判定用字段：

| 字段 | 说明 |
|---|---|
| `is_deleted_period` | `operation_type == 'DELETE'` 时为 `true`，供"显示已删除记录"开关识别并展示 19.1.5 删除的历史周期 |
| `revertable` | 是否可通过 19.1.6 撤销——与 `revert_contract_revision()` 的"只能撤销最近一次未撤销、非 REVERT 的修改"规则完全一致（服务端计算，前端不得自行判断） |
| `status` | `REVERTABLE`/`REVERTED`/`REVERT_RECORD`/`SUPERSEDED` 之一，供前端在不可回退的记录上显示对应的disabled说明文案 |

**错误**：404（达人不存在）、401（未登录）沿用统一错误信封。

**影响范围**：只读，无写入；供"显示已删除记录"开关与逐行"回退"按钮消费。

---

### 19.2 投稿与导入

对应 [ui/data_processing.py](../ui/data_processing.py) 编排的 Excel
整理/校验流程，以及
[database/dashboard_repository.py:279](../database/dashboard_repository.py:279)
`save_monthly_import()` 与
[:234](../database/dashboard_repository.py:234) `upsert_posts()`。

#### 19.2.1 `POST /api/imports/preview`（第一步：上传并预览）

**请求**：`multipart/form-data`，一个或多个 Excel 文件。

**服务端处理**：复用现有整理管线（列名标准化、UID/达人库匹配、异业标记
`annotate_cross_industry_posts()`）对上传内容做**只读**整理，**不写入
`dashboard_post`**。

**返回 `data`**：

```json
{
  "preview_token": "string",
  "input_row_count": 320,
  "matched_row_count": 300,
  "unmatched_uid_count": 20,
  "unmatched_rows": [
    { "row_index": 12, "raw_uid": "abc123", "raw_name": "某某", "reason": "UID在达人库中不存在" }
  ],
  "period_months": ["2026-07"],
  "cross_industry_flagged_count": 5,
  "column_warnings": ["string"]
}
```

- `preview_token`：服务端为本次预览结果生成的临时凭证（建议 TTL 15–30
  分钟），供第二步 `POST /api/imports/{preview_token}/confirm` 引用，避免
  客户端把整理后的全量数据往返传输一次。
- `unmatched_rows`：**强制要求完整列出**每一条因创建者 ID/姓名匹配失败而
  未能关联到达人库的行，**禁止静默丢弃**——对齐需求"创建者 ID/姓名匹配
  失败在导入过程中必须产生显式、可见的错误"。前端必须在确认保存前把这些
  行展示给操作者，由人工决定：（a）先去达人库补录缺失的达人再重新导入，
  或（b）在确认保存时显式勾选"忽略未匹配行，仅保存已匹配部分"。**未匹配
  行默认不随确认保存写入**，除非操作者显式选择忽略。

**错误**：401、422（文件格式不可解析、非 `.xlsx`/`.xls`、必需列缺失）。

#### 19.2.2 `POST /api/imports/{preview_token}/confirm`（第二步：确认保存）

**请求 body**：

```json
{
  "mode": "replace_months",
  "include_unmatched": false,
  "source_file_names": ["7月投稿数据.xlsx"]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `mode` | enum，必填 | `replace_months`（按月完整替换，对齐 `save_monthly_import(replace_months=True)`）\| `append_or_update`（追加/更新，对齐 `replace_months=False`，等价于现有 `upsert_posts()` 的 upsert 语义） |
| `include_unmatched` | bool，默认 `false` | 是否连同 19.2.1 返回的 `unmatched_rows` 一并写入（此时这些行的 `koc_name` 等达人库字段为空，对齐现有 UI "相关投稿已保留，koc_name 为空"的行为） |
| `source_file_names` | array\<string\>，可选 | 覆盖预览阶段记录的文件名（用于展示） |

**返回（200）**：

```json
{
  "data": {
    "batch_id": 42,
    "mode": "REPLACE_MONTHS",
    "period_months": ["2026-07"],
    "input_count": 320,
    "saved_count": 300,
    "removed_count": 280
  }
}
```

字段对齐 `DashboardSaveResult`。

**错误**：

| 状态 | code | 场景 |
|---|---|---|
| 404 | `NOT_FOUND` | `preview_token` 不存在或已过期，`message` 提示"预览已过期，请重新上传" |
| 422 | `VALIDATION_ERROR` | `mode` 非法 |
| 500 | `INTERNAL_ERROR` | 写入过程异常 |

**事务边界（原子性，强制）**：`mode=replace_months` 时，"保存旧数据快照"→
"删除该批次覆盖月份的旧记录"→"写入新记录"必须在**同一数据库事务**内完成——
在现有 `save_monthly_import()` 内部单个 `connect()` 上下文中先 `DELETE`
后 `INSERT`/`UPSERT` 再写 `dashboard_import_batch` 的基础上，**新增一步：
`DELETE` 之前，先把即将被覆盖月份的 `dashboard_post` 全量行序列化写入新增
的快照表（例如 `dashboard_import_batch_snapshot`，按 `batch_id` 关联，
存储被替换前的完整记录 JSON），作为 19.2.3 真回滚的数据来源**；任一步失败
则整体回滚，`dashboard_post` 表中旧数据保持不变，**不允许出现"部分月份已
删除但新数据未写入完成"的中间态，也不允许出现"新数据已写入但旧快照未保存
成功"的中间态**。`mode=append_or_update` 不做删除，仅按
`record_key`（URL 归一化后的哈希，见 `_record_key()`）做 upsert，天然不
存在整体回滚需求之外的额外原子性要求。

**幂等性**：`Idempotency-Key` 强烈建议使用（属于"高风险操作"，见 19.6）。
去重语义定义为"同一个 `preview_token` 只允许成功确认一次"——`confirm`
接口内部应在事务开始时校验并锁定该 `preview_token` 的状态
（`pending`/`confirmed`），重复提交同一 `preview_token` 且已成功过一次，
直接返回首次成功的 `batch_id` 而不二次执行删除/写入，避免网络重试导致
"按月替换"被误执行两次而产生 `removed_count` 异常。

**并发冲突**：若两个操作者几乎同时对同一 `period_months` 发起
`replace_months` 确认，后到达的请求应返回 `409 CONFLICT`
（`message`："该月份数据正在被另一次导入替换，请稍后重试"），**不得**
允许两个 `replace_months` 事务交错执行。

**影响范围**：`GET /api/dashboard/summary`、`GET /api/dashboard/posts`、
`GET /api/dashboard/rankings`、`POST /api/dashboard/comparison`
（涉及 `period_months` 的部分）、`GET /api/dashboard/filter-options`、
`GET /api/dashboard/import-batches`、`GET /api/compensation/periods`
（`has_posts` 字段）、`GET /api/compensation/grassroot`/`long-term`/
`commentary` 的**预览**（`mode=preview`）结果全部失效并需要重新拉取；
**已存在的 `saved_draft`/`frozen` 结算版本不受影响**（读取的是保存时刻
快照，不随投稿数据变化）。

#### 19.2.3 `POST /api/dashboard/import-batches/{batch_id}/rollback`（导入批次回滚）

**新增写接口。** 对应"导入批次记录必须可审计、可真实回滚"的需求。**本
契约定案：回滚必须是真回滚（完整恢复被替换前的旧数据），"仅删除本批次
写入的记录、无法恢复旧数据"的方案不可接受。** 依赖 19.2.2 中新增的
`dashboard_import_batch_snapshot`（或等价快照存储）——该表在每次
`mode=replace_months` 执行时，于同一事务中保存被覆盖月份的
`dashboard_post` 完整旧数据；本端点即读取该快照做原子恢复。现有
repository 层暂无该仓储方法，实现阶段需新增"读取指定 `batch_id` 对应的
旧数据快照，并在同一事务内先删除本批次写入的新记录、再从快照原样
`INSERT` 回旧记录"的方法——本契约只定义 API 形状与语义约束，不预设其
内部 SQL 写法。

**请求 body**：`{ "reason": "string（可选）" }`。

**返回（200）**：

```json
{
  "data": {
    "batch_id": 42,
    "restored_count": 280,
    "removed_count": 300
  }
}
```

**错误**：404（`batch_id` 不存在，或该批次对应的快照缺失/已过期——理论上
不应发生，因为快照与批次同一事务写入且长期保留，若出现说明数据异常，
需按 500 而非静默 404 处理，具体错误码留待实现阶段结合快照保留策略
细化）、422（该批次早于最近一次针对同月份的后续导入，回滚会与更新的数据
冲突，此时应拒绝并提示"存在更新的导入批次，无法安全回滚，请联系管理员
处理"——**回滚只允许针对"最近一次覆盖某月份"的批次**，不支持跳跃式回滚到
任意历史批次，语义与 19.1.6 `revert_contract_revision()` 的"只能撤销最近
一次"原则保持一致）、409（并发回滚冲突）。

**事务边界（原子性，强制）**：单事务内完成"删除本批次写入的新记录"→
"从快照恢复旧记录"两步，整体成功或整体失败；不允许出现"新记录已删除但旧
记录未恢复"的中间态。

**快照保留策略（本契约定案）**：`dashboard_import_batch_snapshot` 长期
保留，不做 TTL 自动清理（不同于 19.2.1 的 `preview_token`），因为回滚是
低频但高风险的审计相关操作，需要保证任意时间点都能追溯到"最近一次替换前
的完整旧数据"；是否需要在数据量过大后引入归档策略，属于后续容量规划问题，
不影响本契约的接口语义。

**影响范围**：同 19.2.2。回滚成功后 `dashboard_post` 完整恢复为
被替换前的状态（不仅仅是"删除"），因此所有依赖 `period_months` 的读接口
与结算**预览**均需失效重新拉取；**已存在的 `saved_draft`/`frozen` 结算
版本不受影响**（快照已固化，不随投稿数据回滚而改变）。

#### 19.2.4 跨行业互斥标记 / 取消标记

对应 [database/dashboard_repository.py:163](../database/dashboard_repository.py:163)
`save_cross_industry_exclusions()`、
[:205](../database/dashboard_repository.py:205)
`deactivate_cross_industry_exclusions()`，均复用
[core/cross_industry.py](../core/cross_industry.py) 既有的 URL 归一化与
标记机制（`normalize_video_url()`/`annotate_cross_industry_posts()`），
**API 层不新造匹配逻辑**。

**`POST /api/cross-industry-exclusions`（新增/重新激活标记）**

请求 body：

```json
{ "urls": ["https://..."], "reason": "该视频为品牌合作，非本项目内容" }
```

返回 `data`：`list_cross_industry_exclusions()` 的最新数组（见
`database/dashboard_repository.py:134` 结构）。

**`DELETE /api/cross-industry-exclusions/{id}`（取消标记，软删除）**

对应 `deactivate_cross_industry_exclusions([id])`，仅将 `active` 置 0，
**不物理删除记录**（保留标记历史）。返回 `{ "data": { "deactivated": 1 } }`；
若 `id` 不存在或已是非激活状态，返回 `{ "data": { "deactivated": 0 } }`
而非报错（幂等）。

**强制不变量**：标记/取消标记**只影响判定字段
`is_cross_industry`/`compensation_eligible`（第 10 节 posts 接口）与后续
聚合口径**，`dashboard_post` 表中投稿自身的原始字段（播放量、标题、发布
日期等）**绝对不被修改**——标记机制是"叠加一层排除规则"而不是"编辑投稿
内容"，这一点与合同修正（19.1.4，会真正修改数据）有本质区别。

**事务边界**：单条 `INSERT ... ON CONFLICT DO UPDATE` / `UPDATE`，天然
原子。

**幂等性**：`url_key`（URL 归一化后的唯一键）天然幂等——重复标记同一 URL
只会更新 `reason`/`active`，不会产生重复记录。

**影响范围**：失效 `GET /api/dashboard/posts`（`is_cross_industry`/
`compensation_eligible` 字段）、`summary`/`rankings`/`comparison`
（当 `include_cross_industry=false` 时的聚合结果，即默认口径）、以及
所有结算**预览**（`exclude_cross_industry_posts()` 前置过滤）；不影响
已存在的 `saved_draft`/`frozen` 版本。

---

### 19.3 月度结算前置配置

对应各结算模块在"生成预览/草稿之前"需要人工录入的按月配置项，均为
"按 `period_month` 覆盖式保存"的幂等写接口，全部对应
[database/dashboard_repository.py](../database/dashboard_repository.py)
中已存在的 `INSERT ... ON CONFLICT DO UPDATE` 方法，**API 层不改写这些
方法的写入语义**。

#### 19.3.1 `PUT /api/compensation/{period_month}/exchange-rate`

**本契约定案（修正此前按赛道拆分路径的草案）**：JPY→USD 汇率是**按月
全局唯一的一个值**，不区分草根/长期/解说三条赛道——三条赛道共享同一个
`get_jpy_to_usd_rate(period_month)`/`save_jpy_to_usd_rate()` 读写口径
（`database/dashboard_repository.py:398`），路径不再挂在
`/api/compensation/grassroot/...` 之下，改为顶层
`/api/compensation/{period_month}/exchange-rate`，避免造成"三条赛道各自
有独立汇率"的误解。

请求：`{ "rate": 149.5 }`。

返回：`{ "data": { "period_month": "2026-07", "rate": 149.5 } }`。

**错误**：422（`rate <= 0`，对齐仓储层 `ValueError`；`period_month`
格式非 `YYYY-MM`）。

**事务边界**：单条 upsert，天然原子。**幂等性**：天然幂等（同值重复保存
无副作用）；不建议要求 `Idempotency-Key`。**并发**：不做乐观并发校验
（汇率是"整月覆盖"配置，后写覆盖先写是预期行为，不视为冲突）。

**影响范围（本契约定案）**：该月**草根、长期、解说三条赛道的当前
预览（`mode=preview`）** 全部立即按新汇率重算——因为三者共享同一个
`period_month` 维度的汇率值；**已 `saved_draft`/`frozen`（即
`LOCKED`）的版本完全不受影响**，无论属于哪条赛道，因为汇率在版本创建
（19.5.1）那一刻已作为 `jpy_to_usd_rate` 字段固化进该版本自己的快照，
本接口的后续修改绝不会回溯改写任何已保存草稿或已锁定版本所使用的汇率。

#### 19.3.2 `PUT /api/dashboard/{period_month}/traffic-boost`

**本契约定案（修正此前按赛道拆分路径、暗示"草根与长期各自独立配置"的
草案）**：流量加成开关是**按月全局唯一的一个开关**，对应看板第 8 节
`traffic_boost_mode=saved_setting` 所读取的同一张
`dashboard_traffic_boost_setting` 表（`get_traffic_boost_enabled()`/
`save_traffic_boost_enabled()`，`database/dashboard_repository.py:414/427`），
**全项目只有一个每月开关，不存在"草根一个开关、长期另一个开关"的独立
配置**——此前草案中"语义与草根‘下沉引流加成’是两个独立配置维度，实现时
不得混用同一张配置表"的表述是错误的，予以删除更正：该表就是唯一权威
存储，草根与长期都读取同一行。

路径改为顶层 `/api/dashboard/{period_month}/traffic-boost`（与看板模块
共用同一张配置表保持路径归属一致），请求/返回形状不变：

请求：`{ "enabled": true }`。返回：
`{ "data": { "period_month": "2026-07", "enabled": true } }`。

**影响范围（本契约定案，取代此前按赛道各自列出的版本）**：本开关影响
且仅影响以下三处：

1. 看板第 8 节 `GET .../summary`/`posts`/`rankings`/`comparison` 等在
   `traffic_boost_mode=saved_setting`（默认展示口径）下的 `views` 计算；
2. 草根结算的**当前预览**（`mode=preview`，不含 `saved_draft`/`frozen`）；
3. 长期结算的**当前预览**（`mode=preview`，不含 `saved_draft`/`frozen`）。

**明确不受影响**：解说（commentary）赛道——按第 18 章约定，解说结算口径
从不引入流量加成概念，本开关变化不触发解说预览的任何重算，解说结算
接口的 `meta` 中也始终不出现 `traffic_boost_enabled` 字段（详见第一阶段
第 8/9 节）；任何已 `saved_draft`/`frozen` 的草根或长期结算版本——
开关在版本创建时已固化为该版本快照的一部分（`traffic_boost_enabled`
字段，见 19.5.4），后续切换开关绝不会回溯改变已保存的版本。

**错误/事务/幂等/并发**：同 19.3.1。

#### 19.3.3 `PUT /api/compensation/long-term/{period_month}/activity-counts`

对应 `save_long_term_activity_counts()`（:477），**按 `creator_id` 批量
覆盖式保存**（传 `null`/缺省的达人会被 `DELETE`，等同清空该达人本月
活动数——需要在前端交互上明确提示"留空 = 清除已录入的活动数"，避免
误清空）。

请求：

```json
{ "activity_counts": { "101": 3, "102": null } }
```

`102` 传 `null` 表示删除该达人本月的活动数记录（对齐仓储层
`_clean_long_term_activity_count(None) -> None` 触发 `DELETE` 分支）。

返回：`{ "data": { "period_month": "2026-07", "updated_count": 2 } }`。

**错误**：422（`creator_id` 非法达人 ID、活动数非非负整数——对齐
`ValueError("每月活动数必须为非负整数。")`；`creator_id` 不存在——对齐
`ValueError("达人记录不存在。")`）。

**事务边界**：单个 `connect()` 内对 `activity_counts` 逐条
`DELETE`/`UPSERT`（仓储层当前实现是逐条 `execute` 而非
`executemany`，本契约按现状描述，不预设批量化优化）。**幂等性**：天然
幂等。**并发**：不做乐观并发校验（按月覆盖式配置）。

**影响范围**：该月 long-term 结算预览；不影响已锁定版本。

#### 19.3.4 评论区指定主题申报

`PUT /api/compensation/commentary/{period_month}/theme-submissions`

对应 `replace_commentary_theme_submissions()`（:1039），依赖
`list_commentary_theme_definitions()`（:974）做主题代码合法性校验。

请求（本契约定案：**整月完整替换**，见下）：

```json
{
  "expected_revision": "rev_20260710_1",
  "rows": [
    {
      "creator_id": 101,
      "theme_code": "SPRING2026",
      "content_format": "LONG",
      "urls": ["https://..."],
      "submitted_date": "2026-07-15",
      "review_status": "PENDING",
      "note": null
    }
  ]
}
```

**错误**：422，场景包括：`theme_code` 不在
`commentary_theme_definition` 中（对齐
`ValueError(f"指定主题不存在：{theme_code}")`）；同一达人同一主题重复
出现在同一请求中（对齐 `ValueError("同一达人同一主题每月只能申报一次。")`）；
`content_format` 不在 `{LONG, SHORT}`；`review_status` 不在
`{PENDING, APPROVED, REJECTED}`。409（`REVISION_EXPIRED`）：
`expected_revision` 与服务端当前该月的最新修订标识不一致，说明期间已被
其他会话保存过一次新的完整列表，`message` 提示"该月申报列表已被其他会话
更新，请刷新后基于最新列表重新提交"。

**关键不变量（必须与第 18 章保持完全一致，不得在此重新定义）**：
指定主题一旦审核通过（`review_status=APPROVED`），**无论其 URL 是否与
投稿库中的实际链接匹配，都计入该达人本月的奖励**；只有"已匹配到具体
投稿链接"的部分会从"可计费/去重"视图中排除，避免重复计酬——该规则的
唯一权威定义在第 18 章，本节仅描述"如何提交/编辑申报"，不重新定义匹配
与排除口径。

**语义（本契约定案，取代此前"需实现时确认范围"的开放问题）**：
`replace_commentary_theme_submissions()` 在本接口中**必须**按"整月完整
替换"语义使用——即每次调用都代表该 `period_month` 下**全部**申报记录的
最新完整状态，**绝不允许把局部/增量 payload 直接透传给该函数从而静默
覆盖/丢弃当月其他未包含在本次请求中的申报记录**。前端交互流程固定为：
（1）先调用读接口取回该月完整的当前申报列表及其 `expected_revision`
标识；（2）在本地基于该完整列表做增删改；（3）把修改后的**完整列表**
连同读取到的 `expected_revision` 一并提交给本接口。服务端在同一事务内
校验 `expected_revision` 匹配后原子替换该月全部记录；若 `expected_revision`
已过期（服务端当前修订与之不一致），拒绝并返回 409（见上），**不做部分
合并**。若现有 `replace_commentary_theme_submissions()` repository 方法
签名尚不支持 `expected_revision` 校验，实现阶段需扩展其参数以支持——这是
已确认的实现前置改造项，不再是语义层面的开放问题。

**幂等性**：整体替换语义下天然幂等（相同 `rows`+ `expected_revision`
重复提交结果一致；`expected_revision` 过期的重复提交会稳定返回 409 而非
重复生效，避免误判为"成功"）。**并发**：通过 `expected_revision` 做乐观
并发校验（见上），不再是"不做校验"。

**影响范围**：该月 commentary 结算预览（申报是否计入奖励、匹配排除
判定）；不影响已锁定版本。

---

### 19.4 粉丝更新

对应 [services/follower_service.py](../services/follower_service.py)
`FollowerService`，API 层**不重新实现**平台识别/抓取/成功失败落库逻辑，
只是把已有的 `update_one`/`preview_tiktok`/`confirm_tiktok_preview`/
`update_many`/`update_all_tiktok`/`update_all_youtube` 包装为 HTTP 接口。

**平台路由规则（不变量，与 `FollowerService._contract_platforms()` 保持
完全一致）**：达人的合同类型文本中若包含 `"tt"`/`"tiktok"`
（大小写和空格不敏感）则视为持有 TikTok 合同，若包含
`"ytb"`/`"youtube"` 则视为持有 YouTube 合同；仅持有其一时，
`required_platform_for_record()` 唯一确定抓取平台；**同时持有两者或都不
持有时返回 `None`，此时前端必须让操作者手动指定平台**，不得由 API 层
臆测。命名规则里的 "TT" 前缀正是这里"TikTok 合同"判定的来源，API 层
不新增额外的命名解析规则。

#### 19.4.1 `POST /api/followers/{creator_id}/update`（单个手动更新）

对应 `update_one()`。请求 body：`{ "required_platform": "TikTok" }`
（可选；缺省时由 `record.homepage_url` 与合同类型推断）。

返回（200，无论抓取成功或失败都是 200，因为"抓取失败"是业务结果而非
HTTP 错误）：

```json
{
  "data": {
    "record_id": 101, "user_id": "abc", "koc_name": "某某",
    "status": "成功", "platform": "TikTok", "follower_count": 15000,
    "error_code": null, "message": "更新成功"
  }
}
```

`status` ∈ `{成功, 跳过, 失败}`，对齐 `_save_result()` 的三分支：
成功写入 `apply_follower_success()`（`sync_status=SUCCESS`,
`operator_mode=AUTOMATIC`）；`error_code` 属于 `SKIPPED_ERROR_CODES` 时
写入 `record_follower_attempt()`（记录尝试但不算失败，例如
`DATA_SOURCE_NOT_CONFIGURED` 等已知的"暂不可用"场景）；其余失败写入
`apply_follower_failure()`。**三种结果都会落库（成功值/跳过原因/失败
原因），不存在"什么都不记录"的静默情况**。

**错误**：404（`creator_id` 不存在，对齐 `ValueError("未找到要更新粉丝数
的达人。")`）。

**事务边界**：单条 upsert（`apply_follower_success`/
`apply_follower_failure`/`record_follower_attempt` 各自内部单事务）。
**幂等性**：重复调用会重新抓取并覆盖上一次结果——**这不是传统意义的
幂等写（结果可能因外部数据源变化而不同），不要求 `Idempotency-Key`**；
但重复调用不会产生副作用叠加（每次都是"覆盖式"落库，不是"追加"）。
**并发**：不做乐观并发校验（抓取结果覆盖是预期行为）。

#### 19.4.2 TikTok 预览确认二步流程

**`POST /api/followers/{creator_id}/tiktok-preview`** —— 对应
`preview_tiktok()`：只抓取、不落库，返回抓取结果供人工核对
（TikTok 抓取依赖浏览器自动化，结果不总是可信，因此设计为"先看一眼
再决定是否采纳"）。

返回：`{ "data": { "follower_count": 15000, "platform": "TikTok", "success": true, "error_code": null } }`。

**`POST /api/followers/{creator_id}/tiktok-preview/confirm`** —— 对应
`confirm_tiktok_preview()`：请求体需回传上一步返回的完整抓取结果
（`follower_count`/`platform`/`success` 等字段，供服务端重新构造
`FollowerFetchResult` 并落库），**服务端不重新抓取，只落库**。

**错误**：422（`success=false` 或 `platform != "TikTok"` 或
`follower_count` 为空——对齐 `ValueError("只能确认写入成功的 TikTok
测试结果。")`）；404（`creator_id` 不存在）。

**幂等性**：与 19.4.1 相同，覆盖式落库不叠加副作用。**并发**：不做
乐观并发校验。

#### 19.4.3 批量更新（本契约定案：改为异步任务 + 状态轮询模式）

**取代此前"同步长请求"设计**：批量更新（尤其 TikTok 浏览器自动化）耗时
不可控，同步长请求容易触发前端/网关/浏览器层面的 HTTP 超时。本契约确定
采用"创建任务 → 轮询进度 → 读取明细结果"的异步任务模式，取代原先单个
同步 `POST /api/followers/batch-update` 直接返回完整
`BatchFollowerUpdateResult` 的设计。三个端点如下，底层仍复用现有
`update_many()`（及 `update_all_tiktok()`/`update_all_youtube()`，见
19.4.4）逐条抓取/落库的既有逻辑，**API 层不重新实现批量更新的业务规则，
只是把同步调用改造为在后台任务中执行、并暴露任务状态查询接口**。

**`POST /api/followers/batch-update-jobs`（创建批量更新任务）**

请求 body：

```json
{
  "record_ids": [101, 102, 103],
  "required_platform": null,
  "platform_by_record": { "101": "TikTok", "102": "YouTube" }
}
```

字段含义同此前 19.4.3 草案（`record_ids`/`required_platform`/
`platform_by_record`）。**返回（202）**：

```json
{ "data": { "job_id": "job_abc123", "status": "PENDING", "total": 3, "created_at": "2026-08-10T10:00:00Z" } }
```

服务端立即返回 `job_id`，实际抓取在后台异步执行（内部仍是对
`update_many()` 的调用，只是执行位置从"请求处理线程内同步等待"改为
"后台任务/队列"）。**错误**：422（`record_ids` 为空）。

**`GET /api/followers/batch-update-jobs/{job_id}`（轮询任务进度）**

返回：

```json
{
  "data": {
    "job_id": "job_abc123",
    "status": "RUNNING",
    "total": 3, "processed": 1,
    "success": 1, "failed": 0, "skipped": 0,
    "youtube_success": 1, "youtube_failed": 0,
    "tiktok_success": 0, "tiktok_failed": 0,
    "started_at": "2026-08-10T10:00:01Z",
    "finished_at": null
  }
}
```

`status` ∈ `{PENDING, RUNNING, SUCCEEDED, FAILED}`（`FAILED` 仅指任务本身
异常终止，不代表批次内某些记录抓取失败——单条记录失败属于正常业务结果，
反映在下方明细接口的 `status=失败` 行中，不影响任务整体 `status`）。
前端以固定间隔（建议 2–3 秒）轮询直至 `status` 进入终态
（`SUCCEEDED`/`FAILED`）。

**`GET /api/followers/batch-update-jobs/{job_id}/results`（只读，逐条
成功/失败明细）**

任务进入 `SUCCEEDED` 后可读取完整明细（`RUNNING`/`PENDING` 阶段返回已
处理部分的明细，供前端做"实时进度列表"展示亦可）：

```json
{
  "data": {
    "job_id": "job_abc123",
    "rows": [ { "user_id": "abc", "koc_name": "某某", "status": "失败", "platform": "TikTok", "follower_count": null, "tiktok_username": null, "error_code": "RECORD_NOT_FOUND", "message": "达人记录不存在。" } ]
  }
}
```

`rows` 明细字段（`_detail_row()`：`user_id`/`koc_name`/`status`/
`platform`/`follower_count`/`tiktok_username`/`error_code`/`message`）
与此前同步设计中的返回结构完全一致，只是从"同步响应体"搬到了本只读
明细接口。

**逐条失败不中断整批**：单条 `RECORD_NOT_FOUND`/抓取失败只记录该行的
`status=失败`，任务继续处理后续 `record_id`（对齐 `update_many()` 的
`for` 循环体，非抓取异常不会中断循环）；只有 TikTok 批次因
`TIKTOK_BATCH_STOP_ERROR_CODES` 中的错误码触发"批次熔断"时，才会对
**尚未处理的剩余记录**统一标记为 `status=失败`、
`error_code=TIKTOK_BATCH_STOPPED`（对齐 `_stopped_result()`），这是为了
避免在 TikTok 反爬限制触发后继续无意义地发起大量请求，此时任务本身仍以
`status=SUCCEEDED` 结束（熔断是批次级别的业务保护，不是任务执行异常）。
**这一"熔断"不等同于事务回滚**——已经成功写入的记录不会被撤销。

**同批次重复 ID/用户名跳过**：`update_many()` 内部对
`seen_user_ids`/`seen_tiktok_usernames` 做同批次去重，重复者标记
`status=跳过`、`error_code=DUPLICATE_CREATOR`，避免同一账号在一次批次
里被处理两次导致的资源浪费或数据竞争。

**幂等性**：创建任务接口不做防重复创建校验（同 19.5.1 的设计取舍——
每次调用都创建一个新 `job_id`，防止误触发产生重复任务是前端交互层
责任）；任务内部的落库行为同 19.4.1，覆盖式落库不叠加副作用。
**并发**：不做乐观并发校验；同批次内部去重已覆盖"同批次并发"场景。

**实现前置事项**：具体任务队列/后台执行机制（进程内线程池、独立
worker 进程、或引入任务队列中间件）由实现阶段按现有部署环境选型，本
契约只约束上述三个端点的请求/响应形状与状态机语义。

#### 19.4.4 `POST /api/followers/batch-update-jobs/all-tiktok` / `all-youtube`

对应 `update_all_tiktok()`/`update_all_youtube()`：分别对
`tiktok_contract_records()`（持有 TikTok 合同的全部达人）与对应
YouTube 全量集合创建 19.4.3 同结构的批量更新任务，底层复用 19.4.3 的
`update_many()` 逻辑与异步任务/轮询/明细三端点结构，**API 层不重复定义
批量更新的业务规则**。

**TikTok 候选人筛选规则（动态判定，禁止固定白名单）**：`all-tiktok`
及 19.4 全部涉及"是否属于 TikTok 更新对象"判定的接口/筛选逻辑，必须以
达人**当前生效合同周期**的**动态合同类型**为准——即取该达人当前有效的
合同变更记录中实际生效的合同类型文本，而非任何写死的查表结果。判定
规则统一为：将合同类型文本做大小写归一化（`lower()`）后，只要**包含
子串 `"tt"`**即视为 TikTok 更新候选人。**禁止使用固定枚举白名单**（例如
`["TT", "4月TT", "5月TT"]`），必须是子串匹配而非枚举匹配，这样才能自动
覆盖未来新增的合同类型命名，例如 `6月TT`、`YTB长+TT`，或任何其他将来
出现的、包含 "TT" 的合同类型字符串，无需修改判定逻辑即可自动纳入。

**`tiktok_user_id` 前置校验**：候选人还必须具备有效的 `tiktok_user_id`
才能真正发起抓取；若某达人合同类型判定为 TikTok 候选但缺失
`tiktok_user_id`，**不得**因此中断或失败整个批次，而是在该批量任务的
逐条结果明细（19.4.3 `.../results` 接口的 `rows`）中为该达人单独记录一条
`status=失败`（或 `跳过`，与 `SKIPPED_ERROR_CODES` 分类一致）、附带对应
`error_code`/`message` 说明"缺失 tiktok_user_id"，其余达人正常继续处理。

**影响范围（19.4 全部接口共同）**：`GET /api/creators`/
`GET /api/creators/{id}`（`follower_count`/`follower_updated_at` 等
字段）、依赖粉丝数的结算预览（若结算规则中有粉丝数分档逻辑，见
`core/*_compensation.py`）；**不影响已 `saved_draft`/`frozen` 的结算
版本**（粉丝数已固化进快照）。粉丝更新**从不需要**
`Idempotency-Key`（抓取结果本身具有时效性，重复请求应重新抓取而非
返回缓存结果）。

---

### 19.5 报酬结算版本

对应三条结算赛道各自的
`create_*_draft()`/`update_*_draft()`/`lock_*_version()` 三件套
（草根：`create_compensation_draft`/`update_compensation_draft`/
`lock_compensation_version`，:667/:706/:743；长期：
`create_long_term_compensation_draft`/`update_long_term_compensation_draft`/
`lock_long_term_compensation_version`，:779/:818/:855；评论区：
`create_commentary_compensation_draft`/`update_commentary_compensation_draft`/
`lock_commentary_compensation_version`，:1133/:1177/:1214）。三条赛道
的 API 形状完全对称，以下以草根为例给出完整定义，长期/评论区仅列出
差异点。

**版本三态模型（权威定义见第 18 章 18.0 第 2 点，本节仅引用、不重新
定义）**：`preview`（实时按当前数据重算，不落库、无 `version_id`）→
`saved_draft`（`status=DRAFT`，落库快照，仍可编辑）→
`frozen`（`status=LOCKED`，落库快照，**不可再编辑**）。19.5 只负责
`saved_draft`/`frozen` 两态的写操作；`preview` 态是纯读接口（见第一阶段
第 8 节结算预览），不在本节范围。

#### 19.5.1 `POST /api/compensation/grassroot/{period_month}/drafts`（创建草稿）

对应 `create_compensation_draft()`。请求 body：

```json
{
  "jpy_to_usd_rate": 149.5,
  "details": [ { "creator_id": 101, "...": "..." } ],
  "summary": { "total_jpy": 1000000 },
  "note": "7月首次提交"
}
```

**说明**：`details`/`summary` 由前端从当前 `preview` 接口获取的完整
计算结果原样提交（**前端不重新计算，只是把已展示给操作者确认过的
预览结果落库**）——这是"预览 → 草稿"的确认落库模式，本质是 19.6 中
"预览/确认二步流程"的一个实例：先调用只读预览接口看到结果，操作者
确认无误后再调用本接口把该次预览结果固化为可追溯的草稿版本。

**返回（201）**：`CompensationVersion` 完整结构
（`id`/`period_month`/`version_no`/`status=DRAFT`/`jpy_to_usd_rate`/
`details`/`summary`/`note`/`created_at`/`updated_at`）。`version_no`
在同一 `period_month` 内自增（`MAX(version_no)+1`，同一 `connect()`
事务中先查后插，避免并发下 `version_no` 冲突）。

**实现前置事项（本契约定案，非假设）**：`(period_month, version_no)`
组合是本节及 19.5.2/19.5.3 全部并发/冲突判定逻辑的最终防线（"先查后插"
只能降低但不能完全消除并发窗口下的重复）。**在实现本节写接口之前，
必须先核实数据库 schema 中 `grassroot_compensation_version`/
`long_term_compensation_version`/`commentary_compensation_version`
三张表是否已存在 `(period_month, version_no)` 唯一约束；若不存在，必须
先编写迁移添加该约束，并补充相应的约束生效测试（例如并发插入同一
`version_no` 时数据库层应拒绝第二次插入），再开始实现本章写接口**——
这是一项前置验证/迁移任务，不是可以延后或默认已具备的假设。

**错误**：422（`jpy_to_usd_rate <= 0`）。

**幂等性**：**不使用 `Idempotency-Key` 做"防重复创建"**——每次调用都
应该创建一个新版本（`version_no` 递增），这是设计意图，"防止误触发
产生多个几乎相同的草稿"是前端交互层面的责任（例如按钮提交后禁用），
不是服务端幂等语义的责任。若网络重试导致同一次操作被提交两次，会产生
两个内容相同但 `version_no` 不同的草稿——**这是可接受的（草稿可以被
后续删除或直接被更高 `version_no` 的草稿取代），不视为数据损坏**。

**事务边界**：单个 `connect()` 内"查询下一个 `version_no`" +
"INSERT" + "回读"，整体在一个事务内完成。

**影响范围**：`GET /api/compensation/grassroot/versions?period_month=`
列表新增一条；不影响其他版本。

#### 19.5.2 `PUT /api/compensation/grassroot/drafts/{version_id}`（更新草稿）

对应 `update_compensation_draft()`。请求 body 同 19.5.1（去掉
`period_month`，改为路径参数隐含）。

**核心不变量（强制）**：仓储层 `UPDATE ... WHERE id = ? AND
status = 'DRAFT'` —— **只有 `status=DRAFT` 的版本能被更新，
`LOCKED` 版本的 `UPDATE` 会因 `WHERE` 条件不匹配而 `rowcount=0`**，
API 层据此区分两种 404 语义：`version_id` 完全不存在，与
`version_id` 存在但已 `LOCKED`（后者应返回更明确的错误）：

| 状态 | code | 场景 |
|---|---|---|
| 404 | `NOT_FOUND` | `version_id` 不存在 |
| 409 | `VERSION_LOCKED` | `version_id` 存在但 `status=LOCKED`，`message`："该结算版本已锁定，如需修正请创建新草稿"（对齐 19.5 全局不变量：LOCKED 版本永不可变） |
| 422 | `VALIDATION_ERROR` | `jpy_to_usd_rate <= 0` |

（实现时需要先查一次版本当前状态以区分 404 与 409，而不是仅凭
`UPDATE` 的 `rowcount=0` 笼统返回 404——这是对仓储层当前
"`rowcount != 1` 一律 `raise ValueError`"行为的 API 层细化包装，
仓储层本身不需要改动。）

**事务边界**：单条 `UPDATE`，天然原子。**并发**：`If-Unmodified-Since`
可选支持（基于 `updated_at`）；即使不做乐观并发校验，`status=DRAFT`
条件本身已经是一种"结构性并发保护"——一旦被锁定，后续更新自动失败。

**影响范围**：同 19.5.1。

#### 19.5.3 `POST /api/compensation/grassroot/drafts/{version_id}/lock`（锁定版本）

对应 `lock_compensation_version()`。**请求 body（本契约定案，取代此前
"无需额外字段"的表述）**：

```json
{ "lock_note": "7月草根结算，已核对无误，正式锁定" }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `lock_note` | string，**必填**，1–500 字符 | 锁定说明/备注，写入该结算版本记录（或其审计字段）；`lock_compensation_version()` 当前签名若未接收该字段，实现阶段需扩展参数以接收并落库——这是已确认的实现前置改造项 |

**`operator_name` 绝不由客户端在请求体中传入或伪造**：锁定操作的
操作人姓名一律从服务端 session 中自动读取（见 19.6.1/19.6.7 的
`operator_name` 登录字段约定）并写入审计记录，**API 层必须显式忽略/
拒绝请求体中任何试图传入 `operator_name`/`operator` 字段的尝试**（若
出现此类字段，建议返回 422 `VALIDATION_ERROR` 而非静默忽略，防止
客户端误以为自定义值会生效）。

**核心不变量（最高优先级，贯穿全文档）**：**已 `LOCKED` 的结算版本
永不改变，无论后续合同、汇率、投稿、粉丝数如何变化**——这是 19 章全部
写接口共同遵守的红线：任何写接口都不得、也没有能力修改
`status=LOCKED` 的 `grassroot_compensation_version`/
`long_term_compensation_version`/`commentary_compensation_version`
记录；发现数据需要修正时，**唯一合法路径是创建新草稿
（19.5.1）→ 核对 → 再次锁定**，绝不「就地编辑已锁定版本」。

**错误**：404（不存在）、422（`VALIDATION_ERROR`，`lock_note` 缺失/为空/
超过 500 字符；或请求体中出现 `operator_name`/`operator` 字段，见上）、
409（`VERSION_ALREADY_LOCKED`，重复锁定同一已锁定版本；对齐仓储层
`rowcount != 1` 时机——即"该 `version_id` 当前不是 `DRAFT` 状态"，此时按
"已锁定"与"不存在"两种可能细化为 404/409，处理方式同 19.5.2）。

**幂等性**：**不建议依赖 `Idempotency-Key` 做防重复锁定**——`status`
字段本身即是幂等保护：第二次锁定请求会因 `WHERE status='DRAFT'` 不
匹配而失败并返回 409，天然防止"重复锁定"产生副作用；因此对
"锁定"操作而言 409 恰好同时承担"已完成同一操作"的提示语义，前端应把
409 + `VERSION_ALREADY_LOCKED` 展示为"该版本已锁定"而非报错阻断流程。

**事务边界**：单条 `UPDATE`，天然原子。

**影响范围**：该版本成为该月"最终"结算结果，前端所有引用该
`period_month` 最新 `LOCKED` 版本的展示（例如结算历史列表、导出）需要
刷新；**不影响其他月份或其他版本**；该版本一旦锁定即从此不再随 19.3
（汇率/加成/活动数/主题申报）或 19.1/19.2/19.4
（合同/投稿/粉丝数）的后续任何写操作而改变——这是因为
`details_json`/`summary_json`/`jpy_to_usd_rate` 都是**创建草稿那一刻
的完整快照**，不是对源表的引用。

#### 19.5.4 长期赛道与评论区赛道的差异点

- **长期**：`create_long_term_compensation_draft`/
  `update_long_term_compensation_draft`/
  `lock_long_term_compensation_version`
  （`database/dashboard_repository.py:779/818/855`），路径前缀
  `/api/compensation/long-term/...`，快照字段除
  `details`/`summary`/`note` 外还需固化当月的
  `traffic_boost_enabled`（19.3.2）与 `activity_counts`（19.3.3），
  具体快照结构以仓储层方法签名为准，实现时需逐字段核对，本契约不
  重复列出仓储层内部字段名。
- **评论区**：`create_commentary_compensation_draft`/
  `update_commentary_compensation_draft`/
  `lock_commentary_compensation_version`
  （`:1133/1177/1214`），路径前缀
  `/api/compensation/commentary/...`，快照需固化当月的
  `theme_submissions`（19.3.4）。
  **指定主题规则（已获批准即计入奖励、只有匹配链接被排除计费）在快照
  落库时必须按第 18 章定义的口径计算好再存入 `summary_json`，API 层
  不在锁定时刻重新解释该规则**。
- 三条赛道的 404/409/422 错误语义、`LOCKED` 不可变红线、
  幂等/并发处理方式与 19.5.1–19.5.3 完全一致，不再重复列出。

---

### 19.6 通用写入安全（适用于本章全部写接口）

#### 19.6.1 认证

与读接口完全一致，依赖 `require_session`（`Depends(require_session)`，
见 `api/main.py`，第一阶段第 14 章已定义 Cookie 规范）。写接口**不**
引入额外的认证机制。

**本契约定案（不再是占位方案）**：`POST /api/auth/login`（第一阶段第 2
章）登录请求体在原有 `password` 基础上**新增必填字段
`operator_name`（string，2–30 字符）**，与团队共享密码一并提交；服务端
校验通过后，将 `operator_name` 与该次登录产生的 `session_id` 一并存入
服务端 session 状态（沿用第 14 章已定义的 Cookie/session 机制，不新增
认证渠道）。**本章全部高风险写操作的审计记录都必须包含 `operator_name`、
`session_id`、时间戳、操作类型这四项**，取代此前 19.6.7 中"占位
`operator: "team"`"的方案（详见 19.6.7）。**注**：由于本次编辑范围限定
在第 19 章，`POST /api/auth/login` 所在的第 2 章正文本身的字段定义
（当前仍写着 `{ "password": "string" }`，未包含 `operator_name`）需要
在后续一并同步更新为要求 `operator_name`，此处先在第 19 章明确该
登录字段变更的业务要求，具体第 2 章文本修订留待下一次编辑动作完成。

#### 19.6.2 写接口禁止自动重试（硬性规则）

`api/main.py` 中的 `DatabaseResilienceMiddleware` 明确写着"Bounded
single retry for GET requests hit by a dead/lost DB connection"、
"At most one retry is ever attempted (never a loop)"——**该中间件的
自动重试逻辑当前只对幂等的只读 GET 生效**。本章新增的全部写接口
（POST/PUT/PATCH/DELETE）**必须被排除在任何自动重试中间件之外**，
无论现在还是将来：即便请求因网络中断等原因未确认成功，也绝不能由
框架层自动重发一次写请求，因为写请求（尤其是月度导入的
`replace_months`、结算版本锁定）重复执行的后果可能是不可逆的
（数据被误删/误覆盖/误重复锁定报错）。**唯一允许的"重试"是由前端在
明确知道上一次请求结果未知的情况下，携带相同 `Idempotency-Key`
重新发起同一请求**（见 19.6.4），且这是应用层的显式重试，不是框架
层的隐式自动重试。

#### 19.6.3 事务与乐观并发

- 每个写接口的多表操作必须在**同一个 `connect()` 事务**内完成
  （复用现有仓储层方法自带的事务边界，API 层不得跨多次
  `connect()` 调用拼凑一个"逻辑事务"）。
- 对"编辑既有资源"类接口（19.1.2 达人资料编辑等），使用
  `updated_at`（或等价 revision 字段）做乐观并发检测：客户端携带
  `If-Unmodified-Since`（或 `If-Match` + 版本号），服务端比对后
  发现被别人抢先修改则返回 `409 CONFLICT`。
- 对"状态机迁移"类接口（19.5 草稿→锁定），`status` 字段本身就是
  天然的并发保护（`WHERE status='DRAFT'` 条件不满足即失败），**不
  需要额外的 `updated_at` 校验**，但仍需返回结构化的 409。
- **"显著冲突"的判定按实体类型分别处理，不做统一的单一定义，且各自
  返回各自专属的 409 业务 code（本契约定案）**：本章至少存在四类彼此
  独立、互不复用的 409 场景，**每一类都必须使用自己专属的 code，而不是
  统一塌缩成一个通用 `CONFLICT`**——
  1. **合同周期重叠**：`(creator_id, effective_date)` 唯一性与区间重叠
     判定（19.1.3/19.1.4），使用 `CONFLICT`（该类场景本身已足够具体，
     由 `message` 区分"该月已有周期"/"周期重叠"两种子情形）；
  2. **导入月份重叠**：并发 `replace_months` 命中同一 `period_months`
     （19.2.2），使用 `CONFLICT`（`message`区分具体重叠月份）；
  3. **结算版本状态冲突**：草稿更新/锁定命中非 `DRAFT` 状态
     （19.5.2/19.5.3），使用 `VERSION_LOCKED`（更新一个已锁定草稿）与
     `VERSION_ALREADY_LOCKED`（重复锁定）两个更具体的 code，不与上面的
     通用 `CONFLICT` 混用；
  4. **乐观锁/过期修订**：`If-Unmodified-Since`/`If-Match`/
     `expected_updated_at`/`expected_revision` 过期（19.1.2、19.3.4、
     结算修正相关场景），使用 `CONFLICT`（19.1.2）或
     `REVISION_EXPIRED`（19.3.4，见该节）等按具体端点定义的专属 code。

  粉丝更新与前置配置类"覆盖式保存"接口（19.3.1–19.3.4 中不涉及乐观锁的
  部分、19.4）**不视为需要冲突检测的场景**（后写覆盖先写是预期行为）。
  **上述四类划分是本次契约写作过程中做出的分类判断，产品侧确认后即为
  最终设计，不再是开放问题。**

**补充：重复提交与幂等冲突的组合处理（本契约定案，回应"合同修正重复
提交"场景，同样适用于其余携带 `Idempotency-Key` 的高风险写接口）**

同一操作若被前端因网络重试等原因提交多次，按以下优先级处理，三条规则
不冲突、可同时生效：

1. **相同 `Idempotency-Key` 的重复请求** → 直接返回服务端缓存的首次
   成功结果（见 19.6.4 缓存机制），不重新执行业务逻辑，不产生新的
   审计/修订记录。
2. **请求内容与目标资源当前状态完全一致（无变化）** → 即使
   `Idempotency-Key` 不同或未携带，只要服务端判定"本次提交的结果与
   该资源当前状态相同"，返回 `200` 且响应体带 `no_change=true`
   标记，**不创建新的修订/版本记录**（避免产生大量内容重复的审计
   噪音）。此规则目前明确适用于 19.1.4 合同修正类"确认性重复提交"
   场景，其余按"覆盖式保存"设计的端点（19.3.1–19.3.4）本身就是
   幂等覆盖，天然满足同等效果，不需要单独实现 `no_change` 判定。
3. **其余"不相同、也不是同一 `Idempotency-Key`"的旧/过期请求**
   （例如基于过期数据构造的修正请求）→ 通过
   `expected_updated_at`/`expected_revision` 等乐观并发字段判定，
   命中则返回 409（见 19.6.3 第 4 类），不静默接受。

#### 19.6.4 `Idempotency-Key`

- 适用范围：19.2.2（导入确认）、19.1.3/19.1.4（合同变更/纠错）、19.1.6
  （合同回退）、19.3.4（指定主题申报，全量替换场景）、19.5.1（创建
  结算草稿，建议但非强制，因为重复创建是可接受的，见 19.5.1 说明）。
  **不适用**：19.4（粉丝更新，抓取本身非确定性）、19.3.1/19.3.2/19.3.3
  （覆盖式配置保存，天然幂等）、19.5.3（锁定，`status` 字段天然幂等）。
- **服务端缓存机制（本契约定案，取代此前"方向性建议"的表述）**：
  高风险写操作携带 `Idempotency-Key` 时，服务端按
  **"操作类型 + `session_id` + `Idempotency-Key` + 请求体哈希"**
  作为缓存键，缓存该键对应的**首次执行结果**（响应体与状态码），
  **保留 24 小时**；24 小时内收到相同缓存键的重复请求，直接返回首次
  缓存的结果，不重新执行任何数据库写入；超过 24 小时后同一
  `Idempotency-Key` 再次出现，视为全新请求重新执行（不再命中缓存）。
  请求体哈希纳入缓存键是为了防止"相同 `Idempotency-Key` 但请求体已
  变化"被误判为重复请求——若命中相同缓存键但请求体哈希不一致，视为
  客户端误用，应返回 422（`IDEMPOTENCY_KEY_REUSED`，`message` 提示
  "该幂等键已用于不同的请求内容，请更换新的 Idempotency-Key"）。
- **与数据库天然唯一约束的关系（本契约定案）**：`Idempotency-Key`
  缓存机制与数据库层的自然业务唯一性约束（例如 `user_id` 唯一约束、
  `(creator_id, effective_date)` 唯一约束、`(period_month, version_no)`
  唯一约束等）是**两套独立生效、互不替代的机制**——前者解决"同一次
  用户操作因网络重试被误发送多次"的请求层去重问题，后者解决"两个
  不同来源的请求试图创建同一业务实体"的业务层去重问题。即使
  服务端未收到 `Idempotency-Key`（或客户端未携带），数据库唯一约束
  仍然独立生效并在冲突时触发 409；即使携带了
  `Idempotency-Key`，数据库唯一约束检查依然按既有逻辑执行，不因
  存在幂等缓存而被跳过。

#### 19.6.5 预览/确认二步流程与缓存失效范围

本章多个高风险写操作采用"预览（只读）→ 确认（写入）"两步模式
（19.2.1→19.2.2 导入；19.5 的"预览接口→创建草稿"事实上也是同一模式的
变体）。前端（Next.js + TanStack Query）实现时：

- 预览请求的结果**不应该**被 TanStack Query 当作可长期缓存的
  "服务器状态"缓存（`preview_token` 有 TTL，缓存过期即失效）。
- 确认成功后，必须显式 `queryClient.invalidateQueries` 每个写接口
  文档中"影响范围"一节列出的全部 query key，**不依赖自动
  refetchOnWindowFocus 等隐式机制**兜底关键业务数据的一致性。
- 每个写接口的"影响范围"小节即是该接口缓存失效范围的权威清单，
  前端实现时应逐条对照。

#### 19.6.6 统一错误信封

写接口与读接口共用同一错误信封（第一阶段已定义）：

```json
{ "error": { "code": "string", "message": "string", "field_errors": {}, "request_id": "string" } }
```

写接口新增的状态码语义：

| 状态 | code | 含义 |
|---|---|---|
| 404 | `NOT_FOUND` | 目标资源不存在 |
| 409 | `CONFLICT` / 更具体的业务 code（如 `VERSION_LOCKED`、`VERSION_ALREADY_LOCKED`） | 并发冲突或状态机冲突 |
| 422 | `VALIDATION_ERROR` | 请求体校验失败，透传仓储层 `ValueError` 消息到 `message`，字段级错误放入 `field_errors` |
| 500 | `INTERNAL_ERROR` | 未预期的服务端异常 |

**绝不**在 `message`/`field_errors` 中泄露数据库连接串、文件系统
路径、堆栈跟踪等内部信息；仓储层抛出的 `ValueError` 消息本身即面向
最终用户设计（均为中文业务提示），可直接透传，但**任何未捕获的
异常都必须被统一异常处理器转换为不含技术细节的 `INTERNAL_ERROR`**。

#### 19.6.7 审计归属（共享团队密码模型，本契约定案）

**本契约定案（取代此前"占位方案，未最终拍板"的表述）**：登录时
（`POST /api/auth/login`，见 19.6.1）新增必填 `operator_name`（2–30
字符）字段，与 `session_id` 一并存入服务端 session。本章所有高风险
写操作在其归属的审计/修订表（`creator_contract_revision`、
`dashboard_import_batch`、`dashboard_import_batch_snapshot`、结算版本
表的 `note`/审计字段等）中统一记录：

```json
{ "operator_name": "张三", "session_id": "sess_xxx", "created_at": "2026-07-01T10:00:00Z", "operation_type": "CONTRACT_CHANGE" }
```

即以 `operator_name`（自然人姓名，仅做标注不做身份校验）取代此前
`operator="team"` 的占位值，`session_id` 仍保留用于区分同一会话内的
连续操作；新增 `operation_type` 字段标注具体操作类型（如
`CONTRACT_CHANGE`/`CONTRACT_CORRECTION`/`CONTRACT_REVERT`/`IMPORT`/
`LOCK_VERSION` 等），便于审计检索。**`operator_name` 由服务端从 session
中读取写入审计记录，客户端不得在具体写接口的请求体中传入/覆盖该字段**
（与 19.5.3 锁定端点的约束一致）。

### 19.7 待产品确认的业务决策汇总

**本轮 12 项业务决策（共享密码审计、Idempotency-Key、409 细分 code、
合同回退、已删除合同周期展示、导入批次真回滚、回退原因必填、重复合同
修正提交、指定主题申报整月替换、粉丝批量更新异步化、结算版本唯一约束
前置校验、锁定版本必填 `lock_note`）已全部确认并写入正文对应小节，
**不再是开放问题**。以下为本轮编辑过程中新发现、仍需产品/工程进一步
明确的残留事项：

1. **仓储层方法签名扩展（实现前置，非语义开放问题）**：
   `revert_contract_revision()`（19.1.6）需扩展以接收并落库 `reason`；
   `lock_compensation_version()`/`lock_long_term_compensation_version()`/
   `lock_commentary_compensation_version()`（19.5.3）需扩展以接收并落库
   `lock_note`；`replace_commentary_theme_submissions()`（19.3.4）需扩展
   以支持 `expected_revision` 乐观并发校验。三者语义已定案，只是需要在
   实现阶段先改造 repository 方法签名，建议排入实现计划的最前置步骤。
2. **导入批次快照存储的物理设计**（19.2.2/19.2.3）：本契约只定义了
   "同事务保存旧数据快照、支持真回滚"的语义要求与建议表名
   `dashboard_import_batch_snapshot`，具体表结构（例如是否需要按行
   压缩存储、是否需要唯一索引）留待实现阶段设计，长期保留是否需要
   容量归档策略也留待后续容量规划。
3. **批量更新任务队列的物理实现**（19.4.3）：异步任务+轮询语义已
   定案，但具体后台执行机制（线程池/独立 worker/任务队列中间件）
   由实现阶段结合现有部署环境选型。
4. **第 2 章 `POST /api/auth/login` 正文字段定义的同步修订**：本次
   编辑范围限定在第 19 章，19.6.1 中已明确登录需新增必填
   `operator_name` 字段的业务要求，但第 2 章正文当前仍写着
   `{ "password": "string" }`，尚未反映该变化——需要在下一次允许跨
   章节编辑时同步更新第 2 章正文，避免两章表述不一致。
5. **TikTok "TT" 合同名称路由规则细节**（19.4 平台路由规则）：本轮未
   涉及该规则的业务变更，维持第一版定义（合同类型文本含
   `tt`/`tiktok` 视为持有 TikTok 合同），未来若命名规则需要调整，
   需另行确认，与本轮 12 项决策无关。

---
