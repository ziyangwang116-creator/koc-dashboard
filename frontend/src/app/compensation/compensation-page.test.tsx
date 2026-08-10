import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithQueryClient } from "@/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/compensation",
}));

const periodsResponse = {
  data: [
    {
      period_month: "2026-07",
      has_posts: true,
      traffic_boost_applicable: true,
      traffic_boost_enabled: true,
      versions: { grassroot: { count: 1, has_locked: false } },
    },
  ],
};

const versionsResponse = { data: [] };

const grassrootResponse = {
  data: [
    {
      creator_key: "koc_1",
      creator_name: "草根达人",
      contract_types: ["YTB"],
      settlement_status: "可结算",
      rank: "A",
      billable_post_count: 3,
      billable_views: 100000,
      all_video_views: 120000,
      total_amount_jpy: 970000,
      creator_receivable_jpy: 972239,
      youdao_receivable_jpy: 1118075,
      creator_receivable_usd: 6514.0,
      youdao_receivable_usd: 7490.1,
      cpm: 1.83,
    },
  ],
  meta: {
    request_id: "r1",
    mode: "preview",
    period_month: "2026-07",
    jpy_to_usd_rate: 0.0067,
    traffic_boost_enabled: true,
    version: null,
    currency: {},
    summary: {
      total_amount_jpy: 970000,
      creator_receivable_usd: 6514.0,
      overall_cpm: 1.83,
    },
    pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
  },
};

vi.mock("@/lib/endpoints", () => ({
  compensationApi: {
    periods: vi.fn(async () => periodsResponse),
    versions: vi.fn(async () => versionsResponse),
    grassroot: vi.fn(async () => grassrootResponse),
    longTerm: vi.fn(async () => ({ data: [], meta: grassrootResponse.meta })),
    commentary: vi.fn(async () => ({ data: [], meta: grassrootResponse.meta })),
    themeSubmissions: vi.fn(async () => ({ data: [] })),
  },
  authApi: { logout: vi.fn(async () => ({ data: { authenticated: false } })) },
}));

import CompensationPage from "@/app/compensation/page";

describe("CompensationPage", () => {
  it("shows creator_receivable_usd as the primary figure, not total_amount_jpy", async () => {
    renderWithQueryClient(<CompensationPage />);

    await waitFor(() => expect(screen.getByText("草根达人")).toBeInTheDocument());
    expect(screen.getAllByText("$6514.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("当前预览").length).toBeGreaterThan(0);
  });
});
