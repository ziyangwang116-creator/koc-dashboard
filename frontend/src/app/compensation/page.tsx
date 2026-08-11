"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { StateShell } from "@/components/DataStates";
import { ModeBadge } from "@/components/ModeBadge";
import { compensationApi, dashboardApi } from "@/lib/endpoints";
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

const LANE_PATH: Record<Lane, "grassroot" | "long-term" | "commentary"> = {
  GRASSROOT: "grassroot",
  LONG_TERM: "long-term",
  COMMENTARY: "commentary",
};

function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `key-${Date.now()}-${Math.random()}`;
}

function errorMessageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "操作失败，请稍后重试。";
}

export default function CompensationPage() {
  const [lane, setLane] = useState<Lane>("GRASSROOT");
  const [periodMonth, setPeriodMonth] = useState<string>("");
  const [settlementStatus, setSettlementStatus] = useState("");
  const [q, setQ] = useState("");
  const [versionId, setVersionId] = useState<number | undefined>(undefined);
  const [rateDraft, setRateDraft] = useState("");
  const [actionMessage, setActionMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [lockDialogOpen, setLockDialogOpen] = useState(false);
  const [lockNote, setLockNote] = useState("");
  const [lockConfirmed, setLockConfirmed] = useState(false);
  const [activityDrafts, setActivityDrafts] = useState<Record<string, string>>({});
  const [themeDrafts, setThemeDrafts] = useState<ThemeSubmission[] | null>(null);

  const queryClient = useQueryClient();

  function invalidateForLane(activeLane: Lane, month: string) {
    queryClient.invalidateQueries({ queryKey: ["compensation", "periods", activeLane] });
    queryClient.invalidateQueries({ queryKey: ["compensation", "versions", activeLane, month] });
    const dataKey =
      activeLane === "GRASSROOT" ? "grassroot" : activeLane === "LONG_TERM" ? "long-term" : "commentary";
    queryClient.invalidateQueries({ queryKey: ["compensation", dataKey] });
    queryClient.invalidateQueries({ queryKey: ["dashboard", "filter-options"] });
  }

  const periodsQuery = useQuery({
    queryKey: ["compensation", "periods", lane],
    queryFn: () => compensationApi.periods(lane),
  });

  const periods = periodsQuery.data?.data ?? [];
  const effectiveMonth = periodMonth || periods[0]?.period_month || "";
  const periodEntry = periods.find((p) => p.period_month === effectiveMonth);

  const versionsQuery = useQuery({
    queryKey: ["compensation", "versions", lane, effectiveMonth],
    queryFn: () => compensationApi.versions(effectiveMonth, lane),
    enabled: Boolean(effectiveMonth),
  });
  const versionList = versionsQuery.data?.data ?? [];
  const selectedVersion = versionList.find((v) => v.version_id === versionId);
  const isLockedSelected = selectedVersion?.status === "LOCKED";
  const isDraftSelected = selectedVersion?.status === "DRAFT";

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
  const currentRate = activeQuery.data?.meta.jpy_to_usd_rate;

  // Sync local editable drafts from server data using the React-documented
  // "adjust state during render" pattern (not an effect) so this counts as
  // deriving state from props/query results, not a synchronized side effect.
  const rateSyncKey = `${effectiveMonth}:${currentRate ?? ""}`;
  const [lastRateSyncKey, setLastRateSyncKey] = useState(rateSyncKey);
  if (rateSyncKey !== lastRateSyncKey) {
    setLastRateSyncKey(rateSyncKey);
    setRateDraft(currentRate != null ? String(currentRate) : "");
  }

  const themeSyncKey = themeSubmissionsQuery.dataUpdatedAt;
  const [lastThemeSyncKey, setLastThemeSyncKey] = useState(themeSyncKey);
  if (themeSyncKey !== lastThemeSyncKey) {
    setLastThemeSyncKey(themeSyncKey);
    setThemeDrafts(themeSubmissionsQuery.data?.data ?? null);
  }

  const writeUiContextKey = `${lane}:${effectiveMonth}:${versionId ?? ""}`;
  const [lastWriteUiContextKey, setLastWriteUiContextKey] = useState(writeUiContextKey);
  if (writeUiContextKey !== lastWriteUiContextKey) {
    setLastWriteUiContextKey(writeUiContextKey);
    setLockDialogOpen(false);
    setLockNote("");
    setLockConfirmed(false);
    setActionMessage(null);
  }

  const saveRateMutation = useMutation({
    mutationFn: () => compensationApi.saveExchangeRate(effectiveMonth, Number(rateDraft)),
    onSuccess: () => {
      setActionMessage({ kind: "success", text: "汇率已保存。" });
      invalidateForLane(lane, effectiveMonth);
    },
    onError: (err) => setActionMessage({ kind: "error", text: errorMessageOf(err) }),
  });

  const trafficBoostMutation = useMutation({
    mutationFn: (enabled: boolean) => dashboardApi.saveTrafficBoost(effectiveMonth, enabled),
    onSuccess: () => {
      setActionMessage({ kind: "success", text: "流量加成开关已保存。" });
      invalidateForLane(lane, effectiveMonth);
    },
    onError: (err) => setActionMessage({ kind: "error", text: errorMessageOf(err) }),
  });

  const activityCountsMutation = useMutation({
    mutationFn: () => {
      const counts: Record<string, number> = {};
      for (const [key, value] of Object.entries(activityDrafts)) {
        if (value.trim() !== "") counts[key] = Number(value);
      }
      return compensationApi.saveLongTermActivityCounts(effectiveMonth, counts);
    },
    onSuccess: () => {
      setActionMessage({ kind: "success", text: "活动数已保存。" });
      invalidateForLane(lane, effectiveMonth);
    },
    onError: (err) => setActionMessage({ kind: "error", text: errorMessageOf(err) }),
  });

  const themeSubmissionsMutation = useMutation({
    mutationFn: () =>
      compensationApi.saveCommentaryThemeSubmissions(
        effectiveMonth,
        (themeDrafts ?? []).map((row) => ({
          creator_id: row.creator_id,
          theme_code: row.theme_code,
          content_format: row.content_format,
          urls: row.urls,
          submitted_date: row.submitted_date,
          review_status: row.review_status,
          note: row.note,
        })),
        themeSubmissionsQuery.data?.meta.revision ?? "rev_0"
      ),
    onSuccess: () => {
      setActionMessage({ kind: "success", text: "指定主题申报已保存。" });
      queryClient.invalidateQueries({ queryKey: ["compensation", "theme-submissions", effectiveMonth] });
      invalidateForLane(lane, effectiveMonth);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setActionMessage({ kind: "error", text: `${err.message}（该月申报列表已被其他会话更新，请刷新后重试）` });
        queryClient.invalidateQueries({ queryKey: ["compensation", "theme-submissions", effectiveMonth] });
      } else {
        setActionMessage({ kind: "error", text: errorMessageOf(err) });
      }
    },
  });

  const createDraftMutation = useMutation({
    mutationFn: () => {
      const details = (activeQuery.data?.data ?? []) as unknown as Record<string, unknown>[];
      return compensationApi.createDraft(
        LANE_PATH[lane],
        effectiveMonth,
        {
          jpy_to_usd_rate: currentRate,
          details,
          summary: summary ?? {},
          note: null,
        },
        { idempotencyKey: newIdempotencyKey() }
      );
    },
    onSuccess: () => {
      setActionMessage({ kind: "success", text: "已创建新的结算草稿。" });
      invalidateForLane(lane, effectiveMonth);
    },
    onError: (err) => setActionMessage({ kind: "error", text: errorMessageOf(err) }),
  });

  const updateDraftMutation = useMutation({
    mutationFn: () => {
      const details = (activeQuery.data?.data ?? []) as unknown as Record<string, unknown>[];
      return compensationApi.updateDraft(LANE_PATH[lane], versionId as number, {
        jpy_to_usd_rate: currentRate,
        details,
        summary: summary ?? {},
        note: selectedVersion?.note ?? null,
      });
    },
    onSuccess: () => {
      setActionMessage({ kind: "success", text: "草稿已更新。" });
      invalidateForLane(lane, effectiveMonth);
    },
    onError: (err) => setActionMessage({ kind: "error", text: errorMessageOf(err) }),
  });

  const lockDraftMutation = useMutation({
    mutationFn: () => compensationApi.lockDraft(LANE_PATH[lane], versionId as number, lockNote.trim()),
    onSuccess: () => {
      setActionMessage({ kind: "success", text: "该版本已锁定，成为不可编辑的历史定稿。" });
      setLockDialogOpen(false);
      setLockNote("");
      setLockConfirmed(false);
      invalidateForLane(lane, effectiveMonth);
    },
    onError: (err) => setActionMessage({ kind: "error", text: errorMessageOf(err) }),
  });

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

        <div style={panelStyle}>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12.5 }}>
              JPY→USD 汇率
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  aria-label="JPY→USD 汇率"
                  value={rateDraft}
                  onChange={(e) => setRateDraft(e.target.value)}
                  style={{ ...selectStyle, width: 110 }}
                  disabled={isLockedSelected}
                />
                <button
                  type="button"
                  style={primaryBtn}
                  disabled={!rateDraft || saveRateMutation.isPending || isLockedSelected}
                  onClick={() => saveRateMutation.mutate()}
                >
                  保存汇率
                </button>
              </div>
            </label>

            {periodEntry?.traffic_boost_applicable && (
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
                <input
                  type="checkbox"
                  checked={Boolean(periodEntry?.traffic_boost_enabled)}
                  disabled={trafficBoostMutation.isPending || lane === "COMMENTARY"}
                  onChange={(e) => trafficBoostMutation.mutate(e.target.checked)}
                />
                启用流量加成（7 月专项）
              </label>
            )}

            <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
              {!versionId && !isLockedSelected && (
                <button
                  type="button"
                  style={primaryBtn}
                  disabled={createDraftMutation.isPending || (activeQuery.data?.data.length ?? 0) === 0}
                  onClick={() => createDraftMutation.mutate()}
                >
                  基于当前预览创建结算草稿
                </button>
              )}
              {isDraftSelected && (
                <>
                  <button
                    type="button"
                    style={primaryBtn}
                    disabled={updateDraftMutation.isPending}
                    onClick={() => updateDraftMutation.mutate()}
                  >
                    更新该草稿
                  </button>
                  <button
                    type="button"
                    style={warningBtn}
                    onClick={() => setLockDialogOpen(true)}
                  >
                    锁定该版本
                  </button>
                </>
              )}
            </div>
          </div>

          {actionMessage && (
            <div
              role={actionMessage.kind === "error" ? "alert" : "status"}
              style={actionMessage.kind === "error" ? alertStyle : successAlertStyle}
            >
              {actionMessage.text}
            </div>
          )}
        </div>

        {isLockedSelected && selectedVersion && (
          <div style={{ ...panelStyle, borderLeft: "4px solid var(--color-text-muted)" }}>
            <strong style={{ fontSize: 13 }}>已锁定的历史版本（只读，不可编辑）</strong>
            <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginTop: 6 }}>
              v{selectedVersion.version_no ?? "?"} · 锁定时间：{selectedVersion.locked_at ?? "—"} · 锁定备注：
              {selectedVersion.note ?? "—"}
            </div>
          </div>
        )}

        <div style={panelStyle}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>历史锁定版本</div>
          <StateShell
            isLoading={versionsQuery.isLoading}
            isError={versionsQuery.isError}
            isEmpty={versionList.filter((v) => v.status === "LOCKED").length === 0}
          >
            <table style={{ width: "100%", fontSize: 12.5 }}>
              <thead>
                <tr>
                  <th style={thCell}>版本</th>
                  <th style={thCell}>状态</th>
                  <th style={thCell}>锁定时间</th>
                  <th style={thCell}>操作</th>
                </tr>
              </thead>
              <tbody>
                {versionList
                  .filter((v) => v.status === "LOCKED")
                  .map((v) => (
                    <tr key={v.version_id}>
                      <td style={tdCell}>v{v.version_no ?? "?"}</td>
                      <td style={tdCell}>
                        <ModeBadge mode="frozen" />
                      </td>
                      <td style={tdCell}>{v.locked_at ?? "—"}</td>
                      <td style={tdCell}>
                        <button type="button" style={linkBtn} onClick={() => setVersionId(v.version_id)}>
                          查看
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </StateShell>
        </div>

        {lockDialogOpen && (
          <div style={modalOverlay}>
            <div style={{ ...modalBox, borderTop: "4px solid var(--color-danger)" }}>
              <h3 style={{ margin: 0 }}>锁定结算版本</h3>
              <p style={{ color: "var(--color-text-muted)", fontSize: 12.5 }}>
                锁定后该版本将成为不可编辑的历史定稿，无法再修改或撤销锁定，请谨慎操作。
              </p>
              <label style={{ display: "block", marginTop: 8, fontSize: 12.5 }}>
                锁定备注（必填，1-500 字符）
                <input
                  style={{ ...selectStyle, width: "100%", marginTop: 4 }}
                  value={lockNote}
                  onChange={(e) => setLockNote(e.target.value)}
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, fontSize: 12.5 }}>
                <input type="checkbox" checked={lockConfirmed} onChange={(e) => setLockConfirmed(e.target.checked)} />
                我确认要锁定该版本，锁定后不可编辑
              </label>
              <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
                <button type="button" style={linkBtn} onClick={() => setLockDialogOpen(false)}>
                  取消
                </button>
                <button
                  type="button"
                  style={dangerBtn}
                  disabled={
                    !lockConfirmed ||
                    !lockNote.trim() ||
                    lockNote.trim().length > 500 ||
                    lockDraftMutation.isPending
                  }
                  onClick={() => lockDraftMutation.mutate()}
                >
                  确认锁定
                </button>
              </div>
            </div>
          </div>
        )}

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

        {lane === "LONG_TERM" && !isLockedSelected && (
          <div style={panelStyle}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>每月活动数录入</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {(longTermQuery.data?.data ?? []).map((row) => (
                <label key={row.creator_key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
                  <span style={{ width: 140 }}>{row.creator_name}</span>
                  <input
                    aria-label={`活动数-${row.creator_name}`}
                    style={{ ...selectStyle, width: 80 }}
                    value={activityDrafts[row.creator_key] ?? (row.monthly_activity_count != null ? String(row.monthly_activity_count) : "")}
                    onChange={(e) =>
                      setActivityDrafts((prev) => ({ ...prev, [row.creator_key]: e.target.value }))
                    }
                  />
                </label>
              ))}
            </div>
            <button
              type="button"
              style={{ ...primaryBtn, marginTop: 8 }}
              disabled={activityCountsMutation.isPending}
              onClick={() => activityCountsMutation.mutate()}
            >
              保存活动数
            </button>
          </div>
        )}

        {lane === "COMMENTARY" && (
          <div style={panelStyle}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>指定主题申报</div>
            <StateShell
              isLoading={themeSubmissionsQuery.isLoading}
              isError={themeSubmissionsQuery.isError}
              isEmpty={(themeDrafts ?? []).length === 0}
            >
              <table style={{ width: "100%", fontSize: 12.5 }}>
                <thead>
                  <tr>
                    <th style={thCell}>达人ID</th>
                    <th style={thCell}>主题</th>
                    <th style={thCell}>格式</th>
                    <th style={thCell}>审核状态</th>
                    <th style={thCell}>计费排除</th>
                  </tr>
                </thead>
                <tbody>
                  {(themeDrafts ?? []).map((row, idx) => (
                    <tr key={row.id}>
                      <td style={tdCell}>{row.creator_id}</td>
                      <td style={tdCell}>{row.theme_name}</td>
                      <td style={tdCell}>{row.content_format}</td>
                      <td style={tdCell}>
                        <select
                          aria-label={`审核状态-${row.id}`}
                          value={row.review_status}
                          onChange={(e) =>
                            setThemeDrafts((prev) =>
                              (prev ?? []).map((item, i) =>
                                i === idx ? { ...item, review_status: e.target.value as ThemeSubmission["review_status"] } : item
                              )
                            )
                          }
                          style={selectStyle}
                        >
                          <option value="PENDING">PENDING</option>
                          <option value="APPROVED">APPROVED</option>
                          <option value="REJECTED">REJECTED</option>
                        </select>
                      </td>
                      <td style={tdCell}>
                        {row.billing_excluded ? (
                          <span style={{ color: "var(--color-warning)" }}>是（{row.billing_excluded_url_count} 条）</span>
                        ) : (
                          "否"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </StateShell>
            <button
              type="button"
              style={{ ...primaryBtn, marginTop: 8 }}
              disabled={themeSubmissionsMutation.isPending || !themeDrafts}
              onClick={() => themeSubmissionsMutation.mutate()}
            >
              保存申报审核状态
            </button>
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

const primaryBtn: React.CSSProperties = {
  background: "var(--color-primary)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--radius)",
  padding: "6px 12px",
  fontSize: 12.5,
  cursor: "pointer",
};

const warningBtn: React.CSSProperties = {
  ...primaryBtn,
  background: "var(--color-warning)",
  color: "#1a1200",
};

const dangerBtn: React.CSSProperties = {
  ...primaryBtn,
  background: "var(--color-danger)",
};

const linkBtn: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--color-primary-dark)",
  fontSize: 12.5,
  padding: 0,
  cursor: "pointer",
};

const alertStyle: React.CSSProperties = {
  background: "var(--color-danger-bg)",
  color: "var(--color-danger)",
  border: "1px solid var(--color-danger)",
  borderRadius: "var(--radius)",
  padding: "8px 12px",
  fontSize: 13,
  marginTop: 8,
};

const successAlertStyle: React.CSSProperties = {
  background: "var(--color-primary-bg)",
  color: "var(--color-primary-dark)",
  border: "1px solid var(--color-primary)",
  borderRadius: "var(--radius)",
  padding: "8px 12px",
  fontSize: 13,
  marginTop: 8,
};

const modalOverlay: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.35)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 50,
};

const modalBox: React.CSSProperties = {
  background: "var(--color-surface)",
  borderRadius: "var(--radius)",
  padding: 20,
  width: 420,
  maxWidth: "90vw",
  boxShadow: "0 8px 30px rgba(0,0,0,0.2)",
};

const thCell: React.CSSProperties = {
  textAlign: "left",
  padding: "6px 8px",
  borderBottom: "2px solid var(--color-border)",
  color: "var(--color-text-muted)",
};

const tdCell: React.CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid var(--color-border)",
};
