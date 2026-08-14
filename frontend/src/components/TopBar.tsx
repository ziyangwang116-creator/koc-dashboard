"use client";

import { CalendarDays, LogOut, Menu, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { authApi } from "@/lib/endpoints";
import { useQueryClient } from "@tanstack/react-query";
import { clearPersistedQueryCache } from "@/lib/providers";

export function TopBar({
  currentPeriod,
  onMenuToggle,
}: {
  currentPeriod?: string;
  onMenuToggle?: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();

  async function handleRefresh() {
    await queryClient.invalidateQueries();
  }

  async function handleLogout() {
    try {
      await authApi.logout();
    } finally {
      queryClient.clear();
      clearPersistedQueryCache();
      router.replace("/login");
    }
  }

  return (
    <header className="app-topbar">
      <div className="topbar-context">
        <button type="button" className="topbar-menu" onClick={onMenuToggle} aria-label="打开导航">
          <Menu size={18} />
        </button>
        <div className="topbar-period">
          <CalendarDays size={15} />
          <span>{currentPeriod ? `当前周期 ${currentPeriod}` : "未选择周期"}</span>
        </div>
      </div>
      <div className="topbar-actions">
        <button
          type="button"
          title="刷新数据"
          aria-label="刷新数据"
          onClick={handleRefresh}
          className="ui-icon-button"
        >
          <RefreshCw size={16} />
        </button>
        <button
          type="button"
          title="退出登录"
          aria-label="退出登录"
          onClick={handleLogout}
          className="ui-icon-button"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}
