import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQueryClient } from "@/test-utils";
import { ApiError } from "@/lib/api-client";
import type { ImportPreview } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/imports",
}));

const previewResponse: { data: ImportPreview } = {
  data: {
    preview_token: "token-1",
    input_row_count: 2,
    matched_row_count: 1,
    period_months: ["2026-01"],
    cross_industry_flagged_count: 0,
    column_warnings: [],
    smart_import: {
      enabled: true,
      files: [
        {
          source_file: "a.xlsx",
          source_columns: ["userId", "subtype", "title", "url", "timestamp", "view"],
          column_mapping: {
            userId: "userId",
            subtype: "subtype",
            title: "title",
            url: "url",
            timestamp: "timestamp",
            view: "view",
          },
          auto_mapped_columns: [],
          date_method_counts: { excel_datetime: 2 },
          date_min: "2026-01-05",
          date_max: "2026-01-06",
          warnings: [],
        },
      ],
    },
    additions: { count: 1, rows: [{ koc_name: "示例达人", platform: "TikTok", publish_date: "2026-01-05", title: "t1", url: "https://x.com/1" }] },
    updates: { count: 0, rows: [] },
    removals: { count: 0, rows: [] },
    unmatched_creators: { count: 1, rows: [{ raw_uid: "u1", reason: "UID 未在启用的达人库中找到", source_file: "a.xlsx" }] },
    date_anomalies: { count: 0, rows: [] },
  },
};

const previewResponseNoUnmatched = {
  data: {
    ...previewResponse.data,
    unmatched_creators: { count: 0, rows: [] },
  },
};

const batchesResponse = {
  data: [
    {
      batch_id: 2,
      mode: "REPLACE_MONTHS",
      period_months: ["2026-01"],
      source_files: ["a.xlsx"],
      input_count: 2,
      saved_count: 2,
      removed_count: 1,
      created_at: "2026-01-10T00:00:00Z",
    },
    {
      batch_id: 1,
      mode: "REPLACE_MONTHS",
      period_months: ["2026-01"],
      source_files: ["b.xlsx"],
      input_count: 1,
      saved_count: 1,
      removed_count: 0,
      created_at: "2026-01-01T00:00:00Z",
    },
  ],
};

const exclusionsResponse = {
  data: [
    {
      id: 9,
      platform: "tiktok",
      url_key: "key-9",
      original_url: "https://x.com/cross1",
      normalized_url: "https://x.com/cross1",
      reason: "异业活动",
      active: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
};

const previewMock = vi.fn(async () => previewResponse);
const standardizeResponse = {
  data: {
    download_token: "download-1",
    download_path: "/api/imports/standardize/download-1/download",
    filename: "KOC_多文件整理结果_20260110_000000.xlsx",
    expires_in_seconds: 1800,
    timezone: "Asia/Shanghai",
    deduplicate_urls: false,
    overall: {
      uploaded_files: 1,
      successful_files: 1,
      failed_files: 0,
      original_rows: 2,
      merged_rows: 2,
      koc_count: 1,
      earliest_date: "2026-01-05",
      latest_date: "2026-01-06",
      unmatched_uid_count: 0,
      duplicate_url_count: 0,
      missing_url_count: 0,
      missing_title_count: 0,
      invalid_timestamp_count: 0,
      blank_subtype_to_shorts_count: 0,
      removed_duplicate_count: 0,
    },
    file_reports: [{ source_file: "a.xlsx", original_rows: 2, processed_rows: 2, unmatched_uid: 0, duplicate_url: 0, status: "成功", error_message: "" }],
    unmatched_uids: [],
    result_preview: [{ koc_name: "示例达人", platform: "TikTok", publish_date: "2026-01-05", title: "t1", url: "https://x.com/1", views: 100 }],
    result_row_count: 2,
    exception_preview: [],
    exception_row_count: 0,
  },
};
const standardizeMock = vi.fn(async () => standardizeResponse);
const confirmMock = vi.fn(async () => ({
  data: { batch_id: 3, mode: "REPLACE_MONTHS", period_months: ["2026-01"], input_count: 2, saved_count: 2, removed_count: 1 },
}));
const rollbackMock = vi.fn(async () => ({ data: { batch_id: 2, restored_count: 1, removed_count: 2 } }));
const importBatchesMock = vi.fn(async () => batchesResponse);
const crossIndustryListMock = vi.fn(async () => exclusionsResponse);
const crossIndustryMarkMock = vi.fn(async () => exclusionsResponse);
const crossIndustryUnmarkMock = vi.fn(async () => ({ data: { deactivated: 1 } }));

vi.mock("@/lib/endpoints", () => ({
  importsApi: {
    standardize: (...args: Parameters<typeof standardizeMock>) => standardizeMock(...args),
    preview: (...args: Parameters<typeof previewMock>) => previewMock(...args),
    confirm: (...args: Parameters<typeof confirmMock>) => confirmMock(...args),
    rollback: (...args: Parameters<typeof rollbackMock>) => rollbackMock(...args),
    crossIndustryList: (...args: Parameters<typeof crossIndustryListMock>) => crossIndustryListMock(...args),
    crossIndustryMark: (...args: Parameters<typeof crossIndustryMarkMock>) => crossIndustryMarkMock(...args),
    crossIndustryUnmark: (...args: Parameters<typeof crossIndustryUnmarkMock>) => crossIndustryUnmarkMock(...args),
  },
  dashboardApi: {
    importBatches: (...args: Parameters<typeof importBatchesMock>) => importBatchesMock(...args),
  },
  authApi: { logout: vi.fn(async () => ({ data: { authenticated: false } })) },
}));

import ImportsPage from "@/app/imports/page";

function fakeFile(name = "a.xlsx") {
  return new File(["content"], name, { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
}

beforeEach(() => {
  previewMock.mockClear();
  standardizeMock.mockClear();
  confirmMock.mockClear();
  rollbackMock.mockClear();
  importBatchesMock.mockClear();
  crossIndustryListMock.mockClear();
  crossIndustryMarkMock.mockClear();
  crossIndustryUnmarkMock.mockClear();
  previewMock.mockResolvedValue(previewResponse);
});

describe("ImportsPage", () => {
  it("restores the legacy standardization preview and Excel download flow", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);

    await user.upload(screen.getByLabelText("标准化整理文件"), fakeFile());
    await user.click(screen.getByRole("button", { name: "开始整理" }));

    await waitFor(() => expect(standardizeMock).toHaveBeenCalledWith(
      [expect.objectContaining({ name: "a.xlsx" })],
      "Asia/Shanghai",
      false
    ));
    expect(await screen.findByText("逐文件处理报告")).toBeInTheDocument();
    expect(screen.getByText("整理结果预览（前 100 条）")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /下载统一标准 Excel/ })).toHaveAttribute(
      "href",
      "/api/imports/standardize/download-1/download"
    );
  });

  it("uploads a file and renders the preview diff categories", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);

    const fileInput = screen.getByLabelText("导入看板数据库文件") as HTMLInputElement;
    await user.upload(fileInput, fakeFile());
    await user.click(screen.getByRole("button", { name: "生成预览" }));

    await waitFor(() => expect(previewMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("新增")).toBeInTheDocument();
    expect(screen.getByText("更新")).toBeInTheDocument();
    expect(screen.getByText(/补充导入不会删除该月已有投稿/)).toBeInTheDocument();
    expect(screen.getByText("未匹配达人")).toBeInTheDocument();
    expect(screen.getByText("日期异常")).toBeInTheDocument();
  });

  it("disables the confirm button and explains why when unmatched creators exist", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);

    const fileInput = screen.getByLabelText("导入看板数据库文件") as HTMLInputElement;
    await user.upload(fileInput, fakeFile());
    await user.click(screen.getByRole("button", { name: "生成预览" }));

    const confirmBtn = await screen.findByRole("button", { name: "确认导入（补充导入）" });
    expect(confirmBtn).toBeDisabled();
    expect(screen.getByText(/无法确认导入/)).toBeInTheDocument();
  });

  it("renders smart recognition and re-previews with a manual mapping", async () => {
    previewMock.mockResolvedValue(previewResponseNoUnmatched);
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);

    await user.upload(screen.getByLabelText("导入看板数据库文件"), fakeFile());
    await user.click(screen.getByRole("button", { name: "生成预览" }));

    expect(await screen.findByText("智能识别结果")).toBeInTheDocument();
    expect(screen.getByText("Excel 日期：2")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("字段映射 发布日期"), "timestamp");
    await user.click(screen.getByRole("button", { name: "应用字段映射并重新预览" }));

    await waitFor(() =>
      expect(previewMock).toHaveBeenLastCalledWith(
        [expect.objectContaining({ name: "a.xlsx" })],
        expect.objectContaining({ timestamp: "timestamp" })
      )
    );
  });

  it("blocks confirmation when dates cannot be recognized", async () => {
    previewMock.mockResolvedValueOnce({
      data: {
        ...previewResponseNoUnmatched.data,
        date_anomalies: {
          count: 1,
          rows: [{ title: "bad date", reason: "发布时间无法解析", source_file: "a.xlsx" }],
        },
      },
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);

    await user.upload(screen.getByLabelText("导入看板数据库文件"), fakeFile());
    await user.click(screen.getByRole("button", { name: "生成预览" }));

    const confirmBtn = await screen.findByRole("button", { name: "确认导入（补充导入）" });
    expect(confirmBtn).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("无法识别发布日期");
  });

  it("defaults to supplement import and requires a second explicit confirmation", async () => {
    previewMock.mockResolvedValueOnce(previewResponseNoUnmatched);
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);

    const fileInput = screen.getByLabelText("导入看板数据库文件") as HTMLInputElement;
    await user.upload(fileInput, fakeFile());
    await user.click(screen.getByRole("button", { name: "生成预览" }));

    const confirmBtn = await screen.findByRole("button", { name: "确认导入（补充导入）" });
    expect(confirmBtn).toBeEnabled();
    await user.click(confirmBtn);

    const dialogConfirmBtn = screen.getByRole("button", { name: "确认执行" });
    expect(dialogConfirmBtn).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /我确认要执行本次补充导入/ }));
    expect(dialogConfirmBtn).toBeEnabled();
    await user.click(dialogConfirmBtn);

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(confirmMock).toHaveBeenCalledWith("token-1", { mode: "append_or_update" }, expect.objectContaining({ idempotencyKey: expect.any(String) }));
  });

  it("allows switching to full-month replacement explicitly", async () => {
    previewMock.mockResolvedValueOnce({
      data: {
        ...previewResponseNoUnmatched.data,
        removals: {
          count: 1,
          rows: [{ title: "旧投稿", url: "https://x.com/old" }] as Record<string, unknown>[],
        },
      },
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);

    await user.click(screen.getByRole("radio", { name: "按月份完整替换" }));
    await user.upload(screen.getByLabelText("导入看板数据库文件"), fakeFile());
    await user.click(screen.getByRole("button", { name: "生成预览" }));

    expect(await screen.findByText("完整替换时将删除")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认导入（按月份完整替换）" }));
    await user.click(screen.getByRole("checkbox", { name: /我确认要执行本次按月份完整替换导入/ }));
    await user.click(screen.getByRole("button", { name: "确认执行" }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(
      "token-1",
      { mode: "replace_months" },
      expect.objectContaining({ idempotencyKey: expect.any(String) })
    ));
  });

  it("disables rollback for a non-most-recent batch and allows it for the latest one", async () => {
    renderWithQueryClient(<ImportsPage />);
    await waitFor(() => expect(importBatchesMock).toHaveBeenCalled());

    await screen.findByText("#2");
    const rollbackButtons = screen.getAllByRole("button", { name: "回滚" });
    // batch #2 is the most recent for its month -> enabled; batch #1 is superseded -> disabled.
    expect(rollbackButtons[0]).toBeEnabled();
    expect(rollbackButtons[1]).toBeDisabled();
  });

  it("runs the rollback flow with a required reason and second confirmation", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);
    await screen.findByText("#2");

    const rollbackButtons = screen.getAllByRole("button", { name: "回滚" });
    await user.click(rollbackButtons[0]);

    const confirmRollbackBtn = screen.getByRole("button", { name: "确认回滚" });
    expect(confirmRollbackBtn).toBeDisabled();

    await user.type(screen.getByLabelText(/回滚原因/), "误导入需要回滚");
    expect(confirmRollbackBtn).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /我确认要回滚该批次/ }));
    expect(confirmRollbackBtn).toBeEnabled();

    await user.click(confirmRollbackBtn);
    await waitFor(() => expect(rollbackMock).toHaveBeenCalledTimes(1));
    expect(rollbackMock).toHaveBeenCalledWith(2, "误导入需要回滚", expect.objectContaining({ idempotencyKey: expect.any(String) }));
  });

  it("marks and unmarks cross-industry URLs", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);
    await waitFor(() => expect(crossIndustryListMock).toHaveBeenCalled());

    await user.type(
      screen.getByPlaceholderText("粘贴一个或多个投稿链接，每行一个"),
      "https://x.com/m1\nhttps://x.com/m2"
    );
    await user.click(screen.getByRole("button", { name: "标记为异业" }));
    await waitFor(() => expect(crossIndustryMarkMock).toHaveBeenCalledTimes(1));
    expect(crossIndustryMarkMock).toHaveBeenCalledWith(["https://x.com/m1", "https://x.com/m2"], expect.any(String));

    await screen.findByText("https://x.com/cross1");
    await user.click(screen.getByRole("button", { name: "取消标记" }));
    await waitFor(() => expect(crossIndustryUnmarkMock).toHaveBeenCalledWith(9));
  });

  it("shows a unified error message when confirm fails", async () => {
    previewMock.mockResolvedValueOnce(previewResponseNoUnmatched);
    confirmMock.mockRejectedValueOnce(new ApiError(422, { code: "VALIDATION_ERROR", message: "存在未匹配的创建者。" }));
    const user = userEvent.setup();
    renderWithQueryClient(<ImportsPage />);

    const fileInput = screen.getByLabelText("导入看板数据库文件") as HTMLInputElement;
    await user.upload(fileInput, fakeFile());
    await user.click(screen.getByRole("button", { name: "生成预览" }));

    const confirmBtn = await screen.findByRole("button", { name: "确认导入（补充导入）" });
    await user.click(confirmBtn);
    await user.click(screen.getByRole("checkbox", { name: /我确认要执行本次补充导入/ }));
    await user.click(screen.getByRole("button", { name: "确认执行" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("存在未匹配的创建者。"));
  });
});
