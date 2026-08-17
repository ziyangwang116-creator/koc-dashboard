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
      read_only: false,
      write_enabled: true,
      writes_require_confirmation: true,
    },
  })),
  createConversation: vi.fn(async () => ({
    data: { conversation_id: "32ee0527-bbc5-4392-965d-bd28ef2751ed" },
  })),
  messages: vi.fn(async () => ({ data: [] })),
  sendMessage: vi.fn(async (_conversationId: string, _message: string) => ({
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
      pending_actions: [] as Array<{
        action_id: string;
        tool_name: string;
        preview: Record<string, unknown>;
        expires_in_seconds: number;
      }>,
    },
  })),
  confirmAction: vi.fn(async () => ({
    data: { status: "executed", action_id: "action-1", result: { status: "ok" } },
  })),
  previewImport: vi.fn(async () => ({
    data: {
      preview_token: "preview-agent-1",
      input_row_count: 12,
      matched_row_count: 12,
      period_months: ["2026-07"],
      cross_industry_flagged_count: 0,
      column_warnings: [],
      additions: { count: 12, rows: [] },
      updates: { count: 0, rows: [] },
      removals: { count: 0, rows: [] },
      unmatched_creators: { count: 0, rows: [] },
      date_anomalies: { count: 0, rows: [] },
    },
  })),
}));

vi.mock("@/lib/endpoints", () => ({
  agentApi: {
    status: mocks.status,
    createConversation: mocks.createConversation,
    messages: mocks.messages,
    sendMessage: mocks.sendMessage,
    confirmAction: mocks.confirmAction,
  },
  importsApi: {
    preview: mocks.previewImport,
  },
  authApi: { logout: vi.fn(async () => ({ data: { authenticated: false } })) },
}));

import AgentPage from "@/app/agent/page";

describe("AgentPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("renders provider status, confirmed-write scope, and suggested questions", async () => {
    renderWithQueryClient(<AgentPage />);

    expect(screen.getByRole("heading", { name: "运营 Agent" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("DeepSeek · deepseek-chat")).toBeInTheDocument());
    expect(screen.getByText("可执行，写入需确认")).toBeInTheDocument();
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

  it("shows a write preview and requires confirmation before execution", async () => {
    mocks.sendMessage.mockResolvedValueOnce({
      data: {
        conversation_id: "32ee0527-bbc5-4392-965d-bd28ef2751ed",
        answer: "请确认写入。",
        tool_calls: [],
        visualizations: [],
        pending_actions: [
          {
            action_id: "action-1",
            tool_name: "save_exchange_rate",
            preview: { period_month: "2026-07", jpy_to_usd_rate: 0.0062 },
            expires_in_seconds: 600,
          },
        ],
      },
    });
    const user = userEvent.setup();
    renderWithQueryClient(<AgentPage />);
    await screen.findByText("DeepSeek · deepseek-chat");

    await user.type(screen.getByLabelText("向运营 Agent 提问"), "保存 7 月汇率");
    await user.click(screen.getByRole("button", { name: "发送问题" }));

    expect(await screen.findByText("待确认操作")).toBeInTheDocument();
    expect(screen.getByText("save_exchange_rate")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认执行" }));
    await waitFor(() =>
      expect(mocks.confirmAction).toHaveBeenCalledWith(
        "32ee0527-bbc5-4392-965d-bd28ef2751ed",
        "action-1",
        true,
      ),
    );
  });

  it("uploads an Excel preview before asking the Agent to import posts", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<AgentPage />);
    await screen.findByText("DeepSeek · deepseek-chat");

    const file = new File(["excel"], "2026-07.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await user.upload(
      screen.getByLabelText("上传投稿 Excel", { selector: "input" }),
      file,
    );
    expect(screen.getByText("2026-07.xlsx")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "发送问题" }));

    await waitFor(() => expect(mocks.previewImport).toHaveBeenCalledWith([file]));
    await waitFor(() =>
      expect(mocks.sendMessage).toHaveBeenCalledWith(
        "32ee0527-bbc5-4392-965d-bd28ef2751ed",
        expect.stringContaining("preview_token=preview-agent-1"),
      ),
    );
    expect(mocks.sendMessage.mock.calls.at(-1)?.[1]).toContain("补充导入/更新");
  });
});
