import { describe, expect, it } from "vitest";
import {
  buildCreatorMovements,
  buildDailyComparison,
  summarizeOperatingMetrics,
} from "./dashboard-analytics";

describe("dashboard analytics", () => {
  it("summarizes only creators with posts", () => {
    const metrics = summarizeOperatingMetrics([
      { creator_key: "a", post_count: 2, total_views: 300 } as never,
      { creator_key: "b", post_count: 1, total_views: 200 } as never,
      { creator_key: "c", post_count: 0, total_views: 0 } as never,
    ]);

    expect(metrics).toEqual({
      totalViews: 500,
      totalPosts: 3,
      coveredCreators: 2,
      averageViews: 500 / 3,
    });
  });

  it("aligns daily comparison by day of month and supports cumulative views", () => {
    const rows = buildDailyComparison(
      [
        { publish_date: "2026-07-01", post_count: 1, total_views: 100 } as never,
        { publish_date: "2026-07-03", post_count: 1, total_views: 300 } as never,
      ],
      [{ publish_date: "2026-06-02", post_count: 2, total_views: 200 } as never],
      "cumulative_views"
    );

    expect(rows).toEqual([
      { day: 1, label: "1日", current: 100, previous: 0 },
      { day: 2, label: "2日", current: 100, previous: 200 },
      { day: 3, label: "3日", current: 400, previous: 200 },
    ]);
  });

  it("marks creator view or post declines of 30 percent", () => {
    const [movement] = buildCreatorMovements([
      {
        group_key: "creator-a",
        group_label: "Creator A",
        points: [
          { period_label: "2026-06", value: 1000, post_count: 10 },
          { period_label: "2026-07", value: 600, post_count: 8 },
        ],
        change_rate: -0.4,
        warning: true,
        breakdown: {},
      },
    ]);

    expect(movement.viewChangeRate).toBe(-0.4);
    expect(movement.postChangeRate).toBe(-0.2);
    expect(movement.warning).toBe(true);
  });
});
