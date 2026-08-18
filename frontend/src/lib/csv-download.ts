import type { Column } from "@/components/DataTable";

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";

  let text: string;
  if (Array.isArray(value)) {
    text = value.map((item) => String(item)).join("、");
  } else if (value instanceof Date) {
    text = value.toISOString();
  } else if (typeof value === "object") {
    text = JSON.stringify(value);
  } else if (typeof value === "boolean") {
    text = value ? "是" : "否";
  } else {
    text = String(value);
  }

  // Prevent Excel and other spreadsheet programs from evaluating imported cells.
  if (typeof value === "string" && /^[=+\-@]/.test(text)) {
    text = `'${text}`;
  }

  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function safeFilename(filename: string): string {
  const normalized = filename.replace(/[\\/:*?"<>|]+/g, "-").trim();
  return `${normalized || "数据导出"}.csv`;
}

export function buildTableCsv<T>(columns: Column<T>[], rows: T[]): string {
  const header = columns.map((column) => csvCell(column.header)).join(",");
  const body = rows.map((row) =>
    columns
      .map((column) => {
        const value = column.exportValue
          ? column.exportValue(row)
          : (row as Record<string, unknown>)[column.key];
        return csvCell(value);
      })
      .join(",")
  );
  return `\uFEFF${[header, ...body].join("\r\n")}`;
}

export function downloadTableCsv<T>(filename: string, columns: Column<T>[], rows: T[]): void {
  const blob = new Blob([buildTableCsv(columns, rows)], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = safeFilename(filename);
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
