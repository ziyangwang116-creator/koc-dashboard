import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const versionsResponse = {
  data: [
    {
      version_id: 5,
      version_no: 1,
      status: "DRAFT",
      schema_version: 1,
      jpy_to_usd_rate: 0.0067,
      note: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      locked_at: null,
      lock_note: null,
      locked_by: null,
      summary: {},
    },
    {
      version_id: 9,
      version_no: 2,
      status: "LOCKED",
      schema_version: 1,
      jpy_to_usd_rate: 0.0067,
      note: "定稿",
      created_at: "2026-07-02T00:00:00Z",
      updated_at: "2026-07-02T00:00:00Z",
      locked_at: "2026-07-05T00:00:00Z",
      lock_note: "月末锁定",
      locked_by: "测试员",
      summary: {},
    },
  ],
};

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
    calculation: {
      source: "cache",
      status: "CURRENT",
      is_stale: false,
      calculation_version: 1,
      calculated_at: "2026-07-03T09:30:00Z",
      invalidated_at: null,
      stale_reason: null,
    },
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
    recalculate: vi.fn(async () => ({
      data: {
        period_month: "2026-07",
        category: "GRASSROOT",
        calculation: grassrootResponse.meta.calculation,
      },
    })),
    themeSubmissions: vi.fn(async () => ({ data: [], meta: { period_month: "2026-07", revision: "rev_0" } })),
    saveExchangeRate: vi.fn(async () => ({ data: { period_month: "2026-07", rate: 0.0067 } })),
    saveLongTermActivityCounts: vi.fn(async () => ({ data: { period_month: "2026-07", updated_count: 0 } })),
    saveCommentaryThemeSubmissions: vi.fn(async () => ({
      data: { period_month: "2026-07", updated_count: 0, revision: "rev_1" },
    })),
    createDraft: vi.fn(async () => ({ data: { id: 1, status: "DRAFT" } })),
    updateDraft: vi.fn(async () => ({ data: { id: 1, status: "DRAFT" } })),
    lockDraft: vi.fn(async () => ({ data: { id: 1, status: "LOCKED" } })),
  },
  dashboardApi: {
    saveTrafficBoost: vi.fn(async () => ({ data: { period_month: "2026-07", enabled: true } })),
  },
  authApi: { logout: vi.fn(async () => ({ data: { authenticated: false } })) },
}));

import CompensationPage from "@/app/compensation/page";
import { compensationApi, dashboardApi } from "@/lib/endpoints";

describe("CompensationPage", () => {
  it("shows creator_receivable_usd as the primary figure, not total_amount_jpy", async () => {
    renderWithQueryClient(<CompensationPage />);

    await waitFor(() => expect(screen.getByText("草根达人")).toBeInTheDocument());
    expect(screen.getAllByText("$6514.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("当前预览").length).toBeGreaterThan(0);
    expect(screen.getByText("使用缓存结果，数据已是最新")).toBeInTheDocument();
    expect(screen.getByText(/上次计算时间/)).toBeInTheDocument();
  });

  it("recalculates the selected lane and month on demand", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CompensationPage />);
    await waitFor(() => expect(screen.getByText("使用缓存结果，数据已是最新")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "重新计算本月" }));

    await waitFor(() =>
      expect(compensationApi.recalculate).toHaveBeenCalledWith("grassroot", "2026-07")
    );
  });

  it("saves the exchange rate", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CompensationPage />);
    await waitFor(() => expect(screen.getByText("草根达人")).toBeInTheDocument());

    const rateInput = screen.getByLabelText("JPY→USD 汇率");
    await user.clear(rateInput);
    await user.type(rateInput, "0.007");
    await user.click(screen.getByRole("button", { name: "保存汇率" }));

    await waitFor(() => expect(compensationApi.saveExchangeRate).toHaveBeenCalledWith("2026-07", 0.007));
  });

  it("toggles traffic boost for an applicable month", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CompensationPage />);
    await waitFor(() => expect(screen.getByText("草根达人")).toBeInTheDocument());

    const toggle = screen.getByRole("checkbox", { name: "启用流量加成（7 月专项）" });
    expect(toggle).toBeChecked();
    await user.click(toggle);

    await waitFor(() => expect(dashboardApi.saveTrafficBoost).toHaveBeenCalledWith("2026-07", false));
  });

  it("creates a draft from the current preview", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CompensationPage />);
    await waitFor(() => expect(screen.getByText("草根达人")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "基于当前预览创建结算草稿" }));
    await waitFor(() => expect(compensationApi.createDraft).toHaveBeenCalledTimes(1));
    expect(compensationApi.createDraft).toHaveBeenCalledWith(
      "grassroot",
      "2026-07",
      expect.objectContaining({ jpy_to_usd_rate: 0.0067 }),
      expect.objectContaining({ idempotencyKey: expect.any(String) })
    );
  });

  it("requires lock_note and a second confirmation before locking a draft version", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CompensationPage />);
    await waitFor(() => expect(screen.getByText("草根达人")).toBeInTheDocument());

    await user.selectOptions(screen.getAllByRole("combobox")[1], "5");
    await user.click(screen.getByRole("button", { name: "锁定该版本" }));

    const confirmLockBtn = screen.getByRole("button", { name: "确认锁定" });
    expect(confirmLockBtn).toBeDisabled();

    await user.type(screen.getByLabelText(/锁定备注/), "7月草根结算最终确认");
    expect(confirmLockBtn).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /我确认要锁定该版本/ }));
    expect(confirmLockBtn).toBeEnabled();
    await user.click(confirmLockBtn);

    await waitFor(() =>
      expect(compensationApi.lockDraft).toHaveBeenCalledWith("grassroot", 5, "7月草根结算最终确认")
    );
  });

  it("shows locked versions as read-only with no edit affordances", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CompensationPage />);
    await waitFor(() => expect(screen.getByText("草根达人")).toBeInTheDocument());

    await user.selectOptions(screen.getAllByRole("combobox")[1], "9");

    expect(await screen.findByText("已锁定的历史版本（只读，不可编辑）")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "更新该草稿" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "锁定该版本" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "基于当前预览创建结算草稿" })).not.toBeInTheDocument();
  });
});
