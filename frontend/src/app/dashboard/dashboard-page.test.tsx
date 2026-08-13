import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithQueryClient } from "@/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/dashboard",
}));

const filterOptions = {
  data: {
    creators: [{ creator_key: "koc_1", creator_label: "达人一" }],
    creator_categories: ["GRASSROOT"],
    source_platforms: ["YouTube"],
    content_types: ["long"],
    available_months: ["2026-07"],
    available_weeks: [{ week_start: "2026-07-28", week_end: "2026-08-03" }],
  },
};

const summary = {
  data: [
    {
      creator_key: "koc_1",
      user_id: "koc_1",
      creator_label: "达人一",
      creator_category: "GRASSROOT",
      contract_types: ["YTB"],
      follower_count: 1000,
      source_platforms: ["YouTube"],
      post_count: 5,
      views: 10000,
      total_views: 10000,
      average_views: 2000,
      max_views: 5000,
      total_likes: 100,
      total_comments: 10,
      total_interactions: 110,
      engagement_rate: 0.011,
      earliest_date: "2026-07-01",
      latest_date: "2026-07-30",
    },
  ],
  meta: { request_id: "r1", pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 } },
};

const posts = { data: [], meta: { request_id: "r1", pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 1 } } };
const daily = { data: [{ publish_date: "2026-07-01", post_count: 1, total_views: 10000, total_interactions: 110 }] };
const rankings = { data: { ranking_type: "creator_views_top10", items: [] } };
const importBatches = { data: [] };

vi.mock("@/lib/endpoints", () => ({
  dashboardApi: {
    filterOptions: vi.fn(async () => filterOptions),
    summary: vi.fn(async () => summary),
    daily: vi.fn(async () => daily),
    posts: vi.fn(async () => posts),
    rankings: vi.fn(async () => rankings),
    importBatches: vi.fn(async () => importBatches),
    comparison: vi.fn(async () => ({ data: { dimension: "creator", metric: "total_views", series: [] } })),
  },
  authApi: { logout: vi.fn(async () => ({ data: { authenticated: false } })) },
}));

import DashboardPage from "@/app/dashboard/page";
import { dashboardApi } from "@/lib/endpoints";

describe("DashboardPage", () => {
  it("renders filter options and summary rows once data resolves", async () => {
    renderWithQueryClient(<DashboardPage />);

    expect(screen.getByRole("combobox", { name: "播放量口径" })).toHaveValue("original");
    await waitFor(() =>
      expect(dashboardApi.summary).toHaveBeenCalledWith(
        expect.objectContaining({ traffic_boost_mode: "original" })
      )
    );

    await waitFor(() => expect(screen.getByText("达人一")).toBeInTheDocument());
    expect(screen.getByText("数据看板")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("草根").length).toBeGreaterThan(0));
    expect(screen.getByText("包含异业活动数据")).toBeInTheDocument();
  });
});
