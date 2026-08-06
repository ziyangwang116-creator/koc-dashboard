# KOC 数据整理工具 V1.7（异业与流量加成联动）

Windows 本地运行的 Streamlit 工具，用于维护 KOC 达人资料，并将一个或多个 Rapid Query Excel 统一整理为固定格式的 KOC 运营数据 Excel。

## 数据整理

- 单个和多个 `.xlsx` 使用同一个处理 Pipeline
- 每个文件独立读取和校验，错误文件不阻止其他文件
- 实时从 SQLite 中读取启用达人，通过 `userId → koc_name` 匹配
- 保留 V0.1/V0.2 的北京时间、subtype、TikTok 和空值处理规则
- 检测未匹配 UID、缺失 URL/title、无效 timestamp 和重复投稿
- 重复记录默认只提示；可选按 `platform + url` 保留第一条
- 导出“整理结果”“文件处理报告”“异常数据”三个工作表

投稿明细字段仍严格保持：

`koc_name`、`platform`、`publish_date`、`title`、`url`、`views`、`remark`、`likes`、`comment`、`reposted`

## 数据看板、异业与流量加成

- 月度、周度和自定义周期均支持“包含异业数据”开关，默认关闭
- 可批量粘贴 YouTube/TikTok 链接，预览匹配后标记为异业视频
- 异业标记独立于投稿保存，按月份完整替换数据后仍会保留
- 未匹配链接可提前保存，后续导入对应投稿时自动生效
- 标记可恢复，不物理删除原始投稿
- 草根、长包和解说薪酬统一排除异业播放量、投稿数和相关奖励
- 已锁定薪酬版本保持冻结，不随异业标记变化
- 2026 年 7 月支持“应用7月流量加成”开关：YTB 投稿需 `description` 和 `title` 同时含 `#手記の加筆`，TT 投稿只需 `description` 含该标签；开关状态按月份保存，命中投稿按播放量增加 5% 展示并作为草根、长包的实时结算口径
- 数据月度总表保留原始播放量、流量加成播放量、加成后播放量及命中规则，原始导入数据不被改写

## 达人库管理

达人基础资料与合同关系分表保存：

- `koc_master`：每位达人一条基础记录，保存 `user_id`、`koc_name`、主页、粉丝数、启用状态和审计字段
- `creator_contract`：通过 `creator_id` 保存任意多条合同关系
- `creator_category`：`LONG_TERM`、`COMMENTARY`、`GRASSROOT`，也可根据实际合同文本在查询时推导
- `contract_type`：按上传 Excel“类型”列的原始文本保存，不限于旧枚举；不会把“4月TT”等类型合并成其他名称
- `homepage_url`
- `follower_count`、`follower_raw_display_value`、`follower_count_is_estimated`
- `follower_source`、`follower_source_url`、`follower_profile_url`
- `follower_count_updated_at`、`follower_sync_status`、`follower_error_code`、`follower_sync_error`
- `settlement_eligible`
- `active`、`note`、`created_at`、`updated_at`

界面只保留“合作类别筛选”和“合同类型筛选”两个列表筛选维度，并支持新增、编辑、停用/启用、批量导入、备份导出、人工粉丝数和自动粉丝数更新。合同类型是多选组件，内部使用 OR 逻辑；合作类别与合同类型之间使用 AND 逻辑。达人列表把同一达人的多个合同类型合并显示，基础资料和粉丝更新仍只按达人执行一次。

合同对应的平台和内容类型由 `get_contract_metadata()` 在运行时推导，不额外存储平台字段。

## 达人 Excel 导入

支持实际达人库及标准表头：

- `UID` → `user_id`
- `NAME` 或 `达人名称` → `koc_name`
- `类型` → `contract_type`
- 也支持 `koc_name`、`user_id`、`contract_type`

可选字段：

`creator_category`、`contract_type`、`homepage_url`、`follower_count`、`active`、`note`

其中 `homepage_url`、`follower_count` 也兼容中文表头 `主页链接`、`粉丝数`。

规则：

- UID 始终按字符串规范化，数字 UID 不保留 `.0`
- 名称、UID 和链接去除前后空格
- 保留日文、中文、Emoji 和特殊字符
- 导入前显示总记录数、重复 UID、同 UID 合同类型、空 UID、空名称和空合同类型
- 重复 UID 只提示，不视为错误；不按 UID、名称或主页链接删除上传行
- 同一 UID 的每一行都会追加为独立合同关系，因此“长包”和“TT”可以同时保留
- 默认仅新增，不覆盖已有达人
- “更新已有”只更新 Excel 中有明确值的字段，空单元格不清空已有资料
- `data/input/达人数据库.xlsx` 存在时，数据库首次执行该导入迁移会保留每一行合同关系；已有达人基础资料不会被覆盖

## 合作类别和合同

实际 Excel 当前出现：`长包`、`解说`、`YTB`、`YTB shorts`、`TT`、`4月YTB`、`4月TT`、`5月YTB`、`5月TT`。这些文本会原样保存；以后上传的新类型也不会被程序擅自合并。

用于合作类别筛选时，`长包`归入长包、`解说`归入解说，其余上述平台合同归入草根。一个达人同时拥有“长包”和“TT”时，会同时符合对应类别，但仍然只有一条达人基础记录。

合同派生规则：

- `YTB`、`APRIL_YTB`、`MAY_YTB` → YouTube / long_livestream
- `YTB_SHORTS` → YouTube / shorts
- `TT`、`MAY_TT` → TikTok / shorts

编辑页使用多选组件新增或移除当前合同类型；不会修改 UID、粉丝数或历史投稿。

## 粉丝数更新

数据库始终保存原始整数；未知粉丝数保存为 `NULL`，不会写成 0。

### YouTube

使用官方 YouTube Data API v3 的 `channels.list`：

- 支持 `/channel/...`
- 支持 `/@handle`
- 支持 `/user/...`
- `/c/...` 等无法稳定映射到官方查询参数的地址会明确提示暂不支持

API Key 只从环境变量或本机 `.env` 的 `YOUTUBE_API_KEY` 读取，不写入代码、SQLite、页面或日志。程序调用 `channels.list(part=snippet,statistics)`，并根据链接使用 `forHandle`、`id` 或 `forUsername`。

推荐在项目根目录复制 `.env.example` 为 `.env`，然后只在本机填写：

```powershell
YOUTUBE_API_KEY=你的正式APIKey
```

也可以通过系统环境变量覆盖 `.env`。真实 `.env` 已被 `.gitignore` 忽略；页面只显示“已配置/未配置”，不会回显完整密钥。

YouTube 成功结果保存整数订阅数、API 原始公开值、频道来源和获取时间。由于官方公开订阅数可能取整，`follower_count_is_estimated` 固定为 `true`，`settlement_eligible` 为 `true`。隐藏订阅数、配额、权限、网络或返回格式错误都不会覆盖旧粉丝数。

### TikTok

使用本机持久化 Chromium 浏览器档案读取 TikTok 主页公开展示的粉丝数，不需要 Token。实现方式与项目附带的 `tiktok-checker-portable-no-token` 一致：浏览器档案仅保存在 `data/tiktok_browser_data`，不会导出、展示或上传 Cookie。

读取流程：

1. 从完整主页链接、`@username` 或 `username` 解析用户名。
2. 使用独立本地 Chromium 用户档案打开 `https://www.tiktok.com/@username`。
3. 首次使用时，在弹出的浏览器中手动登录；出现验证码或安全验证时也在该窗口中手动完成。
4. 只读取 `strong[data-e2e="followers-count"]` 的公开展示值，并解析为整数粉丝数。
5. 将整数粉丝数、达人主页和获取时间写入现有达人库与审计记录。

项目根目录的本机 `.env` 可以选择控制浏览器是否可见：

```dotenv
TIKTOK_PERSISTENT_HEADLESS=false
```

默认值为 `false`，以便完成首次登录和人工验证。完成登录后，后续查询会复用同一份本机浏览器档案。TikTok 批量任务选择合同类型包含 `TT`、`4月TT` 或 `5月TT` 的启用达人，按达人 UID 和 TikTok username 去重并串行执行。

不会自动处理或绕过登录、验证码、安全验证或访问限制。遇到这些情况时，当前达人会失败、旧粉丝数保持不变，并停止本批后续 TikTok 请求，避免重复触发限制。

页面未在限定时间内显示粉丝字段、浏览器启动失败或展示值无法解析时，同样不会覆盖旧粉丝数和上次成功时间。内部来源记为 `TIKTOK_BROWSER`，默认不改变现有结算规则。

### 数据来源与结算保护

- `YOUTUBE_API`：官方 API，默认可用于结算，但仍保留获取时间和估算标记。
- `TIKTOK_BROWSER`：本地登录浏览器读取 TikTok 公开页面，沿用现有人工确认规则。
- `MANUAL`：直接人工填写，默认不可用于结算；编辑达人时可以显式勾选确认。

存在粉丝数不等于自动获得结算资格。达人列表只显示达人名称、UID、合作类别、合同类型、主页链接、粉丝数、粉丝数最后更新时间和启用状态；筛选区只保留合作类别与合同类型。

### 更新审计

每次成功、失败、跳过或人工辅助保存都会写入 `follower_update_audit`，记录更新前后粉丝数、原始展示值、数据源、来源页、获取时间、估算状态、结算资格、错误代码和操作模式。审计表不保存 API Key、Cookie、Token 或认证请求头。

### 更新安全规则

- 成功：写入粉丝数、来源、原始展示值和获取时间，状态为 `SUCCESS`
- 失败：保留旧粉丝数和旧成功时间，状态为 `FAILED`
- 人工填写：状态为 `MANUAL`
- 无主页或不支持平台：跳过，不覆盖旧值
- YouTube 未配置 API Key：明确报错但不覆盖旧值
- TikTok 登录未完成、页面超时、访问受限、验证码或安全验证：当前达人标记失败并停止本批后续查询，不覆盖旧值
- TikTok 其他单达人错误：保留旧值并继续处理下一位达人
- 同一达人即使有多个合同类型，也只按 `creator_id`/`user_id` 更新一次粉丝数

## 草根达人月度报酬

“报酬结算”页面中的草根达人月度报酬，按所选月份的已留存投稿明细和当前达人库实时计算。汇率按月保存；录入并保存该月 3 日的 `JPY → USD` 汇率后，页面会直接显示结算结果。

- 除 `YTB shorts` 外，任何名称包含 `YTB` 的合同（如 `YTB`、`4月YTB`、`5月YTB`、`6月YTB`）只计算 `long` 与 `livestream`。
- `YTB shorts`：只计算月度明细中的 `shorts`（兼容已留存的 `YTB shorts` 标记）。
- `TT` 及所有含 `TT` 的月度合同（如 `4月TT`、`5月TT`）：只计算月度明细中的 `tiktok`。
- 每位草根达人必须有一个有效合同类型。长内容不使用粉丝数；短内容仅在达人库没有任何粉丝数时显示“待补充粉丝数”且不产生金额。最近一次粉丝更新失败不会覆盖历史粉丝数，也不会阻止结算。
- 合同类型会在每个结算月份首次计算时保存为月度合同快照。之后修改达人库主合同只影响尚未冻结的新月份；历史月份始终按已保存的快照结算。需要修正历史月份时，可在“达人库管理 > 设置月度合同快照”中选择月份并单独修改，不会改动达人库主合同。
- 长内容按月播放量等级与投稿数量等级结算；短内容同时满足粉丝数和播放量门槛后取得等级，并按投稿数追加奖励。
- 总金额为 0 时，不增加 `$15` 手续费、不计算服务费或 CPM。
- 草根与长包的 2026 年 7 月实时预览会读取上述开关的已保存状态；关闭时全部按原始播放量结算，打开时仅命中规则的投稿按加成后播放量结算，其他投稿仍按原始播放量。解说不适用。保存或锁定的结算版本保留当时的明细和金额，不会因后续规则或看板变化而被改写。

金额公式：

- 博主应收（美元）=`总金额（日元）×汇率 + 15`
- 有道应收（美元）=`博主应收（美元）×115%`
- 日元应收由上述美元金额按同一汇率折回并取整
- CPM=`有道应收（美元）÷该达人全部视频类型播放量×1000`。全部视频类型播放量包含 `long`、`livestream`、`shorts`（兼容 `YTB shorts`）和 `tiktok`，而合同对应的计费播放量仍只用于等级与报酬判定。

粉丝更新是可选的提醒操作，用于刷新达人库数据；也可在达人库中直接手动补齐粉丝数。报酬明细可下载为 UTF-8 CSV；总体 CPM 仅使用当前可结算或未达标的草根达人全部视频类型播放量。

## 数据库迁移

数据库路径由 `config/settings.json` 配置，当前为 `data/koc.db`。

升级过程：

1. 创建 `creator_contract` 合同关系表。
2. 把旧 `koc_master.contract_type` 迁移为关系记录。
3. 创建新版 `koc_master` 临时表，去除单合同列和 `UNIQUE(user_id)` 数据库约束。
4. 复制全部达人基础字段，并逐行比较迁移前后的 `(id, user_id, koc_name)`。
5. 校验一致后替换旧表，建立非唯一 UID 索引和合同查询索引。
6. 保留粉丝来源、估算值、结算资格及 `follower_update_audit` 审计表，最后运行 SQLite 完整性检查。
7. 浏览器来源迁移前自动备份到 `data/backup/`；旧网页来源标记兼容迁移为 `MANUAL`，粉丝数、主页、成功时间、达人资料和全部合同关系保持不变。

迁移幂等；重复启动不会重复复制或覆盖用户修改。

## 达人库备份

文件名：`KOC达人库_YYYYMMDD_HHMMSS.xlsx`

字段顺序：

`user_id`、`koc_name`、`creator_category`、`contract_type`、`homepage_url`、`follower_count`、`follower_raw_display_value`、`follower_source`、`follower_source_url`、`follower_count_is_estimated`、`follower_count_updated_at`、`follower_sync_status`、`settlement_eligible`、`active`、`note`、`created_at`、`updated_at`

UID 按文本导出，粉丝数按整数导出，主页链接可点击，日文、中文和 Emoji 保持原样。

## 安装与启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

打开 `http://localhost:8501`。

## TikTok 批量更新脚本

首次请通过应用中的 TikTok 粉丝预览或批量更新打开浏览器，在本机完成登录。之后可直接运行：

```powershell
.\.venv\Scripts\python.exe scripts\update_tiktok_followers.py
```

脚本不依赖 Streamlit，结束时输出 `success`、`failed`、`skipped` 和批次停止原因。返回码 `0` 表示无失败，`1` 表示存在普通失败，`2` 表示公开访问受限或遇到验证码/安全验证。

Windows 任务计划程序建议配置：

- 程序：`powershell.exe`
- 参数：`-NoProfile -ExecutionPolicy Bypass -File "C:\Users\wangji07\Documents\数据看板搭建\scripts\run_tiktok_update.ps1"`
- 起始于：`C:\Users\wangji07\Documents\数据看板搭建`

计划任务复用 `data/tiktok_browser_data` 中的本机登录档案。只有档案仍有效且不需要人工验证时，才适合无交互执行；否则任务会安全停止并保留旧粉丝数。

## 测试

```powershell
python -m pytest -q
```

## 当前范围外

- 达人合同历史表
- 公司平台或 Rapid Query 自动登录、自动取数
- 复杂数据大屏
- 绕过登录、验证码、访问控制或反爬机制的任何抓取方式
