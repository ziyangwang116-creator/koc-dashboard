"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  CalendarDays,
  ChartNoAxesCombined,
  Columns3,
  Eye,
  FileText,
  Gauge,
  Layers3,
  RotateCcw,
  SlidersHorizontal,
  UploadCloud,
  Users,
  type LucideIcon,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { AppShell } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { StateShell } from "@/components/DataStates";
import { ApiError } from "@/lib/api-client";
import { compensationApi, dashboardApi } from "@/lib/endpoints";
import {
  creatorCategoryLabel,
  fmtCpm,
  fmtInt,
  fmtPercent,
  fmtUsd,
  isDrop30,
} from "@/lib/format";
import type {
  CpmAlertRow,
  DashboardPostRow,
  DashboardSummaryRow,
  RankingCreatorItem,
  RankingVideoItem,
} from "@/lib/types";
import {
  buildCreatorMovements,
  buildDailyComparison,
  buildDimensionComparison,
  changeRate,
  summarizeOperatingMetrics,
  type CreatorMovement,
} from "./dashboard-analytics";

type PeriodMode = "month" | "week";
type TrafficBoostMode = "original" | "boosted_preview";
type TrendMode = "daily_views" | "cumulative_views" | "daily_posts";
type StructureMetric = "views" | "posts";

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
  const [trafficBoostMode, setTrafficBoostMode] =
    useState<TrafficBoostMode>("original");
  const [comparisonMonth, setComparisonMonth] = useState("");
  const [trendMode, setTrendMode] = useState<TrendMode>("daily_views");
  const [platformMetric, setPlatformMetric] = useState<StructureMetric>("views");
  const [contentMetric, setContentMetric] = useState<StructureMetric>("views");
  const [cpmTarget, setCpmTarget] = useState(3);
  const [showDetails, setShowDetails] = useState(false);
  const [postPage, setPostPage] = useState(1);
  const [showColumnSettings, setShowColumnSettings] = useState(false);
  const [visiblePostColumns, setVisiblePostColumns] = useState(
    DEFAULT_POST_COLUMN_KEYS
  );

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
  const effectiveComparisonMonth =
    comparisonMonth || previousNaturalMonth(effectiveMonth);

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
  const comparisonFilters = useMemo(
    () => ({
      periods: [
        { period_mode: "month", period_month: effectiveComparisonMonth },
        { period_mode: "month", period_month: effectiveMonth },
      ],
      creator_key: creatorKey ? [creatorKey] : [],
      creator_category: category ? [category] : [],
      source_platform: platform ? [platform] : [],
      content_type: contentType ? [contentType] : [],
      include_cross_industry: includeCrossIndustry,
      traffic_boost_mode: trafficBoostMode,
    }),
    [
      effectiveComparisonMonth,
      effectiveMonth,
      creatorKey,
      category,
      platform,
      contentType,
      includeCrossIndustry,
      trafficBoostMode,
    ]
  );
  const canQuery =
    periodMode === "month" ? Boolean(effectiveMonth) : Boolean(effectiveWeekStart);
  const canCompare =
    periodMode === "month" && Boolean(effectiveMonth && effectiveComparisonMonth);

  const summaryQuery = useQuery({
    queryKey: ["dashboard", "summary", periodParams, commonFilters],
    queryFn: () =>
      dashboardApi.summary({ ...periodParams, ...commonFilters, page_size: 100 }),
    enabled: canQuery,
  });
  const previousSummaryQuery = useQuery({
    queryKey: [
      "dashboard",
      "summary",
      effectiveComparisonMonth,
      commonFilters,
    ],
    queryFn: () =>
      dashboardApi.summary({
        period_mode: "month",
        period_month: effectiveComparisonMonth,
        ...commonFilters,
        page_size: 100,
      }),
    enabled: canCompare,
  });
  const dailyQuery = useQuery({
    queryKey: ["dashboard", "daily", periodParams, commonFilters],
    queryFn: () => dashboardApi.daily({ ...periodParams, ...commonFilters }),
    enabled: canQuery,
  });
  const previousDailyQuery = useQuery({
    queryKey: ["dashboard", "daily", effectiveComparisonMonth, commonFilters],
    queryFn: () =>
      dashboardApi.daily({
        period_mode: "month",
        period_month: effectiveComparisonMonth,
        ...commonFilters,
      }),
    enabled: canCompare,
  });
  const platformComparisonQuery = useQuery({
    queryKey: ["dashboard", "comparison", "platform", comparisonFilters],
    queryFn: () =>
      dashboardApi.comparison({
        ...comparisonFilters,
        dimension: "platform",
        metric: "total_views",
      }),
    enabled: canCompare,
  });
  const contentComparisonQuery = useQuery({
    queryKey: ["dashboard", "comparison", "content_type", comparisonFilters],
    queryFn: () =>
      dashboardApi.comparison({
        ...comparisonFilters,
        dimension: "content_type",
        metric: "total_views",
      }),
    enabled: canCompare,
  });
  const creatorComparisonQuery = useQuery({
    queryKey: ["dashboard", "comparison", "creator", comparisonFilters],
    queryFn: () =>
      dashboardApi.comparison({
        ...comparisonFilters,
        dimension: "creator",
        metric: "total_views",
      }),
    enabled: canCompare,
  });
  const cpmAlertsQuery = useQuery({
    queryKey: [
      "compensation",
      "cpm-alerts",
      effectiveMonth,
      effectiveComparisonMonth,
    ],
    queryFn: () =>
      compensationApi.cpmAlerts({
        period_month: effectiveMonth,
        comparison_month: effectiveComparisonMonth || undefined,
      }),
    enabled: canCompare,
  });

  const postsQuery = useQuery({
    queryKey: ["dashboard", "posts", periodParams, commonFilters, postPage],
    queryFn: () =>
      dashboardApi.posts({
        ...periodParams,
        ...commonFilters,
        page: postPage,
        page_size: 100,
      }),
    enabled: showDetails && canQuery,
  });
  const importBatchesQuery = useQuery({
    queryKey: ["dashboard", "import-batches"],
    queryFn: () => dashboardApi.importBatches({ limit: 10 }),
    enabled: showDetails,
  });
  const rankingQuery = (rankingType: string) => ({
    queryKey: ["dashboard", "rankings", rankingType, periodParams, commonFilters],
    queryFn: () =>
      dashboardApi.rankings({
        ...periodParams,
        ...commonFilters,
        ranking_type: rankingType,
      }),
    enabled: showDetails && canQuery,
  });
  const creatorViewsQuery = useQuery(rankingQuery("creator_views_top10"));
  const creatorPostsQuery = useQuery(rankingQuery("creator_posts_top10"));
  const creatorYtbQuery = useQuery(rankingQuery("creator_ytb_top30"));
  const creatorTtQuery = useQuery(rankingQuery("creator_tt_top30"));
  const videoYtbQuery = useQuery(rankingQuery("video_ytb_top20"));
  const videoTtQuery = useQuery(rankingQuery("video_tt_top20"));

  const summaryRows = useMemo(() => summaryQuery.data?.data ?? [], [summaryQuery.data]);
  const previousSummaryRows = useMemo(
    () => previousSummaryQuery.data?.data ?? [],
    [previousSummaryQuery.data]
  );
  const currentMetrics = useMemo(
    () => summarizeOperatingMetrics(summaryRows),
    [summaryRows]
  );
  const previousMetrics = useMemo(
    () => summarizeOperatingMetrics(previousSummaryRows),
    [previousSummaryRows]
  );
  const monthlyComparisonData = [
    {
      period: effectiveComparisonMonth,
      views: previousMetrics.totalViews,
      posts: previousMetrics.totalPosts,
    },
    {
      period: effectiveMonth,
      views: currentMetrics.totalViews,
      posts: currentMetrics.totalPosts,
    },
  ];
  const trendData = useMemo(
    () =>
      buildDailyComparison(
        dailyQuery.data?.data ?? [],
        previousDailyQuery.data?.data ?? [],
        trendMode
      ),
    [dailyQuery.data, previousDailyQuery.data, trendMode]
  );
  const platformData = useMemo(
    () =>
      buildDimensionComparison(
        platformComparisonQuery.data?.data.series ?? [],
        platformMetric
      ),
    [platformComparisonQuery.data, platformMetric]
  );
  const contentData = useMemo(
    () =>
      buildDimensionComparison(
        contentComparisonQuery.data?.data.series ?? [],
        contentMetric
      ),
    [contentComparisonQuery.data, contentMetric]
  );
  const creatorMovements = useMemo(
    () =>
      buildCreatorMovements(creatorComparisonQuery.data?.data.series ?? []),
    [creatorComparisonQuery.data]
  );
  const growthRows = useMemo(
    () =>
      creatorMovements
        .filter((row) => row.viewDelta > 0)
        .sort((a, b) => b.viewDelta - a.viewDelta)
        .slice(0, 5),
    [creatorMovements]
  );
  const declineRows = useMemo(
    () =>
      creatorMovements
        .filter((row) => row.warning)
        .sort(
          (a, b) =>
            (a.viewChangeRate ?? 0) - (b.viewChangeRate ?? 0) ||
            (a.postChangeRate ?? 0) - (b.postChangeRate ?? 0)
        )
        .slice(0, 5),
    [creatorMovements]
  );
  const cpmRows = useMemo(
    () =>
      (cpmAlertsQuery.data?.data ?? [])
        .filter((row) => !category || row.creator_category === category)
        .filter((row) => !creatorKey || row.creator_key === creatorKey)
        .sort(
          (a, b) =>
            cpmSeverity(b, cpmTarget) - cpmSeverity(a, cpmTarget) ||
            (b.cpm ?? 0) - (a.cpm ?? 0)
        ),
    [cpmAlertsQuery.data, category, creatorKey, cpmTarget]
  );
  const cpmScatterData = cpmRows.filter(
    (row) => row.cpm !== null && row.all_video_views > 0
  );
  const highCpmCount = cpmRows.filter(
    (row) => cpmSeverity(row, cpmTarget) >= 2
  ).length;
  const staleCpmSources = (cpmAlertsQuery.data?.meta.sources ?? []).filter(
    (source) => source.status === "STALE"
  ).length;

  const postRows = useMemo(() => postsQuery.data?.data ?? [], [postsQuery.data]);
  const postPagination = postsQuery.data?.meta.pagination;
  const summaryColumns: Column<DashboardSummaryRow>[] = [
    { key: "creator_label", header: "达人", render: (row) => row.creator_label },
    {
      key: "creator_category",
      header: "合作类别",
      render: (row) => creatorCategoryLabel(row.creator_category),
    },
    {
      key: "contract_types",
      header: "合同类型",
      render: (row) => row.contract_types.join("、") || "-",
    },
    {
      key: "post_count",
      header: "投稿数",
      align: "right",
      render: (row) => fmtInt(row.post_count),
    },
    {
      key: "total_views",
      header: "播放量",
      align: "right",
      render: (row) => fmtInt(row.total_views),
    },
    {
      key: "engagement_rate",
      header: "互动率",
      align: "right",
      render: (row) => fmtPercent(row.engagement_rate),
    },
  ];
  const movementColumns = buildMovementColumns();
  const cpmColumns = buildCpmColumns(cpmTarget);
  const creatorRankColumns: Column<RankingCreatorItem>[] = [
    { key: "rank", header: "#", width: 45, align: "right", render: (row) => row.rank },
    { key: "creator_label", header: "达人", width: 130, render: (row) => row.creator_label },
    {
      key: "creator_category",
      header: "合作类别",
      width: 90,
      render: (row) => creatorCategoryLabel(row.creator_category),
    },
    { key: "total_views", header: "播放量", align: "right", render: (row) => fmtInt(row.total_views) },
    { key: "post_count", header: "投稿数", align: "right", render: (row) => fmtInt(row.post_count) },
  ];
  const videoRankColumns: Column<RankingVideoItem>[] = [
    { key: "rank", header: "#", width: 45, align: "right", render: (row) => row.rank },
    { key: "creator_label", header: "达人", width: 130, render: (row) => row.creator_label },
    {
      key: "title",
      header: "标题",
      width: 250,
      render: (row) => (
        <a href={row.url} target="_blank" rel="noreferrer">
          {row.title || "打开视频"}
        </a>
      ),
    },
    { key: "publish_date", header: "发布日期", width: 105, render: (row) => row.publish_date },
    { key: "views", header: "播放量", align: "right", render: (row) => fmtInt(row.views) },
  ];
  const allPostColumns = buildPostColumns();
  const postColumns = allPostColumns.filter((column) =>
    visiblePostColumns.includes(column.key)
  );

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
            <div className="dashboard-eyebrow">运营工作台</div>
            <h1>数据看板</h1>
            <p>聚焦产出、增长、内容结构、达人变化与成本效率</p>
          </div>
          <div className="dashboard-period-badge">
            <CalendarDays size={15} />
            <span>
              {periodMode === "month"
                ? `${effectiveComparisonMonth || "-"} 对比 ${effectiveMonth || "-"}`
                : effectiveWeekStart || "未选择周期"}
            </span>
          </div>
        </header>

        <div className="dashboard-filter-shell">
          <div className="dashboard-filter-header">
            <div className="dashboard-filter-title">
              <SlidersHorizontal size={16} />
              <strong>筛选条件</strong>
            </div>
            <button type="button" className="ui-button ui-button-outline" onClick={resetFilters}>
              <RotateCcw size={14} />重置
            </button>
          </div>
          <div className="dashboard-filter-grid">
            <div className="dashboard-segmented" aria-label="统计周期模式">
              <button
                type="button"
                className={periodMode === "month" ? "is-active" : ""}
                onClick={() => {
                  setPeriodMode("month");
                  setPostPage(1);
                }}
              >
                按月
              </button>
              <button
                type="button"
                className={periodMode === "week" ? "is-active" : ""}
                onClick={() => {
                  setPeriodMode("week");
                  setPostPage(1);
                }}
              >
                按周
              </button>
            </div>
            {periodMode === "month" ? (
              <select
                aria-label="统计月份"
                value={effectiveMonth}
                onChange={(event) => {
                  setPeriodMonth(event.target.value);
                  setPostPage(1);
                }}
                className="ui-select"
              >
                {availableMonths.map((month) => (
                  <option key={month}>{month}</option>
                ))}
              </select>
            ) : (
              <select
                aria-label="统计周度"
                value={effectiveWeekStart}
                onChange={(event) => {
                  setWeekStart(event.target.value);
                  setPostPage(1);
                }}
                className="ui-select"
              >
                {availableWeeks.map((week) => (
                  <option key={week.week_start} value={week.week_start}>
                    {week.week_start} ~ {week.week_end}
                  </option>
                ))}
              </select>
            )}
            <FilterSelect
              label="全部达人"
              value={creatorKey}
              onChange={(value) => {
                setCreatorKey(value);
                setPostPage(1);
              }}
              options={(options?.creators ?? []).map((item) => [
                item.creator_key,
                item.creator_label,
              ])}
            />
            <FilterSelect
              label="全部平台"
              value={platform}
              onChange={(value) => {
                setPlatform(value);
                setPostPage(1);
              }}
              options={(options?.source_platforms ?? []).map((item) => [item, item])}
            />
            <FilterSelect
              label="全部视频类型"
              value={contentType}
              onChange={(value) => {
                setContentType(value);
                setPostPage(1);
              }}
              options={(options?.content_types ?? []).map((item) => [item, item])}
            />
            <FilterSelect
              label="全部合作类别"
              value={category}
              onChange={(value) => {
                setCategory(value);
                setPostPage(1);
              }}
              options={(options?.creator_categories ?? []).map((item) => [
                item,
                creatorCategoryLabel(item),
              ])}
            />
            <select
              aria-label="播放量口径"
              value={trafficBoostMode}
              onChange={(event) => {
                setTrafficBoostMode(event.target.value as TrafficBoostMode);
                setPostPage(1);
              }}
              className="ui-select"
            >
              <option value="original">原始播放量</option>
              <option value="boosted_preview">7月加成后播放量</option>
            </select>
            <label className="dashboard-toggle">
              <span>包含异业活动数据</span>
              <input
                type="checkbox"
                checked={includeCrossIndustry}
                onChange={(event) => {
                  setIncludeCrossIndustry(event.target.checked);
                  setPostPage(1);
                }}
              />
              <span className="dashboard-toggle-track" aria-hidden="true" />
            </label>
          </div>
        </div>

        <div className="dashboard-metrics">
          <MetricCard
            label="总播放量"
            value={fmtInt(currentMetrics.totalViews)}
            icon={Eye}
            tone="blue"
            delta={changeRate(previousMetrics.totalViews, currentMetrics.totalViews)}
          />
          <MetricCard
            label="投稿总数"
            value={fmtInt(currentMetrics.totalPosts)}
            icon={FileText}
            tone="teal"
            delta={changeRate(previousMetrics.totalPosts, currentMetrics.totalPosts)}
          />
          <MetricCard
            label="覆盖达人"
            value={fmtInt(currentMetrics.coveredCreators)}
            icon={Users}
            tone="amber"
            delta={changeRate(
              previousMetrics.coveredCreators,
              currentMetrics.coveredCreators
            )}
          />
          <MetricCard
            label="单条平均播放"
            value={fmtInt(currentMetrics.averageViews)}
            icon={Gauge}
            tone="violet"
            delta={changeRate(previousMetrics.averageViews, currentMetrics.averageViews)}
          />
        </div>

        <div className="dashboard-core-grid">
          <Panel
            title="月度核心对比"
            description={`${effectiveComparisonMonth || "-"} 对比 ${effectiveMonth || "-"}`}
            icon={BarChart3}
            actions={
              <select
                aria-label="对比月份"
                value={effectiveComparisonMonth}
                onChange={(event) => setComparisonMonth(event.target.value)}
                className="ui-select dashboard-compact-select"
              >
                {[...new Set([effectiveComparisonMonth, ...availableMonths])]
                  .filter(Boolean)
                  .map((month) => (
                    <option key={month}>{month}</option>
                  ))}
              </select>
            }
          >
            <StateShell
              isLoading={summaryQuery.isLoading || previousSummaryQuery.isLoading}
              isError={summaryQuery.isError || previousSummaryQuery.isError}
              isEmpty={!canCompare}
              emptyLabel="月度模式下显示对比"
            >
              <div className="dashboard-chart dashboard-chart-medium">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={monthlyComparisonData} margin={{ top: 12, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="period" tickLine={false} axisLine={false} />
                    <YAxis yAxisId="views" tickLine={false} axisLine={false} width={70} />
                    <YAxis yAxisId="posts" orientation="right" tickLine={false} axisLine={false} width={42} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend />
                    <Bar yAxisId="views" dataKey="views" name="播放量" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={72} />
                    <Line yAxisId="posts" type="monotone" dataKey="posts" name="投稿数" stroke="var(--chart-3)" strokeWidth={2.25} dot={{ r: 4 }} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </StateShell>
          </Panel>

          <Panel
            title="月内趋势"
            description="按自然日对齐两个周期"
            icon={ChartNoAxesCombined}
            actions={
              <SegmentedControl
                value={trendMode}
                onChange={(value) => setTrendMode(value as TrendMode)}
                options={[
                  ["daily_views", "每日播放"],
                  ["cumulative_views", "累计播放"],
                  ["daily_posts", "每日投稿"],
                ]}
              />
            }
          >
            <StateShell
              isLoading={dailyQuery.isLoading || previousDailyQuery.isLoading}
              isError={dailyQuery.isError || previousDailyQuery.isError}
              isUnauthorized={dailyQuery.error instanceof ApiError && dailyQuery.error.status === 401}
              isEmpty={trendData.length === 0}
            >
              <div className="dashboard-chart dashboard-chart-medium">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trendData} margin={{ top: 12, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="label" tickLine={false} axisLine={false} interval="preserveStartEnd" />
                    <YAxis tickLine={false} axisLine={false} width={70} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend />
                    <Line type="monotone" dataKey="previous" name={effectiveComparisonMonth} stroke="var(--chart-3)" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="current" name={effectiveMonth} stroke="var(--chart-1)" strokeWidth={2.4} dot={false} activeDot={{ r: 4 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </StateShell>
          </Panel>
        </div>

        <div className="dashboard-core-grid">
          <DimensionPanel
            title="平台表现"
            description="YouTube 与 TikTok 的贡献变化"
            query={platformComparisonQuery}
            data={platformData}
            metric={platformMetric}
            onMetricChange={setPlatformMetric}
          />
          <DimensionPanel
            title="视频类型表现"
            description="long、shorts、livestream 与 TikTok"
            query={contentComparisonQuery}
            data={contentData}
            metric={contentMetric}
            onMetricChange={setContentMetric}
          />
        </div>

        <Panel
          title="达人月度变化"
          description={`${fmtInt(creatorMovements.length)} 位有投稿达人`}
          icon={Users}
        >
          <StateShell
            isLoading={creatorComparisonQuery.isLoading}
            isError={creatorComparisonQuery.isError}
            isEmpty={creatorMovements.length === 0}
          >
            <DataTable
              columns={movementColumns}
              rows={creatorMovements}
              rowKey={(row) => row.creatorKey}
              maxHeight={430}
            />
          </StateShell>
        </Panel>

        <Panel
          title="运营机会与 CPM 预警"
          description="增长贡献、下降风险与达人成本效率"
          icon={AlertTriangle}
          actions={
            <label className="dashboard-cpm-target">
              目标 CPM
              <input
                aria-label="目标CPM"
                type="number"
                min="0"
                step="0.1"
                value={cpmTarget}
                onChange={(event) => setCpmTarget(Math.max(0, Number(event.target.value)))}
              />
              USD
            </label>
          }
        >
          <div className="dashboard-alert-summary">
            <StatusChip tone="positive" label={`增长贡献 ${growthRows.length}`} />
            <StatusChip tone="danger" label={`下降预警 ${declineRows.length}`} />
            <StatusChip tone="warning" label={`高 CPM ${highCpmCount}`} />
            {staleCpmSources > 0 && (
              <StatusChip tone="neutral" label={`${staleCpmSources} 类结算缓存待重算`} />
            )}
          </div>

          <div className="dashboard-alert-grid">
            <InsightList
              title="增长贡献榜"
              rows={growthRows}
              emptyLabel="暂无明显增长"
              renderValue={(row) => `+${fmtInt(row.viewDelta)} 播放`}
              tone="positive"
            />
            <InsightList
              title="下降超过 30%"
              rows={declineRows}
              emptyLabel="暂无重点下降预警"
              renderValue={(row) =>
                `播放 ${fmtPercent(row.viewChangeRate)} · 投稿 ${fmtPercent(row.postChangeRate)}`
              }
              tone="danger"
            />
          </div>

          <div className="dashboard-cpm-grid">
            <div>
              <div className="dashboard-subheading">
                <div>
                  <strong>达人 CPM 分布</strong>
                  <span>气泡大小代表有道应收美元</span>
                </div>
                <span className="dashboard-readonly-badge">只读</span>
              </div>
              <StateShell
                isLoading={cpmAlertsQuery.isLoading}
                isError={cpmAlertsQuery.isError}
                isEmpty={cpmScatterData.length === 0}
                emptyLabel="尚无锁定结算或计算缓存，本页不会自动计算"
              >
                <div className="dashboard-chart dashboard-chart-cpm">
                  <ResponsiveContainer width="100%" height="100%">
                    <ScatterChart margin={{ top: 12, right: 18, left: 0, bottom: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis type="number" dataKey="all_video_views" name="全部播放量" tickLine={false} axisLine={false} />
                      <YAxis type="number" dataKey="cpm" name="CPM" unit="$" tickLine={false} axisLine={false} width={50} />
                      <ZAxis type="number" dataKey="youdao_receivable_usd" range={[55, 320]} />
                      <Tooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={tooltipStyle} />
                      <Scatter data={cpmScatterData} name="达人 CPM">
                        {cpmScatterData.map((row) => (
                          <Cell key={`${row.creator_category}-${row.creator_key}`} fill={cpmColor(row, cpmTarget)} />
                        ))}
                      </Scatter>
                    </ScatterChart>
                  </ResponsiveContainer>
                </div>
              </StateShell>
            </div>
            <div>
              <div className="dashboard-subheading">
                <div>
                  <strong>CPM 预警明细</strong>
                  <span>锁定版本优先，其次读取已有缓存</span>
                </div>
              </div>
              <StateShell
                isLoading={cpmAlertsQuery.isLoading}
                isError={cpmAlertsQuery.isError}
                isEmpty={cpmRows.length === 0}
                emptyLabel="暂无可读取的 CPM 结果"
              >
                <DataTable
                  columns={cpmColumns}
                  rows={cpmRows}
                  rowKey={(row) => `${row.creator_category}-${row.creator_key}`}
                  maxHeight={310}
                />
              </StateShell>
            </div>
          </div>
        </Panel>

        <details
          className="dashboard-disclosure"
          onToggle={(event) => setShowDetails(event.currentTarget.open)}
        >
          <summary>
            <span>
              <Layers3 size={16} />详细数据与排行
            </span>
            <small>达人汇总、六类排行、最近导入与完整投稿明细</small>
          </summary>
          <div className="dashboard-disclosure-body">
            <div className="dashboard-overview-grid">
              <Panel title="达人汇总" description={`${fmtInt(summaryRows.length)} 位达人`} icon={Users}>
                <StateShell
                  isLoading={summaryQuery.isLoading}
                  isError={summaryQuery.isError}
                  isEmpty={summaryRows.length === 0}
                >
                  <DataTable columns={summaryColumns} rows={summaryRows} rowKey={(row) => row.creator_key} maxHeight={360} />
                </StateShell>
              </Panel>
              <Panel title="最近导入" description="最近 10 个批次" icon={UploadCloud}>
                <StateShell
                  isLoading={importBatchesQuery.isLoading}
                  isError={importBatchesQuery.isError}
                  isEmpty={(importBatchesQuery.data?.data.length ?? 0) === 0}
                >
                  <ul className="dashboard-batch-list">
                    {(importBatchesQuery.data?.data ?? []).map((batch) => (
                      <li key={batch.batch_id} className="dashboard-batch-item">
                        <span className="dashboard-batch-index">#{batch.batch_id}</span>
                        <div>
                          <strong>
                            {batch.period_months.join("、") || "未标记月份"} · {importModeLabel(batch.mode)}
                          </strong>
                          <span>
                            输入 {fmtInt(batch.input_count)} · 保存 {fmtInt(batch.saved_count)} · 移除 {fmtInt(batch.removed_count)}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </StateShell>
              </Panel>
            </div>

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
                <button type="button" className="ui-button ui-button-outline" onClick={() => setShowColumnSettings((value) => !value)}>
                  <Columns3 size={14} />字段设置
                </button>
              </div>
              {showColumnSettings && (
                <ColumnSettings columns={allPostColumns} selected={visiblePostColumns} onChange={setVisiblePostColumns} />
              )}
              <StateShell isLoading={postsQuery.isLoading} isError={postsQuery.isError} isEmpty={postRows.length === 0}>
                <DataTable columns={postColumns} rows={postRows} rowKey={(row) => `${row.url}-${row.publish_date ?? ""}`} />
              </StateShell>
              {postPagination && (
                <div className="dashboard-pagination">
                  <button className="ui-button ui-button-outline" disabled={postPage <= 1} onClick={() => setPostPage((page) => page - 1)}>上一页</button>
                  <span>{postPage} / {postPagination.total_pages}</span>
                  <button className="ui-button ui-button-outline" disabled={postPage >= postPagination.total_pages} onClick={() => setPostPage((page) => page + 1)}>下一页</button>
                </div>
              )}
            </Panel>
          </div>
        </details>
      </section>
    </AppShell>
  );
}

const tooltipStyle = {
  border: "1px solid var(--border)",
  borderRadius: 8,
  boxShadow: "var(--shadow-sm)",
  fontSize: 12,
};

function buildMovementColumns(): Column<CreatorMovement>[] {
  return [
    { key: "creatorName", header: "达人", width: 140, render: (row) => row.creatorName },
    { key: "currentViews", header: "本月播放", width: 105, align: "right", render: (row) => fmtInt(row.currentViews) },
    { key: "viewChangeRate", header: "播放环比", width: 95, align: "right", highlight: (row) => isDrop30(row.viewChangeRate), render: (row) => <ChangeValue value={row.viewChangeRate} /> },
    { key: "currentPosts", header: "本月投稿", width: 90, align: "right", render: (row) => fmtInt(row.currentPosts) },
    { key: "postChangeRate", header: "投稿环比", width: 95, align: "right", highlight: (row) => isDrop30(row.postChangeRate), render: (row) => <ChangeValue value={row.postChangeRate} /> },
    { key: "longChangeRate", header: "Long", width: 82, align: "right", highlight: (row) => isDrop30(row.longChangeRate), render: (row) => fmtPercent(row.longChangeRate) },
    { key: "shortsChangeRate", header: "Shorts", width: 82, align: "right", highlight: (row) => isDrop30(row.shortsChangeRate), render: (row) => fmtPercent(row.shortsChangeRate) },
    { key: "livestreamChangeRate", header: "直播", width: 82, align: "right", highlight: (row) => isDrop30(row.livestreamChangeRate), render: (row) => fmtPercent(row.livestreamChangeRate) },
    { key: "tiktokChangeRate", header: "TikTok", width: 82, align: "right", highlight: (row) => isDrop30(row.tiktokChangeRate), render: (row) => fmtPercent(row.tiktokChangeRate) },
  ];
}

function buildCpmColumns(target: number): Column<CpmAlertRow>[] {
  return [
    { key: "creator_name", header: "达人", width: 125, render: (row) => row.creator_name },
    { key: "creator_category", header: "类别", width: 72, render: (row) => creatorCategoryLabel(row.creator_category) },
    { key: "all_video_views", header: "播放量", width: 95, align: "right", render: (row) => fmtInt(row.all_video_views) },
    { key: "youdao_receivable_usd", header: "有道应收", width: 95, align: "right", render: (row) => fmtUsd(row.youdao_receivable_usd) },
    { key: "cpm", header: "CPM", width: 72, align: "right", highlight: (row) => cpmSeverity(row, target) >= 2, render: (row) => fmtCpm(row.cpm) },
    { key: "cpm_change_rate", header: "环比", width: 78, align: "right", highlight: (row) => (row.cpm_change_rate ?? 0) > 0.3, render: (row) => fmtPercent(row.cpm_change_rate) },
    { key: "status", header: "状态", width: 92, render: (row) => <CpmStatus row={row} target={target} /> },
  ];
}

function cpmSeverity(row: CpmAlertRow, target: number): number {
  if (row.all_video_views <= 0 && row.youdao_receivable_usd > 0) return 3;
  if ((row.cpm ?? 0) > target * 1.3 || (row.cpm_change_rate ?? 0) > 0.3) return 3;
  if ((row.cpm ?? 0) > target || row.calculation_status === "STALE") return 2;
  if (row.cpm === null) return 0;
  return 1;
}

function cpmColor(row: CpmAlertRow, target: number): string {
  const severity = cpmSeverity(row, target);
  if (severity >= 3) return "#dc2626";
  if (severity === 2) return "#d97706";
  return "#0f766e";
}

function CpmStatus({ row, target }: { row: CpmAlertRow; target: number }) {
  const severity = cpmSeverity(row, target);
  const label =
    row.all_video_views <= 0 && row.youdao_receivable_usd > 0
      ? "数据异常"
      : severity >= 3
        ? "严重预警"
        : severity === 2
          ? "关注"
          : row.cpm === null
            ? "无CPM"
            : "正常";
  return <span className={`dashboard-status dashboard-status-${severity}`}>{label}</span>;
}

function ChangeValue({ value }: { value: number | null }) {
  if (value === null) return <span>新增</span>;
  const positive = value > 0;
  const Icon = positive ? ArrowUpRight : value < 0 ? ArrowDownRight : null;
  return (
    <span className={positive ? "dashboard-change-positive" : value < 0 ? "dashboard-change-negative" : ""}>
      {Icon && <Icon size={12} />}{fmtPercent(value)}
    </span>
  );
}

function DimensionPanel({
  title,
  description,
  query,
  data,
  metric,
  onMetricChange,
}: {
  title: string;
  description: string;
  query: { isLoading: boolean; isError: boolean };
  data: Array<{ name: string; previous: number; current: number; changeRate: number | null }>;
  metric: StructureMetric;
  onMetricChange: (value: StructureMetric) => void;
}) {
  return (
    <Panel
      title={title}
      description={description}
      icon={BarChart3}
      actions={
        <SegmentedControl
          value={metric}
          onChange={(value) => onMetricChange(value as StructureMetric)}
          options={[["views", "播放"], ["posts", "投稿"]]}
        />
      }
    >
      <StateShell isLoading={query.isLoading} isError={query.isError} isEmpty={data.length === 0}>
        <div className="dashboard-chart dashboard-chart-medium">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 12, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="name" tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} width={66} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend />
              <Bar dataKey="previous" name="对比期" fill="var(--chart-3)" radius={[3, 3, 0, 0]} />
              <Bar dataKey="current" name="目标期" fill="var(--chart-2)" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </StateShell>
    </Panel>
  );
}

function InsightList({
  title,
  rows,
  emptyLabel,
  renderValue,
  tone,
}: {
  title: string;
  rows: CreatorMovement[];
  emptyLabel: string;
  renderValue: (row: CreatorMovement) => string;
  tone: "positive" | "danger";
}) {
  return (
    <section className="dashboard-insight-list">
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <p>{emptyLabel}</p>
      ) : (
        <ol>
          {rows.map((row) => (
            <li key={row.creatorKey}>
              <span>{row.creatorName}</span>
              <strong className={`dashboard-insight-${tone}`}>{renderValue(row)}</strong>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function StatusChip({ tone, label }: { tone: "positive" | "danger" | "warning" | "neutral"; label: string }) {
  return <span className={`dashboard-chip dashboard-chip-${tone}`}>{label}</span>;
}

function SegmentedControl({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: [string, string][] }) {
  return (
    <div className="dashboard-mini-segmented">
      {options.map(([key, label]) => (
        <button key={key} type="button" className={value === key ? "is-active" : ""} onClick={() => onChange(key)}>
          {label}
        </button>
      ))}
    </div>
  );
}

function buildPostColumns(): Column<DashboardPostRow>[] {
  return [
    { key: "source_file", header: "来源文件", width: 150, render: (row) => row.source_file ?? "-" },
    { key: "kol_name", header: "KOL Name", width: 120, render: (row) => row.kol_name ?? row.koc_name },
    { key: "koc_name", header: "达人", width: 120, render: (row) => row.koc_name },
    { key: "user_id", header: "UID", width: 120, render: (row) => row.user_id },
    { key: "creator_key", header: "达人匹配键", width: 125, render: (row) => row.creator_key },
    { key: "creator_id", header: "达人内部ID", width: 105, align: "right", render: (row) => fmtInt(row.creator_id) },
    { key: "creator_category", header: "合作类别", width: 90, render: (row) => creatorCategoryLabel(row.creator_category) },
    { key: "contract_types", header: "合同类型", width: 150, render: (row) => row.contract_types.join("、") || "-" },
    { key: "contract_start_date", header: "合同开始", width: 105, render: (row) => row.contract_start_date ?? "-" },
    { key: "contract_end_date", header: "合同截止", width: 105, render: (row) => row.contract_end_date ?? "-" },
    { key: "source_platform", header: "平台", width: 85, render: (row) => row.source_platform },
    { key: "content_type", header: "内容类型", width: 95, render: (row) => row.content_type },
    { key: "subtype", header: "Subtype", width: 95, render: (row) => row.subtype },
    { key: "description", header: "Description", width: 260, render: (row) => row.description ?? "-" },
    { key: "title", header: "标题", width: 240, render: (row) => row.title },
    { key: "url", header: "URL", width: 110, render: (row) => <a href={row.url} target="_blank" rel="noreferrer">打开视频</a> },
    { key: "publish_date", header: "发布日期", width: 105, render: (row) => row.publish_date ?? "-" },
    { key: "timestamp", header: "Timestamp", width: 150, render: (row) => row.timestamp ?? "-" },
    { key: "view", header: "原字段播放量", width: 115, align: "right", render: (row) => fmtInt(row.view) },
    { key: "original_views", header: "原始播放量", width: 105, align: "right", render: (row) => fmtInt(row.original_views) },
    { key: "traffic_boost_views", header: "流量加成", width: 100, align: "right", render: (row) => fmtInt(row.traffic_boost_views) },
    { key: "boosted_views", header: "加成后播放量", width: 115, align: "right", render: (row) => fmtInt(row.boosted_views) },
    { key: "views", header: "最终播放量", width: 105, align: "right", render: (row) => fmtInt(row.views) },
    { key: "likes", header: "Likes", width: 85, align: "right", render: (row) => fmtInt(row.likes) },
    { key: "comment", header: "Comment", width: 85, align: "right", render: (row) => fmtInt(row.comment) },
    { key: "reposted", header: "Reposted", width: 85, align: "right", render: (row) => fmtInt(row.reposted) },
    { key: "collect", header: "Collect", width: 85, align: "right", render: (row) => fmtInt(row.collect) },
    { key: "matched", header: "达人匹配", width: 85, render: (row) => row.matched ? "是" : "否" },
    { key: "profile_status", header: "资料状态", width: 105, render: (row) => row.profile_status },
    { key: "profile_effective_date", header: "资料生效日", width: 105, render: (row) => row.profile_effective_date ?? "-" },
    { key: "creator_active", header: "达人启用", width: 85, render: (row) => row.creator_active ? "是" : "否" },
    { key: "compensation_eligible", header: "计费资格", width: 85, render: (row) => row.compensation_eligible ? "是" : "否" },
    { key: "is_cross_industry", header: "异业活动", width: 85, render: (row) => row.is_cross_industry ? "是" : "否" },
    { key: "cross_industry_url_key", header: "异业URL键", width: 180, render: (row) => row.cross_industry_url_key ?? "-" },
    { key: "cross_industry_reason", header: "异业排除原因", width: 180, render: (row) => row.cross_industry_reason ?? "-" },
    { key: "cross_industry_exclusion_id", header: "异业排除ID", width: 105, align: "right", render: (row) => fmtInt(row.cross_industry_exclusion_id) },
    { key: "follower_count", header: "总粉丝数", width: 95, align: "right", render: (row) => fmtInt(row.follower_count) },
    { key: "homepage_url", header: "主页", width: 180, render: (row) => row.homepage_url ?? "-" },
    { key: "youtube_user_id", header: "YouTube UID", width: 120, render: (row) => row.youtube_user_id ?? "-" },
    { key: "youtube_homepage_url", header: "YouTube主页", width: 190, render: (row) => row.youtube_homepage_url ?? "-" },
    { key: "youtube_follower_count", header: "YouTube粉丝数", width: 120, align: "right", render: (row) => fmtInt(row.youtube_follower_count) },
    { key: "tiktok_user_id", header: "TikTok UID", width: 120, render: (row) => row.tiktok_user_id ?? "-" },
    { key: "tiktok_homepage_url", header: "TikTok主页", width: 190, render: (row) => row.tiktok_homepage_url ?? "-" },
    { key: "tiktok_follower_count", header: "TikTok粉丝数", width: 120, align: "right", render: (row) => fmtInt(row.tiktok_follower_count) },
  ];
}

function importModeLabel(mode: string): string {
  if (mode === "REPLACE_MONTHS") return "按月完整替换";
  if (mode === "APPEND_OR_UPDATE") return "补充或更新";
  return mode;
}

function ColumnSettings({ columns, selected, onChange }: { columns: Column<DashboardPostRow>[]; selected: string[]; onChange: (keys: string[]) => void }) {
  return (
    <div className="dashboard-column-settings">
      {columns.map((column) => (
        <label key={column.key} className="dashboard-check-label">
          <input type="checkbox" checked={selected.includes(column.key)} onChange={(event) => onChange(event.target.checked ? [...selected, column.key] : selected.filter((key) => key !== column.key))} />
          {column.header}
        </label>
      ))}
      <button type="button" className="ui-button ui-button-outline" onClick={() => onChange(DEFAULT_POST_COLUMN_KEYS)}>恢复默认</button>
      <button type="button" className="ui-button ui-button-outline" onClick={() => onChange(columns.map((column) => column.key))}>显示全部</button>
    </div>
  );
}

function RankingPanel<T extends RankingCreatorItem | RankingVideoItem>({ title, query, columns }: { title: string; query: { isLoading: boolean; isError: boolean; data?: { data: { items: (RankingCreatorItem | RankingVideoItem)[] } } }; columns: Column<T>[] }) {
  const rows = (query.data?.data.items ?? []) as T[];
  return (
    <Panel title={title} description={`${fmtInt(rows.length)} 条`}>
      <StateShell isLoading={query.isLoading} isError={query.isError} isEmpty={rows.length === 0}>
        <DataTable columns={columns} rows={rows} rowKey={(row) => row.rank} maxHeight={360} />
      </StateShell>
    </Panel>
  );
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: [string, string][] }) {
  return (
    <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} className="ui-select">
      <option value="">{label}</option>
      {options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}
    </select>
  );
}

function MetricCard({ label, value, icon: Icon, tone, delta }: { label: string; value: string; icon: LucideIcon; tone: "blue" | "teal" | "amber" | "violet"; delta: number | null }) {
  return (
    <div className="dashboard-metric">
      <span className={`dashboard-metric-icon dashboard-metric-${tone}`}><Icon size={17} /></span>
      <div>
        <div className="dashboard-metric-label">{label}</div>
        <div className="dashboard-metric-value">{value || "-"}</div>
        <div className="dashboard-metric-delta"><ChangeValue value={delta} /><span>较对比月</span></div>
      </div>
    </div>
  );
}

function Panel({ title, description, icon: Icon, actions, children }: { title: string; description?: string; icon?: LucideIcon; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="dashboard-panel">
      <header className="dashboard-panel-header">
        <div className="dashboard-panel-title">{Icon && <Icon size={15} />}<strong>{title}</strong>{description && <span>{description}</span>}</div>
        {actions && <div className="dashboard-panel-actions">{actions}</div>}
      </header>
      <div className="dashboard-panel-body">{children}</div>
    </section>
  );
}

export { isDrop30 };
