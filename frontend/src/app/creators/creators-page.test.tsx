import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQueryClient } from "@/test-utils";
import { ApiError } from "@/lib/api-client";

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
      homepage_url: "https://example.com",
      follower_count: 5000,
      follower_sync_status: "SUCCESS",
      active: true,
      note: null,
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
  meta: { request_id: "r1", pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 } },
};

const detailResponse = {
  data: {
    id: 1,
    user_id: "koc_1",
    koc_name: "示例达人",
    creator_category: "GRASSROOT",
    contract_periods: [
      {
        id: 10,
        effective_date: "2026-01-01",
        creator_category: "GRASSROOT",
        contract_types: ["YTB"],
        contract_start_date: "2026-01-01",
        contract_end_date: "2026-12-31",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ],
  },
};

const listMock = vi.fn(async () => listResponse);
const detailMock = vi.fn(async () => detailResponse);
const updateMock = vi.fn(async (_id: number, _body: Record<string, unknown>, _expectedUpdatedAt?: string) => ({
  data: detailResponse.data,
}));
const setActiveMock = vi.fn(async (_id: number, _value: boolean) => ({ data: detailResponse.data }));
const createContractChangeMock = vi.fn(async (_id: number, _body: Record<string, unknown>) => ({
  data: detailResponse.data,
}));
const createContractCorrectionMock = vi.fn(async (_id: number, _body: Record<string, unknown>) => ({
  data: detailResponse.data,
}));
const deleteContractPeriodMock = vi.fn(async (_id: number, _date: string, _reason?: string) => ({
  data: detailResponse.data,
}));
const revertContractRevisionMock = vi.fn(async (_id: number, _revisionId: number, _reason: string) => ({
  data: detailResponse.data,
}));

vi.mock("@/lib/endpoints", () => ({
  creatorsApi: {
    list: (...args: Parameters<typeof listMock>) => listMock(...args),
    detail: (...args: Parameters<typeof detailMock>) => detailMock(...args),
    update: (...args: Parameters<typeof updateMock>) => updateMock(...args),
    setActive: (...args: Parameters<typeof setActiveMock>) => setActiveMock(...args),
    createContractChange: (...args: Parameters<typeof createContractChangeMock>) =>
      createContractChangeMock(...args),
    createContractCorrection: (...args: Parameters<typeof createContractCorrectionMock>) =>
      createContractCorrectionMock(...args),
    deleteContractPeriod: (...args: Parameters<typeof deleteContractPeriodMock>) =>
      deleteContractPeriodMock(...args),
    revertContractRevision: (...args: Parameters<typeof revertContractRevisionMock>) =>
      revertContractRevisionMock(...args),
  },
  metaApi: { contractTypes: vi.fn(async () => ({ data: { contract_types: ["YTB", "TT"] } })) },
  authApi: { logout: vi.fn(async () => ({ data: { authenticated: false } })) },
}));

import CreatorsPage from "@/app/creators/page";

beforeEach(() => {
  listMock.mockClear();
  detailMock.mockClear();
  updateMock.mockClear();
  setActiveMock.mockClear();
  createContractChangeMock.mockClear();
  createContractCorrectionMock.mockClear();
  deleteContractPeriodMock.mockClear();
  revertContractRevisionMock.mockClear();
});

describe("CreatorsPage", () => {
  it("renders the creator list once data resolves", async () => {
    renderWithQueryClient(<CreatorsPage />);
    await waitFor(() => expect(screen.getByText("示例达人")).toBeInTheDocument());
    expect(screen.getByPlaceholderText("搜索达人名称 / UID")).toBeInTheDocument();
  });

  it("saves an inline profile edit via PUT and refetches the list", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CreatorsPage />);
    await waitFor(() => expect(screen.getByText("示例达人")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "编辑" }));
    const nameInput = screen.getByDisplayValue("示例达人");
    await user.clear(nameInput);
    await user.type(nameInput, "新名字");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock.mock.calls[0][1]).toMatchObject({ koc_name: "新名字" });
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
  });

  it("shows the unified error message when an edit hits a 409 conflict", async () => {
    updateMock.mockRejectedValueOnce(
      new ApiError(409, { code: "CONFLICT", message: "该达人资料已被修改，请刷新后重试。" })
    );
    const user = userEvent.setup();
    renderWithQueryClient(<CreatorsPage />);
    await waitFor(() => expect(screen.getByText("示例达人")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "编辑" }));
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("该达人资料已被修改，请刷新后重试。")
    );
  });

  it("opens two visually distinct entry points for contract change vs correction", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CreatorsPage />);
    await waitFor(() => expect(screen.getByText("示例达人")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "查看详情" }));
    await waitFor(() => expect(detailMock).toHaveBeenCalled());

    expect(await screen.findByRole("button", { name: "＋ 新增合同变更" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "✎ 修正错误合同" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "＋ 新增合同变更" }));
    expect(screen.getByText("新增合同变更", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByText(/这将作为一次真实的合同变更/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "取消" }));

    await user.click(screen.getByRole("button", { name: "✎ 修正错误合同" }));
    expect(screen.getByText("修正错误合同", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByText(/这是对已录入历史数据的更正/)).toBeInTheDocument();
  });

  it("submits a contract change with distinct confirmation copy and invalidates caches", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CreatorsPage />);
    await waitFor(() => expect(screen.getByText("示例达人")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "查看详情" }));
    await screen.findByRole("button", { name: "＋ 新增合同变更" });

    await user.click(screen.getByRole("button", { name: "＋ 新增合同变更" }));
    const dialog = screen.getByText("新增合同变更", { selector: "h3" }).closest("div") as HTMLElement;
    await user.type(within(dialog).getByPlaceholderText("YTB,TT"), "YTB,TT");
    const dateInputs = within(dialog).getAllByDisplayValue("");
    await user.type(dateInputs[0], "2026-06-01");
    await user.click(screen.getByRole("button", { name: "确认新增变更" }));

    await waitFor(() => expect(createContractChangeMock).toHaveBeenCalledTimes(1));
  });

  it("requires a second confirmation and a reason before deleting a contract period", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CreatorsPage />);
    await waitFor(() => expect(screen.getByText("示例达人")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "查看详情" }));
    await screen.findByText("合同周期");

    await user.click(screen.getByRole("button", { name: "删除" }));
    const confirmDeleteBtn = screen.getByRole("button", { name: "确认删除" });
    expect(confirmDeleteBtn).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /我确认要删除该合同周期/ }));
    expect(confirmDeleteBtn).toBeEnabled();
    await user.click(confirmDeleteBtn);

    await waitFor(() => expect(deleteContractPeriodMock).toHaveBeenCalledTimes(1));
  });

  it("requires a 1-500 char reason before enabling the revert action", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CreatorsPage />);
    await waitFor(() => expect(screen.getByText("示例达人")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "查看详情" }));
    await screen.findByText("合同周期");

    await user.click(screen.getByRole("button", { name: "撤销历史修改…" }));
    const confirmRevertBtn = screen.getByRole("button", { name: "确认撤销" });
    expect(confirmRevertBtn).toBeDisabled();

    await user.type(screen.getByPlaceholderText("修订记录 ID"), "5");
    expect(confirmRevertBtn).toBeDisabled();

    await user.type(screen.getByPlaceholderText("撤销原因（1-500 字符，必填）"), "录入时误选了合同类型");
    expect(confirmRevertBtn).toBeEnabled();

    vi.spyOn(window, "confirm").mockReturnValue(true);
    await user.click(confirmRevertBtn);

    await waitFor(() => expect(revertContractRevisionMock).toHaveBeenCalledTimes(1));
    expect(revertContractRevisionMock).toHaveBeenCalledWith(1, 5, "录入时误选了合同类型");
  });
});
