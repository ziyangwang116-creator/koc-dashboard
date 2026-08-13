import { chromium, type Route } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";

const OUT_DIR = path.resolve(__dirname, "..", "e2e-screenshots");
fs.mkdirSync(OUT_DIR, { recursive: true });

const conversationId = "32ee0527-bbc5-4392-965d-bd28ef2751ed";
const charts = [
  {
    schema_version: 1,
    id: "posts",
    kind: "grouped_bar",
    title: "白黑女神 投稿数量对比",
    subtitle: "2026-06 vs 2026-07",
    category_key: "category",
    value_format: "integer",
    series: [
      { key: "baseline", label: "2026-06", color: "#64748b" },
      { key: "current", label: "2026-07", color: "#0f9b9b" },
    ],
    data: [{ category: "投稿数量", baseline: 31, current: 38, change: 7, change_rate: 0.225806, decline_over_30_percent: false }],
    warnings: [],
    source: { tool: "compare_creator_months", database_backed: true, creator_id: 1, creator_name: "白黑女神", periods: ["2026-06", "2026-07"] },
  },
  {
    schema_version: 1,
    id: "views",
    kind: "grouped_bar",
    title: "白黑女神 总播放量对比",
    subtitle: "2026-06 vs 2026-07",
    category_key: "category",
    value_format: "integer",
    series: [
      { key: "baseline", label: "2026-06", color: "#64748b" },
      { key: "current", label: "2026-07", color: "#0f9b9b" },
    ],
    data: [{ category: "总播放量", baseline: 26249, current: 77307, change: 51058, change_rate: 1.945217, decline_over_30_percent: false }],
    warnings: [],
    source: { tool: "compare_creator_months", database_backed: true, creator_id: 1, creator_name: "白黑女神", periods: ["2026-06", "2026-07"] },
  },
  {
    schema_version: 1,
    id: "subtype-posts",
    kind: "grouped_bar",
    title: "白黑女神 分类型投稿数量",
    subtitle: "2026-06 vs 2026-07",
    category_key: "category",
    value_format: "integer",
    series: [
      { key: "baseline", label: "2026-06", color: "#64748b" },
      { key: "current", label: "2026-07", color: "#0f9b9b" },
    ],
    data: [
      { category: "long", baseline: 0, current: 3, change: 3, change_rate: null, decline_over_30_percent: false },
      { category: "shorts", baseline: 1, current: 3, change: 2, change_rate: 2, decline_over_30_percent: false },
      { category: "livestream", baseline: 30, current: 32, change: 2, change_rate: 0.066667, decline_over_30_percent: false },
    ],
    warnings: [],
    source: { tool: "compare_creator_months", database_backed: true, creator_id: 1, creator_name: "白黑女神", periods: ["2026-06", "2026-07"] },
  },
  {
    schema_version: 1,
    id: "subtype-views",
    kind: "grouped_bar",
    title: "白黑女神 分类型播放量",
    subtitle: "2026-06 vs 2026-07",
    category_key: "category",
    value_format: "integer",
    series: [
      { key: "baseline", label: "2026-06", color: "#64748b" },
      { key: "current", label: "2026-07", color: "#0f9b9b" },
    ],
    data: [
      { category: "long", baseline: 0, current: 62969, change: 62969, change_rate: null, decline_over_30_percent: false },
      { category: "shorts", baseline: 1659, current: 10294, change: 8635, change_rate: 5.205546, decline_over_30_percent: false },
      { category: "livestream", baseline: 24590, current: 4044, change: -20546, change_rate: -0.835543, decline_over_30_percent: true },
    ],
    warnings: [{ level: "danger", message: "livestream播放量下降 83.6%，超过 30% 警戒线。" }],
    source: { tool: "compare_creator_months", database_backed: true, creator_id: 1, creator_name: "白黑女神", periods: ["2026-06", "2026-07"] },
  },
];

const messages = {
  data: [
    { role: "user", content: "对比白黑女神 2026-06 和 2026-07" },
    {
      role: "assistant",
      content: "## 白黑女神 6 月 vs 7 月\n\n**结论：** 总播放量增长，但直播播放量明显下降。\n\n| 指标 | 2026-06 | 2026-07 | 变化 |\n|---|---:|---:|---:|\n| 投稿数 | 31 | 38 | +7 |\n| 总播放量 | 26,249 | 77,307 | +51,058 |\n\n- long 播放量新增 62,969。\n- livestream 播放量下降超过 30%。",
      visualizations: charts,
    },
  ],
};

async function fulfill(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

async function main() {
  const server = spawn("npm", ["run", "start", "--", "-p", "3101"], {
    cwd: path.resolve(__dirname, ".."),
    shell: true,
    stdio: "pipe",
  });
  await new Promise<void>((resolve) => {
    let done = false;
    server.stdout?.on("data", (chunk) => {
      if (!done && chunk.toString().includes("Ready")) {
        done = true;
        resolve();
      }
    });
    setTimeout(() => {
      if (!done) resolve();
    }, 15000);
  });

  const browser = await chromium.launch();
  for (const [width, height] of [[1440, 900], [390, 844]]) {
    const context = await browser.newContext({ viewport: { width, height }, acceptDownloads: true });
    await context.addInitScript((id) => localStorage.setItem("koc-agent-conversation-id", id), conversationId);
    const page = await context.newPage();
    await page.route("**/api/agent/status", (route) => fulfill(route, { data: { configured: true, provider: "deepseek", provider_label: "DeepSeek", model: "deepseek-v4-pro", read_only: true } }));
    await page.route(`**/api/agent/conversations/${conversationId}/messages`, (route) => fulfill(route, messages));
    await page.route("**/api/auth/logout", (route) => fulfill(route, { data: { authenticated: false } }));
    await page.goto("http://localhost:3101/agent", { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "白黑女神 6 月 vs 7 月" }).waitFor();
    const tableCount = await page.locator(".agent-markdown table").count();
    const chartCount = await page.locator(".agent-chart-canvas").count();
    const warningCount = await page.getByText(/下降 83.6%/).count();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    if (tableCount !== 1 || chartCount !== 4 || warningCount < 1 || overflow) {
      throw new Error(JSON.stringify({ width, tableCount, chartCount, warningCount, overflow }));
    }
    if (width === 1440) {
      const downloadPromise = page.waitForEvent("download");
      await page.getByRole("button", { name: "下载 白黑女神 投稿数量对比 PNG" }).click();
      const download = await downloadPromise;
      const downloadedPath = path.join(OUT_DIR, "agent-chart-download.png");
      await download.saveAs(downloadedPath);
      if (fs.statSync(downloadedPath).size < 1000) throw new Error("PNG download is empty");
    }
    await page.screenshot({ path: path.join(OUT_DIR, `agent-${width}x${height}.png`), fullPage: false });
    await context.close();
  }
  await browser.close();
  server.kill();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
