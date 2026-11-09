"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components, paths } from "@/lib/api/schema";

export type Pipeline = components["schemas"]["PipelineOut"];
export type PipelineStage = components["schemas"]["PipelineStageOut"];
export type Deal = components["schemas"]["DealOut"];
export type DealLine = components["schemas"]["LineOut"];
export type Board = components["schemas"]["BoardOut"];
export type LostReason = components["schemas"]["LostReasonOut"];
export type Product = components["schemas"]["ProductOut"];
export type DealQuery = NonNullable<paths["/api/v1/deals"]["get"]["parameters"]["query"]>;

export function usePipelines() {
  return useQuery({ queryKey: ["pipelines"], staleTime: 60_000, queryFn: async () => unwrap(await api.GET("/api/v1/pipelines")) });
}
export function useLostReasons() {
  return useQuery({ queryKey: ["lost-reasons"], staleTime: 60_000, queryFn: async () => unwrap(await api.GET("/api/v1/lost-reasons")) });
}
export function useProducts(query: { active?: boolean; currency?: string } = {}) {
  return useQuery({ queryKey: ["products", query], queryFn: async () => unwrap(await api.GET("/api/v1/products", { params: { query } })) });
}
export function useBoard(query: { pipeline_id?: string; owner?: string[]; q?: string }) {
  return useQuery({ queryKey: ["deals", "board", query], queryFn: async () => unwrap(await api.GET("/api/v1/deals/board", { params: { query } })) });
}
export function useDeals(query: DealQuery, enabled = true) {
  return useQuery({ queryKey: ["deals", "list", query], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/deals", { params: { query } })) });
}
export function useDeal(id: string) {
  return useQuery({ queryKey: ["deal", id], queryFn: async () => unwrap(await api.GET("/api/v1/deals/{deal_id}", { params: { path: { deal_id: id } } })) });
}
export function useDealLines(id: string) {
  return useQuery({
    queryKey: ["deal-lines", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/deals/{deal_id}/products", { params: { path: { deal_id: id } } })),
  });
}
export function useDealTimeline(id: string) {
  return useQuery({
    queryKey: ["deal-timeline", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/deals/{deal_id}/activities", { params: { path: { deal_id: id } } })),
  });
}
export function useDealTasks(id: string) {
  return useQuery({ queryKey: ["deal-tasks", id], queryFn: async () => unwrap(await api.GET("/api/v1/tasks", { params: { query: { deal_id: id } } })) });
}
export function useDealFields() {
  return useQuery({ queryKey: ["fields", "deal"], queryFn: async () => unwrap(await api.GET("/api/v1/custom-fields", { params: { query: { entity: "deal" } } })) });
}

/** After any deal change: refresh everything that shows deals (and the lead's timeline). */
export function useRefreshDeals() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["deals", "deal", "deal-lines", "deal-timeline", "deal-tasks", "links", "timeline", "lead", "pipelines"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

// ---------- money (rule 7: integer minor units; never floats for amounts) ----------
const digitsCache = new Map<string, number>();
/** Minor-unit digits of a currency: INR 2, JPY 0, KWD 3. */
export function currencyDigits(currency: string): number {
  if (!digitsCache.has(currency)) {
    let d = 2;
    try {
      d = new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;
    } catch {}
    digitsCache.set(currency, d);
  }
  return digitsCache.get(currency)!;
}

/** "₹69,999" from 6999900 minor units. Whole amounts drop the decimals; exact via BigInt. */
export function formatMoney(minor: number, currency: string, opts: { compact?: boolean } = {}): string {
  const d = currencyDigits(currency);
  const scale = BigInt(10) ** BigInt(d);
  const big = BigInt(minor);
  const whole = big / scale;
  const frac = big % scale;
  const fmt = (n: number | bigint, fd: number, notation?: "compact") =>
    new Intl.NumberFormat("en-IN", { style: "currency", currency, minimumFractionDigits: fd, maximumFractionDigits: fd, notation }).format(n as number);
  if (opts.compact && whole >= BigInt(100000)) return fmt(Number(whole), 0, "compact").replace(/\.0(?=\D*$)/, "");
  if (frac === BigInt(0)) return fmt(whole, 0);
  // Show the fraction exactly: format the whole part, then append the digits.
  const base = fmt(whole, 0);
  return `${base}.${frac.toString().padStart(d, "0")}`;
}

/** "69,999.50" → 6999950 minor units, exactly (string arithmetic). null when not a number. */
export function parseMoney(text: string, currency: string): number | null {
  const d = currencyDigits(currency);
  const clean = text.replace(/[\s,_]/g, "").replace(/^[^\d.]+/, "");
  if (!clean) return 0;
  const m = clean.match(/^(\d+)(?:\.(\d*))?$/);
  if (!m) return null;
  const frac = m[2] ?? "";
  if (frac.length > d) return null;
  const minor = BigInt(m[1]) * BigInt(10) ** BigInt(d) + BigInt((frac + "0".repeat(d)).slice(0, d) || "0");
  if (minor > BigInt(10) ** BigInt(15)) return null;
  return Number(minor);
}

/** 6999900 → "69999" (for an input box; exact). */
export function moneyInput(minor: number, currency: string): string {
  const d = currencyDigits(currency);
  if (d === 0) return String(minor);
  const s = String(minor).padStart(d + 1, "0");
  const frac = s.slice(-d).replace(/0+$/, "");
  return s.slice(0, -d) + (frac ? `.${frac}` : "");
}
