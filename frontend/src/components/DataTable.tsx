"use client";

import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right";
  width?: number;
  render: (row: T) => ReactNode;
  highlight?: (row: T) => boolean;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
}) {
  return (
    <div style={{ overflow: "auto", maxHeight: 480, border: "1px solid var(--color-border)", borderRadius: "var(--radius)" }}>
      <table>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                style={{
                  ...thStyle,
                  textAlign: col.align === "right" ? "right" : "left",
                  width: col.width,
                  minWidth: col.width,
                }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((col) => {
                const highlighted = col.highlight?.(row);
                return (
                  <td
                    key={col.key}
                    style={{
                      ...tdStyle,
                      textAlign: col.align === "right" ? "right" : "left",
                      background: highlighted ? "var(--color-danger-bg)" : undefined,
                      color: highlighted ? "var(--color-danger)" : undefined,
                      fontWeight: highlighted ? 600 : undefined,
                    }}
                  >
                    {col.render(row)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  position: "sticky",
  top: 0,
  background: "var(--color-surface)",
  borderBottom: "2px solid var(--color-border)",
  padding: "8px 10px",
  fontSize: 12.5,
  color: "var(--color-text-muted)",
  whiteSpace: "nowrap",
  zIndex: 1,
};

const tdStyle: React.CSSProperties = {
  padding: "7px 10px",
  fontSize: 13,
  borderBottom: "1px solid var(--color-border)",
  whiteSpace: "nowrap",
};
