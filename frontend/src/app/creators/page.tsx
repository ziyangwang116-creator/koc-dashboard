"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { StateShell } from "@/components/DataStates";
import { creatorsApi, metaApi } from "@/lib/endpoints";
import { fmtInt } from "@/lib/format";
import type { Creator } from "@/lib/types";
import { ApiError } from "@/lib/api-client";

export default function CreatorsPage() {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [contractType, setContractType] = useState("");
  const [active, setActive] = useState<"all" | "true" | "false">("all");
  const [followerStatus, setFollowerStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);

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

  const rows = listQuery.data?.data ?? [];
  const pagination = listQuery.data?.meta.pagination;

  const columns: Column<Creator>[] = [
    { key: "koc_name", header: "达人名称", width: 130, render: (r) => r.koc_name },
    { key: "user_id", header: "UID", width: 100, render: (r) => r.user_id },
    { key: "creator_category", header: "合作类别", width: 100, render: (r) => r.creator_category ?? "—" },
    {
      key: "contract_types",
      header: "合同类型",
      width: 140,
      render: (r) => r.contract_types.join("、") || "—",
    },
    {
      key: "follower_count",
      header: "粉丝数",
      width: 90,
      align: "right",
      render: (r) => fmtInt(r.follower_count),
    },
    {
      key: "follower_sync_status",
      header: "粉丝同步状态",
      width: 100,
      render: (r) => r.follower_sync_status,
    },
    {
      key: "active",
      header: "启用状态",
      width: 80,
      render: (r) => (r.active ? "启用" : "停用"),
    },
    {
      key: "op",
      header: "操作",
      width: 70,
      render: (r) => (
        <button type="button" style={linkBtn} onClick={() => setSelectedId(r.id)}>
          查看详情
        </button>
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
          <select value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }} style={selectStyle}>
            <option value="">全部合作类别</option>
            <option value="LONG_TERM">LONG_TERM</option>
            <option value="COMMENTARY">COMMENTARY</option>
            <option value="GRASSROOT">GRASSROOT</option>
          </select>
          <select
            value={contractType}
            onChange={(e) => { setContractType(e.target.value); setPage(1); }}
            style={selectStyle}
          >
            <option value="">全部合同类型</option>
            {(contractTypesQuery.data?.data.contract_types ?? []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select value={active} onChange={(e) => { setActive(e.target.value as "all"|"true"|"false"); setPage(1); }} style={selectStyle}>
            <option value="all">全部启用状态</option>
            <option value="true">仅启用</option>
            <option value="false">仅停用</option>
          </select>
          <select
            value={followerStatus}
            onChange={(e) => { setFollowerStatus(e.target.value); setPage(1); }}
            style={selectStyle}
          >
            <option value="">全部粉丝同步状态</option>
            <option value="NEVER">NEVER</option>
            <option value="SUCCESS">SUCCESS</option>
            <option value="FAILED">FAILED</option>
            <option value="MANUAL">MANUAL</option>
          </select>
        </div>

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
          <div style={panelStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <strong>达人详情</strong>
              <button type="button" style={linkBtn} onClick={() => setSelectedId(null)}>
                关闭
              </button>
            </div>
            <StateShell
              isLoading={detailQuery.isLoading}
              isError={detailQuery.isError}
              errorMessage={detailQuery.error instanceof ApiError ? detailQuery.error.message : undefined}
              isEmpty={false}
            >
              {detailQuery.data && (
                <div style={{ fontSize: 13, display: "flex", flexDirection: "column", gap: 10 }}>
                  <div>
                    {detailQuery.data.data.koc_name}（{detailQuery.data.data.user_id}）·{" "}
                    {detailQuery.data.data.creator_category ?? "—"}
                  </div>
                  <div>
                    <strong>合同周期</strong>
                    <ul style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 4 }}>
                      {detailQuery.data.data.contract_periods.map((p) => (
                        <li key={p.id} style={{ color: "var(--color-text-muted)" }}>
                          {p.effective_date} · {p.contract_start_date} ~ {p.contract_end_date} ·{" "}
                          {p.contract_types.join("、")}
                        </li>
                      ))}
                      {detailQuery.data.data.contract_periods.length === 0 && <li>无合同周期记录</li>}
                    </ul>
                  </div>
                </div>
              )}
            </StateShell>
          </div>
        )}
      </section>
    </AppShell>
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
  minWidth: 180,
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
};
