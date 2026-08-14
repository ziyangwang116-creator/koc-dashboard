import { chromium, type Route } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";
import { execFileSync, spawn } from "node:child_process";

const OUT_DIR = path.resolve(__dirname, "..", "e2e-screenshots");
fs.mkdirSync(OUT_DIR, { recursive: true });

const filterOptions = {
  data: {
    creators: [
      { creator_key: "koc_1", creator_label: "示例达人一" },
      { creator_key: "koc_2", creator_label: "示例达人二" },
    ],
    creator_categories: ["GRASSROOT", "LONG_TERM", "COMMENTARY"],
    source_platforms: ["YouTube", "TikTok"],
    content_types: ["long", "livestream", "YTB shorts", "tiktok"],
    available_months: ["2026-06", "2026-07"],
    available_weeks: [{ week_start: "2026-07-28", week_end: "2026-08-03" }],
  },
  meta: { request_id: "r1" },
};

const summary = {
  data: Array.from({ length: 8 }, (_, i) => ({
    creator_key: `koc_${i}`,
    user_id: `koc_${i}`,
    creator_label: `示例达人${i + 1}`,
    creator_category: ["GRASSROOT", "LONG_TERM", "COMMENTARY"][i % 3],
    contract_types: ["YTB"],
    follower_count: 10000 * (i + 1),
    source_platforms: ["YouTube"],
    post_count: 5 + i,
    views: 100000 * (i + 1),
    total_views: 100000 * (i + 1),
    average_views: 20000,
    max_views: 50000,
    total_likes: 1000,
    total_comments: 100,
    total_interactions: 1100,
    engagement_rate: 0.012,
    earliest_date: "2026-07-01",
    latest_date: "2026-07-30",
  })),
  meta: { request_id: "r1", pagination: { page: 1, page_size: 20, total_items: 8, total_pages: 1 } },
};

const posts = {
  data: Array.from({ length: 12 }, (_, i) => ({
    creator_key: `koc_${i % 3}`,
    user_id: `koc_${i % 3}`,
    koc_name: `示例达人${(i % 3) + 1}`,
    creator_category: "GRASSROOT",
    contract_types: ["YTB"],
    source_platform: i % 2 === 0 ? "YouTube" : "TikTok",
    content_type: "long",
    title: `示例投稿标题 ${i + 1}`,
    url: `https://example.com/${i}`,
    publish_date: `2026-07-${String((i % 28) + 1).padStart(2, "0")}`,
    views: 20000 + i * 1000,
    likes: 500,
    comment: 20,
    matched: true,
    profile_status: "MATCHED",
    is_cross_industry: false,
    compensation_eligible: true,
  })),
  meta: { request_id: "r1", pagination: { page: 1, page_size: 50, total_items: 12, total_pages: 1 } },
};

const daily = {
  data: Array.from({ length: 31 }, (_, i) => ({
    publish_date: `2026-07-${String(i + 1).padStart(2, "0")}`,
    post_count: 8 + (i % 5),
    total_views: 240000 + Math.round(Math.sin(i / 3) * 70000) + i * 8500,
    total_interactions: 4200 + i * 120,
  })),
  meta: { request_id: "r1" },
};

function rankingResponse(type: string, video: boolean) {
  return {
    data: {
      ranking_type: type,
      items: Array.from({ length: 5 }, (_, i) =>
        video
          ? {
              rank: i + 1,
              creator_key: `koc_${i}`,
              creator_label: `示例达人${i + 1}`,
              title: `热门视频 ${i + 1}`,
              url: `https://example.com/v${i}`,
              publish_date: "2026-07-10",
              views: 500000 - i * 10000,
            }
          : {
              rank: i + 1,
              creator_key: `koc_${i}`,
              creator_label: `示例达人${i + 1}`,
              creator_category: "GRASSROOT",
              total_views: 500000 - i * 10000,
              post_count: 10 - i,
            }
      ),
    },
    meta: { request_id: "r1" },
  };
}

const importBatches = {
  data: [
    {
      batch_id: 12,
      mode: "REPLACE_MONTHS",
      period_months: ["2026-07"],
      source_files: ["7月投稿数据.xlsx"],
      input_count: 320,
      saved_count: 300,
      removed_count: 20,
      created_at: "2026-08-01T09:00:00",
    },
    {
      batch_id: 11,
      mode: "REPLACE_MONTHS",
      period_months: ["2026-06"],
      source_files: ["6月投稿数据.xlsx"],
      input_count: 286,
      saved_count: 286,
      removed_count: 12,
      created_at: "2026-07-05T09:00:00",
    },
  ],
  meta: { request_id: "r1" },
};

const contractTypes = { data: { contract_types: ["YTB", "TT", "YTB shorts"] }, meta: { request_id: "r1" } };

const creatorsList = {
  data: Array.from({ length: 10 }, (_, i) => ({
    id: i + 1,
    user_id: `koc_${i}`,
    koc_name: `示例达人${i + 1}`,
    creator_category: ["GRASSROOT", "LONG_TERM", "COMMENTARY"][i % 3],
    contract_types: ["YTB"],
    contract_start_date: "2026-01-01",
    contract_end_date: "2026-12-31",
    homepage_url: null,
    follower_count: 10000 * (i + 1),
    youtube_user_id: `yt_${i}`,
    youtube_follower_count: 5000,
    tiktok_user_id: null,
    tiktok_follower_count: null,
    follower_source: "YOUTUBE_API",
    follower_sync_status: i % 4 === 0 ? "FAILED" : "SUCCESS",
    settlement_eligible: true,
    active: i % 5 !== 0,
    note: null,
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-08-01T00:00:00",
  })),
  meta: { request_id: "r1", pagination: { page: 1, page_size: 20, total_items: 42, total_pages: 3 } },
};

const creatorDetail = {
  data: {
    ...creatorsList.data[0],
    follower_error_code: null,
    follower_sync_error: null,
    follower_source_url: null,
    follower_profile_url: null,
    contract_periods: [
      {
        id: 1,
        effective_date: "2026-01-01",
        creator_category: "GRASSROOT",
        contract_types: ["YTB"],
        contract_start_date: "2026-01-01",
        contract_end_date: "2026-06-30",
        created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:00",
      },
    ],
  },
  meta: { request_id: "r1" },
};

const compPeriods = {
  data: [
    {
      period_month: "2026-07",
      has_posts: true,
      traffic_boost_applicable: true,
      traffic_boost_enabled: true,
      versions: {
        grassroot: { count: 2, has_locked: true },
        long_term: { count: 1, has_locked: false },
        commentary: { count: 1, has_locked: true },
      },
    },
  ],
  meta: { request_id: "r1" },
};

const compVersions = {
  data: [
    {
      version_id: 12,
      version_no: 2,
      status: "LOCKED",
      schema_version: 1,
      jpy_to_usd_rate: 0.0067,
      note: null,
      created_at: "2026-08-01T09:00:00",
      updated_at: "2026-08-02T10:30:00",
      locked_at: "2026-08-02T10:30:00",
      summary: {},
    },
    {
      version_id: 8,
      version_no: 1,
      status: "DRAFT",
      schema_version: 1,
      jpy_to_usd_rate: 0.0067,
      note: "初稿",
      created_at: "2026-07-31T18:00:00",
      updated_at: "2026-07-31T18:00:00",
      locked_at: null,
      summary: {},
    },
  ],
  meta: { request_id: "r1" },
};

function compMeta(mode: string) {
  return {
    request_id: "r1",
    mode,
    period_month: "2026-07",
    jpy_to_usd_rate: 0.0067,
    traffic_boost_enabled: true,
    version: mode === "preview" ? null : { version_id: 12, version_no: 2, status: mode === "frozen" ? "LOCKED" : "DRAFT" },
    currency: { base: "JPY" },
    summary: {
      total_amount_jpy: 970000,
      creator_receivable_jpy: 972239,
      youdao_receivable_jpy: 1118075,
      creator_receivable_usd: 6514.0,
      youdao_receivable_usd: 7490.1,
      settled_views: 3500000,
      total_video_views: 4100000,
      overall_cpm: 1.83,
    },
    pagination: { page: 1, page_size: 20, total_items: 3, total_pages: 1 },
  };
}

const grassroot = {
  data: Array.from({ length: 6 }, (_, i) => ({
    creator_key: `koc_${i}`,
    creator_name: `草根达人${i + 1}`,
    contract_types: ["YTB"],
    settlement_status: i === 0 ? "未达标" : "可结算",
    rank: "A+",
    billable_post_count: 10,
    billable_views: 3500000,
    all_video_views: 4100000,
    total_amount_jpy: i === 0 ? 0 : 970000,
    creator_receivable_jpy: i === 0 ? 0 : 972239,
    youdao_receivable_jpy: i === 0 ? 0 : 1118075,
    creator_receivable_usd: i === 0 ? 0 : 6514.0,
    youdao_receivable_usd: i === 0 ? 0 : 7490.1,
    cpm: 1.83,
  })),
  meta: compMeta("preview"),
};

const longTerm = {
  data: Array.from({ length: 4 }, (_, i) => ({
    record_id: 80 + i,
    creator_key: `koc_lt_${i}`,
    creator_name: `长包达人${i + 1}`,
    contract_types: ["长包"],
    settlement_status: "可结算",
    rank: "B+",
    followers: 240000,
    monthly_new_post_views: 1800000,
    monthly_activity_count: 3,
    total_amount_jpy: 500000,
    creator_receivable_jpy: 502239,
    youdao_receivable_jpy: 577575,
    creator_receivable_usd: 3365.0,
    youdao_receivable_usd: 3869.75,
    cpm: 2.21,
  })),
  meta: compMeta("preview"),
};

const commentary = {
  data: Array.from({ length: 4 }, (_, i) => ({
    creator_id: 500 + i,
    creator_key: `koc_cm_${i}`,
    creator_name: `解说达人${i + 1}`,
    contract_types: ["YTB长+TT短"],
    settlement_status: "可结算",
    designated_theme_count: 2,
    designated_theme_reward_jpy: 30000,
    all_paid_views: 3100000,
    total_jpy_tax_incl: 930000,
    creator_receivable_jpy: 932239,
    youdao_receivable_jpy: 1072075,
    creator_receivable_usd: 6246.0,
    youdao_receivable_usd: 7182.9,
    cpm: 2.32,
  })),
  meta: compMeta("preview"),
};

const themeSubmissions = {
  data: [
    {
      id: 3001,
      period_month: "2026-07",
      creator_id: 501,
      theme_code: "SUMMER_A",
      theme_name: "夏季主题A",
      content_format: "LONG",
      urls: ["https://youtube.example/watch?v=abc"],
      submitted_date: "2026-07-20",
      review_status: "APPROVED",
      note: null,
      theme_reward_eligible: true,
      matched_post_urls: ["https://youtube.example/watch?v=abc"],
      billing_excluded_url_count: 1,
      billing_excluded: true,
    },
    {
      id: 3002,
      period_month: "2026-07",
      creator_id: 502,
      theme_code: "SUMMER_B",
      theme_name: "夏季主题B",
      content_format: "SHORT",
      urls: ["https://a", "https://b", "https://c"],
      submitted_date: "2026-07-21",
      review_status: "PENDING",
      note: "待复核",
      theme_reward_eligible: false,
      matched_post_urls: [],
      billing_excluded_url_count: 0,
      billing_excluded: false,
    },
  ],
  meta: { request_id: "r1" },
};

const routes: Record<string, unknown> = {
  "**/api/dashboard/filter-options": filterOptions,
  "**/api/dashboard/summary*": summary,
  "**/api/dashboard/posts*": posts,
  "**/api/dashboard/daily*": daily,
  "**/api/dashboard/import-batches*": importBatches,
  "**/api/meta/contract-types": contractTypes,
  "**/api/creators/1": creatorDetail,
  "**/api/creators*": creatorsList,
  "**/api/compensation/periods*": compPeriods,
  "**/api/compensation/versions*": compVersions,
  "**/api/compensation/grassroot*": grassroot,
  "**/api/compensation/long-term*": longTerm,
  "**/api/compensation/commentary/theme-submissions*": themeSubmissions,
  "**/api/compensation/commentary*": commentary,
};

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

async function main() {
  const nextCli = path.resolve(__dirname, "..", "node_modules", "next", "dist", "bin", "next");
  const server = spawn(process.execPath, [nextCli, "start", "-p", "3100"], {
    cwd: path.resolve(__dirname, ".."),
    shell: false,
    stdio: "pipe",
  });

  await new Promise<void>((resolve, reject) => {
    let resolved = false;
    server.stdout?.on("data", (chunk) => {
      const text = chunk.toString();
      if (text.includes("Ready") && !resolved) {
        resolved = true;
        resolve();
      }
    });
    server.stderr?.on("data", (chunk) => process.stderr.write(chunk));
    setTimeout(() => {
      if (!resolved) {
        resolved = true;
        resolve();
      }
    }, 15000);
    server.on("error", reject);
  });

  const browser = await chromium.launch();

  const rankingHandler = (route: Route) => {
    const url = route.request().url();
    const type = new URL(url).searchParams.get("ranking_type") ?? "creator_views_top10";
    const video = type.startsWith("video_");
    fulfillJson(route, rankingResponse(type, video));
  };

  async function newPage(width: number, height: number) {
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    for (const [pattern, body] of Object.entries(routes)) {
      await page.route(pattern, (route) => fulfillJson(route, body));
    }
    await page.route("**/api/dashboard/rankings*", rankingHandler);
    await page.route("**/api/dashboard/comparison", (route) =>
      fulfillJson(route, { data: { dimension: "creator", metric: "total_views", series: [] } })
    );
    await page.route("**/api/auth/login", (route) =>
      fulfillJson(route, { data: { authenticated: true } })
    );
    await page.route("**/api/auth/logout", (route) =>
      fulfillJson(route, { data: { authenticated: false } })
    );
    return page;
  }

  const shots: [string, string, number, number][] = [
    ["login", "/login", 1440, 900],
    ["login", "/login", 390, 844],
    ["dashboard", "/dashboard", 1440, 900],
    ["dashboard", "/dashboard", 390, 844],
    ["creators", "/creators", 1440, 900],
    ["creators", "/creators", 390, 844],
    ["compensation", "/compensation", 1440, 900],
    ["compensation", "/compensation", 390, 844],
  ];

  try {
    for (const [name, route, width, height] of shots) {
      const page = await newPage(width, height);
      await page.goto(`http://localhost:3100${route}`, { waitUntil: "networkidle" });
      await page.waitForTimeout(600);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth
      );
      if (overflow) throw new Error(`${name} ${width}x${height} has horizontal page overflow`);
      const filename = path.join(OUT_DIR, `${name}-${width}x${height}.png`);
      await page.screenshot({ path: filename, fullPage: false });
      console.log("saved", filename);
      await page.context().close();
    }
  } finally {
    await browser.close();
    if (server.pid && process.platform === "win32") {
      try {
        execFileSync("taskkill", ["/pid", String(server.pid), "/T", "/F"], {
          stdio: "ignore",
        });
      } catch {
        // The process may already have exited normally.
      }
    } else {
      server.kill("SIGTERM");
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
