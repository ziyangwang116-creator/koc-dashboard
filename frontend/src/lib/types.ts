// Shared API types, aligned field-for-field with docs/frontend-api-contract.md.
// The frontend must never recompute business values — only display API fields verbatim.

export interface ApiErrorPayload {
  code: string;
  message: string;
  field_errors?: { field: string; message: string }[];
  request_id?: string;
}

export interface Pagination {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
}

export interface ListMeta {
  request_id: string;
  pagination?: Pagination;
  [key: string]: unknown;
}

export interface Creator {
  id: number;
  user_id: string;
  koc_name: string;
  creator_category: "LONG_TERM" | "COMMENTARY" | "GRASSROOT" | null;
  contract_types: string[];
  contract_start_date: string | null;
  contract_end_date: string | null;
  homepage_url: string | null;
  follower_count: number | null;
  youtube_user_id: string | null;
  youtube_follower_count: number | null;
  tiktok_user_id: string | null;
  tiktok_follower_count: number | null;
  follower_source: string | null;
  follower_sync_status: string;
  settlement_eligible: boolean;
  active: boolean;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContractPeriod {
  id: number;
  effective_date: string;
  creator_category: string | null;
  contract_types: string[];
  contract_start_date: string;
  contract_end_date: string;
  created_at: string;
  updated_at: string;
}

export interface ContractRevision {
  id: number;
  creator_id: number;
  operation_type: "CHANGE" | "CORRECTION" | "DELETE" | "REVERT";
  before_periods: Record<string, unknown>[];
  after_periods: Record<string, unknown>[];
  affected_start_date: string | null;
  affected_end_date: string | null;
  reason: string | null;
  reverted_revision_id: number | null;
  reverted_at: string | null;
  created_at: string;
  is_deleted_period: boolean;
  revertable: boolean;
  status: "REVERTABLE" | "REVERTED" | "REVERT_RECORD" | "SUPERSEDED";
}

export interface CreatorDetail extends Creator {
  follower_error_code: string | null;
  follower_sync_error: string | null;
  follower_source_url: string | null;
  follower_profile_url: string | null;
  contract_periods: ContractPeriod[];
}

export interface FilterOptions {
  creators: { creator_key: string; creator_label: string }[];
  creator_categories: string[];
  source_platforms: string[];
  content_types: string[];
  available_months: string[];
  available_weeks: { week_start: string; week_end: string }[];
}

export interface DashboardSummaryRow {
  creator_key: string;
  user_id: string;
  creator_label: string;
  creator_category: string | null;
  contract_types: string[];
  follower_count: number | null;
  source_platforms: string[];
  post_count: number;
  view: number;
  original_views: number;
  traffic_boost_views: number;
  boosted_views: number;
  total_views: number;
  average_views: number;
  max_views: number;
  total_likes: number;
  total_comments: number;
  total_interactions: number;
  engagement_rate: number;
  earliest_date: string;
  latest_date: string;
}

export interface DashboardPostRow {
  creator_key: string;
  user_id: string;
  koc_name: string;
  creator_category: string | null;
  contract_types: string[];
  source_platform: string;
  content_type: string;
  subtype: string;
  title: string;
  url: string;
  publish_date: string | null;
  view: number;
  original_views: number;
  traffic_boost_views: number;
  boosted_views: number;
  views: number;
  likes: number | null;
  comment: number | null;
  reposted: number | null;
  collect: number | null;
  matched: boolean;
  profile_status: string;
  is_cross_industry: boolean;
  compensation_eligible: boolean;
  cross_industry_reason: string | null;
}

export interface ComparisonPoint {
  period_label: string;
  value: number;
  post_count: number;
}

export interface ComparisonSeriesEntry {
  points: ComparisonPoint[];
  change_rate: number | null;
  warning: boolean;
}

export interface ComparisonSeries {
  group_key: string;
  group_label: string;
  points: ComparisonPoint[];
  change_rate: number | null;
  warning: boolean;
  breakdown?: Record<string, ComparisonSeriesEntry>;
}

export interface ComparisonResult {
  dimension: string;
  metric: string;
  series: ComparisonSeries[];
}

export interface RankingCreatorItem {
  rank: number;
  creator_key: string;
  creator_label: string;
  creator_category: string | null;
  total_views: number;
  post_count: number;
}

export interface RankingVideoItem {
  rank: number;
  creator_key: string;
  creator_label: string;
  title: string;
  url: string;
  publish_date: string;
  views: number;
}

export interface ImportBatch {
  batch_id: number;
  mode: "REPLACE_MONTHS" | "APPEND_OR_UPDATE";
  period_months: string[];
  source_files: string[];
  input_count: number;
  saved_count: number;
  removed_count: number;
  created_at: string;
}

export interface ImportDiffBucket {
  count: number;
  rows: Record<string, unknown>[];
}

export interface ImportPreview {
  preview_token: string;
  input_row_count: number;
  matched_row_count: number;
  period_months: string[];
  cross_industry_flagged_count: number;
  column_warnings: string[];
  additions: ImportDiffBucket;
  updates: ImportDiffBucket;
  removals: ImportDiffBucket;
  unmatched_creators: ImportDiffBucket;
  date_anomalies: ImportDiffBucket;
}

export interface CrossIndustryExclusion {
  id: number;
  platform: string;
  url_key: string;
  original_url: string;
  normalized_url: string;
  reason: string | null;
  active: number;
  created_at: string;
  updated_at: string;
}

// --- Compensation ---

export interface CompensationPeriod {
  period_month: string;
  has_posts: boolean;
  traffic_boost_applicable: boolean;
  traffic_boost_enabled: boolean;
  versions: Record<string, { count: number; has_locked: boolean }>;
}

export interface CompensationVersion {
  version_id: number;
  version_no: number | null;
  status: "DRAFT" | "LOCKED";
  schema_version: number | null;
  jpy_to_usd_rate: number;
  note: string | null;
  created_at: string;
  updated_at: string;
  locked_at: string | null;
  summary: Record<string, number | null>;
}

export type CompensationMode = "preview" | "saved_draft" | "frozen";

export interface CompensationMeta {
  request_id: string;
  mode: CompensationMode;
  period_month: string;
  jpy_to_usd_rate: number;
  traffic_boost_enabled?: boolean;
  version: { version_id: number; version_no: number | null; status: string } | null;
  currency: Record<string, unknown>;
  summary: Record<string, number | null>;
  pagination: Pagination;
}

export interface GrassrootRow {
  creator_key: string;
  creator_name: string;
  contract_types: string[];
  settlement_status: string;
  rank: string;
  billable_post_count: number;
  billable_views: number;
  all_video_views: number;
  total_amount_jpy: number;
  creator_receivable_jpy: number;
  youdao_receivable_jpy: number;
  creator_receivable_usd: number;
  youdao_receivable_usd: number;
  cpm: number | null;
}

export interface LongTermRow {
  record_id: number;
  creator_key: string;
  creator_name: string;
  contract_types: string[];
  settlement_status: string;
  rank: string;
  followers: number | null;
  monthly_new_post_views: number;
  monthly_activity_count: number | null;
  total_amount_jpy: number;
  creator_receivable_jpy: number;
  youdao_receivable_jpy: number;
  creator_receivable_usd: number;
  youdao_receivable_usd: number;
  cpm: number | null;
}

export interface CommentaryRow {
  creator_id: number;
  creator_key: string;
  creator_name: string;
  contract_types: string[];
  settlement_status: string;
  designated_theme_count: number;
  designated_theme_reward_jpy: number;
  all_paid_views: number;
  total_jpy_tax_incl: number;
  creator_receivable_jpy: number;
  youdao_receivable_jpy: number;
  creator_receivable_usd: number;
  youdao_receivable_usd: number;
  cpm: number | null;
}

export interface ThemeSubmission {
  id: number;
  period_month: string;
  creator_id: number;
  theme_code: string;
  theme_name: string;
  content_format: "LONG" | "SHORT";
  urls: string[];
  submitted_date: string;
  review_status: "PENDING" | "APPROVED" | "REJECTED";
  note: string | null;
  theme_reward_eligible: boolean;
  matched_post_urls: string[];
  billing_excluded_url_count: number;
  billing_excluded: boolean;
}

export interface ThemeSubmissionsMeta {
  period_month: string;
  revision: string;
}

export interface CompensationVersionDetail {
  id: number;
  period_month: string;
  version_no: number | null;
  status: "DRAFT" | "LOCKED";
  jpy_to_usd_rate: number;
  details: Record<string, unknown>[];
  summary: Record<string, unknown>;
  note: string | null;
  created_at: string;
  updated_at: string;
  locked_at: string | null;
  lock_note: string | null;
  locked_by: string | null;
}

// --- Followers ---

export interface FollowerBatchJobSummary {
  job_id: string;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
  total: number;
  created_at: string;
}

export interface FollowerBatchJobStatus {
  job_id: string;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
  total: number;
  processed: number;
  success: number;
  failed: number;
  skipped: number;
  youtube_success: number;
  youtube_failed: number;
  tiktok_success: number;
  tiktok_failed: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface FollowerBatchJobResultRow {
  [key: string]: unknown;
}

export interface FollowerManualUpdateResult {
  record_id: number;
  results: Record<
    string,
    {
      status: string;
      follower_count: number | null;
      error_code: string | null;
      message: string | null;
    }
  >;
}
