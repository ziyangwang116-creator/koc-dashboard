"use client";

import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right";
  width?: number;
  render: (row: T) => ReactNode;
  exportValue?: (row: T) => unknown;
  highlight?: (row: T) => boolean;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  maxHeight = 480,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  maxHeight?: number;
}) {
  return (
    <div className="data-table-wrap" style={{ maxHeight }}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                style={{
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
