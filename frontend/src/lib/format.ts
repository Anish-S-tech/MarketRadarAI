import { twMerge } from "tailwind-merge";

/** Joins class names; later Tailwind classes override conflicting earlier ones (e.g. `w-full` + `w-auto`). */
export function cn(...parts: (string | false | null | undefined)[]): string {
  return twMerge(parts.filter(Boolean).join(" "));
}

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
  return new Date(iso).toLocaleDateString();
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function money(value: string | number | null | undefined, currency = "USD", period?: string): string {
  if (value === null || value === undefined || value === "") return "Custom";
  const n = typeof value === "string" ? Number(value) : value;
  const s = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(n);
  return period ? `${s}/${period === "month" ? "mo" : period === "year" ? "yr" : period}` : s;
}

export function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`;
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const CATEGORIES = [
  "pricing",
  "product",
  "feature",
  "positioning",
  "partnership",
  "strategy",
  "leadership",
  "financial",
  "other",
] as const;

export const PRIORITIES = ["critical", "high", "medium", "low"] as const;
export const ROLES = ["admin", "executive", "product", "sales", "marketing", "pricing"] as const;
export const SOURCE_TYPES = ["pricing", "webpage", "changelog", "blog_rss", "news", "sec_filing", "sitemap"] as const;
