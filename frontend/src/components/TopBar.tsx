"use client";

import { RefreshCw, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { authApi } from "@/lib/endpoints";
import { useQueryClient } from "@tanstack/react-query";

export function TopBar({ currentPeriod }: { currentPeriod?: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();

  async function handleRefresh() {
    await queryClient.invalidateQueries();
  }

  async function handleLogout() {
    try {
      await authApi.logout();
    } finally {
      router.replace("/login");
    }
  }

  return (
    <header style={styles.bar}>
      <div style={styles.period}>{currentPeriod ? `当前周期：${currentPeriod}` : "未选择周期"}</div>
      <div style={styles.actions}>
        <button
          type="button"
          title="刷新数据"
          aria-label="刷新数据"
          onClick={handleRefresh}
          style={styles.iconBtn}
        >
          <RefreshCw size={16} />
        </button>
        <button
          type="button"
          title="退出登录"
          aria-label="退出登录"
          onClick={handleLogout}
          style={styles.iconBtn}
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}

const styles: Record<string, React.CSSProperties> = {
  bar: {
    height: 48,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 16px",
    background: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border)",
  },
  period: { fontSize: 13, color: "var(--color-text-muted)" },
  actions: { display: "flex", gap: 8 },
  iconBtn: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: 32,
    height: 32,
    borderRadius: "var(--radius)",
    border: "1px solid var(--color-border)",
    background: "var(--color-surface)",
    color: "var(--color-text-muted)",
  },
};
