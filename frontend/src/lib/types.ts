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
  youtube_homepage_url: string | null;
  youtube_follower_count: number | null;
  tiktok_user_id: string | null;
  tiktok_homepage_url: string | null;
  tiktok_follower_count: number | null;
  follower_raw_display_value: string | null;
  follower_source: string | null;
  follower_count_is_estimated: boolean | null;
  follower_count_updated_at: string | null;
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

export interface DashboardDailyRow {
  publish_date: string;
  post_count: number;
  total_views: number;
  total_interactions: number;
}

export interface DashboardPostRow {
  source_file: string | null;
  creator_key: string;
  user_id: string;
  creator_id: number | null;
  creator_active: boolean;
  profile_effective_date: string | null;
  koc_name: string;
  creator_label: string | null;
  kol_name: string | null;
  creator_category: string | null;
  contract_types: string[];
  contract_start_date: string | null;
  contract_end_date: string | null;
  follower_count: number | null;
  homepage_url: string | null;
  youtube_user_id: string | null;
  youtube_homepage_url: string | null;
  youtube_follower_count: number | null;
  tiktok_user_id: string | null;
  tiktok_homepage_url: string | null;
  tiktok_follower_count: number | null;
  source_platform: string;
  content_type: string;
  subtype: string;
  description: string | null;
  timestamp: string | null;
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
  cross_industry_url_key: string | null;
  matched: boolean;
  profile_status: string;
  is_cross_industry: boolean;
  compensation_eligible: boolean;
  cross_industry_reason: string | null;
  cross_industry_exclusion_id: number | null;
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
  post_count_change_rate?: number | null;
  post_count_warning?: boolean;
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

export interface SmartImportFileDiagnostic {
  source_file: string;
  source_columns: string[];
  column_mapping: Record<string, string>;
  auto_mapped_columns: string[];
  date_method_counts: Record<string, number>;
  date_min: string | null;
  date_max: string | null;
  warnings: string[];
}

export interface SmartImportDiagnostic {
  enabled: boolean;
  files: SmartImportFileDiagnostic[];
}

export interface ImportPreview {
  preview_token: string;
  input_row_count: number;
  matched_row_count: number;
  period_months: string[];
  cross_industry_flagged_count: number;
  column_warnings: string[];
  smart_import?: SmartImportDiagnostic;
  additions: ImportDiffBucket;
  updates: ImportDiffBucket;
  removals: ImportDiffBucket;
  unmatched_creators: ImportDiffBucket;
  date_anomalies: ImportDiffBucket;
}

export interface StandardizationOverall {
  uploaded_files: number;
  successful_files: number;
  failed_files: number;
  original_rows: number;
  merged_rows: number;
  koc_count: number;
  earliest_date: string | null;
  latest_date: string | null;
  unmatched_uid_count: number;
  duplicate_url_count: number;
  missing_url_count: number;
  missing_title_count: number;
  invalid_timestamp_count: number;
  blank_subtype_to_shorts_count: number;
  removed_duplicate_count: number;
}

export interface StandardizationResult {
  download_token: string;
  download_path: string;
  filename: string;
  expires_in_seconds: number;
  timezone: string;
  deduplicate_urls: boolean;
  overall: StandardizationOverall;
  file_reports: Record<string, unknown>[];
  unmatched_uids: Record<string, unknown>[];
  result_preview: Record<string, unknown>[];
  result_row_count: number;
  exception_preview: Record<string, unknown>[];
  exception_row_count: number;
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
  lock_note: string | null;
  locked_by: string | null;
  summary: Record<string, number | null>;
}

export type CompensationMode = "preview" | "saved_draft" | "frozen";

export interface CompensationCalculationMeta {
  source: "cache" | "saved_draft" | "locked_version";
  status: "CURRENT" | "STALE" | "DRAFT" | "LOCKED";
  is_stale: boolean;
  calculation_version?: number | null;
  calculated_at: string | null;
  invalidated_at?: string | null;
  stale_reason?: string | null;
  calculated_with_jpy_to_usd_rate?: number | null;
  calculated_with_traffic_boost_enabled?: boolean;
}

export interface CompensationMeta {
  request_id: string;
  mode: CompensationMode;
  period_month: string;
  jpy_to_usd_rate: number;
  traffic_boost_enabled?: boolean;
  version: { version_id: number; version_no: number | null; status: string } | null;
  currency: Record<string, unknown>;
  summary: Record<string, number | null>;
  calculation: CompensationCalculationMeta;
  pagination: Pagination;
}

export interface CpmAlertRow {
  creator_key: string;
  creator_name: string;
  creator_category: "GRASSROOT" | "LONG_TERM" | "COMMENTARY";
  contract_types: string[];
  settlement_status: string | null;
  all_video_views: number;
  youdao_receivable_usd: number;
  cpm: number | null;
  previous_cpm: number | null;
  cpm_change_rate: number | null;
  source: "locked_version" | "cache";
  calculation_status: string;
  calculated_at: string | null;
  stale_reason: string | null;
}

export interface CpmAlertMeta {
  period_month: string;
  comparison_month: string | null;
  read_only: true;
  sources: Array<{
    category: string;
    source: "locked_version" | "cache" | "unavailable";
    status: string;
    calculated_at: string | null;
    stale_reason: string | null;
  }>;
  comparison_sources: Array<{
    category: string;
    source: "locked_version" | "cache" | "unavailable";
    status: string;
    calculated_at: string | null;
    stale_reason: string | null;
  }>;
}

export interface GrassrootRow {
  creator_key: string;
  creator_name: string;
  contract_types: string[];
  followers: number | null;
  youtube_followers: number | null;
  tiktok_followers: number | null;
  settlement_status: string;
  rank: string;
  settlement_subtype: string | null;
  contract_billable_views: number;
  billable_post_count: number;
  billable_views: number;
  all_video_views: number;
  cpm_views_no_boost: number;
  rewards_jpy: {
    short_rank: number;
    long_livestream_rank: number;
    short_post: number;
    long_livestream_post: number;
  };
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
  contract_start_date: string | null;
  contract_end_date: string | null;
  settlement_status: string;
  rank: string;
  followers: number | null;
  youtube_post_count: number;
  monthly_new_post_views: number;
  cpm_views_no_boost: number;
  monthly_activity_count: number | null;
  activity_threshold: number | null;
  rank_reward_jpy: number;
  expected_cpm_jpy: number | null;
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
  youtube_uid: string | null;
  youtube_followers: number;
  tiktok_uid: string | null;
  tiktok_followers: number;
  short_platform: string | null;
  long_views: number;
  long_view_rank: string | null;
  long_follower_cap_rank: string | null;
  long_final_rank: string | null;
  long_reward_jpy: number;
  short_views: number;
  short_view_rank: string | null;
  short_follower_cap_rank: string | null;
  short_final_rank: string | null;
  short_reward_jpy: number;
  combined_bonus_rank: string | null;
  combined_bonus_jpy: number;
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
  id: number | null;
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
  definitions?: ThemeDefinition[];
  eligible_creators?: ThemeCreatorOption[];
}

export interface ThemeDefinition {
  period_month: string;
  theme_code: string;
  theme_name: string;
  description: string | null;
  max_per_creator: number;
  reward_jpy: number;
  enabled: boolean;
}

export interface ThemeCreatorOption {
  id: number;
  creator_key: string;
  creator_name: string;
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
  last_progress_at: string | null;
  current_index: number;
  current_record_id: number | null;
  current_koc_name: string | null;
  error_code: string | null;
  error_message: string | null;
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

// --- Agent ---

export interface AgentStatus {
  configured: boolean;
  provider: "deepseek" | "openai";
  provider_label: string;
  model: string;
  read_only: boolean;
  write_enabled?: boolean;
  writes_require_confirmation?: boolean;
}

export interface AgentMessage {
  role: "user" | "assistant";
  content: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
  tool_calls?: AgentToolEvidence[];
  visualizations?: AgentVisualization[];
  pending_actions?: AgentPendingAction[];
}

export interface AgentToolEvidence {
  tool_name: string;
  summary: Record<string, unknown>;
  duration_ms: number;
}

export interface AgentReply {
  conversation_id: string;
  answer: string;
  tool_calls: AgentToolEvidence[];
  visualizations: AgentVisualization[];
  pending_actions: AgentPendingAction[];
}

export interface AgentPendingAction {
  action_id: string;
  tool_name: string;
  preview: Record<string, unknown>;
  expires_in_seconds: number;
}

export interface AgentActionResult {
  status: "rejected" | "executed" | "pending" | "approved" | "failed" | string;
  action_id: string;
  result?: Record<string, unknown>;
  result_summary?: Record<string, unknown> | null;
}

export interface AgentVisualizationSeries {
  key: "baseline" | "current";
  label: string;
  color: string;
}

export interface AgentVisualizationRow {
  category: string;
  baseline: number;
  current: number;
  change: number;
  change_rate: number | null;
  decline_over_30_percent: boolean;
}

export interface AgentVisualizationWarning {
  level: "danger";
  message: string;
}

export interface AgentVisualization {
  schema_version: 1;
  id: string;
  kind: "grouped_bar";
  title: string;
  subtitle: string;
  category_key: "category";
  value_format: "integer";
  series: AgentVisualizationSeries[];
  data: AgentVisualizationRow[];
  warnings: AgentVisualizationWarning[];
  source: {
    tool: "compare_creator_months";
    database_backed: true;
    creator_id: number | null;
    creator_name: string;
    periods: string[];
  };
}
