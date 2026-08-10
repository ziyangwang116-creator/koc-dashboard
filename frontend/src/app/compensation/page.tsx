"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { StateShell } from "@/components/DataStates";
import { ModeBadge } from "@/components/ModeBadge";
import { compensationApi } from "@/lib/endpoints";
import { ApiError } from "@/lib/api-client";
import { fmtInt, fmtUsd, fmtCpm } from "@/lib/format";
import type {
  CompensationMode,
  CommentaryRow,
  GrassrootRow,
  LongTermRow,
  ThemeSubmission,
} from "@/lib/types";

type Lane = "GRASSROOT" | "LONG_TERM" | "COMMENTARY";

const LANES: { key: Lane; label: string }[] = [
  { key: "GRASSROOT", label: "草根" },
  { key: "LONG_TERM", label: "长包" },
  { key: "COMMENTARY", label: "解说" },
];

export default function CompensationPage() {
  const [lane, setLane] = useState<Lane>("GRASSROOT");
  const [periodMonth, setPeriodMonth] = useState<string>("");
  const [settlementStatus, setSettlementStatus] = useState("");
  const [q, setQ] = useState("");
  const [versionId, setVersionId] = useState<number | undefined>(undefined);

  const periodsQuery = useQuery({
    queryKey: ["compensation", "periods", lane],
    queryFn: () => compensationApi.periods(lane),
  });

  const periods = periodsQuery.data?.data ?? [];
  const effectiveMonth = periodMonth || periods[0]?.period_month || "";

  const versionsQuery = useQuery({
    queryKey: ["compensation", "versions", lane, effectiveMonth],
    queryFn: () => compensationApi.versions(effectiveMonth, lane),
    enabled: Boolean(effectiveMonth),
  });

  const baseParams = {
    period_month: effectiveMonth,
    settlement_status: settlementStatus || undefined,
    q: q || undefined,
    version_id: versionId,
    page_size: 50,
  };

  const grassrootQuery = useQuery({
    queryKey: ["compensation", "grassroot", baseParams],
    queryFn: () => compensationApi.grassroot(baseParams),
    enabled: lane === "GRASSROOT" && Boolean(effectiveMonth),
  });

  const longTermQuery = useQuery({
    queryKey: ["compensation", "long-term", baseParams],
    queryFn: () => compensationApi.longTerm(baseParams),
    enabled: lane === "LONG_TERM" && Boolean(effectiveMonth),
  });

  const commentaryQuery = useQuery({
    queryKey: ["compensation", "commentary", baseParams],
    queryFn: () => compensationApi.commentary(baseParams),
    enabled: lane === "COMMENTARY" && Boolean(effectiveMonth),
  });

  const themeSubmissionsQuery = useQuery({
    queryKey: ["compensation", "theme-submissions", effectiveMonth],
    queryFn: () => compensationApi.themeSubmissions({ period_month: effectiveMonth }),
    enabled: lane === "COMMENTARY" && Boolean(effectiveMonth),
  });

  const activeQuery = lane === "GRASSROOT" ? grassrootQuery : lane === "LONG_TERM" ? longTermQuery : commentaryQuery;
  const mode: CompensationMode = (activeQuery.data?.meta.mode as CompensationMode) ?? "preview";
  const summary = activeQuery.data?.meta.summary;

  const grassrootColumns: Column<GrassrootRow>[] = useMemo(
    () => [
      { key: "creator_name", header: "达人", width: 110, render: (r) => r.creator_name },
      { key: "settlement_status", header: "结算状态", width: 100, render: (r) => r.settlement_status },
      { key: "rank", header: "等级", width: 60, render: (r) => r.rank },
      {
        key: "creator_receivable_usd",
        header: "博主应收美元",
        width: 120,
        align: "right",
        render: (r) => <strong>{fmtUsd(r.creator_receivable_usd)}</strong>,
      },
      {
        key: "total_amount_jpy",
        header: "总金额（日元）",
        width: 110,
        align: "right",
        render: (r) => (
          <span style={{ color: "var(--color-text-muted)", fontSize: 12 }}>{fmtInt(r.total_amount_jpy)}</span>
        ),
      },
      { key: "billable_views", header: "计费播放量", width: 110, align: "right", render: (r) => fmtInt(r.billable_views) },
      { key: "cpm", header: "CPM", width: 70, align: "right", render: (r) => fmtCpm(r.cpm) },
    ],
    []
  );

  const longTermColumns: Column<LongTermRow>[] = useMemo(
    () => [
      { key: "creator_name", header: "达人", width: 110, render: (r) => r.creator_name },
      { key: "settlement_status", header: "结算状态", width: 110, render: (r) => r.settlement_status },
      { key: "rank", header: "等级", width: 60, render: (r) => r.rank },
      {
        key: "monthly_activity_count",
        header: "活动数",
        width: 80,
        align: "right",
        render: (r) => fmtInt(r.monthly_activity_count),
      },
      {
        key: "monthly_new_post_views",
        header: "月度播放量",
        width: 110,
        align: "right",
        render: (r) => fmtInt(r.monthly_new_post_views),
      },
      {
        key: "creator_receivable_usd",
        header: "博主应收美元",
        width: 120,
        align: "right",
        render: (r) => <strong>{fmtUsd(r.creator_receivable_usd)}</strong>,
      },
      { key: "cpm", header: "CPM", width: 70, align: "right", render: (r) => fmtCpm(r.cpm) },
    ],
    []
  );

  const commentaryColumns: Column<CommentaryRow>[] = useMemo(
    () => [
      { key: "creator_name", header: "达人", width: 110, render: (r) => r.creator_name },
      { key: "settlement_status", header: "结算状态", width: 100, render: (r) => r.settlement_status },
      {
        key: "designated_theme_count",
        header: "指定主题件数",
        width: 100,
        align: "right",
        render: (r) => fmtInt(r.designated_theme_count),
      },
      {
        key: "designated_theme_reward_jpy",
        header: "指定主题报酬（日元）",
        width: 130,
        align: "right",
        render: (r) => fmtInt(r.designated_theme_reward_jpy),
      },
      { key: "all_paid_views", header: "全部已付费播放量", width: 120, align: "right", render: (r) => fmtInt(r.all_paid_views) },
      {
        key: "creator_receivable_usd",
        header: "博主应收美元",
        width: 120,
        align: "right",
        render: (r) => <strong>{fmtUsd(r.creator_receivable_usd)}</strong>,
      },
      { key: "cpm", header: "CPM", width: 70, align: "right", render: (r) => fmtCpm(r.cpm) },
    ],
    []
  );

  const themeColumns: Column<ThemeSubmission>[] = [
    { key: "creator_id", header: "达人ID", width: 70, align: "right", render: (r) => r.creator_id },
    { key: "theme_name", header: "主题", width: 120, render: (r) => r.theme_name },
    { key: "content_format", header: "格式", width: 70, render: (r) => r.content_format },
    { key: "review_status", header: "审核状态", width: 90, render: (r) => r.review_status },
    {
      key: "billing_excluded",
      header: "计费排除",
      width: 90,
      render: (r) =>
        r.billing_excluded ? (
          <span style={{ color: "var(--color-warning)" }}>是（{r.billing_excluded_url_count} 条）</span>
        ) : (
          "否"
        ),
    },
  ];

  return (
    <AppShell currentPeriod={effectiveMonth}>
      <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={tabBar}>
          {LANES.map((l) => (
            <button
              key={l.key}
              onClick={() => {
                setLane(l.key);
                setVersionId(undefined);
              }}
              style={{
                ...tabBtn,
                ...(lane === l.key ? tabBtnActive : {}),
              }}
            >
              {l.label}
            </button>
          ))}
        </div>

        <div style={filterBar}>
          <select
            value={effectiveMonth}
            onChange={(e) => {
              setPeriodMonth(e.target.value);
              setVersionId(undefined);
            }}
            style={selectStyle}
          >
            {periods.map((p) => (
              <option key={p.period_month} value={p.period_month}>
                {p.period_month}
              </option>
            ))}
          </select>
          <input
            placeholder="搜索达人"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ ...selectStyle, minWidth: 160 }}
          />
          <input
            placeholder="结算状态筛选"
            value={settlementStatus}
            onChange={(e) => setSettlementStatus(e.target.value)}
            style={{ ...selectStyle, minWidth: 140 }}
          />
          <select
            value={versionId ?? ""}
            onChange={(e) => setVersionId(e.target.value ? Number(e.target.value) : undefined)}
            style={selectStyle}
          >
            <option value="">当前预览</option>
            {(versionsQuery.data?.data ?? []).map((v) => (
              <option key={v.version_id} value={v.version_id}>
                v{v.version_no ?? "?"}（{v.status}）
              </option>
            ))}
          </select>
          <ModeBadge mode={mode} />
        </div>

        {summary && (
          <div className="metric-row">
            <div className="metric-card" style={summaryCard}>
              <div style={summaryLabel}>
                {lane === "GRASSROOT" ? "博主应收美元合计（主展示口径）" : "博主应收美元合计"}
              </div>
              <div style={summaryValue}>{fmtUsd(summary.creator_receivable_usd as number)}</div>
            </div>
            <div className="metric-card" style={{ ...summaryCard, opacity: 0.7 }}>
              <div style={summaryLabel}>总金额（日元，审计口径）</div>
              <div style={{ ...summaryValue, fontSize: 15 }}>{fmtInt(summary.total_amount_jpy as number)}</div>
            </div>
            <div className="metric-card" style={summaryCard}>
              <div style={summaryLabel}>整体 CPM</div>
              <div style={summaryValue}>{fmtCpm(summary.overall_cpm as number)}</div>
            </div>
          </div>
        )}

        <div style={panelStyle}>
          {lane === "GRASSROOT" && (
            <StateShell
              isLoading={grassrootQuery.isLoading}
              isError={grassrootQuery.isError}
              isUnauthorized={grassrootQuery.error instanceof ApiError && grassrootQuery.error.status === 401}
              errorMessage={grassrootQuery.error instanceof ApiError ? grassrootQuery.error.message : undefined}
              isEmpty={(grassrootQuery.data?.data.length ?? 0) === 0}
            >
              <DataTable
                columns={grassrootColumns}
                rows={grassrootQuery.data?.data ?? []}
                rowKey={(r) => r.creator_key}
              />
            </StateShell>
          )}
          {lane === "LONG_TERM" && (
            <StateShell
              isLoading={longTermQuery.isLoading}
              isError={longTermQuery.isError}
              errorMessage={longTermQuery.error instanceof ApiError ? longTermQuery.error.message : undefined}
              isEmpty={(longTermQuery.data?.data.length ?? 0) === 0}
            >
              <DataTable columns={longTermColumns} rows={longTermQuery.data?.data ?? []} rowKey={(r) => r.record_id} />
            </StateShell>
          )}
          {lane === "COMMENTARY" && (
            <StateShell
              isLoading={commentaryQuery.isLoading}
              isError={commentaryQuery.isError}
              errorMessage={commentaryQuery.error instanceof ApiError ? commentaryQuery.error.message : undefined}
              isEmpty={(commentaryQuery.data?.data.length ?? 0) === 0}
            >
              <DataTable
                columns={commentaryColumns}
                rows={commentaryQuery.data?.data ?? []}
                rowKey={(r) => r.creator_id}
              />
            </StateShell>
          )}
        </div>

        {lane === "COMMENTARY" && (
          <div style={panelStyle}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>指定主题申报</div>
            <StateShell
              isLoading={themeSubmissionsQuery.isLoading}
              isError={themeSubmissionsQuery.isError}
              isEmpty={(themeSubmissionsQuery.data?.data.length ?? 0) === 0}
            >
              <DataTable
                columns={themeColumns}
                rows={themeSubmissionsQuery.data?.data ?? []}
                rowKey={(r) => r.id}
              />
            </StateShell>
          </div>
        )}
      </section>
    </AppShell>
  );
}

const tabBar: React.CSSProperties = { display: "flex", gap: 8 };

const tabBtn: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: "var(--radius)",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
  fontSize: 13,
};

const tabBtnActive: React.CSSProperties = {
  background: "var(--color-primary)",
  color: "#fff",
  borderColor: "var(--color-primary)",
  fontWeight: 600,
};

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

const panelStyle: React.CSSProperties = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  padding: 12,
};

const summaryCard: React.CSSProperties = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  padding: 12,
};

const summaryLabel: React.CSSProperties = { fontSize: 12, color: "var(--color-text-muted)" };
const summaryValue: React.CSSProperties = { fontSize: 22, fontWeight: 700, marginTop: 4, color: "var(--color-primary-dark)" };
