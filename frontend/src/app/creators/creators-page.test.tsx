import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithQueryClient } from "@/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/creators",
}));

const listResponse = {
  data: [
    {
      id: 1,
      user_id: "koc_1",
      koc_name: "示例达人",
      creator_category: "GRASSROOT",
      contract_types: ["YTB"],
      follower_count: 5000,
      follower_sync_status: "SUCCESS",
      active: true,
    },
  ],
  meta: { request_id: "r1", pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 } },
};

vi.mock("@/lib/endpoints", () => ({
  creatorsApi: {
    list: vi.fn(async () => listResponse),
    detail: vi.fn(async () => ({ data: { contract_periods: [] } })),
  },
  metaApi: { contractTypes: vi.fn(async () => ({ data: { contract_types: ["YTB", "TT"] } })) },
  authApi: { logout: vi.fn(async () => ({ data: { authenticated: false } })) },
}));

import CreatorsPage from "@/app/creators/page";

describe("CreatorsPage", () => {
  it("renders the creator list once data resolves", async () => {
    renderWithQueryClient(<CreatorsPage />);
    await waitFor(() => expect(screen.getByText("示例达人")).toBeInTheDocument());
    expect(screen.getByPlaceholderText("搜索达人名称 / UID")).toBeInTheDocument();
  });
});
