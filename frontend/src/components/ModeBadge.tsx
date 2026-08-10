import type { CompensationMode } from "@/lib/types";

const CONFIG: Record<CompensationMode, { label: string; bg: string; fg: string; border: string }> = {
  preview: {
    label: "当前预览",
    bg: "#eef2f5",
    fg: "#52606d",
    border: "1px dashed #9aa5b1",
  },
  saved_draft: {
    label: "已保存草稿",
    bg: "var(--color-warning-bg)",
    fg: "var(--color-warning)",
    border: "1px solid var(--color-warning)",
  },
  frozen: {
    label: "已锁定 · 官方定稿",
    bg: "var(--color-primary-bg)",
    fg: "var(--color-primary-dark)",
    border: "1px solid var(--color-primary)",
  },
};

export function ModeBadge({ mode }: { mode: CompensationMode }) {
  const c = CONFIG[mode];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "3px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        background: c.bg,
        color: c.fg,
        border: c.border,
      }}
    >
      {c.label}
    </span>
  );
}
