"use client";

import { useRef, useState } from "react";
import { toPng } from "html-to-image";
import { AlertTriangle, Download, Loader2 } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AgentVisualization as AgentVisualizationPayload } from "@/lib/types";

const NUMBER_FORMAT = new Intl.NumberFormat("zh-CN");

function formatRate(value: number | null): string {
  if (value === null) return "基期为 0";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(1)}%`;
}

function downloadName(value: string): string {
  const normalized = value.replace(/[\\/:*?"<>|]+/g, "-").trim();
  return `${normalized || "Agent图表"}.png`;
}

export function AgentVisualization({ chart }: { chart: AgentVisualizationPayload }) {
  const exportRef = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");

  async function handleDownload() {
    if (!exportRef.current || exporting) return;
    setExporting(true);
    setExportError("");
    try {
      await document.fonts?.ready;
      const dataUrl = await toPng(exportRef.current, {
        cacheBust: true,
        pixelRatio: 2,
        backgroundColor: "#ffffff",
        filter: (node) =>
          !(node instanceof HTMLElement && node.dataset.exportIgnore === "true"),
      });
      const link = document.createElement("a");
      link.download = downloadName(chart.title);
      link.href = dataUrl;
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch {
      setExportError("PNG 导出失败，请稍后重试。")
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="agent-visualization-shell">
      <div ref={exportRef} className="agent-visualization-export">
        <header className="agent-visualization-header">
          <div>
            <h3>{chart.title}</h3>
            <p>{chart.subtitle} · 数据库实时工具结果</p>
          </div>
          <button
            type="button"
            className="agent-chart-download"
            aria-label={`下载 ${chart.title} PNG`}
            title="下载 PNG"
            onClick={handleDownload}
            disabled={exporting}
            data-export-ignore="true"
          >
            {exporting ? <Loader2 className="spin" size={16} /> : <Download size={16} />}
          </button>
        </header>

        <div className="agent-chart-canvas" role="img" aria-label={chart.title}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart.data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5eaee" vertical={false} />
              <XAxis dataKey="category" tick={{ fontSize: 12, fill: "#52606d" }} />
              <YAxis
                width={72}
                tick={{ fontSize: 11, fill: "#52606d" }}
                tickFormatter={(value) => NUMBER_FORMAT.format(Number(value))}
              />
              <Tooltip formatter={(value) => NUMBER_FORMAT.format(Number(value))} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {chart.series.map((series) => (
                <Bar
                  key={series.key}
                  dataKey={series.key}
                  name={series.label}
                  fill={series.color}
                  radius={[3, 3, 0, 0]}
                  maxBarSize={56}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="agent-chart-changes">
          {chart.data.map((row) => (
            <div
              key={row.category}
              className={row.decline_over_30_percent ? "agent-chart-change-danger" : ""}
            >
              <strong>{row.category}</strong>
              <span>{NUMBER_FORMAT.format(row.baseline)} → {NUMBER_FORMAT.format(row.current)}</span>
              <span>{row.change > 0 ? "+" : ""}{NUMBER_FORMAT.format(row.change)}</span>
              <span>{formatRate(row.change_rate)}</span>
            </div>
          ))}
        </div>

        {chart.warnings.length > 0 && (
          <div className="agent-chart-warnings">
            {chart.warnings.map((warning, index) => (
              <div key={`${warning.message}-${index}`}>
                <AlertTriangle size={14} />
                <span>{warning.message}</span>
              </div>
            ))}
          </div>
        )}

        <footer className="agent-chart-source">
          来源：{chart.source.tool} · 数据库结果 · {chart.source.creator_name}
        </footer>
      </div>
      {exportError && <div className="agent-chart-export-error">{exportError}</div>}
    </section>
  );
}
