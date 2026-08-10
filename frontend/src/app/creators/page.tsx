"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { StateShell } from "@/components/DataStates";
import { creatorsApi, metaApi } from "@/lib/endpoints";
import { fmtInt } from "@/lib/format";
import type { Creator, ContractPeriod, CreatorDetail, ContractRevision } from "@/lib/types";
import { ApiError } from "@/lib/api-client";

/**
 * Invalidate every query key that the API contract's affected-scope sections
 * list for creator/contract writes: creators list + detail, dynamic
 * contract-type meta, dashboard filter options, and any open compensation
 * preview (which re-resolves the effective contract on refetch).
 */
function invalidateAffectedQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  creatorId?: number
) {
  queryClient.invalidateQueries({ queryKey: ["creators", "list"] });
  if (creatorId !== undefined) {
    queryClient.invalidateQueries({ queryKey: ["creators", "detail", creatorId] });
  }
  queryClient.invalidateQueries({ queryKey: ["meta", "contract-types"] });
  queryClient.invalidateQueries({ queryKey: ["dashboard", "filter-options"] });
  queryClient.invalidateQueries({ queryKey: ["compensation"] });
}

function errorMessageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "操作失败，请稍后重试。";
}

export default function CreatorsPage() {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [contractType, setContractType] = useState("");
  const [active, setActive] = useState<"all" | "true" | "false">("all");
  const [followerStatus, setFollowerStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<{
    koc_name: string;
    homepage_url: string;
    follower_count: string;
    note: string;
  } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const contractTypesQuery = useQuery({
    queryKey: ["meta", "contract-types"],
    queryFn: () => metaApi.contractTypes(),
    staleTime: 5 * 60_000,
  });

  const listParams = {
    q: q || undefined,
    creator_category: category || undefined,
    contract_type: contractType || undefined,
    active,
    follower_sync_status: followerStatus || undefined,
    page,
    page_size: 20,
  };

  const listQuery = useQuery({
    queryKey: ["creators", "list", listParams],
    queryFn: () => creatorsApi.list(listParams),
  });

  const detailQuery = useQuery({
    queryKey: ["creators", "detail", selectedId],
    queryFn: () => creatorsApi.detail(selectedId as number),
    enabled: selectedId !== null,
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      body,
      expectedUpdatedAt,
    }: {
      id: number;
      body: Record<string, unknown>;
      expectedUpdatedAt?: string;
    }) => creatorsApi.update(id, body, expectedUpdatedAt),
    onSuccess: (_data, variables) => {
      setActionError(null);
      setEditingId(null);
      setEditDraft(null);
      invalidateAffectedQueries(queryClient, variables.id);
    },
    onError: (err) => setActionError(errorMessageOf(err)),
  });

  const activeMutation = useMutation({
    mutationFn: ({ id, value }: { id: number; value: boolean }) => creatorsApi.setActive(id, value),
    onSuccess: (_data, variables) => {
      setActionError(null);
      invalidateAffectedQueries(queryClient, variables.id);
    },
    onError: (err) => setActionError(errorMessageOf(err)),
  });

  const rows = listQuery.data?.data ?? [];
  const pagination = listQuery.data?.meta.pagination;

  function beginEdit(row: Creator) {
    setActionError(null);
    setEditingId(row.id);
    setEditDraft({
      koc_name: row.koc_name,
      homepage_url: row.homepage_url ?? "",
      follower_count: row.follower_count != null ? String(row.follower_count) : "",
      note: row.note ?? "",
    });
  }

  function saveEdit(row: Creator) {
    if (!editDraft) return;
    updateMutation.mutate({
      id: row.id,
      body: {
        user_id: row.user_id,
        koc_name: editDraft.koc_name,
        creator_category: row.creator_category,
        contract_types: row.contract_types,
        homepage_url: editDraft.homepage_url || null,
        follower_count: editDraft.follower_count === "" ? null : Number(editDraft.follower_count),
        active: row.active,
        note: editDraft.note || null,
        manual_follower_update: true,
      },
      expectedUpdatedAt: row.updated_at,
    });
  }

  const columns: Column<Creator>[] = [
    {
      key: "koc_name",
      header: "达人名称",
      width: 150,
      render: (r) =>
        editingId === r.id ? (
          <input
            style={inputStyle}
            value={editDraft?.koc_name ?? ""}
            onChange={(e) => setEditDraft((d) => (d ? { ...d, koc_name: e.target.value } : d))}
          />
        ) : (
          r.koc_name
        ),
    },
    { key: "user_id", header: "UID", width: 100, render: (r) => r.user_id },
    {
      key: "creator_category",
      header: "合作类别",
      width: 100,
      render: (r) => r.creator_category ?? "—",
    },
    {
      key: "contract_types",
      header: "合同类型",
      width: 140,
      render: (r) => r.contract_types.join("、") || "—",
    },
    {
      key: "homepage_url",
      header: "主页链接",
      width: 160,
      render: (r) =>
        editingId === r.id ? (
          <input
            style={inputStyle}
            value={editDraft?.homepage_url ?? ""}
            onChange={(e) => setEditDraft((d) => (d ? { ...d, homepage_url: e.target.value } : d))}
          />
        ) : (
          r.homepage_url ?? "—"
        ),
    },
    {
      key: "follower_count",
      header: "粉丝数",
      width: 100,
      align: "right",
      render: (r) =>
        editingId === r.id ? (
          <input
            style={{ ...inputStyle, textAlign: "right" }}
            value={editDraft?.follower_count ?? ""}
            onChange={(e) =>
              setEditDraft((d) => (d ? { ...d, follower_count: e.target.value } : d))
            }
          />
        ) : (
          fmtInt(r.follower_count)
        ),
    },
    {
      key: "note",
      header: "备注",
      width: 140,
      render: (r) =>
        editingId === r.id ? (
          <input
            style={inputStyle}
            value={editDraft?.note ?? ""}
            onChange={(e) => setEditDraft((d) => (d ? { ...d, note: e.target.value } : d))}
          />
        ) : (
          r.note ?? "—"
        ),
    },
    {
      key: "active",
      header: "启用状态",
      width: 90,
      render: (r) => (
        <button
          type="button"
          style={r.active ? enabledBadge : disabledBadge}
          onClick={() =>
            window.confirm(r.active ? `确认停用达人「${r.koc_name}」？` : `确认启用达人「${r.koc_name}」？`) &&
            activeMutation.mutate({ id: r.id, value: !r.active })
          }
        >
          {r.active ? "启用" : "停用"}
        </button>
      ),
    },
    {
      key: "op",
      header: "操作",
      width: 150,
      render: (r) =>
        editingId === r.id ? (
          <div style={{ display: "flex", gap: 6 }}>
            <button type="button" style={primaryBtn} onClick={() => saveEdit(r)} disabled={updateMutation.isPending}>
              保存
            </button>
            <button
              type="button"
              style={linkBtn}
              onClick={() => {
                setEditingId(null);
                setEditDraft(null);
              }}
            >
              取消
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 6 }}>
            <button type="button" style={linkBtn} onClick={() => beginEdit(r)}>
              编辑
            </button>
            <button type="button" style={linkBtn} onClick={() => setSelectedId(r.id)}>
              查看详情
            </button>
          </div>
        ),
    },
  ];

  return (
    <AppShell>
      <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={filterBar}>
          <input
            placeholder="搜索达人名称 / UID"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            style={inputStyle}
          />
          <select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              setPage(1);
            }}
            style={selectStyle}
          >
            <option value="">全部合作类别</option>
            <option value="LONG_TERM">LONG_TERM</option>
            <option value="COMMENTARY">COMMENTARY</option>
            <option value="GRASSROOT">GRASSROOT</option>
          </select>
          <select
            value={contractType}
            onChange={(e) => {
              setContractType(e.target.value);
              setPage(1);
            }}
            style={selectStyle}
          >
            <option value="">全部合同类型</option>
            {(contractTypesQuery.data?.data.contract_types ?? []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            value={active}
            onChange={(e) => {
              setActive(e.target.value as "all" | "true" | "false");
              setPage(1);
            }}
            style={selectStyle}
          >
            <option value="all">全部启用状态</option>
            <option value="true">仅启用</option>
            <option value="false">仅停用</option>
          </select>
          <select
            value={followerStatus}
            onChange={(e) => {
              setFollowerStatus(e.target.value);
              setPage(1);
            }}
            style={selectStyle}
          >
            <option value="">全部粉丝同步状态</option>
            <option value="NEVER">NEVER</option>
            <option value="SUCCESS">SUCCESS</option>
            <option value="FAILED">FAILED</option>
            <option value="MANUAL">MANUAL</option>
          </select>
        </div>

        {actionError && (
          <div style={alertStyle} role="alert">
            {actionError}
          </div>
        )}

        <div style={panelStyle}>
          <StateShell
            isLoading={listQuery.isLoading}
            isError={listQuery.isError}
            isUnauthorized={listQuery.error instanceof ApiError && listQuery.error.status === 401}
            errorMessage={listQuery.error instanceof ApiError ? listQuery.error.message : undefined}
            isEmpty={rows.length === 0}
          >
            <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
          </StateShell>
          {pagination && (
            <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center", fontSize: 13 }}>
              <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} style={linkBtn}>
                上一页
              </button>
              <span>
                第 {pagination.page} / {pagination.total_pages} 页（共 {pagination.total_items} 条）
              </span>
              <button
                disabled={page >= pagination.total_pages}
                onClick={() => setPage((p) => p + 1)}
                style={linkBtn}
              >
                下一页
              </button>
            </div>
          )}
        </div>

        {selectedId !== null && (
          <CreatorDetailPanel creatorId={selectedId} onClose={() => setSelectedId(null)} detailQuery={detailQuery} />
        )}
      </section>
    </AppShell>
  );
}

// ---------------------------------------------------------------------------
// Detail panel: contract periods, contract-change vs contract-correction,
// delete-period and revert-to-revision actions.
// ---------------------------------------------------------------------------

function CreatorDetailPanel({
  creatorId,
  onClose,
  detailQuery,
}: {
  creatorId: number;
  onClose: () => void;
  detailQuery: UseQueryResult<{ data: CreatorDetail }>;
}) {
  const queryClient = useQueryClient();
  const [showDeleted, setShowDeleted] = useState(false);
  const [periodSearch, setPeriodSearch] = useState("");
  const [changeModalOpen, setChangeModalOpen] = useState(false);
  const [correctionModalOpen, setCorrectionModalOpen] = useState(false);
  const [correctionTarget, setCorrectionTarget] = useState<ContractPeriod | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ContractPeriod | null>(null);
  const [deleteReason, setDeleteReason] = useState("");
  const [revertOpen, setRevertOpen] = useState(false);
  const [revertReasons, setRevertReasons] = useState<Record<number, string>>({});
  const [panelError, setPanelError] = useState<string | null>(null);

  const revisionsQuery = useQuery({
    queryKey: ["creators", "contract-revisions", creatorId],
    queryFn: () => creatorsApi.contractRevisions(creatorId),
    enabled: showDeleted || revertOpen,
  });
  const revisions: ContractRevision[] = revisionsQuery.data?.data ?? [];
  const deletedPeriodRevisions = revisions.filter((r) => r.is_deleted_period);

  function onWriteSuccess() {
    setPanelError(null);
    invalidateAffectedQueries(queryClient, creatorId);
    queryClient.invalidateQueries({ queryKey: ["creators", "contract-revisions", creatorId] });
  }
  function onWriteError(err: unknown) {
    setPanelError(errorMessageOf(err));
  }

  const changeMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => creatorsApi.createContractChange(creatorId, body),
    onSuccess: () => {
      onWriteSuccess();
      setChangeModalOpen(false);
    },
    onError: onWriteError,
  });

  const correctionMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => creatorsApi.createContractCorrection(creatorId, body),
    onSuccess: () => {
      onWriteSuccess();
      setCorrectionModalOpen(false);
      setCorrectionTarget(null);
    },
    onError: onWriteError,
  });

  const deleteMutation = useMutation({
    mutationFn: ({ date, reason }: { date: string; reason?: string }) =>
      creatorsApi.deleteContractPeriod(creatorId, date, reason),
    onSuccess: () => {
      onWriteSuccess();
      setDeleteTarget(null);
      setDeleteReason("");
    },
    onError: onWriteError,
  });

  const revertMutation = useMutation({
    mutationFn: ({ revisionId, reason }: { revisionId: number; reason: string }) =>
      creatorsApi.revertContractRevision(creatorId, revisionId, reason),
    onSuccess: (_data, variables) => {
      onWriteSuccess();
      setRevertReasons((prev) => {
        const next = { ...prev };
        delete next[variables.revisionId];
        return next;
      });
    },
    onError: onWriteError,
  });

  const detail = detailQuery.data?.data;
  const periods = (detail?.contract_periods ?? []).filter((p) =>
    periodSearch
      ? p.contract_types.join(",").toLowerCase().includes(periodSearch.toLowerCase()) ||
        p.contract_start_date.includes(periodSearch)
      : true
  );

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <strong>达人详情</strong>
        <button type="button" style={linkBtn} onClick={onClose}>
          关闭
        </button>
      </div>
      <StateShell
        isLoading={detailQuery.isLoading}
        isError={detailQuery.isError}
        errorMessage={detailQuery.error instanceof ApiError ? detailQuery.error.message : undefined}
        isEmpty={false}
      >
        {detail && (
          <div style={{ fontSize: 13, display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              {detail.koc_name}（{detail.user_id}）· {detail.creator_category ?? "—"}
            </div>

            {panelError && (
              <div style={alertStyle} role="alert">
                {panelError}
              </div>
            )}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button type="button" style={changeBtn} onClick={() => setChangeModalOpen(true)}>
                ＋ 新增合同变更
              </button>
              <button
                type="button"
                style={correctionBtn}
                onClick={() => {
                  setCorrectionTarget(periods[0] ?? null);
                  setCorrectionModalOpen(true);
                }}
                disabled={periods.length === 0}
              >
                ✎ 修正错误合同
              </button>
              <button type="button" style={linkBtn} onClick={() => setRevertOpen((v) => !v)}>
                撤销历史修改…
              </button>
              <label style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
                <input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />
                显示已删除记录
              </label>
              <input
                placeholder="搜索合同周期（类型/日期）"
                value={periodSearch}
                onChange={(e) => setPeriodSearch(e.target.value)}
                style={{ ...inputStyle, minWidth: 160 }}
              />
            </div>

            <div>
              <strong>合同周期</strong>
              <table style={{ width: "100%", marginTop: 6, fontSize: 12.5 }}>
                <thead>
                  <tr>
                    <th style={thCell}>生效日</th>
                    <th style={thCell}>起止</th>
                    <th style={thCell}>合同类型</th>
                    <th style={thCell}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {periods.map((p) => (
                    <tr key={p.id}>
                      <td style={tdCell}>{p.effective_date}</td>
                      <td style={tdCell}>
                        {p.contract_start_date} ~ {p.contract_end_date}
                      </td>
                      <td style={tdCell}>{p.contract_types.join("、")}</td>
                      <td style={tdCell}>
                        <button
                          type="button"
                          style={linkBtn}
                          onClick={() => {
                            setCorrectionTarget(p);
                            setCorrectionModalOpen(true);
                          }}
                        >
                          修正
                        </button>{" "}
                        <button
                          type="button"
                          style={{ ...linkBtn, color: "var(--color-danger)" }}
                          onClick={() => setDeleteTarget(p)}
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                  {periods.length === 0 && (
                    <tr>
                      <td style={tdCell} colSpan={4}>
                        无合同周期记录
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              {showDeleted && (
                <div style={{ marginTop: 8 }}>
                  <strong style={{ fontSize: 12.5 }}>已删除的合同周期</strong>
                  <StateShell
                    isLoading={revisionsQuery.isLoading}
                    isError={revisionsQuery.isError}
                    errorMessage={
                      revisionsQuery.error instanceof ApiError ? revisionsQuery.error.message : undefined
                    }
                    isEmpty={deletedPeriodRevisions.length === 0}
                  >
                    <table style={{ width: "100%", marginTop: 6, fontSize: 12.5 }}>
                      <thead>
                        <tr>
                          <th style={thCell}>修订ID</th>
                          <th style={thCell}>受影响区间</th>
                          <th style={thCell}>删除前周期</th>
                          <th style={thCell}>原因</th>
                          <th style={thCell}>删除时间</th>
                        </tr>
                      </thead>
                      <tbody>
                        {deletedPeriodRevisions.map((rev) => (
                          <tr key={rev.id}>
                            <td style={tdCell}>#{rev.id}</td>
                            <td style={tdCell}>
                              {rev.affected_start_date} ~ {rev.affected_end_date}
                            </td>
                            <td style={tdCell}>
                              {rev.before_periods
                                .map((p) =>
                                  Array.isArray(p.contract_types) ? (p.contract_types as string[]).join("、") : ""
                                )
                                .filter(Boolean)
                                .join("; ") || "—"}
                            </td>
                            <td style={tdCell}>{rev.reason ?? "—"}</td>
                            <td style={tdCell}>{rev.created_at}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </StateShell>
                </div>
              )}
            </div>

            {revertOpen && (
              <div style={{ ...panelStyle, background: "var(--color-warning-bg)" }}>
                <strong>合同修改历史 / 撤销</strong>
                <StateShell
                  isLoading={revisionsQuery.isLoading}
                  isError={revisionsQuery.isError}
                  errorMessage={
                    revisionsQuery.error instanceof ApiError ? revisionsQuery.error.message : undefined
                  }
                  isEmpty={revisions.length === 0}
                >
                  <table style={{ width: "100%", marginTop: 8, fontSize: 12.5 }}>
                    <thead>
                      <tr>
                        <th style={thCell}>修订ID</th>
                        <th style={thCell}>类型</th>
                        <th style={thCell}>原因</th>
                        <th style={thCell}>时间</th>
                        <th style={thCell}>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {revisions.map((rev) => (
                        <tr key={rev.id}>
                          <td style={tdCell}>#{rev.id}</td>
                          <td style={tdCell}>{rev.operation_type}</td>
                          <td style={tdCell}>{rev.reason ?? "—"}</td>
                          <td style={tdCell}>{rev.created_at}</td>
                          <td style={tdCell}>
                            {rev.revertable ? (
                              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                                <input
                                  placeholder="撤销原因（1-500 字符，必填）"
                                  value={revertReasons[rev.id] ?? ""}
                                  onChange={(e) =>
                                    setRevertReasons((prev) => ({ ...prev, [rev.id]: e.target.value }))
                                  }
                                  style={{ ...inputStyle, minWidth: 200 }}
                                />
                                <button
                                  type="button"
                                  style={dangerBtn}
                                  disabled={
                                    !(revertReasons[rev.id] ?? "").trim() ||
                                    (revertReasons[rev.id] ?? "").length > 500
                                  }
                                  onClick={() => {
                                    const reason = (revertReasons[rev.id] ?? "").trim();
                                    if (
                                      window.confirm(
                                        "这将撤销该达人最近一次未撤销的合同修改，并生成一条新的撤销记录；原记录不会被物理删除。确认继续？"
                                      )
                                    ) {
                                      revertMutation.mutate({ revisionId: rev.id, reason });
                                    }
                                  }}
                                >
                                  回退
                                </button>
                              </div>
                            ) : (
                              <span
                                style={{ color: "var(--color-text-muted)" }}
                                title={
                                  rev.status === "REVERTED"
                                    ? "该修改已被撤销，无法再次撤销"
                                    : rev.status === "REVERT_RECORD"
                                      ? "撤销记录本身不可再次撤销"
                                      : "只能撤销该达人最近一次未撤销的合同修改"
                                }
                              >
                                {rev.status === "REVERTED"
                                  ? "已回退"
                                  : rev.status === "REVERT_RECORD"
                                    ? "回退记录不可回退"
                                    : "不可回退"}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </StateShell>
              </div>
            )}
          </div>
        )}
      </StateShell>

      {changeModalOpen && (
        <ContractChangeModal
          onCancel={() => setChangeModalOpen(false)}
          onSubmit={(body) => changeMutation.mutate(body)}
          pending={changeMutation.isPending}
        />
      )}

      {correctionModalOpen && correctionTarget && (
        <ContractCorrectionModal
          target={correctionTarget}
          onCancel={() => {
            setCorrectionModalOpen(false);
            setCorrectionTarget(null);
          }}
          onSubmit={(body) => correctionMutation.mutate(body)}
          pending={correctionMutation.isPending}
        />
      )}

      {deleteTarget && (
        <ConfirmDeleteDialog
          period={deleteTarget}
          reason={deleteReason}
          onReasonChange={setDeleteReason}
          onCancel={() => {
            setDeleteTarget(null);
            setDeleteReason("");
          }}
          onConfirm={() =>
            deleteMutation.mutate({ date: deleteTarget.contract_start_date, reason: deleteReason || undefined })
          }
          pending={deleteMutation.isPending}
        />
      )}
    </div>
  );
}

function ContractChangeModal({
  onCancel,
  onSubmit,
  pending,
}: {
  onCancel: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
  pending: boolean;
}) {
  const [effectiveDate, setEffectiveDate] = useState("");
  const [contractTypes, setContractTypes] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");

  return (
    <div style={modalOverlay}>
      <div style={{ ...modalBox, borderTop: "4px solid var(--color-primary)" }}>
        <h3 style={{ margin: 0 }}>新增合同变更</h3>
        <p style={{ color: "var(--color-text-muted)", fontSize: 12.5 }}>
          这将作为一次真实的合同变更被记录在该达人的合同历史中，从生效日起生效。请确认这不是对历史录入错误的更正——如果是录入错误，请改用「修正错误合同」。
        </p>
        <div style={formGrid}>
          <label>
            生效日 *
            <input type="date" style={inputStyle} value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
          </label>
          <label>
            合同类型（逗号分隔）*
            <input
              style={inputStyle}
              value={contractTypes}
              onChange={(e) => setContractTypes(e.target.value)}
              placeholder="YTB,TT"
            />
          </label>
          <label>
            截止日期（可选）
            <input type="date" style={inputStyle} value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
          <label>
            变更原因
            <input
              style={inputStyle}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="例如：客户方要求新增短视频合作"
            />
          </label>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
          <button type="button" style={linkBtn} onClick={onCancel}>
            取消
          </button>
          <button
            type="button"
            style={primaryBtn}
            disabled={pending || !effectiveDate || !contractTypes.trim()}
            onClick={() =>
              onSubmit({
                effective_date: effectiveDate,
                contract_types: contractTypes
                  .split(",")
                  .map((v) => v.trim())
                  .filter(Boolean),
                contract_end_date: endDate || undefined,
                reason: reason || undefined,
              })
            }
          >
            确认新增变更
          </button>
        </div>
      </div>
    </div>
  );
}

function ContractCorrectionModal({
  target,
  onCancel,
  onSubmit,
  pending,
}: {
  target: ContractPeriod;
  onCancel: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
  pending: boolean;
}) {
  const [contractTypes, setContractTypes] = useState(target.contract_types.join(","));
  const [startDate, setStartDate] = useState(target.contract_start_date);
  const [endDate, setEndDate] = useState(target.contract_end_date);
  const [reason, setReason] = useState("");

  return (
    <div style={modalOverlay}>
      <div style={{ ...modalBox, borderTop: "4px solid var(--color-warning)" }}>
        <h3 style={{ margin: 0 }}>修正错误合同</h3>
        <p style={{ color: "var(--color-text-muted)", fontSize: 12.5 }}>
          这是对已录入历史数据的更正，不会被视为一次新的业务变更。该周期在历史时间线上将被视为「从未错过」。请确认这是录入错误而非业务变化。
        </p>
        <div style={formGrid}>
          <label>
            定位周期（生效日）
            <input style={inputStyle} value={target.contract_start_date} disabled />
          </label>
          <label>
            合同类型（逗号分隔）*
            <input style={inputStyle} value={contractTypes} onChange={(e) => setContractTypes(e.target.value)} />
          </label>
          <label>
            开始日期 *
            <input type="date" style={inputStyle} value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            截止日期 *
            <input type="date" style={inputStyle} value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
          <label>
            修正原因
            <input
              style={inputStyle}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="例如：原录入误填为YTB+TT，实际仅有YTB"
            />
          </label>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
          <button type="button" style={linkBtn} onClick={onCancel}>
            取消
          </button>
          <button
            type="button"
            style={warningBtn}
            disabled={pending || !contractTypes.trim() || !startDate || !endDate}
            onClick={() =>
              onSubmit({
                source_effective_date: target.contract_start_date,
                contract_types: contractTypes
                  .split(",")
                  .map((v) => v.trim())
                  .filter(Boolean),
                contract_start_date: startDate,
                contract_end_date: endDate,
                reason: reason || undefined,
              })
            }
          >
            确认修正
          </button>
        </div>
      </div>
    </div>
  );
}

function ConfirmDeleteDialog({
  period,
  reason,
  onReasonChange,
  onCancel,
  onConfirm,
  pending,
}: {
  period: ContractPeriod;
  reason: string;
  onReasonChange: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
  pending: boolean;
}) {
  const [confirmed, setConfirmed] = useState(false);
  return (
    <div style={modalOverlay}>
      <div style={{ ...modalBox, borderTop: "4px solid var(--color-danger)" }}>
        <h3 style={{ margin: 0 }}>删除合同周期</h3>
        <p style={{ color: "var(--color-text-muted)", fontSize: 12.5 }}>
          即将删除 {period.contract_start_date} ~ {period.contract_end_date} 的合同周期（{period.contract_types.join("、")}）。
          该操作用于清除因录入失误产生的周期，历史审计记录会完整保留，但不可在此界面撤销恢复。
        </p>
        <label style={{ display: "block", marginTop: 8 }}>
          删除原因（可选）
          <input style={inputStyle} value={reason} onChange={(e) => onReasonChange(e.target.value)} />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, fontSize: 12.5 }}>
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          我确认要删除该合同周期
        </label>
        <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
          <button type="button" style={linkBtn} onClick={onCancel}>
            取消
          </button>
          <button type="button" style={dangerBtn} disabled={!confirmed || pending} onClick={onConfirm}>
            确认删除
          </button>
        </div>
      </div>
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

const inputStyle: React.CSSProperties = {
  padding: "6px 8px",
  borderRadius: "var(--radius)",
  border: "1px solid var(--color-border)",
  fontSize: 13,
  minWidth: 120,
};

const selectStyle: React.CSSProperties = { ...inputStyle, minWidth: 140 };

const panelStyle: React.CSSProperties = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  padding: 12,
};

const linkBtn: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--color-primary-dark)",
  fontSize: 12.5,
  padding: 0,
  cursor: "pointer",
};

const primaryBtn: React.CSSProperties = {
  background: "var(--color-primary)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--radius)",
  padding: "6px 12px",
  fontSize: 12.5,
  cursor: "pointer",
};

const changeBtn: React.CSSProperties = {
  ...primaryBtn,
  background: "var(--color-primary)",
};

const warningBtn: React.CSSProperties = {
  ...primaryBtn,
  background: "var(--color-warning)",
  color: "#1a1200",
};

const correctionBtn: React.CSSProperties = {
  ...primaryBtn,
  background: "var(--color-warning)",
  color: "#1a1200",
};

const dangerBtn: React.CSSProperties = {
  ...primaryBtn,
  background: "var(--color-danger)",
};

const enabledBadge: React.CSSProperties = {
  border: "1px solid var(--color-primary)",
  color: "var(--color-primary-dark)",
  background: "transparent",
  borderRadius: "var(--radius)",
  fontSize: 12,
  padding: "2px 8px",
  cursor: "pointer",
};

const disabledBadge: React.CSSProperties = {
  ...enabledBadge,
  border: "1px solid var(--color-text-muted)",
  color: "var(--color-text-muted)",
};

const alertStyle: React.CSSProperties = {
  background: "var(--color-danger-bg)",
  color: "var(--color-danger)",
  border: "1px solid var(--color-danger)",
  borderRadius: "var(--radius)",
  padding: "8px 12px",
  fontSize: 13,
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

const formGrid: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
  marginTop: 10,
  fontSize: 12.5,
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
