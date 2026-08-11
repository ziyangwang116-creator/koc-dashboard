"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { StateShell } from "@/components/DataStates";
import { importsApi, dashboardApi } from "@/lib/endpoints";
import type { ImportBatch, ImportPreview, CrossIndustryExclusion } from "@/lib/types";
import { ApiError } from "@/lib/api-client";

/**
 * Invalidate every query key the API contract's affected-scope sections list
 * for import confirm/rollback writes: creators, dashboard summary/posts/
 * comparison/rankings, compensation previews, period/month lists,
 * filter-options, and the import-batch history itself.
 */
function invalidateAffectedQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["creators"] });
  queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  queryClient.invalidateQueries({ queryKey: ["compensation"] });
  queryClient.invalidateQueries({ queryKey: ["cross-industry"] });
}

function errorMessageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "操作失败，请稍后重试。";
}

function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `key-${Date.now()}-${Math.random()}`;
}

export default function ImportsPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [confirmChecked, setConfirmChecked] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState<ImportBatch | null>(null);
  const [rollbackReason, setRollbackReason] = useState("");
  const [rollbackChecked, setRollbackChecked] = useState(false);
  const [rollbackError, setRollbackError] = useState<string | null>(null);
  const [pastedUrls, setPastedUrls] = useState("");
  const [crossIndustryError, setCrossIndustryError] = useState<string | null>(null);

  const batchesQuery = useQuery({
    queryKey: ["dashboard", "import-batches"],
    queryFn: () => dashboardApi.importBatches(),
  });
  const batches = batchesQuery.data?.data ?? [];

  const exclusionsQuery = useQuery({
    queryKey: ["cross-industry", "exclusions"],
    queryFn: () => importsApi.crossIndustryList(),
  });
  const exclusions = exclusionsQuery.data?.data ?? [];

  const previewMutation = useMutation({
    mutationFn: (files: File[]) => importsApi.preview(files),
    onSuccess: (res) => {
      setPreviewError(null);
      setPreview(res.data);
    },
    onError: (err) => {
      setPreviewError(errorMessageOf(err));
      setPreview(null);
    },
  });

  const confirmMutation = useMutation({
    mutationFn: () =>
      importsApi.confirm(
        preview!.preview_token,
        { mode: "replace_months" },
        { idempotencyKey: newIdempotencyKey() }
      ),
    onSuccess: () => {
      setConfirmError(null);
      setConfirmDialogOpen(false);
      setConfirmChecked(false);
      setPreview(null);
      setSelectedFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      invalidateAffectedQueries(queryClient);
    },
    onError: (err) => setConfirmError(errorMessageOf(err)),
  });

  const rollbackMutation = useMutation({
    mutationFn: () =>
      importsApi.rollback(rollbackTarget!.batch_id, rollbackReason, {
        idempotencyKey: newIdempotencyKey(),
      }),
    onSuccess: () => {
      setRollbackError(null);
      setRollbackTarget(null);
      setRollbackReason("");
      setRollbackChecked(false);
      invalidateAffectedQueries(queryClient);
    },
    onError: (err) => setRollbackError(errorMessageOf(err)),
  });

  const markMutation = useMutation({
    mutationFn: (urls: string[]) => importsApi.crossIndustryMark(urls, "异业活动链接"),
    onSuccess: () => {
      setCrossIndustryError(null);
      setPastedUrls("");
      queryClient.invalidateQueries({ queryKey: ["cross-industry"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err) => setCrossIndustryError(errorMessageOf(err)),
  });

  const unmarkMutation = useMutation({
    mutationFn: (id: number) => importsApi.crossIndustryUnmark(id),
    onSuccess: () => {
      setCrossIndustryError(null);
      queryClient.invalidateQueries({ queryKey: ["cross-industry"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err) => setCrossIndustryError(errorMessageOf(err)),
  });

  const hasUnmatched = (preview?.unmatched_creators.count ?? 0) > 0;

  // A batch may only be rolled back if it is the most recent REPLACE_MONTHS
  // batch covering its month(s) — derived client-side from the batch list,
  // which is already ordered most-recent-first by the read endpoint.
  function isMostRecentForMonths(batch: ImportBatch): boolean {
    if (batch.mode !== "REPLACE_MONTHS") return false;
    return !batches.some(
      (other) =>
        other.batch_id !== batch.batch_id &&
        other.mode === "REPLACE_MONTHS" &&
        other.batch_id > batch.batch_id &&
        other.period_months.some((m) => batch.period_months.includes(m))
    );
  }

  const diffColumns: Column<Record<string, unknown>>[] = [
    { key: "koc_name", header: "达人", width: 120, render: (r) => String(r.koc_name ?? "—") },
    { key: "platform", header: "平台", width: 90, render: (r) => String(r.platform ?? "—") },
    { key: "publish_date", header: "发布日期", width: 110, render: (r) => String(r.publish_date ?? "—") },
    { key: "title", header: "标题", width: 200, render: (r) => String(r.title ?? "—") },
    { key: "url", header: "链接", width: 220, render: (r) => String(r.url ?? "—") },
  ];

  const unmatchedColumns: Column<Record<string, unknown>>[] = [
    { key: "raw_uid", header: "UID", width: 120, render: (r) => String(r.raw_uid ?? "—") },
    { key: "reason", header: "原因", width: 220, render: (r) => String(r.reason ?? "—") },
    { key: "source_file", header: "来源文件", width: 160, render: (r) => String(r.source_file ?? "—") },
  ];

  const dateAnomalyColumns: Column<Record<string, unknown>>[] = [
    { key: "raw_uid", header: "UID", width: 120, render: (r) => String(r.raw_uid ?? "—") },
    { key: "title", header: "标题", width: 200, render: (r) => String(r.title ?? "—") },
    { key: "reason", header: "原因", width: 200, render: (r) => String(r.reason ?? "—") },
    { key: "source_file", header: "来源文件", width: 160, render: (r) => String(r.source_file ?? "—") },
  ];

  return (
    <AppShell>
      <section style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div style={panelStyle}>
          <h3 style={{ marginTop: 0 }}>数据导入</h3>
          <p style={{ color: "var(--color-text-muted)", fontSize: 12.5 }}>
            上传 Rapid Query 导出的 Excel 文件，系统会先生成预览（新增/更新/删除/未匹配达人/日期异常），
            确认后才会按月完整替换并写入数据库；替换前会自动保存快照，可在下方「导入历史」中回滚。
          </p>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls"
              multiple
              onChange={(e) => setSelectedFiles(Array.from(e.target.files ?? []))}
            />
            <button
              type="button"
              style={primaryBtn}
              disabled={selectedFiles.length === 0 || previewMutation.isPending}
              onClick={() => previewMutation.mutate(selectedFiles)}
            >
              {previewMutation.isPending ? "解析中…" : "生成预览"}
            </button>
          </div>

          {previewError && (
            <div style={alertStyle} role="alert">
              {previewError}
            </div>
          )}

          {preview && (
            <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 16 }}>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 13 }}>
                <span>输入行数：{preview.input_row_count}</span>
                <span>匹配行数：{preview.matched_row_count}</span>
                <span>覆盖月份：{preview.period_months.join("、") || "—"}</span>
                <span>命中异业排除：{preview.cross_industry_flagged_count}</span>
              </div>

              <DiffSection title="新增" bucket={preview.additions} columns={diffColumns} />
              <DiffSection title="更新" bucket={preview.updates} columns={diffColumns} />
              <DiffSection title="删除" bucket={preview.removals} columns={diffColumns} />
              <DiffSection
                title="未匹配达人"
                bucket={preview.unmatched_creators}
                columns={unmatchedColumns}
                tone={hasUnmatched ? "danger" : undefined}
              />
              <DiffSection title="日期异常" bucket={preview.date_anomalies} columns={dateAnomalyColumns} tone="warning" />

              {hasUnmatched && (
                <div style={alertStyle} role="alert">
                  存在 {preview.unmatched_creators.count}{" "}
                  条未匹配达人库的投稿，无法确认导入。请先在「达人库」中补录对应 UID，或修正 Excel 数据后重新上传预览。
                </div>
              )}

              {confirmError && (
                <div style={alertStyle} role="alert">
                  {confirmError}
                </div>
              )}

              <div>
                <button
                  type="button"
                  style={hasUnmatched ? disabledBtn : primaryBtn}
                  disabled={hasUnmatched}
                  title={hasUnmatched ? "存在未匹配达人，确认导入已被阻止" : undefined}
                  onClick={() => setConfirmDialogOpen(true)}
                >
                  确认导入（按月完整替换）
                </button>
              </div>
            </div>
          )}
        </div>

        <div style={panelStyle}>
          <h3 style={{ marginTop: 0 }}>导入历史</h3>
          <StateShell
            isLoading={batchesQuery.isLoading}
            isError={batchesQuery.isError}
            isUnauthorized={batchesQuery.error instanceof ApiError && batchesQuery.error.status === 401}
            errorMessage={batchesQuery.error instanceof ApiError ? batchesQuery.error.message : undefined}
            isEmpty={batches.length === 0}
          >
            <table style={{ width: "100%", fontSize: 12.5 }}>
              <thead>
                <tr>
                  <th style={thCell}>批次</th>
                  <th style={thCell}>模式</th>
                  <th style={thCell}>覆盖月份</th>
                  <th style={thCell}>输入/保存/删除</th>
                  <th style={thCell}>创建时间</th>
                  <th style={thCell}>操作</th>
                </tr>
              </thead>
              <tbody>
                {batches.map((batch) => {
                  const canRollback = isMostRecentForMonths(batch);
                  return (
                    <tr key={batch.batch_id}>
                      <td style={tdCell}>#{batch.batch_id}</td>
                      <td style={tdCell}>{batch.mode}</td>
                      <td style={tdCell}>{batch.period_months.join("、") || "—"}</td>
                      <td style={tdCell}>
                        {batch.input_count}/{batch.saved_count}/{batch.removed_count}
                      </td>
                      <td style={tdCell}>{batch.created_at}</td>
                      <td style={tdCell}>
                        <button
                          type="button"
                          style={canRollback ? dangerBtn : disabledBtn}
                          disabled={!canRollback}
                          title={
                            canRollback
                              ? undefined
                              : "只能回滚该月份最近一次的按月完整替换批次"
                          }
                          onClick={() => setRollbackTarget(batch)}
                        >
                          回滚
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </StateShell>
        </div>

        <div style={panelStyle}>
          <h3 style={{ marginTop: 0 }}>异业排除管理</h3>
          <p style={{ color: "var(--color-text-muted)", fontSize: 12.5 }}>
            标记为异业的投稿链接会在看板与结算统计中被排除，但原始投稿数据不会被删除或修改。
          </p>
          {crossIndustryError && (
            <div style={alertStyle} role="alert">
              {crossIndustryError}
            </div>
          )}
          <textarea
            placeholder="粘贴一个或多个投稿链接，每行一个"
            value={pastedUrls}
            onChange={(e) => setPastedUrls(e.target.value)}
            style={textareaStyle}
            rows={4}
          />
          <button
            type="button"
            style={primaryBtn}
            disabled={!pastedUrls.trim() || markMutation.isPending}
            onClick={() => {
              const urls = pastedUrls
                .split(/\r?\n/)
                .map((u) => u.trim())
                .filter(Boolean);
              if (urls.length > 0) markMutation.mutate(urls);
            }}
          >
            标记为异业
          </button>

          <div style={{ marginTop: 12 }}>
            <StateShell
              isLoading={exclusionsQuery.isLoading}
              isError={exclusionsQuery.isError}
              errorMessage={exclusionsQuery.error instanceof ApiError ? exclusionsQuery.error.message : undefined}
              isEmpty={exclusions.filter((e) => e.active).length === 0}
            >
              <table style={{ width: "100%", fontSize: 12.5 }}>
                <thead>
                  <tr>
                    <th style={thCell}>平台</th>
                    <th style={thCell}>链接</th>
                    <th style={thCell}>原因</th>
                    <th style={thCell}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {exclusions
                    .filter((e) => e.active)
                    .map((exclusion: CrossIndustryExclusion) => (
                      <tr key={exclusion.id}>
                        <td style={tdCell}>{exclusion.platform}</td>
                        <td style={tdCell}>{exclusion.original_url}</td>
                        <td style={tdCell}>{exclusion.reason ?? "—"}</td>
                        <td style={tdCell}>
                          <button
                            type="button"
                            style={linkBtn}
                            onClick={() => unmarkMutation.mutate(exclusion.id)}
                          >
                            取消标记
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </StateShell>
          </div>
        </div>
      </section>

      {confirmDialogOpen && preview && (
        <div style={modalOverlay}>
          <div style={{ ...modalBox, borderTop: "4px solid var(--color-primary)" }}>
            <h3 style={{ margin: 0 }}>确认导入</h3>
            <p style={{ color: "var(--color-text-muted)", fontSize: 12.5 }}>
              即将按月完整替换覆盖月份 {preview.period_months.join("、") || "—"} 的全部投稿数据。
              替换前会自动保存快照，可在导入历史中回滚。该操作会写入数据库，请确认无误后再继续。
            </p>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
              <input
                type="checkbox"
                checked={confirmChecked}
                onChange={(e) => setConfirmChecked(e.target.checked)}
              />
              我确认要执行本次按月完整替换导入
            </label>
            <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
              <button
                type="button"
                style={linkBtn}
                onClick={() => {
                  setConfirmDialogOpen(false);
                  setConfirmChecked(false);
                }}
              >
                取消
              </button>
              <button
                type="button"
                style={primaryBtn}
                disabled={!confirmChecked || confirmMutation.isPending}
                onClick={() => confirmMutation.mutate()}
              >
                确认执行
              </button>
            </div>
          </div>
        </div>
      )}

      {rollbackTarget && (
        <div style={modalOverlay}>
          <div style={{ ...modalBox, borderTop: "4px solid var(--color-danger)" }}>
            <h3 style={{ margin: 0 }}>回滚导入批次 #{rollbackTarget.batch_id}</h3>
            <p style={{ color: "var(--color-text-muted)", fontSize: 12.5 }}>
              这将把覆盖月份 {rollbackTarget.period_months.join("、") || "—"} 的投稿数据恢复到本次替换之前的状态。
            </p>
            {rollbackError && (
              <div style={alertStyle} role="alert">
                {rollbackError}
              </div>
            )}
            <label style={{ display: "block", marginTop: 8, fontSize: 12.5 }}>
              回滚原因（必填）
              <input
                style={inputStyle}
                value={rollbackReason}
                onChange={(e) => setRollbackReason(e.target.value)}
              />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, fontSize: 12.5 }}>
              <input
                type="checkbox"
                checked={rollbackChecked}
                onChange={(e) => setRollbackChecked(e.target.checked)}
              />
              我确认要回滚该批次
            </label>
            <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
              <button
                type="button"
                style={linkBtn}
                onClick={() => {
                  setRollbackTarget(null);
                  setRollbackReason("");
                  setRollbackChecked(false);
                  setRollbackError(null);
                }}
              >
                取消
              </button>
              <button
                type="button"
                style={dangerBtn}
                disabled={!rollbackChecked || !rollbackReason.trim() || rollbackMutation.isPending}
                onClick={() => rollbackMutation.mutate()}
              >
                确认回滚
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}

function DiffSection({
  title,
  bucket,
  columns,
  tone,
}: {
  title: string;
  bucket: { count: number; rows: Record<string, unknown>[] };
  columns: Column<Record<string, unknown>>[];
  tone?: "danger" | "warning";
}) {
  const [open, setOpen] = useState(false);
  const badgeStyle =
    tone === "danger" && bucket.count > 0
      ? { ...countBadge, background: "var(--color-danger-bg)", color: "var(--color-danger)" }
      : tone === "warning" && bucket.count > 0
        ? { ...countBadge, background: "var(--color-warning-bg)", color: "var(--color-warning)" }
        : countBadge;
  return (
    <div>
      <button
        type="button"
        style={{ ...linkBtn, display: "flex", alignItems: "center", gap: 8 }}
        onClick={() => setOpen((v) => !v)}
      >
        <strong style={{ color: "var(--color-text)" }}>{title}</strong>
        <span style={badgeStyle}>{bucket.count}</span>
        <span>{open ? "收起" : "展开"}</span>
      </button>
      {open && (
        <div style={{ marginTop: 8 }}>
          <StateShell isLoading={false} isError={false} isEmpty={bucket.rows.length === 0}>
            <DataTable
              columns={columns}
              rows={bucket.rows.map((r, i) => ({ ...r, __row_index: i }))}
              rowKey={(r) => r.__row_index as number}
            />
          </StateShell>
        </div>
      )}
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  padding: 16,
};

const primaryBtn: React.CSSProperties = {
  background: "var(--color-primary)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--radius)",
  padding: "6px 14px",
  fontSize: 12.5,
  cursor: "pointer",
};

const disabledBtn: React.CSSProperties = {
  ...primaryBtn,
  background: "var(--color-border)",
  color: "var(--color-text-muted)",
  cursor: "not-allowed",
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

const inputStyle: React.CSSProperties = {
  padding: "6px 8px",
  borderRadius: "var(--radius)",
  border: "1px solid var(--color-border)",
  fontSize: 13,
  minWidth: 240,
  display: "block",
  marginTop: 4,
};

const textareaStyle: React.CSSProperties = {
  ...inputStyle,
  width: "100%",
  minWidth: 0,
  fontFamily: "inherit",
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

const countBadge: React.CSSProperties = {
  background: "var(--color-primary-bg)",
  color: "var(--color-primary-dark)",
  borderRadius: 999,
  fontSize: 11.5,
  padding: "1px 8px",
};

const thCell: React.CSSProperties = {
  textAlign: "left",
  padding: "6px 8px",
  borderBottom: "2px solid var(--color-border)",
  color: "var(--color-text-muted)",
  position: "sticky",
  top: 0,
  background: "var(--color-surface)",
};

const tdCell: React.CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid var(--color-border)",
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
  width: 460,
  maxWidth: "90vw",
  boxShadow: "0 8px 30px rgba(0,0,0,0.2)",
};
