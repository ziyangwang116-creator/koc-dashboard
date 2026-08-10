import type { ApiErrorPayload } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  code: string;
  status: number;
  fieldErrors?: { field: string; message: string }[];

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message);
    this.code = payload.code;
    this.status = status;
    this.fieldErrors = payload.field_errors;
  }
}

let unauthorizedHandler: (() => void) | null = null;

/** Registered once by the app shell; called whenever any request receives a 401. */
export function setUnauthorizedHandler(handler: () => void) {
  unauthorizedHandler = handler;
}

function buildUrl(path: string, params?: Record<string, unknown>): string {
  const url = new URL(
    `${BASE_URL}${path}`,
    typeof window === "undefined" ? "http://localhost" : window.location.origin
  );
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      if (Array.isArray(value)) {
        for (const v of value) {
          if (v === undefined || v === null || v === "") continue;
          url.searchParams.append(key, String(v));
        }
      } else {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.pathname + url.search;
}

async function request<T>(
  path: string,
  options: {
    method?: string;
    params?: Record<string, unknown>;
    body?: unknown;
  } = {}
): Promise<T> {
  const { method = "GET", params, body } = options;
  const res = await fetch(buildUrl(path, params), {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    unauthorizedHandler?.();
  }

  let json: unknown;
  try {
    json = await res.json();
  } catch {
    throw new ApiError(res.status, {
      code: "INTERNAL_ERROR",
      message: "服务器返回了无法解析的响应。",
    });
  }

  if (!res.ok) {
    const errPayload = (json as { error?: ApiErrorPayload }).error ?? {
      code: "INTERNAL_ERROR",
      message: "发生未知错误。",
    };
    throw new ApiError(res.status, errPayload);
  }

  return json as T;
}

export const apiClient = {
  get: <T>(path: string, params?: Record<string, unknown>) =>
    request<T>(path, { method: "GET", params }),
  post: <T>(path: string, body?: unknown, params?: Record<string, unknown>) =>
    request<T>(path, { method: "POST", body, params }),
};
