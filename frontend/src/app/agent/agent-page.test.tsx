import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQueryClient } from "@/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/agent",
}));

const mocks = vi.hoisted(() => ({
  status: vi.fn(async () => ({
    data: {
      configured: true,
      provider: "deepseek",
      provider_label: "DeepSeek",
      model: "deepseek-chat",
      read_only: true,
    },
  })),
  createConversation: vi.fn(async () => ({
    data: { conversation_id: "32ee0527-bbc5-4392-965d-bd28ef2751ed" },
  })),
  messages: vi.fn(async () => ({ data: [] })),
  sendMessage: vi.fn(async () => ({
    data: {
      conversation_id: "32ee0527-bbc5-4392-965d-bd28ef2751ed",
      answer: "## 7 月分析\n\n**结论：** 投稿增长。\n\n| 指标 | 数值 |\n|---|---:|\n| 投稿 | 3021 |",
      tool_calls: [
        {
          tool_name: "audit_month_data",
          summary: { status: "ok", post_count: 3021 },
          duration_ms: 12,
        },
      ],
      visualizations: [
        {
          schema_version: 1,
          id: "creator-1-posts",
          kind: "grouped_bar",
          title: "白黑女神 投稿数量对比",
          subtitle: "2026-06 vs 2026-07",
          category_key: "category",
          value_format: "integer",
          series: [
            { key: "baseline", label: "2026-06", color: "#64748b" },
            { key: "current", label: "2026-07", color: "#0f9b9b" },
          ],
          data: [
            { category: "投稿数量", baseline: 31, current: 38, change: 7, change_rate: 0.225806, decline_over_30_percent: false },
          ],
          warnings: [],
          source: { tool: "compare_creator_months", database_backed: true, creator_id: 1, creator_name: "白黑女神", periods: ["2026-06", "2026-07"] },
        },
      ],
    },
  })),
}));

vi.mock("@/lib/endpoints", () => ({
  agentApi: {
    status: mocks.status,
    createConversation: mocks.createConversation,
    messages: mocks.messages,
    sendMessage: mocks.sendMessage,
  },
  authApi: { logout: vi.fn(async () => ({ data: { authenticated: false } })) },
}));

import AgentPage from "@/app/agent/page";

describe("AgentPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("renders provider status, read-only scope, and suggested questions", async () => {
    renderWithQueryClient(<AgentPage />);

    expect(screen.getByRole("heading", { name: "运营 Agent" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("DeepSeek · deepseek-chat")).toBeInTheDocument());
    expect(screen.getByText("只读模式")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "分析 2026-07 整体运营表现" })).toBeEnabled();
  });

  it("creates a conversation, sends a message, and shows tool evidence", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<AgentPage />);
    await screen.findByText("DeepSeek · deepseek-chat");

    const input = screen.getByLabelText("向运营 Agent 提问");
    expect(input).toBeEnabled();
    await user.type(input, "审计 2026-07 数据");
    await user.click(screen.getByRole("button", { name: "发送问题" }));

    await waitFor(() =>
      expect(mocks.sendMessage).toHaveBeenCalledWith(
        "32ee0527-bbc5-4392-965d-bd28ef2751ed",
        "审计 2026-07 数据"
      )
    );
    expect(await screen.findByRole("heading", { name: "7 月分析" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("白黑女神 投稿数量对比")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载 白黑女神 投稿数量对比 PNG" })).toBeInTheDocument();
    await user.click(screen.getByText("查询依据"));
    expect(screen.getByText("audit_month_data")).toBeInTheDocument();
  });
});
