import { describe, it, expect, vi, afterEach } from "vitest";
import { apiClient, ApiError, setUnauthorizedHandler } from "@/lib/api-client";

describe("apiClient", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("sends credentials include and parses successful envelope", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: { authenticated: true }, meta: { request_id: "r1" } }),
    });
    global.fetch = mockFetch as unknown as typeof fetch;

    const result = await apiClient.get<{ data: { authenticated: boolean } }>("/health");

    expect(result.data.authenticated).toBe(true);
    const [, options] = mockFetch.mock.calls[0];
    expect(options.credentials).toBe("include");
  });

  it("serializes repeated array query params", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [], meta: { request_id: "r1" } }),
    });
    global.fetch = mockFetch as unknown as typeof fetch;

    await apiClient.get("/creators", { contract_type: ["YTB", "TT"] });

    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain("contract_type=YTB");
    expect(url).toContain("contract_type=TT");
  });

  it("throws ApiError with the unified error envelope fields on failure", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        error: { code: "VALIDATION_ERROR", message: "参数非法", request_id: "r2" },
      }),
    });
    global.fetch = mockFetch as unknown as typeof fetch;

    await expect(apiClient.get("/dashboard/summary")).rejects.toMatchObject({
      status: 422,
      code: "VALIDATION_ERROR",
      message: "参数非法",
    });
  });

  it("never surfaces raw non-JSON/stack-trace bodies to callers", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    });
    global.fetch = mockFetch as unknown as typeof fetch;

    await expect(apiClient.get("/dashboard/summary")).rejects.toBeInstanceOf(ApiError);
  });

  it("invokes the registered unauthorized handler on 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ error: { code: "UNAUTHENTICATED", message: "未登录" } }),
    });
    global.fetch = mockFetch as unknown as typeof fetch;

    await expect(apiClient.get("/creators")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
    setUnauthorizedHandler(() => {});
  });
});
