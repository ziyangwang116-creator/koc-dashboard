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
      answer: "7 月共有 3021 条投稿。",
      tool_calls: [
        {
          tool_name: "audit_month_data",
          summary: { status: "ok", post_count: 3021 },
          duration_ms: 12,
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
    expect(await screen.findByText("7 月共有 3021 条投稿。")).toBeInTheDocument();
    await user.click(screen.getByText("查询依据"));
    expect(screen.getByText("audit_month_data")).toBeInTheDocument();
  });
});
