import { apiClient, uploadMultipart, type WriteOptions } from "./api-client";
import type {
  Creator,
  CreatorDetail,
  ContractRevision,
  FilterOptions,
  DashboardSummaryRow,
  DashboardDailyRow,
  DashboardPostRow,
  ComparisonResult,
  RankingCreatorItem,
  RankingVideoItem,
  ImportBatch,
  ImportPreview,
  StandardizationResult,
  CrossIndustryExclusion,
  ListMeta,
  CompensationPeriod,
  CompensationVersion,
  GrassrootRow,
  LongTermRow,
  CommentaryRow,
  ThemeSubmission,
  CompensationMeta,
  CompensationVersionDetail,
  ThemeSubmissionsMeta,
  FollowerBatchJobSummary,
  FollowerBatchJobStatus,
  FollowerBatchJobResultRow,
  FollowerManualUpdateResult,
  AgentStatus,
  AgentMessage,
  AgentReply,
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
  create: (body: Record<string, unknown>, options?: WriteOptions) =>
    apiClient.post<{ data: CreatorDetail }>("/creators", body, undefined, options),
  update: (id: number, body: Record<string, unknown>, expectedUpdatedAt?: string) =>
    apiClient.put<{ data: CreatorDetail }>(`/creators/${id}`, body, {
      headers: expectedUpdatedAt ? { "If-Unmodified-Since": expectedUpdatedAt } : undefined,
    }),
  setActive: (id: number, active: boolean) =>
    apiClient.patch<{ data: CreatorDetail }>(`/creators/${id}/active`, { active }),
  createContractChange: (
    id: number,
    body: Record<string, unknown>,
    options?: WriteOptions
  ) =>
    apiClient.post<{ data: CreatorDetail }>(
      `/creators/${id}/contract-changes`,
      body,
      undefined,
      options
    ),
  createContractCorrection: (
    id: number,
    body: Record<string, unknown>,
    options?: WriteOptions
  ) =>
    apiClient.post<{ data: CreatorDetail & { no_change?: boolean } }>(
      `/creators/${id}/contract-corrections`,
      body,
      undefined,
      options
    ),
  deleteContractPeriod: (id: number, sourceEffectiveDate: string, reason?: string) =>
    apiClient.delete<{ data: CreatorDetail }>(
      `/creators/${id}/contract-periods/${sourceEffectiveDate}`,
      reason ? { reason } : undefined
    ),
  revertContractRevision: (
    id: number,
    revisionId: number,
    reason: string,
    options?: WriteOptions
  ) =>
    apiClient.post<{ data: CreatorDetail }>(
      `/creators/${id}/contract-revisions/${revisionId}/revert`,
      { reason },
      undefined,
      options
    ),
  contractRevisions: (id: number) =>
    apiClient.get<{ data: ContractRevision[] }>(`/creators/${id}/contract-revisions`),
};

export const dashboardApi = {
  filterOptions: () => apiClient.get<{ data: FilterOptions }>("/dashboard/filter-options"),
  summary: (params: Record<string, unknown>) =>
    apiClient.get<Envelope<DashboardSummaryRow[]>>("/dashboard/summary", params),
  daily: (params: Record<string, unknown>) =>
    apiClient.get<{ data: DashboardDailyRow[] }>("/dashboard/daily", params),
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
  saveTrafficBoost: (periodMonth: string, enabled: boolean, options?: WriteOptions) =>
    apiClient.put<{ data: { period_month: string; enabled: boolean } }>(
      `/dashboard/${periodMonth}/traffic-boost`,
      { enabled },
      options
    ),
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
  recalculate: (lane: "grassroot" | "long-term" | "commentary", periodMonth: string) =>
    apiClient.post<{ data: { period_month: string; category: string; calculation: CompensationMeta["calculation"] } }>(
      `/compensation/${lane}/${periodMonth}/recalculate`,
      {}
    ),
  themeSubmissions: (params: Record<string, unknown>) =>
    apiClient.get<{ data: ThemeSubmission[]; meta: ThemeSubmissionsMeta }>(
      "/compensation/commentary/theme-submissions",
      params
    ),
  saveExchangeRate: (periodMonth: string, rate: number, options?: WriteOptions) =>
    apiClient.put<{ data: { period_month: string; rate: number } }>(
      `/compensation/${periodMonth}/exchange-rate`,
      { rate },
      options
    ),
  saveLongTermActivityCounts: (
    periodMonth: string,
    activityCounts: Record<string, number>,
    options?: WriteOptions
  ) =>
    apiClient.put<{ data: { period_month: string; updated_count: number } }>(
      `/compensation/long-term/${periodMonth}/activity-counts`,
      { activity_counts: activityCounts },
      options
    ),
  saveCommentaryThemeSubmissions: (
    periodMonth: string,
    rows: Record<string, unknown>[],
    expectedRevision: string,
    options?: WriteOptions
  ) =>
    apiClient.put<{
      data: { period_month: string; updated_count: number; revision: string };
    }>(
      `/compensation/commentary/${periodMonth}/theme-submissions`,
      { expected_revision: expectedRevision, rows },
      options
    ),
  createDraft: (
    lane: "grassroot" | "long-term" | "commentary",
    periodMonth: string,
    body: Record<string, unknown>,
    options?: WriteOptions
  ) =>
    apiClient.post<{ data: CompensationVersionDetail }>(
      `/compensation/${lane}/${periodMonth}/drafts`,
      body,
      undefined,
      options
    ),
  updateDraft: (
    lane: "grassroot" | "long-term" | "commentary",
    versionId: number,
    body: Record<string, unknown>
  ) =>
    apiClient.put<{ data: CompensationVersionDetail }>(
      `/compensation/${lane}/drafts/${versionId}`,
      body
    ),
  lockDraft: (
    lane: "grassroot" | "long-term" | "commentary",
    versionId: number,
    lockNote: string
  ) =>
    apiClient.post<{ data: CompensationVersionDetail }>(
      `/compensation/${lane}/drafts/${versionId}/lock`,
      { lock_note: lockNote }
    ),
};

export const followersApi = {
  manualUpdate: (
    creatorId: number,
    body: { youtube_follower_count?: number | null; tiktok_follower_count?: number | null }
  ) =>
    apiClient.post<{ data: FollowerManualUpdateResult }>(
      `/followers/${creatorId}/manual-update`,
      body
    ),
  createBatchJob: (body: {
    record_ids: number[];
    required_platform?: string;
    platform_by_record?: Record<number, string>;
  }) =>
    apiClient.post<{ data: FollowerBatchJobSummary }>("/followers/batch-update-jobs", body),
  createAllTiktokJob: () =>
    apiClient.post<{ data: FollowerBatchJobSummary }>("/followers/batch-update-jobs/all-tiktok"),
  createAllYoutubeJob: () =>
    apiClient.post<{ data: FollowerBatchJobSummary }>("/followers/batch-update-jobs/all-youtube"),
  getBatchJob: (jobId: string) =>
    apiClient.get<{ data: FollowerBatchJobStatus }>(`/followers/batch-update-jobs/${jobId}`),
  getBatchJobResults: (jobId: string) =>
    apiClient.get<{ data: { job_id: string; rows: FollowerBatchJobResultRow[] } }>(
      `/followers/batch-update-jobs/${jobId}/results`
    ),
};

export const agentApi = {
  status: () => apiClient.get<{ data: AgentStatus }>("/agent/status"),
  createConversation: () =>
    apiClient.post<{ data: { conversation_id: string } }>("/agent/conversations", {}),
  messages: (conversationId: string) =>
    apiClient.get<{ data: AgentMessage[] }>(
      `/agent/conversations/${conversationId}/messages`
    ),
  sendMessage: (conversationId: string, message: string) =>
    apiClient.post<{ data: AgentReply }>(
      `/agent/conversations/${conversationId}/messages`,
      { message }
    ),
};

export const importsApi = {
  standardize: (files: File[], processingTimezone: string, deduplicateUrls: boolean) =>
    uploadMultipart<{ data: StandardizationResult }>("/imports/standardize", files, "files", {
      processing_timezone: processingTimezone,
      deduplicate_urls: deduplicateUrls,
    }),
  preview: (files: File[]) => uploadMultipart<{ data: ImportPreview }>("/imports/preview", files),
  confirm: (previewToken: string, body: Record<string, unknown>, options?: WriteOptions) =>
    apiClient.post<{
      data: {
        batch_id: number;
        mode: string;
        period_months: string[];
        input_count: number;
        saved_count: number;
        removed_count: number;
      };
    }>(`/imports/${previewToken}/confirm`, body, undefined, options),
  rollback: (batchId: number, reason: string, options?: WriteOptions) =>
    apiClient.post<{ data: { batch_id: number; restored_count: number; removed_count: number } }>(
      `/dashboard/import-batches/${batchId}/rollback`,
      { reason },
      undefined,
      options
    ),
  crossIndustryList: () =>
    apiClient.get<{ data: CrossIndustryExclusion[] }>("/cross-industry-exclusions"),
  crossIndustryMark: (urls: string[], reason?: string) =>
    apiClient.post<{ data: CrossIndustryExclusion[] }>("/cross-industry-exclusions", {
      urls,
      reason,
    }),
  crossIndustryUnmark: (id: number) =>
    apiClient.delete<{ data: { deactivated: number } }>(`/cross-industry-exclusions/${id}`),
};
