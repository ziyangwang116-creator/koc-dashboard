import { apiClient } from "./api-client";
import type {
  Creator,
  CreatorDetail,
  FilterOptions,
  DashboardSummaryRow,
  DashboardPostRow,
  ComparisonResult,
  RankingCreatorItem,
  RankingVideoItem,
  ImportBatch,
  ListMeta,
  CompensationPeriod,
  CompensationVersion,
  GrassrootRow,
  LongTermRow,
  CommentaryRow,
  ThemeSubmission,
  CompensationMeta,
} from "./types";

interface Envelope<T> {
  data: T;
  meta: ListMeta;
}

export const authApi = {
  login: (password: string) =>
    apiClient.post<{ data: { authenticated: boolean } }>("/auth/login", { password }),
  logout: () => apiClient.post<{ data: { authenticated: boolean } }>("/auth/logout"),
};

export const metaApi = {
  contractTypes: () =>
    apiClient.get<{ data: { contract_types: string[] } }>("/meta/contract-types"),
};

export const creatorsApi = {
  list: (params: Record<string, unknown>) =>
    apiClient.get<Envelope<Creator[]>>("/creators", params),
  detail: (id: number) => apiClient.get<{ data: CreatorDetail }>(`/creators/${id}`),
};

export const dashboardApi = {
  filterOptions: () => apiClient.get<{ data: FilterOptions }>("/dashboard/filter-options"),
  summary: (params: Record<string, unknown>) =>
    apiClient.get<Envelope<DashboardSummaryRow[]>>("/dashboard/summary", params),
  posts: (params: Record<string, unknown>) =>
    apiClient.get<Envelope<DashboardPostRow[]>>("/dashboard/posts", params),
  comparison: (body: unknown) =>
    apiClient.post<{ data: ComparisonResult }>("/dashboard/comparison", body),
  rankings: (params: Record<string, unknown>) =>
    apiClient.get<{ data: { ranking_type: string; items: (RankingCreatorItem | RankingVideoItem)[] } }>(
      "/dashboard/rankings",
      params
    ),
  importBatches: (params: Record<string, unknown> = {}) =>
    apiClient.get<{ data: ImportBatch[] }>("/dashboard/import-batches", params),
};

export interface CompensationListResponse<T> {
  data: T[];
  meta: CompensationMeta;
}

export const compensationApi = {
  periods: (category?: string) =>
    apiClient.get<{ data: CompensationPeriod[] }>("/compensation/periods", { category }),
  versions: (period_month: string, category: string) =>
    apiClient.get<{ data: CompensationVersion[] }>("/compensation/versions", {
      period_month,
      category,
    }),
  grassroot: (params: Record<string, unknown>) =>
    apiClient.get<CompensationListResponse<GrassrootRow>>("/compensation/grassroot", params),
  longTerm: (params: Record<string, unknown>) =>
    apiClient.get<CompensationListResponse<LongTermRow>>("/compensation/long-term", params),
  commentary: (params: Record<string, unknown>) =>
    apiClient.get<CompensationListResponse<CommentaryRow>>("/compensation/commentary", params),
  themeSubmissions: (params: Record<string, unknown>) =>
    apiClient.get<{ data: ThemeSubmission[] }>(
      "/compensation/commentary/theme-submissions",
      params
    ),
};
