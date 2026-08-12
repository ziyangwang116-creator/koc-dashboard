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
  ThemeDefinition,
  ThemeCreatorOption,
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
  const [themeEditorOpen, setThemeEditorOpen] = useState(false);

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
    page_size: 100,
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

  const themeDefinitions = (themeSubmissionsQuery.data?.meta.definitions ?? []) as ThemeDefinition[];
  const eligibleThemeCreators = (themeSubmissionsQuery.data?.meta.eligible_creators ?? []) as ThemeCreatorOption[];

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
        if (value.trim() !== "") {
          const parsed = Number(value);
          if (!Number.isInteger(parsed) || parsed < 0) {
            throw new Error("活动数必须是非负整数。");
          }
          counts[key] = parsed;
        }
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

  function addThemeSubmission() {
    const creator = eligibleThemeCreators[0];
    const definition = themeDefinitions[0];
    if (!creator || !definition) return;
    setThemeDrafts((prev) => [
      ...(prev ?? []),
      {
        id: null,
        period_month: effectiveMonth,
        creator_id: creator.id,
        theme_code: definition.theme_code,
        theme_name: definition.theme_name,
        content_format: "LONG",
        urls: [""],
        submitted_date: effectiveMonth ? `${effectiveMonth}-01` : "",
        review_status: "PENDING",
        note: null,
        theme_reward_eligible: false,
        matched_post_urls: [],
        billing_excluded_url_count: 0,
        billing_excluded: false,
      },
    ]);
    setThemeEditorOpen(true);
  }

  function updateThemeRow(index: number, patch: Partial<ThemeSubmission>) {
    setThemeDrafts((prev) => (prev ?? []).map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row));
  }

  function removeThemeSubmission(index: number) {
    setThemeDrafts((prev) => (prev ?? []).filter((_row, rowIndex) => rowIndex !== index));
  }

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
      { key: "creator_key", header: "UID", width: 110, render: (r) => r.creator_key },
      { key: "contract_types", header: "合同类型", width: 120, render: (r) => r.contract_types.join("、") || "—" },
      { key: "followers", header: "粉丝数", width: 90, align: "right", render: (r) => fmtInt(r.followers) },
      { key: "settlement_status", header: "结算状态", width: 100, render: (r) => r.settlement_status },
      { key: "rank", header: "等级", width: 60, render: (r) => r.rank },
      { key: "settlement_subtype", header: "计费类型", width: 110, render: (r) => r.settlement_subtype ?? "—" },
      { key: "contract_billable_views", header: "合同内播放量", width: 120, align: "right", render: (r) => fmtInt(r.contract_billable_views) },
      { key: "billable_views", header: "计费播放量", width: 110, align: "right", render: (r) => fmtInt(r.billable_views) },
      { key: "all_video_views", header: "全部播放量", width: 110, align: "right", render: (r) => fmtInt(r.all_video_views) },
      { key: "billable_post_count", header: "投稿数", width: 70, align: "right", render: (r) => fmtInt(r.billable_post_count) },
      { key: "creator_receivable_usd", header: "博主应收美元", width: 120, align: "right", render: (r) => <strong>{fmtUsd(r.creator_receivable_usd)}</strong> },
      { key: "cpm", header: "CPM", width: 70, align: "right", render: (r) => fmtCpm(r.cpm) },
    ],
    []
  );

  const longTermColumns: Column<LongTermRow>[] = useMemo(
    () => [
      { key: "creator_name", header: "达人", width: 110, render: (r) => r.creator_name },
      { key: "creator_key", header: "UID", width: 110, render: (r) => r.creator_key },
      { key: "contract_types", header: "合同类型", width: 120, render: (r) => r.contract_types.join("、") || "—" },
      { key: "contract_start_date", header: "合同开始", width: 105, render: (r) => r.contract_start_date ?? "—" },
      { key: "contract_end_date", header: "合同截止", width: 105, render: (r) => r.contract_end_date ?? "—" },
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
      { key: "youtube_post_count", header: "YouTube投稿数", width: 115, align: "right", render: (r) => fmtInt(r.youtube_post_count) },
      { key: "activity_threshold", header: "活动门槛", width: 80, align: "right", render: (r) => fmtInt(r.activity_threshold) },
      { key: "rank_reward_jpy", header: "等级金额", width: 100, align: "right", render: (r) => fmtInt(r.rank_reward_jpy) },
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
      { key: "creator_key", header: "UID", width: 110, render: (r) => r.creator_key },
      { key: "contract_types", header: "合同类型", width: 140, render: (r) => r.contract_types.join("、") || "—" },
      { key: "settlement_status", header: "结算状态", width: 100, render: (r) => r.settlement_status },
      { key: "long_views", header: "长视频播放量", width: 115, align: "right", render: (r) => fmtInt(r.long_views) },
      { key: "long_final_rank", header: "长视频等级", width: 90, render: (r) => r.long_final_rank ?? "—" },
      { key: "short_views", header: "短视频播放量", width: 115, align: "right", render: (r) => fmtInt(r.short_views) },
      { key: "short_final_rank", header: "短视频等级", width: 90, render: (r) => r.short_final_rank ?? "—" },
      { key: "combined_bonus_jpy", header: "并用奖金", width: 95, align: "right", render: (r) => fmtInt(r.combined_bonus_jpy) },
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
                  value={activityDrafts[String(row.record_id)] ?? (row.monthly_activity_count != null ? String(row.monthly_activity_count) : "")}
                  onChange={(e) =>
                      setActivityDrafts((prev) => ({ ...prev, [String(row.record_id)]: e.target.value }))
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
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>指定主题申报</div>
              <button type="button" style={primaryBtn} disabled={!themeDefinitions.length || !eligibleThemeCreators.length} onClick={addThemeSubmission}>
                新增申报
              </button>
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 8 }}>
              仅显示解说达人；长视频填写 1 条链接，短视频填写 3 条链接。已通过的链接会从计费播放量中排除。
            </div>
            <StateShell isLoading={themeSubmissionsQuery.isLoading} isError={themeSubmissionsQuery.isError} isEmpty={(themeDrafts ?? []).length === 0}>
              {themeEditorOpen || (themeDrafts ?? []).length > 0 ? (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", fontSize: 12.5, minWidth: 1040 }}>
                    <thead><tr>
                      <th style={thCell}>解说达人</th><th style={thCell}>指定主题</th><th style={thCell}>内容形式</th>
                      <th style={thCell}>视频链接</th><th style={thCell}>提交日期</th><th style={thCell}>审核状态</th>
                      <th style={thCell}>匹配/排除</th><th style={thCell}>操作</th>
                    </tr></thead>
                    <tbody>
                      {(themeDrafts ?? []).map((row, idx) => {
                        const definition = themeDefinitions.find((item) => item.theme_code === row.theme_code);
                        const expectedCount = row.content_format === "LONG" ? 1 : 3;
                        return <tr key={row.id ?? `new-${idx}`}>
                          <td style={tdCell}>
                            <select aria-label={`解说达人-${idx}`} value={String(row.creator_id)} style={selectStyle} onChange={(e) => updateThemeRow(idx, { creator_id: Number(e.target.value) })}>
                              {eligibleThemeCreators.map((creator) => <option key={creator.id} value={creator.id}>{creator.creator_name} · {creator.creator_key}</option>)}
                            </select>
                          </td>
                          <td style={tdCell}>
                            <select aria-label={`指定主题-${idx}`} value={row.theme_code} style={selectStyle} onChange={(e) => { const next = themeDefinitions.find((item) => item.theme_code === e.target.value); updateThemeRow(idx, { theme_code: e.target.value, theme_name: next?.theme_name ?? row.theme_name }); }}>
                              {themeDefinitions.map((item) => <option key={item.theme_code} value={item.theme_code}>{item.theme_name} · {item.theme_code}</option>)}
                            </select>
                          </td>
                          <td style={tdCell}>
                            <select aria-label={`内容形式-${idx}`} value={row.content_format} style={selectStyle} onChange={(e) => updateThemeRow(idx, { content_format: e.target.value as ThemeSubmission["content_format"], urls: e.target.value === "LONG" ? [row.urls[0] ?? ""] : [...row.urls, "", ""].slice(0, 3) })}>
                              <option value="LONG">长视频（1条）</option><option value="SHORT">短视频（3条）</option>
                            </select>
                          </td>
                          <td style={tdCell}>
                            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                              {Array.from({ length: expectedCount }).map((_value, urlIndex) => <input key={urlIndex} aria-label={`视频链接-${idx}-${urlIndex}`} style={{ ...selectStyle, width: 260 }} value={row.urls[urlIndex] ?? ""} onChange={(e) => { const urls = [...row.urls]; urls[urlIndex] = e.target.value; updateThemeRow(idx, { urls }); }} placeholder={`视频链接 ${urlIndex + 1}`} />)}
                            </div>
                          </td>
                          <td style={tdCell}><input type="date" aria-label={`提交日期-${idx}`} style={selectStyle} value={row.submitted_date ?? ""} onChange={(e) => updateThemeRow(idx, { submitted_date: e.target.value })} /></td>
                          <td style={tdCell}><select aria-label={`审核状态-${idx}`} value={row.review_status} style={selectStyle} onChange={(e) => updateThemeRow(idx, { review_status: e.target.value as ThemeSubmission["review_status"] })}><option value="PENDING">待审核</option><option value="APPROVED">已通过</option><option value="REJECTED">不通过</option></select></td>
                          <td style={tdCell}>{row.billing_excluded ? `已匹配 ${row.billing_excluded_url_count} 条` : (definition ? `${definition.reward_jpy.toLocaleString()} 日元` : "—")}</td>
                          <td style={tdCell}><button type="button" style={linkBtn} onClick={() => removeThemeSubmission(idx)}>删除</button></td>
                        </tr>;
                      })}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </StateShell>
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button type="button" style={primaryBtn} disabled={themeSubmissionsMutation.isPending || !themeDrafts} onClick={() => themeSubmissionsMutation.mutate()}>保存指定主题申报</button>
              {!themeEditorOpen && <button type="button" style={linkBtn} onClick={() => setThemeEditorOpen(true)}>编辑申报</button>}
            </div>
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
