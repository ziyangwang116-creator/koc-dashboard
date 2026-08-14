"use client";

import { useState } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell({
  children,
  currentPeriod,
}: {
  children: React.ReactNode;
  currentPeriod?: string;
}) {
  const [navigationOpen, setNavigationOpen] = useState(false);

  return (
    <div className="app-shell">
      <Sidebar open={navigationOpen} onClose={() => setNavigationOpen(false)} />
      {navigationOpen && (
        <button
          type="button"
          className="sidebar-backdrop"
          onClick={() => setNavigationOpen(false)}
          aria-label="关闭导航"
        />
      )}
      <div className="app-workspace">
        <TopBar currentPeriod={currentPeriod} onMenuToggle={() => setNavigationOpen(true)} />
        <main className="app-main">
          <div className="app-content">{children}</div>
        </main>
      </div>
    </div>
  );
}
