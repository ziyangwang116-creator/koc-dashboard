"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  ChartNoAxesCombined,
  Columns3,
  Eye,
  FileText,
  RotateCcw,
  SlidersHorizontal,
  UploadCloud,
  Users,
  type LucideIcon,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AppShell } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { StateShell } from "@/components/DataStates";
import { ApiError } from "@/lib/api-client";
import { dashboardApi } from "@/lib/endpoints";
import { creatorCategoryLabel, fmtInt, fmtPercent, isDrop30 } from "@/lib/format";
import type {
  ComparisonSeries,
  DashboardPostRow,
  DashboardSummaryRow,
  RankingCreatorItem,
  RankingVideoItem,
} from "@/lib/types";

type PeriodMode = "month" | "week";
type TrafficBoostMode = "original" | "boosted_preview";

function previousNaturalMonth(month: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return "";
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 2, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

const DEFAULT_POST_COLUMN_KEYS = [
  "kol_name",
  "user_id",
  "creator_category",
  "contract_types",
  "source_platform",
  "subtype",
  "description",
  "title",
  "url",
  "publish_date",
  "timestamp",
  "views",
  "likes",
  "comment",
  "reposted",
  "collect",
  "compensation_eligible",
];

export default function DashboardPage() {
  const [periodMode, setPeriodMode] = useState<PeriodMode>("month");
  const [periodMonth, setPeriodMonth] = useState("");
  const [weekStart, setWeekStart] = useState("");
  const [creatorKey, setCreatorKey] = useState("");
  const [platform, setPlatform] = useState("");
  const [contentType, setContentType] = useState("");
  const [category, setCategory] = useState("");
  const [includeCrossIndustry, setIncludeCrossIndustry] = useState(false);
  const [trafficBoostMode, setTrafficBoostMode] = useState<TrafficBoostMode>("original");
  const [postPage, setPostPage] = useState(1);
  const [showColumnSettings, setShowColumnSettings] = useState(false);
  const [visiblePostColumns, setVisiblePostColumns] = useState(DEFAULT_POST_COLUMN_KEYS);
  const [comparisonMonth, setComparisonMonth] = useState("");
  const [comparisonDimension, setComparisonDimension] = useState("creator");
  const [comparisonMetric, setComparisonMetric] = useState("total_views");

  const filterOptionsQuery = useQuery({
    queryKey: ["dashboard", "filter-options"],
    queryFn: () => dashboardApi.filterOptions(),
    staleTime: 5 * 60_000,
  });
  const options = filterOptionsQuery.data?.data;
  const availableMonths = options?.available_months ?? [];
  const availableWeeks = options?.available_weeks ?? [];
  const effectiveMonth = periodMonth || availableMonths.at(-1) || "";
  const effectiveWeekStart = weekStart || availableWeeks.at(-1)?.week_start || "";
  const effectiveComparisonMonth = comparisonMonth || previousNaturalMonth(effectiveMonth);

  const periodParams = useMemo(
    () =>
      periodMode === "month"
        ? { period_mode: "month", period_month: effectiveMonth }
        : { period_mode: "week", week_start: effectiveWeekStart },
    [periodMode, effectiveMonth, effectiveWeekStart]
  );
  const commonFilters = useMemo(
    () => ({
      creator_key: creatorKey || undefined,
      source_platform: platform || undefined,
      content_type: contentType || undefined,
      creator_category: category || undefined,
      include_cross_industry: includeCrossIndustry,
      traffic_boost_mode: trafficBoostMode,
    }),
    [creatorKey, platform, contentType, category, includeCrossIndustry, trafficBoostMode]
  );
  const canQuery = periodMode === "month" ? Boolean(effectiveMonth) : Boolean(effectiveWeekStart);

  const summaryQuery = useQuery({
    queryKey: ["dashboard", "summary", periodParams, commonFilters],
    queryFn: () => dashboardApi.summary({ ...periodParams, ...commonFilters, page_size: 100 }),
    enabled: canQuery,
  });
  const postsQuery = useQuery({
    queryKey: ["dashboard", "posts", periodParams, commonFilters, postPage],
    queryFn: () => dashboardApi.posts({ ...periodParams, ...commonFilters, page: postPage, page_size: 100 }),
    enabled: canQuery,
  });
  const dailyQuery = useQuery({
    queryKey: ["dashboard", "daily", periodParams, commonFilters],
    queryFn: () => dashboardApi.daily({ ...periodParams, ...commonFilters }),
    enabled: canQuery,
  });

  const rankingQuery = (rankingType: string) => ({
    queryKey: ["dashboard", "rankings", rankingType, periodParams, commonFilters],
    queryFn: () => dashboardApi.rankings({ ...periodParams, ...commonFilters, ranking_type: rankingType }),
    enabled: canQuery,
  });
  const creatorViewsQuery = useQuery(rankingQuery("creator_views_top10"));
  const creatorPostsQuery = useQuery(rankingQuery("creator_posts_top10"));
  const creatorYtbQuery = useQuery(rankingQuery("creator_ytb_top30"));
  const creatorTtQuery = useQuery(rankingQuery("creator_tt_top30"));
  const videoYtbQuery = useQuery(rankingQuery("video_ytb_top20"));
  const videoTtQuery = useQuery(rankingQuery("video_tt_top20"));

  const comparisonQuery = useQuery({
    queryKey: ["dashboard", "comparison", effectiveComparisonMonth, effectiveMonth, comparisonDimension, comparisonMetric, commonFilters],
    queryFn: () => dashboardApi.comparison({
      periods: [
        { period_mode: "month", period_month: effectiveComparisonMonth },
        { period_mode: "month", period_month: effectiveMonth },
      ],
      dimension: comparisonDimension,
      metric: comparisonMetric,
      creator_key: creatorKey ? [creatorKey] : [],
      creator_category: category ? [category] : [],
      source_platform: platform ? [platform] : [],
      content_type: contentType ? [contentType] : [],
      include_cross_industry: includeCrossIndustry,
      traffic_boost_mode: trafficBoostMode,
    }),
    enabled: periodMode === "month" && Boolean(effectiveMonth && effectiveComparisonMonth),
  });
  const importBatchesQuery = useQuery({
    queryKey: ["dashboard", "import-batches"],
    queryFn: () => dashboardApi.importBatches({ limit: 10 }),
  });

  const summaryRows = summaryQuery.data?.data ?? [];
  const postRows = useMemo(() => postsQuery.data?.data ?? [], [postsQuery.data]);
  const postPagination = postsQuery.data?.meta.pagination;
  const totalViews = summaryRows.reduce((sum, row) => sum + row.total_views, 0);
  const totalPosts = summaryRows.reduce((sum, row) => sum + row.post_count, 0);
  const coveredCreators = new Set(
    summaryRows.filter((row) => row.post_count > 0).map((row) => row.creator_key)
  ).size;
  const trendData = useMemo(
    () =>
      (dailyQuery.data?.data ?? []).map((row) => ({
        date: row.publish_date,
        views: row.total_views,
      })),
    [dailyQuery.data]
  );

  const summaryColumns: Column<DashboardSummaryRow>[] = [
    { key: "creator_label", header: "达人", render: (r) => r.creator_label },
    { key: "creator_category", header: "合作类别", render: (r) => creatorCategoryLabel(r.creator_category) },
    { key: "contract_types", header: "合同类型", render: (r) => r.contract_types.join("、") || "-" },
    { key: "post_count", header: "投稿数", align: "right", render: (r) => fmtInt(r.post_count) },
    { key: "total_views", header: "播放量", align: "right", render: (r) => fmtInt(r.total_views) },
    { key: "engagement_rate", header: "互动率", align: "right", render: (r) => fmtPercent(r.engagement_rate) },
  ];
  const creatorRankColumns: Column<RankingCreatorItem>[] = [
    { key: "rank", header: "#", width: 45, align: "right", render: (r) => r.rank },
    { key: "creator_label", header: "达人", width: 130, render: (r) => r.creator_label },
    { key: "creator_category", header: "合作类别", width: 90, render: (r) => creatorCategoryLabel(r.creator_category) },
    { key: "total_views", header: "播放量", align: "right", render: (r) => fmtInt(r.total_views) },
    { key: "post_count", header: "投稿数", align: "right", render: (r) => fmtInt(r.post_count) },
  ];
  const videoRankColumns: Column<RankingVideoItem>[] = [
    { key: "rank", header: "#", width: 45, align: "right", render: (r) => r.rank },
    { key: "creator_label", header: "达人", width: 130, render: (r) => r.creator_label },
    { key: "title", header: "标题", width: 250, render: (r) => <a href={r.url} target="_blank" rel="noreferrer">{r.title || "打开视频"}</a> },
    { key: "publish_date", header: "发布日期", width: 105, render: (r) => r.publish_date },
    { key: "views", header: "播放量", align: "right", render: (r) => fmtInt(r.views) },
  ];
  const allPostColumns = buildPostColumns();
  const postColumns = allPostColumns.filter((column) => visiblePostColumns.includes(column.key));

  function resetFilters() {
    setCreatorKey("");
    setPlatform("");
    setContentType("");
    setCategory("");
    setIncludeCrossIndustry(false);
    setTrafficBoostMode("original");
    setPostPage(1);
  }

  return (
    <AppShell currentPeriod={periodMode === "month" ? effectiveMonth : effectiveWeekStart}>
      <section className="dashboard-page">
        <header className="dashboard-heading">
          <div>
            <div className="dashboard-eyebrow">运营概览</div>
            <h1>数据看板</h1>
            <p>内容运营数据概览</p>
          </div>
          <div className="dashboard-period-badge">
            <CalendarDays size={15} />
            <span>{periodMode === "month" ? effectiveMonth : effectiveWeekStart || "未选择周期"}</span>
          </div>
        </header>

        <div className="dashboard-filter-shell">
          <div className="dashboard-filter-header">
            <div className="dashboard-filter-title">
              <SlidersHorizontal size={16} />
              <strong>筛选条件</strong>
            </div>
            <button type="button" className="ui-button ui-button-outline" onClick={resetFilters}>
              <RotateCcw size={14} />
              重置
            </button>
          </div>
          <div className="dashboard-filter-grid">
            <div className="dashboard-segmented" aria-label="统计周期模式">
              <button type="button" className={periodMode === "month" ? "is-active" : ""} onClick={() => { setPeriodMode("month"); setPostPage(1); }}>按月</button>
              <button type="button" className={periodMode === "week" ? "is-active" : ""} onClick={() => { setPeriodMode("week"); setPostPage(1); }}>按周</button>
            </div>
          {periodMode === "month" ? (
            <select aria-label="统计月份" value={effectiveMonth} onChange={(e) => { setPeriodMonth(e.target.value); setPostPage(1); }} className="ui-select">
              {availableMonths.map((month) => <option key={month}>{month}</option>)}
            </select>
          ) : (
            <select aria-label="统计周度" value={effectiveWeekStart} onChange={(e) => { setWeekStart(e.target.value); setPostPage(1); }} className="ui-select">
              {availableWeeks.map((week) => <option key={week.week_start} value={week.week_start}>{week.week_start} ~ {week.week_end}</option>)}
            </select>
          )}
          <FilterSelect label="全部达人" value={creatorKey} onChange={(value) => { setCreatorKey(value); setPostPage(1); }} options={(options?.creators ?? []).map((item) => [item.creator_key, item.creator_label])} />
          <FilterSelect label="全部平台" value={platform} onChange={(value) => { setPlatform(value); setPostPage(1); }} options={(options?.source_platforms ?? []).map((item) => [item, item])} />
          <FilterSelect label="全部视频类型" value={contentType} onChange={(value) => { setContentType(value); setPostPage(1); }} options={(options?.content_types ?? []).map((item) => [item, item])} />
          <FilterSelect label="全部合作类别" value={category} onChange={(value) => { setCategory(value); setPostPage(1); }} options={(options?.creator_categories ?? []).map((item) => [item, creatorCategoryLabel(item)])} />
          <select aria-label="播放量口径" value={trafficBoostMode} onChange={(e) => { setTrafficBoostMode(e.target.value as TrafficBoostMode); setPostPage(1); }} className="ui-select">
            <option value="original">原始播放量</option>
            <option value="boosted_preview">7月加成后播放量</option>
          </select>
            <label className="dashboard-toggle">
              <span>包含异业活动数据</span>
              <input type="checkbox" checked={includeCrossIndustry} onChange={(e) => { setIncludeCrossIndustry(e.target.checked); setPostPage(1); }} />
              <span className="dashboard-toggle-track" aria-hidden="true" />
            </label>
          </div>
        </div>

        <div className="dashboard-metrics">
          <MetricCard label="总播放量" value={fmtInt(totalViews)} icon={Eye} tone="blue" />
          <MetricCard label="投稿总数" value={fmtInt(totalPosts)} icon={FileText} tone="teal" />
          <MetricCard label="覆盖达人" value={fmtInt(coveredCreators)} icon={Users} tone="amber" />
          <MetricCard label="统计周期" value={periodMode === "month" ? effectiveMonth : effectiveWeekStart} icon={CalendarDays} tone="violet" />
        </div>

        <div className="dashboard-overview-grid">
          <Panel title="播放量趋势" description="完整统计周期" icon={ChartNoAxesCombined}>
            <StateShell isLoading={dailyQuery.isLoading} isError={dailyQuery.isError} isUnauthorized={dailyQuery.error instanceof ApiError && dailyQuery.error.status === 401} isEmpty={trendData.length === 0}>
              <div className="dashboard-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trendData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 10.5, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fontSize: 10.5, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ border: "1px solid var(--border)", borderRadius: 8, boxShadow: "var(--shadow-sm)", fontSize: 12 }} />
                    <Line type="monotone" dataKey="views" name="播放量" stroke="var(--chart-1)" strokeWidth={2.25} dot={false} activeDot={{ r: 4 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </StateShell>
          </Panel>

          <Panel title="最近导入" description="最近 10 个批次" icon={UploadCloud}>
            <StateShell isLoading={importBatchesQuery.isLoading} isError={importBatchesQuery.isError} isEmpty={(importBatchesQuery.data?.data.length ?? 0) === 0}>
              <ul className="dashboard-batch-list">
                {(importBatchesQuery.data?.data ?? []).map((batch) => (
                  <li key={batch.batch_id} className="dashboard-batch-item">
                    <span className="dashboard-batch-index">#{batch.batch_id}</span>
                    <div>
                      <strong>{batch.period_months.join("、") || "未标记月份"} · {importModeLabel(batch.mode)}</strong>
                      <span>输入 {fmtInt(batch.input_count)} · 保存 {fmtInt(batch.saved_count)} · 移除 {fmtInt(batch.removed_count)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </StateShell>
          </Panel>
        </div>

        <Panel title="达人汇总" description={`${fmtInt(summaryRows.length)} 位达人`} icon={Users}><StateShell isLoading={summaryQuery.isLoading} isError={summaryQuery.isError} isEmpty={summaryRows.length === 0}><DataTable columns={summaryColumns} rows={summaryRows} rowKey={(r) => r.creator_key} maxHeight={420} /></StateShell></Panel>

        <Panel title="月度增长对比" description={`${effectiveComparisonMonth || "-"} 对比 ${effectiveMonth || "-"}`} icon={ChartNoAxesCombined}>
          <div className="dashboard-comparison-controls">
            <select aria-label="对比月份" value={effectiveComparisonMonth} onChange={(e) => setComparisonMonth(e.target.value)} className="ui-select">
              {[...new Set([effectiveComparisonMonth, ...availableMonths])].filter(Boolean).map((month) => <option key={month}>{month}</option>)}
            </select>
            <select aria-label="对比维度" value={comparisonDimension} onChange={(e) => setComparisonDimension(e.target.value)} className="ui-select">
              <option value="creator">达人间</option><option value="platform">平台间</option><option value="content_type">视频类型间</option><option value="creator_category">达人类型间</option>
            </select>
            <select aria-label="对比指标" value={comparisonMetric} onChange={(e) => setComparisonMetric(e.target.value)} className="ui-select">
              <option value="total_views">播放量变化</option><option value="post_count">投稿数量变化</option><option value="engagement_rate">互动率变化</option>
            </select>
          </div>
          <StateShell isLoading={comparisonQuery.isLoading} isError={comparisonQuery.isError} isEmpty={(comparisonQuery.data?.data.series.length ?? 0) === 0}>
            <DataTable columns={comparisonColumns(comparisonDimension, comparisonMetric)} rows={comparisonQuery.data?.data.series ?? []} rowKey={(r) => r.group_key} />
          </StateShell>
        </Panel>

        <div className="dashboard-ranking-grid">
          <RankingPanel title="达人播放量 Top 10" query={creatorViewsQuery} columns={creatorRankColumns} />
          <RankingPanel title="达人投稿数 Top 10" query={creatorPostsQuery} columns={creatorRankColumns} />
          <RankingPanel title="YouTube 达人播放与投稿 Top 30" query={creatorYtbQuery} columns={creatorRankColumns} />
          <RankingPanel title="TikTok 达人播放与投稿 Top 30" query={creatorTtQuery} columns={creatorRankColumns} />
          <RankingPanel title="YouTube 视频播放量 Top 20" query={videoYtbQuery} columns={videoRankColumns} />
          <RankingPanel title="TikTok 视频播放量 Top 20" query={videoTtQuery} columns={videoRankColumns} />
        </div>

        <Panel title="数据月度总表" description="完整投稿明细" icon={FileText}>
          <div className="dashboard-table-toolbar">
            <span>共 {fmtInt(postPagination?.total_items)} 条，当前第 {postPage} 页</span>
            <button type="button" className="ui-button ui-button-outline" onClick={() => setShowColumnSettings((value) => !value)}><Columns3 size={14} />字段设置</button>
          </div>
          {showColumnSettings && <ColumnSettings columns={allPostColumns} selected={visiblePostColumns} onChange={setVisiblePostColumns} />}
          <StateShell isLoading={postsQuery.isLoading} isError={postsQuery.isError} isEmpty={postRows.length === 0}><DataTable columns={postColumns} rows={postRows} rowKey={(r) => `${r.url}-${r.publish_date ?? ""}`} /></StateShell>
          {postPagination && <div className="dashboard-pagination"><button className="ui-button ui-button-outline" disabled={postPage <= 1} onClick={() => setPostPage((page) => page - 1)}>上一页</button><span>{postPage} / {postPagination.total_pages}</span><button className="ui-button ui-button-outline" disabled={postPage >= postPagination.total_pages} onClick={() => setPostPage((page) => page + 1)}>下一页</button></div>}
        </Panel>
      </section>
    </AppShell>
  );
}

function buildPostColumns(): Column<DashboardPostRow>[] {
  return [
    { key: "source_file", header: "来源文件", width: 150, render: (r) => r.source_file ?? "-" },
    { key: "kol_name", header: "KOL Name", width: 120, render: (r) => r.kol_name ?? r.koc_name },
    { key: "koc_name", header: "达人", width: 120, render: (r) => r.koc_name },
    { key: "user_id", header: "UID", width: 120, render: (r) => r.user_id },
    { key: "creator_key", header: "达人匹配键", width: 125, render: (r) => r.creator_key },
    { key: "creator_id", header: "达人内部ID", width: 105, align: "right", render: (r) => fmtInt(r.creator_id) },
    { key: "creator_category", header: "合作类别", width: 90, render: (r) => creatorCategoryLabel(r.creator_category) },
    { key: "contract_types", header: "合同类型", width: 150, render: (r) => r.contract_types.join("、") || "-" },
    { key: "contract_start_date", header: "合同开始", width: 105, render: (r) => r.contract_start_date ?? "-" },
    { key: "contract_end_date", header: "合同截止", width: 105, render: (r) => r.contract_end_date ?? "-" },
    { key: "source_platform", header: "平台", width: 85, render: (r) => r.source_platform },
    { key: "content_type", header: "内容类型", width: 95, render: (r) => r.content_type },
    { key: "subtype", header: "Subtype", width: 95, render: (r) => r.subtype },
    { key: "description", header: "Description", width: 260, render: (r) => r.description ?? "-" },
    { key: "title", header: "标题", width: 240, render: (r) => r.title },
    { key: "url", header: "URL", width: 110, render: (r) => <a href={r.url} target="_blank" rel="noreferrer">打开视频</a> },
    { key: "publish_date", header: "发布日期", width: 105, render: (r) => r.publish_date ?? "-" },
    { key: "timestamp", header: "Timestamp", width: 150, render: (r) => r.timestamp ?? "-" },
    { key: "view", header: "原字段播放量", width: 115, align: "right", render: (r) => fmtInt(r.view) },
    { key: "original_views", header: "原始播放量", width: 105, align: "right", render: (r) => fmtInt(r.original_views) },
    { key: "traffic_boost_views", header: "流量加成", width: 100, align: "right", render: (r) => fmtInt(r.traffic_boost_views) },
    { key: "boosted_views", header: "加成后播放量", width: 115, align: "right", render: (r) => fmtInt(r.boosted_views) },
    { key: "views", header: "最终播放量", width: 105, align: "right", render: (r) => fmtInt(r.views) },
    { key: "likes", header: "Likes", width: 85, align: "right", render: (r) => fmtInt(r.likes) },
    { key: "comment", header: "Comment", width: 85, align: "right", render: (r) => fmtInt(r.comment) },
    { key: "reposted", header: "Reposted", width: 85, align: "right", render: (r) => fmtInt(r.reposted) },
    { key: "collect", header: "Collect", width: 85, align: "right", render: (r) => fmtInt(r.collect) },
    { key: "matched", header: "达人匹配", width: 85, render: (r) => r.matched ? "是" : "否" },
    { key: "profile_status", header: "资料状态", width: 105, render: (r) => r.profile_status },
    { key: "profile_effective_date", header: "资料生效日", width: 105, render: (r) => r.profile_effective_date ?? "-" },
    { key: "creator_active", header: "达人启用", width: 85, render: (r) => r.creator_active ? "是" : "否" },
    { key: "compensation_eligible", header: "计费资格", width: 85, render: (r) => r.compensation_eligible ? "是" : "否" },
    { key: "is_cross_industry", header: "异业活动", width: 85, render: (r) => r.is_cross_industry ? "是" : "否" },
    { key: "cross_industry_url_key", header: "异业URL键", width: 180, render: (r) => r.cross_industry_url_key ?? "-" },
    { key: "cross_industry_reason", header: "异业排除原因", width: 180, render: (r) => r.cross_industry_reason ?? "-" },
    { key: "cross_industry_exclusion_id", header: "异业排除ID", width: 105, align: "right", render: (r) => fmtInt(r.cross_industry_exclusion_id) },
    { key: "follower_count", header: "总粉丝数", width: 95, align: "right", render: (r) => fmtInt(r.follower_count) },
    { key: "homepage_url", header: "主页", width: 180, render: (r) => r.homepage_url ?? "-" },
    { key: "youtube_user_id", header: "YouTube UID", width: 120, render: (r) => r.youtube_user_id ?? "-" },
    { key: "youtube_homepage_url", header: "YouTube主页", width: 190, render: (r) => r.youtube_homepage_url ?? "-" },
    { key: "youtube_follower_count", header: "YouTube粉丝数", width: 120, align: "right", render: (r) => fmtInt(r.youtube_follower_count) },
    { key: "tiktok_user_id", header: "TikTok UID", width: 120, render: (r) => r.tiktok_user_id ?? "-" },
    { key: "tiktok_homepage_url", header: "TikTok主页", width: 190, render: (r) => r.tiktok_homepage_url ?? "-" },
    { key: "tiktok_follower_count", header: "TikTok粉丝数", width: 120, align: "right", render: (r) => fmtInt(r.tiktok_follower_count) },
  ];
}

function importModeLabel(mode: string): string {
  if (mode === "REPLACE_MONTHS") return "按月完整替换";
  if (mode === "APPEND_OR_UPDATE") return "补充或更新";
  return mode;
}

function comparisonColumns(dimension: string, metric: string): Column<ComparisonSeries>[] {
  const breakdownRate = (row: ComparisonSeries, key: string) => {
    const entry = row.breakdown?.[key];
    return metric === "post_count"
      ? entry?.post_count_change_rate ?? null
      : entry?.change_rate ?? null;
  };
  return [
    { key: "group_label", header: "对象", width: 150, render: (r) => r.group_label },
    { key: "previous", header: "对比期", width: 105, align: "right", render: (r) => fmtInt(r.points[0]?.value) },
    { key: "current", header: "目标期", width: 105, align: "right", render: (r) => fmtInt(r.points.at(-1)?.value) },
    { key: "previous_posts", header: "对比期投稿数", width: 110, align: "right", render: (r) => fmtInt(r.points[0]?.post_count) },
    { key: "current_posts", header: "目标期投稿数", width: 110, align: "right", render: (r) => fmtInt(r.points.at(-1)?.post_count) },
    { key: "change_rate", header: "变化率", width: 90, align: "right", highlight: (r) => isDrop30(r.change_rate), render: (r) => fmtPercent(r.change_rate) },
    ...(dimension === "creator" ? ([
      { key: "long", header: "Long变化", width: 90, align: "right" as const, highlight: (r: ComparisonSeries) => isDrop30(breakdownRate(r, "long")), render: (r: ComparisonSeries) => fmtPercent(breakdownRate(r, "long")) },
      { key: "livestream", header: "直播变化", width: 90, align: "right" as const, highlight: (r: ComparisonSeries) => isDrop30(breakdownRate(r, "livestream")), render: (r: ComparisonSeries) => fmtPercent(breakdownRate(r, "livestream")) },
      { key: "shorts", header: "Shorts变化", width: 95, align: "right" as const, highlight: (r: ComparisonSeries) => isDrop30(breakdownRate(r, "shorts")), render: (r: ComparisonSeries) => fmtPercent(breakdownRate(r, "shorts")) },
      { key: "tiktok", header: "TikTok变化", width: 95, align: "right" as const, highlight: (r: ComparisonSeries) => isDrop30(breakdownRate(r, "tiktok")), render: (r: ComparisonSeries) => fmtPercent(breakdownRate(r, "tiktok")) },
    ] as Column<ComparisonSeries>[]) : []),
  ];
}

function ColumnSettings({ columns, selected, onChange }: { columns: Column<DashboardPostRow>[]; selected: string[]; onChange: (keys: string[]) => void }) {
  return <div className="dashboard-column-settings">{columns.map((column) => <label key={column.key} className="dashboard-check-label"><input type="checkbox" checked={selected.includes(column.key)} onChange={(e) => onChange(e.target.checked ? [...selected, column.key] : selected.filter((key) => key !== column.key))} />{column.header}</label>)}<button type="button" className="ui-button ui-button-outline" onClick={() => onChange(DEFAULT_POST_COLUMN_KEYS)}>恢复默认</button><button type="button" className="ui-button ui-button-outline" onClick={() => onChange(columns.map((column) => column.key))}>显示全部</button></div>;
}

function RankingPanel<T extends RankingCreatorItem | RankingVideoItem>({ title, query, columns }: { title: string; query: { isLoading: boolean; isError: boolean; data?: { data: { items: (RankingCreatorItem | RankingVideoItem)[] } } }; columns: Column<T>[] }) {
  const rows = (query.data?.data.items ?? []) as T[];
  return <Panel title={title} description={`${fmtInt(rows.length)} 条`}><StateShell isLoading={query.isLoading} isError={query.isError} isEmpty={rows.length === 0}><DataTable columns={columns} rows={rows} rowKey={(row) => row.rank} maxHeight={360} /></StateShell></Panel>;
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: [string, string][] }) {
  return <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="ui-select"><option value="">{label}</option>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select>;
}

function MetricCard({ label, value, icon: Icon, tone }: { label: string; value: string; icon: LucideIcon; tone: "blue" | "teal" | "amber" | "violet" }) {
  return <div className="dashboard-metric"><span className={`dashboard-metric-icon dashboard-metric-${tone}`}><Icon size={17} /></span><div><div className="dashboard-metric-label">{label}</div><div className="dashboard-metric-value">{value || "-"}</div></div></div>;
}

function Panel({ title, description, icon: Icon, children }: { title: string; description?: string; icon?: LucideIcon; children: React.ReactNode }) {
  return <section className="dashboard-panel"><header className="dashboard-panel-header"><div className="dashboard-panel-title">{Icon && <Icon size={15} />}<strong>{title}</strong>{description && <span>{description}</span>}</div></header><div className="dashboard-panel-body">{children}</div></section>;
}

export { isDrop30 };
