"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { formatMoney } from "@/lib/deals";

export type Amount = components["schemas"]["Amount"];
export type MyDashboard = components["schemas"]["MyDashboard"];
export type TeamDashboard = components["schemas"]["TeamDashboard"];
export type BusinessDashboard = components["schemas"]["BusinessDashboard"];
export type MoneyDashboard = components["schemas"]["MoneyDashboard"];
export type Headline = components["schemas"]["Headline"];
export type PeriodKind = "today" | "week" | "month" | "last_month" | "quarter" | "year" | "custom";
export type PeriodQuery = { period: PeriodKind; from?: string; to?: string };

export const PERIODS: { value: PeriodKind; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "week", label: "This week" },
  { value: "month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "quarter", label: "This quarter" },
  { value: "year", label: "This year" },
  { value: "custom", label: "Choose dates" },
];

const ready = (q: PeriodQuery) => q.period !== "custom" || Boolean(q.from && q.to);

export function useMyDashboard(q: PeriodQuery, enabled = true) {
  return useQuery({ queryKey: ["dash", "me", q], enabled: enabled && ready(q), queryFn: async () => unwrap(await api.GET("/api/v1/dashboards/me", { params: { query: q } })) });
}
export function useTeamDashboard(q: PeriodQuery, enabled = true) {
  return useQuery({ queryKey: ["dash", "team", q], enabled: enabled && ready(q), queryFn: async () => unwrap(await api.GET("/api/v1/dashboards/team", { params: { query: q } })) });
}
export function useBusinessDashboard(q: PeriodQuery, enabled = true) {
  return useQuery({ queryKey: ["dash", "business", q], enabled: enabled && ready(q), queryFn: async () => unwrap(await api.GET("/api/v1/dashboards/business", { params: { query: q } })) });
}
export function useMoneyDashboard(q: PeriodQuery, enabled = true) {
  return useQuery({ queryKey: ["dash", "money", q], enabled: enabled && ready(q), queryFn: async () => unwrap(await api.GET("/api/v1/dashboards/money", { params: { query: q } })) });
}

/** "₹1,20,000 · $500": each currency on its own, never added together (rule 7). */
export function amounts(list: Amount[] | undefined, empty = "—"): string {
  if (!list?.length) return empty;
  return list.map((a) => formatMoney(a.minor, a.currency)).join(" · ");
}

/** The change against the previous period, as a short label and a tone. */
export function change(now: number, before: number): { text: string; tone: "up" | "down" | "flat" } | null {
  if (now === before) return before ? { text: "same as before", tone: "flat" } : null;
  if (!before) return { text: "up from nothing before", tone: "up" };
  const pct = Math.round(((now - before) * 100) / before);
  return { text: `${pct > 0 ? "+" : ""}${pct}% vs before`, tone: pct > 0 ? "up" : "down" };
}

type ExportPath = "/api/v1/leads/export" | "/api/v1/deals/export" | "/api/v1/customers/export" | "/api/v1/invoices/export" | "/api/v1/payments/export";

/** Download a list as CSV, with exactly the filters the list shows. */
export async function exportCsv(path: ExportPath, query: Record<string, unknown>, name: string) {
  const clean = Object.fromEntries(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && !v.length)));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- each export takes its own list's filters
  const res = await (api.GET as any)(path, { params: { query: clean }, parseAs: "blob" });
  if (res.error || !res.data) {
    const detail = (res.error as { detail?: string } | undefined)?.detail;
    throw new Error(typeof detail === "string" ? detail : res.response?.status === 403 ? "You are not allowed to export this list" : "Could not export");
  }
  const href = URL.createObjectURL(res.data as Blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = `${name}-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 30_000);
}
