"use client";

import { AlertTriangle, Inbox, Loader2, Lock } from "lucide-react";
import type { ReactNode } from "react";

export function LoadingState({ label = "加载中..." }: { label?: string }) {
  return (
    <div style={styles.wrap} role="status" aria-live="polite">
      <Loader2 className="spin" size={20} color="var(--color-primary)" />
      <span style={styles.text}>{label}</span>
    </div>
  );
}

export function EmptyState({ label = "暂无数据" }: { label?: string }) {
  return (
    <div style={styles.wrap}>
      <Inbox size={20} color="var(--color-text-muted)" />
      <span style={styles.text}>{label}</span>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div style={{ ...styles.wrap, background: "var(--color-danger-bg)", borderRadius: "var(--radius)" }}>
      <AlertTriangle size={20} color="var(--color-danger)" />
      <span style={{ ...styles.text, color: "var(--color-danger)" }}>{message}</span>
    </div>
  );
}

export function UnauthorizedState() {
  return (
    <div style={{ ...styles.wrap, background: "var(--color-warning-bg)", borderRadius: "var(--radius)" }}>
      <Lock size={20} color="var(--color-warning)" />
      <span style={{ ...styles.text, color: "var(--color-warning)" }}>登录已过期，请重新登录。</span>
    </div>
  );
}

export function StateShell({
  isLoading,
  isError,
  isUnauthorized,
  isEmpty,
  errorMessage,
  loadingLabel,
  emptyLabel,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  isUnauthorized?: boolean;
  isEmpty: boolean;
  errorMessage?: string;
  loadingLabel?: string;
  emptyLabel?: string;
  children: ReactNode;
}) {
  if (isUnauthorized) return <UnauthorizedState />;
  if (isLoading) return <LoadingState label={loadingLabel} />;
  if (isError) return <ErrorState message={errorMessage ?? "加载失败，请稍后重试。"} />;
  if (isEmpty) return <EmptyState label={emptyLabel} />;
  return <>{children}</>;
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    padding: "32px 16px",
    color: "var(--color-text-muted)",
  },
  text: { fontSize: 13 },
};
