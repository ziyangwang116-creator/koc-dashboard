"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
      postRows
        .slice()
        .sort((a, b) => (a.publish_date ?? "").localeCompare(b.publish_date ?? ""))
        .reduce<{ date: string; views: number }[]>((rows, post) => {
          const date = post.publish_date ?? "未知日期";
          const existing = rows.find((row) => row.date === date);
          if (existing) existing.views += post.views;
          else rows.push({ date, views: post.views });
          return rows;
        }, []),
    [postRows]
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

  return (
    <AppShell currentPeriod={periodMode === "month" ? effectiveMonth : effectiveWeekStart}>
      <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={filterBar}>
          <select value={periodMode} onChange={(e) => { setPeriodMode(e.target.value as PeriodMode); setPostPage(1); }} style={selectStyle}>
            <option value="month">按月</option><option value="week">按周</option>
          </select>
          {periodMode === "month" ? (
            <select value={effectiveMonth} onChange={(e) => { setPeriodMonth(e.target.value); setPostPage(1); }} style={selectStyle}>
              {availableMonths.map((month) => <option key={month}>{month}</option>)}
            </select>
          ) : (
            <select value={effectiveWeekStart} onChange={(e) => { setWeekStart(e.target.value); setPostPage(1); }} style={selectStyle}>
              {availableWeeks.map((week) => <option key={week.week_start} value={week.week_start}>{week.week_start} ~ {week.week_end}</option>)}
            </select>
          )}
          <FilterSelect label="全部达人" value={creatorKey} onChange={(value) => { setCreatorKey(value); setPostPage(1); }} options={(options?.creators ?? []).map((item) => [item.creator_key, item.creator_label])} />
          <FilterSelect label="全部平台" value={platform} onChange={(value) => { setPlatform(value); setPostPage(1); }} options={(options?.source_platforms ?? []).map((item) => [item, item])} />
          <FilterSelect label="全部视频类型" value={contentType} onChange={(value) => { setContentType(value); setPostPage(1); }} options={(options?.content_types ?? []).map((item) => [item, item])} />
          <FilterSelect label="全部合作类别" value={category} onChange={(value) => { setCategory(value); setPostPage(1); }} options={(options?.creator_categories ?? []).map((item) => [item, creatorCategoryLabel(item)])} />
          <select aria-label="播放量口径" value={trafficBoostMode} onChange={(e) => { setTrafficBoostMode(e.target.value as TrafficBoostMode); setPostPage(1); }} style={selectStyle}>
            <option value="original">原始播放量</option>
            <option value="boosted_preview">7月加成后播放量</option>
          </select>
          <label style={checkLabel}><input type="checkbox" checked={includeCrossIndustry} onChange={(e) => { setIncludeCrossIndustry(e.target.checked); setPostPage(1); }} />包含异业活动数据</label>
        </div>

        <div className="metric-row">
          <MetricCard label="总播放量" value={fmtInt(totalViews)} />
          <MetricCard label="投稿总数" value={fmtInt(totalPosts)} />
          <MetricCard label="覆盖达人" value={fmtInt(coveredCreators)} />
          <MetricCard label="统计周期" value={periodMode === "month" ? effectiveMonth : effectiveWeekStart} />
        </div>

        <Panel title="播放量趋势（当前明细页）">
          <StateShell isLoading={postsQuery.isLoading} isError={postsQuery.isError} isUnauthorized={postsQuery.error instanceof ApiError && postsQuery.error.status === 401} isEmpty={trendData.length === 0}>
            <ResponsiveContainer width="100%" height={240}><LineChart data={trendData}><CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" /><XAxis dataKey="date" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Line type="monotone" dataKey="views" stroke="var(--color-primary)" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer>
          </StateShell>
        </Panel>

        <Panel title="达人汇总"><StateShell isLoading={summaryQuery.isLoading} isError={summaryQuery.isError} isEmpty={summaryRows.length === 0}><DataTable columns={summaryColumns} rows={summaryRows} rowKey={(r) => r.creator_key} /></StateShell></Panel>

        <Panel title="月度增长对比">
          <div style={{ ...filterBar, padding: 0, border: 0, marginBottom: 10 }}>
            <span style={{ fontSize: 13 }}>对比月</span>
            <select value={effectiveComparisonMonth} onChange={(e) => setComparisonMonth(e.target.value)} style={selectStyle}>
              {[...new Set([effectiveComparisonMonth, ...availableMonths])].filter(Boolean).map((month) => <option key={month}>{month}</option>)}
            </select>
            <select value={comparisonDimension} onChange={(e) => setComparisonDimension(e.target.value)} style={selectStyle}>
              <option value="creator">达人间</option><option value="platform">平台间</option><option value="content_type">视频类型间</option><option value="creator_category">达人类型间</option>
            </select>
            <select value={comparisonMetric} onChange={(e) => setComparisonMetric(e.target.value)} style={selectStyle}>
              <option value="total_views">播放量变化</option><option value="post_count">投稿数量变化</option><option value="engagement_rate">互动率变化</option>
            </select>
          </div>
          <StateShell isLoading={comparisonQuery.isLoading} isError={comparisonQuery.isError} isEmpty={(comparisonQuery.data?.data.series.length ?? 0) === 0}>
            <DataTable columns={comparisonColumns(comparisonDimension, comparisonMetric)} rows={comparisonQuery.data?.data.series ?? []} rowKey={(r) => r.group_key} />
          </StateShell>
        </Panel>

        <div style={gridTwo}>
          <RankingPanel title="达人播放量 Top 10" query={creatorViewsQuery} columns={creatorRankColumns} />
          <RankingPanel title="达人投稿数 Top 10" query={creatorPostsQuery} columns={creatorRankColumns} />
          <RankingPanel title="YouTube 达人播放与投稿 Top 30" query={creatorYtbQuery} columns={creatorRankColumns} />
          <RankingPanel title="TikTok 达人播放与投稿 Top 30" query={creatorTtQuery} columns={creatorRankColumns} />
          <RankingPanel title="YouTube 视频播放量 Top 20" query={videoYtbQuery} columns={videoRankColumns} />
          <RankingPanel title="TikTok 视频播放量 Top 20" query={videoTtQuery} columns={videoRankColumns} />
        </div>

        <Panel title="数据月度总表">
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, color: "var(--color-text-muted)" }}>共 {fmtInt(postPagination?.total_items)} 条，当前第 {postPage} 页</span>
            <button type="button" style={secondaryButton} onClick={() => setShowColumnSettings((value) => !value)}>字段设置</button>
          </div>
          {showColumnSettings && <ColumnSettings columns={allPostColumns} selected={visiblePostColumns} onChange={setVisiblePostColumns} />}
          <StateShell isLoading={postsQuery.isLoading} isError={postsQuery.isError} isEmpty={postRows.length === 0}><DataTable columns={postColumns} rows={postRows} rowKey={(r) => `${r.url}-${r.publish_date ?? ""}`} /></StateShell>
          {postPagination && <div style={paginationStyle}><button style={secondaryButton} disabled={postPage <= 1} onClick={() => setPostPage((page) => page - 1)}>上一页</button><span>{postPage} / {postPagination.total_pages}</span><button style={secondaryButton} disabled={postPage >= postPagination.total_pages} onClick={() => setPostPage((page) => page + 1)}>下一页</button></div>}
        </Panel>

        <Panel title="导入批次记录"><StateShell isLoading={importBatchesQuery.isLoading} isError={importBatchesQuery.isError} isEmpty={(importBatchesQuery.data?.data.length ?? 0) === 0}><ul style={{ display: "flex", flexDirection: "column", gap: 7 }}>{(importBatchesQuery.data?.data ?? []).map((batch) => <li key={batch.batch_id} style={batchItem}>#{batch.batch_id} · {batch.mode} · {batch.period_months.join("、")} · 输入 {fmtInt(batch.input_count)} · 保存 {fmtInt(batch.saved_count)} · 移除 {fmtInt(batch.removed_count)}</li>)}</ul></StateShell></Panel>
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
  return <div style={columnSettings}>{columns.map((column) => <label key={column.key} style={checkLabel}><input type="checkbox" checked={selected.includes(column.key)} onChange={(e) => onChange(e.target.checked ? [...selected, column.key] : selected.filter((key) => key !== column.key))} />{column.header}</label>)}<button type="button" style={secondaryButton} onClick={() => onChange(DEFAULT_POST_COLUMN_KEYS)}>恢复默认</button><button type="button" style={secondaryButton} onClick={() => onChange(columns.map((column) => column.key))}>显示全部</button></div>;
}

function RankingPanel<T extends RankingCreatorItem | RankingVideoItem>({ title, query, columns }: { title: string; query: { isLoading: boolean; isError: boolean; data?: { data: { items: (RankingCreatorItem | RankingVideoItem)[] } } }; columns: Column<T>[] }) {
  const rows = (query.data?.data.items ?? []) as T[];
  return <Panel title={title}><StateShell isLoading={query.isLoading} isError={query.isError} isEmpty={rows.length === 0}><DataTable columns={columns} rows={rows} rowKey={(row) => row.rank} /></StateShell></Panel>;
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: [string, string][] }) {
  return <select value={value} onChange={(e) => onChange(e.target.value)} style={selectStyle}><option value="">{label}</option>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select>;
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return <div className="metric-card" style={metricCard}><div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{label}</div><div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>{value || "-"}</div></div>;
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <div style={panelStyle}><div style={{ fontSize: 14, fontWeight: 650, marginBottom: 10 }}>{title}</div>{children}</div>;
}

const filterBar: React.CSSProperties = { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius)", padding: 10 };
const selectStyle: React.CSSProperties = { padding: "6px 8px", borderRadius: "var(--radius)", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", fontSize: 13 };
const checkLabel: React.CSSProperties = { display: "flex", alignItems: "center", gap: 5, fontSize: 12.5, whiteSpace: "nowrap" };
const panelStyle: React.CSSProperties = { background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius)", padding: 12, minWidth: 0 };
const metricCard: React.CSSProperties = { background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius)", padding: 12 };
const gridTwo: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 430px), 1fr))", gap: 16 };
const secondaryButton: React.CSSProperties = { border: "1px solid var(--color-border)", borderRadius: "var(--radius)", padding: "6px 10px", background: "var(--color-surface)", color: "var(--color-text)", cursor: "pointer" };
const paginationStyle: React.CSSProperties = { display: "flex", justifyContent: "center", alignItems: "center", gap: 10, marginTop: 10, fontSize: 13 };
const columnSettings: React.CSSProperties = { display: "flex", flexWrap: "wrap", gap: "8px 14px", padding: 10, marginBottom: 10, background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: "var(--radius)" };
const batchItem: React.CSSProperties = { fontSize: 13, padding: "7px 10px", border: "1px solid var(--color-border)", borderRadius: "var(--radius)", background: "var(--color-bg)" };

export { isDrop30 };
