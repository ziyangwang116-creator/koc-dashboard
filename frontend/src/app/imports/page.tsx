"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { StateShell } from "@/components/DataStates";
import { importsApi, dashboardApi } from "@/lib/endpoints";
import type {
  ImportBatch,
  ImportPreview,
  CrossIndustryExclusion,
  StandardizationResult,
} from "@/lib/types";
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

type ImportMode = "append_or_update" | "replace_months";

const IMPORT_MODE_COPY: Record<
  ImportMode,
  { label: string; description: string; confirmLabel: string }
> = {
  append_or_update: {
    label: "补充导入",
    description: "保留数据库中已有投稿，仅新增新链接，并更新平台 + URL 相同的投稿。",
    confirmLabel: "我确认要执行本次补充导入",
  },
  replace_months: {
    label: "按月份完整替换",
    description: "删除覆盖月份的原有投稿后写入本次完整文件，并自动保存可回滚快照。",
    confirmLabel: "我确认要执行本次按月份完整替换导入",
  },
};

const SMART_FIELD_LABELS: Record<string, string> = {
  view: "播放量",
  subtype: "视频类型",
  title: "标题",
  userId: "达人 ID",
  url: "视频链接",
  timestamp: "发布日期",
  platform: "平台",
  likes: "点赞数",
  comment: "评论数",
  reposted: "转发数",
  description: "描述",
  collect: "收藏数",
};

const DATE_METHOD_LABELS: Record<string, string> = {
  excel_datetime: "Excel 日期",
  excel_serial: "Excel 日期序列号",
  unix_ms: "毫秒时间戳",
  unix_s: "秒级时间戳",
  yyyymmdd: "YYYYMMDD",
  date_text: "日期文本",
};

export default function ImportsPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [importMode, setImportMode] = useState<ImportMode>("append_or_update");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
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
    mutationFn: ({ files, mapping }: { files: File[]; mapping?: Record<string, string> }) =>
      importsApi.preview(files, mapping),
    onSuccess: (res) => {
      setPreviewError(null);
      setPreview(res.data);
      const firstFile = res.data.smart_import?.files[0];
      if (firstFile) setColumnMapping(firstFile.column_mapping);
    },
    onError: (err) => {
      setPreviewError(errorMessageOf(err));
      setPreview(null);
      setColumnMapping({});
    },
  });

  const confirmMutation = useMutation({
    mutationFn: () =>
      importsApi.confirm(
        preview!.preview_token,
        { mode: importMode },
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
  const hasDateAnomalies = (preview?.date_anomalies.count ?? 0) > 0;
  const hasBlockingIssues = hasUnmatched || hasDateAnomalies;
  const isReplaceMode = importMode === "replace_months";
  const importModeCopy = IMPORT_MODE_COPY[importMode];

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
        <StandardizationPanel />

        <div style={panelStyle}>
          <h3 style={{ marginTop: 0 }}>导入看板数据库</h3>
          <p style={{ color: "var(--color-text-muted)", fontSize: 12.5 }}>
            上传 Rapid Query 导出的 Excel 文件，系统会先生成新增、更新、未匹配达人和日期异常预览，确认后才写入数据库。
          </p>
          <fieldset style={modeFieldset}>
            <legend style={modeLegend}>导入方式</legend>
            <div style={modeSelector}>
              {(Object.keys(IMPORT_MODE_COPY) as ImportMode[]).map((mode) => (
                <label
                  key={mode}
                  style={{
                    ...modeOption,
                    ...(importMode === mode ? modeOptionActive : {}),
                  }}
                >
                  <input
                    type="radio"
                    name="import-mode"
                    value={mode}
                    checked={importMode === mode}
                    onChange={() => {
                      setImportMode(mode);
                      setConfirmChecked(false);
                      setConfirmError(null);
                    }}
                  />
                  <span>{IMPORT_MODE_COPY[mode].label}</span>
                </label>
              ))}
            </div>
            <div style={importMode === "replace_months" ? warningStyle : infoStyle}>
              {importModeCopy.description}
            </div>
          </fieldset>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              ref={fileInputRef}
              aria-label="导入看板数据库文件"
              type="file"
              accept=".xlsx"
              multiple
              onChange={(e) => {
                setSelectedFiles(Array.from(e.target.files ?? []));
                setPreview(null);
                setColumnMapping({});
                setPreviewError(null);
              }}
            />
            <button
              type="button"
              style={primaryBtn}
              disabled={selectedFiles.length === 0 || previewMutation.isPending}
              onClick={() => previewMutation.mutate({ files: selectedFiles })}
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
                <span>数据月份：{preview.period_months.join("、") || "—"}</span>
                <span>命中异业排除：{preview.cross_industry_flagged_count}</span>
              </div>

              {preview.smart_import?.enabled && preview.smart_import.files.length > 0 && (
                <div style={smartImportPanelStyle}>
                  <div>
                    <strong>智能识别结果</strong>
                    <div style={smartImportHintStyle}>
                      系统按表格内容识别字段与日期，不使用文件名判断月份。
                    </div>
                  </div>
                  {preview.smart_import.files.map((diagnostic) => (
                    <div key={diagnostic.source_file} style={smartImportFileStyle}>
                      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
                        <strong>{diagnostic.source_file}</strong>
                        <span>
                          日期范围：{diagnostic.date_min ?? "—"} 至 {diagnostic.date_max ?? "—"}
                        </span>
                        {Object.entries(diagnostic.date_method_counts).map(([method, count]) => (
                          <span key={method} style={diagnosticTagStyle}>
                            {DATE_METHOD_LABELS[method] ?? method}：{count}
                          </span>
                        ))}
                      </div>
                      <div style={mappingGridStyle}>
                        {Object.entries(SMART_FIELD_LABELS).map(([canonical, label]) => (
                          <label key={canonical} style={mappingFieldStyle}>
                            <span>{label}</span>
                            <select
                              aria-label={`字段映射 ${label}`}
                              value={columnMapping[canonical] ?? ""}
                              disabled={selectedFiles.length !== 1}
                              onChange={(event) =>
                                setColumnMapping((current) => ({
                                  ...current,
                                  [canonical]: event.target.value,
                                }))
                              }
                              style={mappingSelectStyle}
                            >
                              <option value="">未映射</option>
                              {diagnostic.source_columns.map((source) => (
                                <option key={source} value={source}>
                                  {source}
                                </option>
                              ))}
                            </select>
                          </label>
                        ))}
                      </div>
                      {selectedFiles.length === 1 ? (
                        <button
                          type="button"
                          style={secondaryBtn}
                          disabled={previewMutation.isPending}
                          onClick={() =>
                            previewMutation.mutate({
                              files: selectedFiles,
                              mapping: Object.fromEntries(
                                Object.entries(columnMapping).filter(([, source]) => source)
                              ),
                            })
                          }
                        >
                          应用字段映射并重新预览
                        </button>
                      ) : (
                        <div style={smartImportHintStyle}>
                          多文件导入会分别自动识别字段，手动映射仅支持单文件。
                        </div>
                      )}
                      {diagnostic.warnings.map((warning) => (
                        <div key={warning} style={warningTextStyle}>{warning}</div>
                      ))}
                    </div>
                  ))}
                </div>
              )}

              <DiffSection title="新增" bucket={preview.additions} columns={diffColumns} />
              <DiffSection title="更新" bucket={preview.updates} columns={diffColumns} />
              {isReplaceMode ? (
                <DiffSection title="完整替换时将删除" bucket={preview.removals} columns={diffColumns} tone="warning" />
              ) : (
                <div style={infoStyle}>补充导入不会删除该月已有投稿，本次预览中的缺失记录将继续保留。</div>
              )}
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

              {hasDateAnomalies && (
                <div style={alertStyle} role="alert">
                  存在 {preview.date_anomalies.count}{" "}
                  条无法识别发布日期的投稿，无法确认导入。请在「智能识别结果」中修正日期字段映射，或修改 Excel 日期后重新预览。
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
                  style={hasBlockingIssues ? disabledBtn : primaryBtn}
                  disabled={hasBlockingIssues}
                  title={
                    hasUnmatched
                      ? "存在未匹配达人，确认导入已被阻止"
                      : hasDateAnomalies
                        ? "存在无法识别的发布日期，确认导入已被阻止"
                        : undefined
                  }
                  onClick={() => setConfirmDialogOpen(true)}
                >
                  确认导入（{importModeCopy.label}）
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
                      <td style={tdCell}>
                        {batch.mode === "REPLACE_MONTHS" ? "按月份完整替换" : "补充导入"}
                      </td>
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
              {isReplaceMode ? (
                <>
                  即将完整替换 {preview.period_months.join("、") || "—"} 的全部投稿数据，并删除未出现在本次文件中的旧投稿。
                  替换前会自动保存快照，可在导入历史中回滚。
                </>
              ) : (
                <>
                  即将补充 {preview.period_months.join("、") || "—"} 的投稿数据。现有投稿不会删除；平台和 URL 相同的记录会更新，其他记录会新增。
                </>
              )}
            </p>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
              <input
                type="checkbox"
                checked={confirmChecked}
                onChange={(e) => setConfirmChecked(e.target.checked)}
              />
              {importModeCopy.confirmLabel}
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

function StandardizationPanel() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [processingTimezone, setProcessingTimezone] = useState("Asia/Shanghai");
  const [deduplicateUrls, setDeduplicateUrls] = useState(false);
  const [result, setResult] = useState<StandardizationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => importsApi.standardize(files, processingTimezone, deduplicateUrls),
    onSuccess: (response) => {
      setError(null);
      setResult(response.data);
    },
    onError: (err) => {
      setError(errorMessageOf(err));
      setResult(null);
    },
  });

  const fileReportColumns: Column<Record<string, unknown>>[] = [
    { key: "source_file", header: "文件名", width: 180, render: (r) => String(r.source_file ?? "—") },
    { key: "original_rows", header: "原始行数", align: "right", render: (r) => String(r.original_rows ?? 0) },
    { key: "processed_rows", header: "处理行数", align: "right", render: (r) => String(r.processed_rows ?? 0) },
    { key: "unmatched_uid", header: "未匹配 UID", align: "right", render: (r) => String(r.unmatched_uid ?? 0) },
    { key: "duplicate_url", header: "重复记录", align: "right", render: (r) => String(r.duplicate_url ?? 0) },
    { key: "status", header: "状态", width: 80, render: (r) => String(r.status ?? "—") },
    { key: "error_message", header: "错误信息", width: 260, render: (r) => String(r.error_message ?? "—") },
  ];
  const unmatchedColumns: Column<Record<string, unknown>>[] = [
    { key: "userId", header: "UID", width: 150, render: (r) => String(r.userId ?? "—") },
    { key: "出现次数", header: "出现次数", align: "right", render: (r) => String(r["出现次数"] ?? 0) },
    { key: "来源文件", header: "来源文件", width: 240, render: (r) => String(r["来源文件"] ?? "—") },
  ];
  const resultColumns: Column<Record<string, unknown>>[] = [
    { key: "koc_name", header: "达人", width: 140, render: (r) => String(r.koc_name ?? "—") },
    { key: "platform", header: "平台/类型", width: 110, render: (r) => String(r.platform ?? "—") },
    { key: "publish_date", header: "发布日期", width: 110, render: (r) => String(r.publish_date ?? "—") },
    { key: "title", header: "标题", width: 240, render: (r) => String(r.title ?? "—") },
    { key: "url", header: "链接", width: 300, render: (r) => String(r.url ?? "—") },
    { key: "views", header: "播放量", align: "right", render: (r) => String(r.views ?? "—") },
    { key: "likes", header: "点赞", align: "right", render: (r) => String(r.likes ?? "—") },
    { key: "comment", header: "评论", align: "right", render: (r) => String(r.comment ?? "—") },
    { key: "reposted", header: "转发", align: "right", render: (r) => String(r.reposted ?? "—") },
  ];
  const exceptionColumns: Column<Record<string, unknown>>[] = [
    { key: "issue_type", header: "异常类型", width: 150, render: (r) => String(r.issue_type ?? "—") },
    { key: "source_file", header: "来源文件", width: 180, render: (r) => String(r.source_file ?? "—") },
    { key: "userId", header: "UID", width: 140, render: (r) => String(r.userId ?? "—") },
    { key: "koc_name", header: "达人", width: 130, render: (r) => String(r.koc_name ?? "—") },
    { key: "title", header: "标题", width: 220, render: (r) => String(r.title ?? "—") },
    { key: "url", header: "链接", width: 260, render: (r) => String(r.url ?? "—") },
    { key: "detail", header: "说明", width: 260, render: (r) => String(r.detail ?? "—") },
  ];

  const metrics = result
    ? [
        ["上传文件", result.overall.uploaded_files],
        ["成功文件", result.overall.successful_files],
        ["失败文件", result.overall.failed_files],
        ["原始总行数", result.overall.original_rows],
        ["整理后行数", result.overall.merged_rows],
        ["不同达人", result.overall.koc_count],
        ["未匹配 UID", result.overall.unmatched_uid_count],
        ["重复记录涉及行数", result.overall.duplicate_url_count],
        ["实际移除重复 URL", result.overall.removed_duplicate_count],
        ["缺失 URL", result.overall.missing_url_count],
        ["缺失标题", result.overall.missing_title_count],
        ["无效日期", result.overall.invalid_timestamp_count],
        ["最早日期", result.overall.earliest_date ?? "—"],
        ["最晚日期", result.overall.latest_date ?? "—"],
      ]
    : [];

  return (
    <div style={{ ...panelStyle, borderTop: "3px solid var(--color-primary)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <FileSpreadsheet size={20} color="var(--color-primary-dark)" />
        <h3 style={{ margin: 0 }}>标准化整理与下载</h3>
        <span style={readOnlyBadge}>不写入数据库</span>
      </div>
      <p style={{ color: "var(--color-text-muted)", fontSize: 12.5, marginTop: 8 }}>
        上传一个或多个 Rapid Query xlsx 文件，按照原版规则统一字段、匹配达人库、合并数据并生成标准 Excel。
        下载文件包含「整理结果」「文件处理报告」「异常数据」三个工作表。
      </p>

      <div style={standardizeControls}>
        <input
          ref={fileInputRef}
          aria-label="标准化整理文件"
          type="file"
          accept=".xlsx"
          multiple
          onChange={(event) => {
            setFiles(Array.from(event.target.files ?? []));
            setResult(null);
            setError(null);
          }}
        />
        <label style={fieldLabel}>
          时间戳时区
          <input
            aria-label="时间戳时区"
            style={{ ...inputStyle, marginTop: 0, minWidth: 170 }}
            value={processingTimezone}
            onChange={(event) => setProcessingTimezone(event.target.value)}
          />
        </label>
        <label style={{ ...fieldLabel, flexDirection: "row" }}>
          <input
            type="checkbox"
            checked={deduplicateUrls}
            onChange={(event) => setDeduplicateUrls(event.target.checked)}
          />
          导出时去除完全重复的 URL
        </label>
        <button
          type="button"
          style={files.length === 0 || mutation.isPending ? disabledBtn : primaryBtn}
          disabled={files.length === 0 || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "整理中…" : "开始整理"}
        </button>
      </div>

      {files.length > 0 && (
        <div style={fileListStyle}>
          {files.map((file) => (
            <span key={`${file.name}-${file.size}`}>{file.name}（{Math.max(1, Math.round(file.size / 1024))} KB）</span>
          ))}
        </div>
      )}
      {deduplicateUrls && (
        <div style={infoStyle}>按 platform + url 去重，保留上传顺序中第一次出现的记录；空 URL 不删除。</div>
      )}
      {error && <div style={alertStyle} role="alert">{error}</div>}

      {result && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 18 }}>
          <div className="metric-row">
            {metrics.map(([label, value]) => (
              <div className="metric-card" style={processingMetric} key={String(label)}>
                <div style={{ color: "var(--color-text-muted)", fontSize: 12 }}>{label}</div>
                <strong style={{ display: "block", fontSize: 18, marginTop: 4 }}>{String(value)}</strong>
              </div>
            ))}
          </div>

          {result.overall.removed_duplicate_count > 0 && (
            <div style={warningStyle}>
              已从导出明细移除 {result.overall.removed_duplicate_count} 条重复 URL；异常表仍保留重复记录信息。
            </div>
          )}

          <ResultSection title="逐文件处理报告" count={result.file_reports.length} rows={result.file_reports} columns={fileReportColumns} defaultOpen />
          <ResultSection title="未匹配 UID" count={result.unmatched_uids.length} rows={result.unmatched_uids} columns={unmatchedColumns} tone={result.unmatched_uids.length ? "warning" : undefined} />
          <ResultSection title="整理结果预览（前 100 条）" count={result.result_row_count} rows={result.result_preview} columns={resultColumns} defaultOpen />
          <ResultSection title="异常数据预览（前 200 条）" count={result.exception_row_count} rows={result.exception_preview} columns={exceptionColumns} tone={result.exception_row_count ? "warning" : undefined} />

          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <a href={result.download_path} download={result.filename} style={downloadBtn}>
              <Download size={16} />
              下载统一标准 Excel
            </a>
            <span style={{ color: "var(--color-text-muted)", fontSize: 12 }}>
              下载结果临时保留 {Math.round(result.expires_in_seconds / 60)} 分钟
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function ResultSection({
  title,
  count,
  rows,
  columns,
  tone,
  defaultOpen = false,
}: {
  title: string;
  count: number;
  rows: Record<string, unknown>[];
  columns: Column<Record<string, unknown>>[];
  tone?: "warning";
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button type="button" style={sectionToggle} onClick={() => setOpen((value) => !value)}>
        <strong>{title}</strong>
        <span style={tone === "warning" && count ? warningBadge : countBadge}>{count}</span>
        <span>{open ? "收起" : "展开"}</span>
      </button>
      {open && (
        <div style={{ marginTop: 8 }}>
          <StateShell isLoading={false} isError={false} isEmpty={rows.length === 0} emptyLabel="无">
            <DataTable
              columns={columns}
              rows={rows.map((row, index) => ({ ...row, __row_index: index }))}
              rowKey={(row) => row.__row_index as number}
            />
          </StateShell>
        </div>
      )}
    </div>
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

const secondaryBtn: React.CSSProperties = {
  background: "var(--color-surface)",
  color: "var(--color-text)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  padding: "7px 12px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  justifySelf: "start",
};

const modeFieldset: React.CSSProperties = {
  border: 0,
  padding: 0,
  margin: "0 0 14px",
};

const modeLegend: React.CSSProperties = {
  fontSize: 12.5,
  fontWeight: 700,
  marginBottom: 6,
};

const modeSelector: React.CSSProperties = {
  display: "inline-flex",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  overflow: "hidden",
};

const modeOption: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  padding: "7px 12px",
  fontSize: 12.5,
  cursor: "pointer",
  background: "var(--color-surface)",
  color: "var(--color-text-muted)",
};

const modeOptionActive: React.CSSProperties = {
  background: "var(--color-primary-bg)",
  color: "var(--color-primary-dark)",
  fontWeight: 700,
};

const standardizeControls: React.CSSProperties = {
  display: "flex",
  gap: 12,
  alignItems: "center",
  flexWrap: "wrap",
  marginTop: 14,
};

const fieldLabel: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  alignItems: "center",
  fontSize: 12.5,
};

const readOnlyBadge: React.CSSProperties = {
  background: "var(--color-primary-bg)",
  color: "var(--color-primary-dark)",
  borderRadius: 999,
  padding: "2px 8px",
  fontSize: 11.5,
  fontWeight: 600,
};

const fileListStyle: React.CSSProperties = {
  display: "flex",
  gap: "6px 14px",
  flexWrap: "wrap",
  marginTop: 10,
  color: "var(--color-text-muted)",
  fontSize: 12,
};

const infoStyle: React.CSSProperties = {
  background: "var(--color-primary-bg)",
  color: "var(--color-primary-dark)",
  borderRadius: "var(--radius)",
  padding: "8px 10px",
  fontSize: 12.5,
  marginTop: 10,
};

const warningStyle: React.CSSProperties = {
  background: "var(--color-warning-bg)",
  color: "var(--color-warning)",
  border: "1px solid var(--color-warning)",
  borderRadius: "var(--radius)",
  padding: "8px 12px",
  fontSize: 12.5,
};

const smartImportPanelStyle: React.CSSProperties = {
  display: "grid",
  gap: 12,
  padding: 14,
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  background: "var(--color-bg-subtle)",
};

const smartImportHintStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  fontSize: 12,
  marginTop: 4,
};

const smartImportFileStyle: React.CSSProperties = {
  display: "grid",
  gap: 10,
  paddingTop: 12,
  borderTop: "1px solid var(--color-border)",
};

const diagnosticTagStyle: React.CSSProperties = {
  background: "var(--color-primary-bg)",
  color: "var(--color-primary-dark)",
  borderRadius: 4,
  padding: "2px 7px",
  fontSize: 11.5,
  fontWeight: 600,
};

const mappingGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 8,
};

const mappingFieldStyle: React.CSSProperties = {
  display: "grid",
  gap: 4,
  color: "var(--color-text-muted)",
  fontSize: 12,
};

const mappingSelectStyle: React.CSSProperties = {
  width: "100%",
  minWidth: 0,
  padding: "6px 8px",
  borderRadius: "var(--radius)",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
  color: "var(--color-text)",
  fontSize: 12.5,
};

const warningTextStyle: React.CSSProperties = {
  color: "var(--color-warning)",
  fontSize: 12,
};

const warningBadge: React.CSSProperties = {
  ...countBadge,
  background: "var(--color-warning-bg)",
  color: "var(--color-warning)",
};

const sectionToggle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  background: "none",
  border: 0,
  color: "var(--color-primary-dark)",
  padding: 0,
};

const processingMetric: React.CSSProperties = {
  background: "var(--color-bg)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  padding: 10,
};

const downloadBtn: React.CSSProperties = {
  ...primaryBtn,
  display: "inline-flex",
  alignItems: "center",
  gap: 7,
  textDecoration: "none",
};
