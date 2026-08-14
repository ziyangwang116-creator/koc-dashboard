import type {
  ComparisonSeries,
  DashboardDailyRow,
  DashboardSummaryRow,
} from "@/lib/types";

export interface OperatingMetrics {
  totalViews: number;
  totalPosts: number;
  coveredCreators: number;
  averageViews: number;
}

export interface DailyComparisonPoint {
  day: number;
  label: string;
  current: number;
  previous: number;
}

export interface DimensionComparisonPoint {
  name: string;
  current: number;
  previous: number;
  changeRate: number | null;
}

export interface CreatorMovement {
  creatorKey: string;
  creatorName: string;
  previousViews: number;
  currentViews: number;
  viewDelta: number;
  viewChangeRate: number | null;
  previousPosts: number;
  currentPosts: number;
  postDelta: number;
  postChangeRate: number | null;
  longChangeRate: number | null;
  shortsChangeRate: number | null;
  livestreamChangeRate: number | null;
  tiktokChangeRate: number | null;
  warning: boolean;
}

export function changeRate(previous: number, current: number): number | null {
  if (previous === 0) return current === 0 ? 0 : null;
  return (current - previous) / previous;
}

export function summarizeOperatingMetrics(
  rows: DashboardSummaryRow[]
): OperatingMetrics {
  const active = rows.filter((row) => row.post_count > 0 && Boolean(row.creator_key));
  const totalViews = active.reduce((sum, row) => sum + row.total_views, 0);
  const totalPosts = active.reduce((sum, row) => sum + row.post_count, 0);
  return {
    totalViews,
    totalPosts,
    coveredCreators: new Set(active.map((row) => row.creator_key)).size,
    averageViews: totalPosts > 0 ? totalViews / totalPosts : 0,
  };
}

export function buildDailyComparison(
  currentRows: DashboardDailyRow[],
  previousRows: DashboardDailyRow[],
  mode: "daily_views" | "cumulative_views" | "daily_posts"
): DailyComparisonPoint[] {
  const currentByDay = new Map(
    currentRows.map((row) => [Number(row.publish_date.slice(-2)), row])
  );
  const previousByDay = new Map(
    previousRows.map((row) => [Number(row.publish_date.slice(-2)), row])
  );
  const maxDay = Math.max(
    0,
    ...currentByDay.keys(),
    ...previousByDay.keys()
  );
  let currentRunning = 0;
  let previousRunning = 0;

  return Array.from({ length: maxDay }, (_, index) => {
    const day = index + 1;
    const currentRow = currentByDay.get(day);
    const previousRow = previousByDay.get(day);
    const currentValue =
      mode === "daily_posts" ? currentRow?.post_count ?? 0 : currentRow?.total_views ?? 0;
    const previousValue =
      mode === "daily_posts" ? previousRow?.post_count ?? 0 : previousRow?.total_views ?? 0;
    if (mode === "cumulative_views") {
      currentRunning += currentValue;
      previousRunning += previousValue;
    }
    return {
      day,
      label: `${day}日`,
      current: mode === "cumulative_views" ? currentRunning : currentValue,
      previous: mode === "cumulative_views" ? previousRunning : previousValue,
    };
  });
}

export function buildDimensionComparison(
  series: ComparisonSeries[],
  metric: "views" | "posts"
): DimensionComparisonPoint[] {
  return series
    .map((row) => {
      const previousPoint = row.points[0];
      const currentPoint = row.points.at(-1);
      const previous =
        metric === "posts" ? previousPoint?.post_count ?? 0 : previousPoint?.value ?? 0;
      const current =
        metric === "posts" ? currentPoint?.post_count ?? 0 : currentPoint?.value ?? 0;
      return {
        name: row.group_label,
        current,
        previous,
        changeRate: changeRate(previous, current),
      };
    })
    .sort((a, b) => b.current - a.current);
}

function breakdownRate(row: ComparisonSeries, key: string): number | null {
  return row.breakdown?.[key]?.change_rate ?? null;
}

export function buildCreatorMovements(
  series: ComparisonSeries[]
): CreatorMovement[] {
  return series
    .map((row) => {
      const previousViews = row.points[0]?.value ?? 0;
      const currentViews = row.points.at(-1)?.value ?? 0;
      const previousPosts = row.points[0]?.post_count ?? 0;
      const currentPosts = row.points.at(-1)?.post_count ?? 0;
      const viewChangeRate = changeRate(previousViews, currentViews);
      const postChangeRate = changeRate(previousPosts, currentPosts);
      return {
        creatorKey: row.group_key,
        creatorName: row.group_label,
        previousViews,
        currentViews,
        viewDelta: currentViews - previousViews,
        viewChangeRate,
        previousPosts,
        currentPosts,
        postDelta: currentPosts - previousPosts,
        postChangeRate,
        longChangeRate: breakdownRate(row, "long"),
        shortsChangeRate: breakdownRate(row, "shorts"),
        livestreamChangeRate: breakdownRate(row, "livestream"),
        tiktokChangeRate: breakdownRate(row, "tiktok"),
        warning:
          viewChangeRate !== null && viewChangeRate <= -0.3
            ? true
            : postChangeRate !== null && postChangeRate <= -0.3,
      };
    })
    .filter((row) => row.previousPosts > 0 || row.currentPosts > 0)
    .sort((a, b) => b.currentViews - a.currentViews);
}
