export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("zh-CN").format(Math.round(n));
}

export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `$${n.toFixed(2)}`;
}

export function fmtCpm(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toFixed(2);
}

export function fmtPercent(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

export function isDrop30(changeRate: number | null): boolean {
  return changeRate !== null && changeRate <= -0.3;
}

const CREATOR_CATEGORY_LABELS: Record<string, string> = {
  GRASSROOT: "草根",
  LONG_TERM: "长包",
  COMMENTARY: "解说",
};

export function creatorCategoryLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return CREATOR_CATEGORY_LABELS[value] ?? value;
}
