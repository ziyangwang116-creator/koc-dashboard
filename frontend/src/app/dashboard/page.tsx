"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { StateShell } from "@/components/DataStates";
import { dashboardApi } from "@/lib/endpoints";
import { ApiError } from "@/lib/api-client";
import { creatorCategoryLabel, fmtInt, fmtPercent, isDrop30 } from "@/lib/format";
import type { DashboardPostRow, DashboardSummaryRow, RankingCreatorItem, RankingVideoItem } from "@/lib/types";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

type PeriodMode = "month" | "week" | "custom";

export default function DashboardPage() {
  const [periodMode, setPeriodMode] = useState<PeriodMode>("month");
  const [periodMonth, setPeriodMonth] = useState<string>("");
  const [weekStart, setWeekStart] = useState<string>("");
  const [creatorKey, setCreatorKey] = useState<string>("");
  const [platform, setPlatform] = useState<string>("");
  const [contentType, setContentType] = useState<string>("");
  const [category, setCategory] = useState<string>("");
  const [includeCrossIndustry, setIncludeCrossIndustry] = useState(false);

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

  const periodParams = useMemo(() => {
    if (periodMode === "month") return { period_mode: "month", period_month: effectiveMonth };
    if (periodMode === "week") return { period_mode: "week", week_start: effectiveWeekStart };
    return { period_mode: "custom" };
  }, [periodMode, effectiveMonth, effectiveWeekStart]);

  const commonFilters = useMemo(
    () => ({
      creator_key: creatorKey || undefined,
      source_platform: platform || undefined,
      content_type: contentType || undefined,
      creator_category: category || undefined,
      include_cross_industry: includeCrossIndustry,
    }),
    [creatorKey, platform, contentType, category, includeCrossIndustry]
  );

  const canQuery = periodMode !== "month" || Boolean(effectiveMonth);

  const summaryQuery = useQuery({
    queryKey: ["dashboard", "summary", periodParams, commonFilters],
    queryFn: () => dashboardApi.summary({ ...periodParams, ...commonFilters, page_size: 50 }),
    enabled: canQuery,
  });

  const postsQuery = useQuery({
    queryKey: ["dashboard", "posts", periodParams, commonFilters],
    queryFn: () => dashboardApi.posts({ ...periodParams, ...commonFilters, page_size: 50 }),
    enabled: canQuery,
  });

  const rankingsYtbQuery = useQuery({
    queryKey: ["dashboard", "rankings", "video_ytb_top20", periodParams, commonFilters],
    queryFn: () =>
      dashboardApi.rankings({ ...periodParams, ...commonFilters, ranking_type: "video_ytb_top20" }),
    enabled: canQuery,
  });

  const rankingsTtQuery = useQuery({
    queryKey: ["dashboard", "rankings", "video_tt_top20", periodParams, commonFilters],
    queryFn: () =>
      dashboardApi.rankings({ ...periodParams, ...commonFilters, ranking_type: "video_tt_top20" }),
    enabled: canQuery,
  });

  const creatorRankingsQuery = useQuery({
    queryKey: ["dashboard", "rankings", "creator_views_top10", periodParams, commonFilters],
    queryFn: () =>
      dashboardApi.rankings({ ...periodParams, ...commonFilters, ranking_type: "creator_views_top10" }),
    enabled: canQuery,
  });

  const importBatchesQuery = useQuery({
    queryKey: ["dashboard", "import-batches"],
    queryFn: () => dashboardApi.importBatches({ limit: 10 }),
  });

  const summaryRows = summaryQuery.data?.data ?? [];
  const postRows = postsQuery.data?.data ?? [];

  const totalViews = summaryRows.reduce((acc, r) => acc + (r.total_views ?? 0), 0);
  const totalPosts = summaryRows.reduce((acc, r) => acc + (r.post_count ?? 0), 0);

  const trendData = useMemo(
    () =>
      [...(postsQuery.data?.data ?? [])]
        .sort((a, b) => (a.publish_date ?? "").localeCompare(b.publish_date ?? ""))
        .reduce<{ date: string; views: number }[]>((acc, p) => {
          const date = p.publish_date ?? "未知日期";
          const existing = acc.find((d) => d.date === date);
          if (existing) existing.views += p.views;
          else acc.push({ date, views: p.views });
          return acc;
        }, []),
    [postsQuery.data]
  );

  const summaryColumns: Column<DashboardSummaryRow>[] = [
    { key: "creator_label", header: "达人", render: (r) => r.creator_label },
    { key: "creator_category", header: "合作类别", render: (r) => creatorCategoryLabel(r.creator_category) },
    { key: "post_count", header: "投稿数", align: "right", render: (r) => fmtInt(r.post_count) },
    { key: "total_views", header: "播放量", align: "right", render: (r) => fmtInt(r.total_views) },
    {
      key: "engagement_rate",
      header: "互动率",
      align: "right",
      render: (r) => fmtPercent(r.engagement_rate),
    },
  ];

  const postColumns: Column<DashboardPostRow>[] = [
    { key: "koc_name", header: "达人", width: 110, render: (r) => r.koc_name },
    { key: "source_platform", header: "平台", width: 80, render: (r) => r.source_platform },
    { key: "content_type", header: "内容类型", width: 90, render: (r) => r.content_type },
    { key: "title", header: "标题", width: 220, render: (r) => r.title },
    { key: "publish_date", header: "发布日期", width: 100, render: (r) => r.publish_date },
    { key: "views", header: "播放量", width: 100, align: "right", render: (r) => fmtInt(r.views) },
    { key: "profile_status", header: "匹配状态", width: 100, render: (r) => r.profile_status },
  ];

  const creatorRankColumns: Column<RankingCreatorItem>[] = [
    { key: "rank", header: "#", width: 40, align: "right", render: (r) => r.rank },
    { key: "creator_label", header: "达人", render: (r) => r.creator_label },
    { key: "total_views", header: "播放量", align: "right", render: (r) => fmtInt(r.total_views) },
    { key: "post_count", header: "投稿数", align: "right", render: (r) => fmtInt(r.post_count) },
  ];

  function videoRankColumns(): Column<RankingVideoItem>[] {
    return [
      { key: "rank", header: "#", width: 40, align: "right", render: (r) => r.rank },
      { key: "creator_label", header: "达人", width: 110, render: (r) => r.creator_label },
      { key: "title", header: "标题", width: 220, render: (r) => r.title },
      { key: "views", header: "播放量", width: 100, align: "right", render: (r) => fmtInt(r.views) },
    ];
  }

  return (
    <AppShell currentPeriod={periodMode === "month" ? effectiveMonth : effectiveWeekStart}>
      <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={filterBar}>
          <select value={periodMode} onChange={(e) => setPeriodMode(e.target.value as PeriodMode)} style={selectStyle}>
            <option value="month">按月</option>
            <option value="week">按周</option>
            <option value="custom">自定义区间</option>
          </select>
          {periodMode === "month" && (
            <select value={effectiveMonth} onChange={(e) => setPeriodMonth(e.target.value)} style={selectStyle}>
              {(options?.available_months ?? []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          )}
          {periodMode === "week" && (
            <select value={effectiveWeekStart} onChange={(e) => setWeekStart(e.target.value)} style={selectStyle}>
              {(options?.available_weeks ?? []).map((w) => (
                <option key={w.week_start} value={w.week_start}>
                  {w.week_start} ~ {w.week_end}
                </option>
              ))}
            </select>
          )}
          <select value={creatorKey} onChange={(e) => setCreatorKey(e.target.value)} style={selectStyle}>
            <option value="">全部达人</option>
            {(options?.creators ?? []).map((c) => (
              <option key={c.creator_key} value={c.creator_key}>
                {c.creator_label}
              </option>
            ))}
          </select>
          <select value={platform} onChange={(e) => setPlatform(e.target.value)} style={selectStyle}>
            <option value="">全部平台</option>
            {(options?.source_platforms ?? []).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <select value={contentType} onChange={(e) => setContentType(e.target.value)} style={selectStyle}>
            <option value="">全部内容类型</option>
            {(options?.content_types ?? []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select value={category} onChange={(e) => setCategory(e.target.value)} style={selectStyle}>
            <option value="">全部合作类别</option>
            {(options?.creator_categories ?? []).map((c) => (
              <option key={c} value={c}>
                {creatorCategoryLabel(c)}
              </option>
            ))}
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={includeCrossIndustry}
              onChange={(e) => setIncludeCrossIndustry(e.target.checked)}
            />
            包含异业活动数据
          </label>
        </div>

        <div className="metric-row">
          <MetricCard label="总播放量" value={fmtInt(totalViews)} />
          <MetricCard label="投稿总数" value={fmtInt(totalPosts)} />
          <MetricCard label="达人数" value={fmtInt(summaryRows.length)} />
          <MetricCard
            label="流量加成设置（只读）"
            value={summaryQuery.isSuccess ? "以数据库保存值渲染" : "—"}
          />
        </div>

        <Panel title="播放量趋势" unit="次">
          <StateShell
            isLoading={postsQuery.isLoading}
            isError={postsQuery.isError}
            isUnauthorized={postsQuery.error instanceof ApiError && postsQuery.error.status === 401}
            errorMessage={postsQuery.error instanceof ApiError ? postsQuery.error.message : undefined}
            isEmpty={trendData.length === 0}
          >
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="views" stroke="var(--color-primary)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </StateShell>
        </Panel>

        <Panel title="达人汇总">
          <StateShell
            isLoading={summaryQuery.isLoading}
            isError={summaryQuery.isError}
            isUnauthorized={summaryQuery.error instanceof ApiError && summaryQuery.error.status === 401}
            errorMessage={summaryQuery.error instanceof ApiError ? summaryQuery.error.message : undefined}
            isEmpty={summaryRows.length === 0}
          >
            <DataTable columns={summaryColumns} rows={summaryRows} rowKey={(r) => r.creator_key} />
          </StateShell>
        </Panel>

        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <Panel title="达人播放量 Top 10" style={{ flex: 1, minWidth: 320 }}>
            <StateShell
              isLoading={creatorRankingsQuery.isLoading}
              isError={creatorRankingsQuery.isError}
              isEmpty={(creatorRankingsQuery.data?.data.items.length ?? 0) === 0}
            >
              <DataTable
                columns={creatorRankColumns}
                rows={(creatorRankingsQuery.data?.data.items ?? []) as RankingCreatorItem[]}
                rowKey={(r) => r.rank}
              />
            </StateShell>
          </Panel>
          <Panel title="YouTube Top 20（按播放量）" style={{ flex: 1, minWidth: 320 }}>
            <StateShell
              isLoading={rankingsYtbQuery.isLoading}
              isError={rankingsYtbQuery.isError}
              isEmpty={(rankingsYtbQuery.data?.data.items.length ?? 0) === 0}
            >
              <DataTable
                columns={videoRankColumns()}
                rows={(rankingsYtbQuery.data?.data.items ?? []) as RankingVideoItem[]}
                rowKey={(r) => r.rank}
              />
            </StateShell>
          </Panel>
          <Panel title="TikTok Top 20（按播放量）" style={{ flex: 1, minWidth: 320 }}>
            <StateShell
              isLoading={rankingsTtQuery.isLoading}
              isError={rankingsTtQuery.isError}
              isEmpty={(rankingsTtQuery.data?.data.items.length ?? 0) === 0}
            >
              <DataTable
                columns={videoRankColumns()}
                rows={(rankingsTtQuery.data?.data.items ?? []) as RankingVideoItem[]}
                rowKey={(r) => r.rank}
              />
            </StateShell>
          </Panel>
        </div>

        <Panel title="投稿明细">
          <StateShell
            isLoading={postsQuery.isLoading}
            isError={postsQuery.isError}
            isEmpty={postRows.length === 0}
          >
            <DataTable columns={postColumns} rows={postRows} rowKey={(r) => r.url + r.publish_date} />
          </StateShell>
        </Panel>

        <Panel title="导入批次记录">
          <StateShell
            isLoading={importBatchesQuery.isLoading}
            isError={importBatchesQuery.isError}
            isEmpty={(importBatchesQuery.data?.data.length ?? 0) === 0}
          >
            <ul style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {(importBatchesQuery.data?.data ?? []).map((b) => (
                <li
                  key={b.batch_id}
                  style={{
                    fontSize: 13,
                    padding: "6px 10px",
                    border: "1px solid var(--color-border)",
                    borderRadius: "var(--radius)",
                    background: b.removed_count > 0 ? "var(--color-warning-bg)" : "var(--color-surface)",
                  }}
                >
                  #{b.batch_id} · {b.mode} · {b.period_months.join(", ")} · 导入{fmtInt(b.input_count)}条 / 保存
                  {fmtInt(b.saved_count)}条
                  {b.removed_count > 0 && (
                    <strong style={{ color: "var(--color-warning)" }}> · 覆盖移除 {fmtInt(b.removed_count)} 条</strong>
                  )}
                </li>
              ))}
            </ul>
          </StateShell>
        </Panel>
      </section>
    </AppShell>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="metric-card"
      style={{
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius)",
        padding: 12,
      }}
    >
      <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>{value}</div>
    </div>
  );
}

function Panel({
  title,
  unit,
  children,
  style,
}: {
  title: string;
  unit?: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius)",
        padding: 12,
        ...style,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
        {title}
        {unit && <span style={{ color: "var(--color-text-muted)", fontWeight: 400 }}> （单位：{unit}）</span>}
      </div>
      {children}
    </div>
  );
}

const filterBar: React.CSSProperties = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap",
  alignItems: "center",
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  padding: 10,
};

const selectStyle: React.CSSProperties = {
  padding: "6px 8px",
  borderRadius: "var(--radius)",
  border: "1px solid var(--color-border)",
  fontSize: 13,
};

// exported for potential test usage
export { isDrop30 };
