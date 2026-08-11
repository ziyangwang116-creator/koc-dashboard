"use client";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell({
  children,
  currentPeriod,
}: {
  children: React.ReactNode;
  currentPeriod?: string;
}) {
  return (
    <div className="app-shell">
      <Sidebar />
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <TopBar currentPeriod={currentPeriod} />
        <main style={{ flex: 1, minWidth: 0, padding: 16, overflowX: "auto" }}>{children}</main>
      </div>
    </div>
  );
}
