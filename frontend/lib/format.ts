import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...c: ClassValue[]) => twMerge(clsx(c));

/** Indian digit grouping, e.g. 2,73,18,288 */
export function inr(x: number | null | undefined, decimals = 0, symbol = true): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const s = new Intl.NumberFormat("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(x);
  return symbol ? `₹${s}` : s;
}

export function compactInr(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  const a = Math.abs(x);
  if (a >= 1e7) return `₹${(x / 1e7).toFixed(2)} cr`;
  if (a >= 1e5) return `₹${(x / 1e5).toFixed(2)} L`;
  return inr(x, 0);
}

export function num(x: number | null | undefined, d = 2): string {
  if (x === null || x === undefined) return "—";
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).format(x);
}

export function title(s?: string | null) {
  return (s || "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export function when(s?: string | null) {
  if (!s) return "—";
  const d = new Date(s);
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export const STATUS_TONE: Record<string, "green" | "amber" | "red" | "slate" | "blue" | "violet"> = {
  QUOTED: "green", ELIGIBLE: "green", PASS: "green", SUCCEEDED: "green", READY: "green", APPROVED: "green",
  NEEDS_REVIEW: "amber", PENDING: "amber", NEEDS_CLARIFICATION: "amber", RUNNING: "blue", QUEUED: "blue", PROCESSING: "blue",
  NOT_COMPARABLE: "violet", UNREADABLE: "red", FAILED: "red", FAIL: "red", INELIGIBLE: "red", BLOCKING: "red",
  NOT_QUOTED: "slate", AI_UNAVAILABLE: "slate", AWAITING: "slate", DRAFT: "slate", WARNING: "amber", INFO: "slate",
  RECEIVED: "blue", EVALUATION: "blue", PUBLISHED: "blue", AWARDED: "green", PREFERRED: "violet", SUPERSEDED: "slate",
};
