"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type KeyAccount = components["schemas"]["AccountRow"];
export type KeyAccountDetail = components["schemas"]["AccountDetail"];
export type Grid = components["schemas"]["GridOut"];
export type Cell = components["schemas"]["CellOut"];
export type Person = components["schemas"]["PersonOut"];
export type Unit = components["schemas"]["UnitOut"];
export type Competitor = components["schemas"]["CompetitorOut"];

/** Is the key accounts add-on switched on for this company? */
export function useKeyAccountsOn() {
  const q = useQuery({ queryKey: ["modules"], staleTime: 60_000, queryFn: async () => unwrap(await api.GET("/api/v1/modules")) });
  return Boolean(q.data?.find((m) => m.key === "key_accounts")?.enabled);
}

export function useKeyAccounts(query: { q?: string; tier?: "strategic" | "growth" | "maintain"; health?: "on_track" | "at_risk" | "off_track"; mine?: boolean }, enabled = true) {
  return useQuery({ queryKey: ["key-accounts", query], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/key-accounts", { params: { query } })) });
}
export function useKeyAccount(id: string) {
  return useQuery({ queryKey: ["key-account", id], queryFn: async () => unwrap(await api.GET("/api/v1/key-accounts/{account_id}", { params: { path: { account_id: id } } })) });
}
export function useLeadKeyAccount(leadId: string, enabled = true) {
  return useQuery({ queryKey: ["key-account", "of-lead", leadId], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/leads/{lead_id}/key-account", { params: { path: { lead_id: leadId } } })) });
}
export function useGrid(id: string) {
  return useQuery({ queryKey: ["key-account", id, "grid"], queryFn: async () => unwrap(await api.GET("/api/v1/key-accounts/{account_id}/grid", { params: { path: { account_id: id } } })) });
}
export function usePeopleMap(id: string) {
  return useQuery({ queryKey: ["key-account", id, "people"], queryFn: async () => unwrap(await api.GET("/api/v1/key-accounts/{account_id}/people", { params: { path: { account_id: id } } })) });
}
export function useCompetitors() {
  return useQuery({ queryKey: ["competitors"], queryFn: async () => unwrap(await api.GET("/api/v1/competitors")) });
}

export function useRefreshAccounts() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["key-accounts", "key-account", "competitors", "timeline", "deals"]) qc.invalidateQueries({ queryKey: [key] });
  };
}

export const TIER: Record<string, { label: string; tone: string }> = {
  strategic: { label: "Strategic", tone: "bg-violet-500/10 text-violet-700 dark:text-violet-300" },
  growth: { label: "Growth", tone: "bg-sky-500/10 text-sky-700 dark:text-sky-300" },
  maintain: { label: "Maintain", tone: "bg-muted text-muted-foreground" },
};
export const HEALTH: Record<string, { label: string; dot: string }> = {
  on_track: { label: "On track", dot: "bg-emerald-500" },
  at_risk: { label: "At risk", dot: "bg-amber-500" },
  off_track: { label: "Off track", dot: "bg-red-500" },
};
export const ROLE: Record<string, string> = { decision_maker: "Decision maker", influencer: "Influencer", user: "User", gatekeeper: "Gatekeeper" };
export const STANCE: Record<string, { label: string; tone: string }> = {
  champion: { label: "Champion", tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" },
  supporter: { label: "Supporter", tone: "bg-sky-500/10 text-sky-700 dark:text-sky-300" },
  neutral: { label: "Neutral", tone: "bg-muted text-muted-foreground" },
  blocker: { label: "Blocker", tone: "bg-red-500/10 text-red-700 dark:text-red-300" },
};
export const CELL: Record<string, { label: string; tone: string }> = {
  won: { label: "Won", tone: "bg-emerald-500/15 text-emerald-800 dark:text-emerald-200" },
  open: { label: "In progress", tone: "bg-sky-500/15 text-sky-800 dark:text-sky-200" },
  lost: { label: "Lost", tone: "bg-red-500/10 text-red-700 dark:text-red-300" },
  competitor: { label: "Competitor", tone: "bg-amber-500/15 text-amber-800 dark:text-amber-200" },
  not_fit: { label: "Not a fit", tone: "bg-muted text-muted-foreground line-through" },
  empty: { label: "Open space", tone: "bg-background text-muted-foreground border border-dashed" },
};
