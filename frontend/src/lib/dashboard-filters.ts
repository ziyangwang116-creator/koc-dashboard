// Pure helpers for building dashboard query params from filter UI state.
// Kept side-effect free so they can be unit tested without mocking fetch.

export type PeriodMode = "month" | "week" | "custom";

export interface DashboardFilterState {
  periodMode: PeriodMode;
  periodMonth?: string;
  weekStart?: string;
  startDate?: string;
  endDate?: string;
  creatorKey: string[];
  creatorCategory: string[];
  sourcePlatform: string[];
  contentType: string[];
  includeCrossIndustry: boolean;
}

export function defaultDashboardFilters(defaultMonth?: string): DashboardFilterState {
  return {
    periodMode: "month",
    periodMonth: defaultMonth,
    creatorKey: [],
    creatorCategory: [],
    sourcePlatform: [],
    contentType: [],
    includeCrossIndustry: false,
  };
}

/** Build the query-param object shared by summary/posts/rankings requests. */
export function buildCommonParams(state: DashboardFilterState): Record<string, unknown> {
  const params: Record<string, unknown> = {
    period_mode: state.periodMode,
    creator_key: state.creatorKey,
    creator_category: state.creatorCategory,
    source_platform: state.sourcePlatform,
    content_type: state.contentType,
    include_cross_industry: state.includeCrossIndustry,
  };
  if (state.periodMode === "month") {
    params.period_month = state.periodMonth;
  } else if (state.periodMode === "week") {
    params.week_start = state.weekStart;
  } else {
    params.start_date = state.startDate;
    params.end_date = state.endDate;
  }
  return params;
}

/** Stable, order-independent query key fragment for TanStack Query. */
export function filtersQueryKey(state: DashboardFilterState): unknown[] {
  return [
    state.periodMode,
    state.periodMonth ?? null,
    state.weekStart ?? null,
    state.startDate ?? null,
    state.endDate ?? null,
    [...state.creatorKey].sort(),
    [...state.creatorCategory].sort(),
    [...state.sourcePlatform].sort(),
    [...state.contentType].sort(),
    state.includeCrossIndustry,
  ];
}

export function periodLabel(state: DashboardFilterState): string {
  if (state.periodMode === "month") return state.periodMonth ?? "未选择月份";
  if (state.periodMode === "week")
    return state.weekStart ? `周：${state.weekStart} 起` : "未选择周";
  return state.startDate && state.endDate
    ? `${state.startDate} ~ ${state.endDate}`
    : "未选择自定义区间";
}

export function isDropOverThreshold(changeRate: number | null): boolean {
  return changeRate !== null && changeRate <= -0.3;
}
