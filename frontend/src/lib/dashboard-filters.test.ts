import { describe, it, expect } from "vitest";
import {
  buildCommonParams,
  defaultDashboardFilters,
  filtersQueryKey,
  isDropOverThreshold,
  periodLabel,
} from "@/lib/dashboard-filters";

describe("dashboard-filters", () => {
  it("defaults to month mode with no extra filters selected", () => {
    const state = defaultDashboardFilters("2026-07");
    expect(state.periodMode).toBe("month");
    expect(state.periodMonth).toBe("2026-07");
    expect(state.creatorKey).toEqual([]);
  });

  it("builds month-mode params without week/custom fields", () => {
    const state = defaultDashboardFilters("2026-07");
    const params = buildCommonParams(state);
    expect(params.period_mode).toBe("month");
    expect(params.period_month).toBe("2026-07");
    expect(params.week_start).toBeUndefined();
  });

  it("builds week-mode params with week_start only", () => {
    const state = { ...defaultDashboardFilters(), periodMode: "week" as const, weekStart: "2026-07-28" };
    const params = buildCommonParams(state);
    expect(params.period_mode).toBe("week");
    expect(params.week_start).toBe("2026-07-28");
    expect(params.period_month).toBeUndefined();
  });

  it("produces a stable, order-independent query key", () => {
    const a = { ...defaultDashboardFilters("2026-07"), creatorKey: ["b", "a"] };
    const b = { ...defaultDashboardFilters("2026-07"), creatorKey: ["a", "b"] };
    expect(filtersQueryKey(a)).toEqual(filtersQueryKey(b));
  });

  it("changes query key when the filter month changes (scoped invalidation)", () => {
    const a = defaultDashboardFilters("2026-06");
    const b = defaultDashboardFilters("2026-07");
    expect(filtersQueryKey(a)).not.toEqual(filtersQueryKey(b));
  });

  it("labels the period for month/week/custom modes", () => {
    expect(periodLabel(defaultDashboardFilters("2026-07"))).toBe("2026-07");
    expect(
      periodLabel({ ...defaultDashboardFilters(), periodMode: "week", weekStart: "2026-07-28" })
    ).toContain("2026-07-28");
  });

  it("flags a drop of more than 30% as warning-worthy", () => {
    expect(isDropOverThreshold(-0.31)).toBe(true);
    expect(isDropOverThreshold(-0.3)).toBe(true);
    expect(isDropOverThreshold(-0.29)).toBe(false);
    expect(isDropOverThreshold(null)).toBe(false);
  });
});
