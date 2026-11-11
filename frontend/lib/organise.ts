"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type Tag = components["schemas"]["TagOut"];
export type TagRef = components["schemas"]["TagRef"];
export type SavedView = components["schemas"]["ViewOut"];
export type ScoreRule = components["schemas"]["ScoreRuleOut"];
export type ScoreSettings = components["schemas"]["ScoreSettings"];
export type Automation = components["schemas"]["AutomationOut"];
export type AutomationRun = components["schemas"]["RunOut"];
export type Condition = { field: string; op: string; value?: unknown };

export function useTags() {
  return useQuery({ queryKey: ["tags"], staleTime: 30_000, queryFn: async () => unwrap(await api.GET("/api/v1/tags")) });
}
export function useViews(entity: "leads" | "deals") {
  return useQuery({ queryKey: ["views", entity], queryFn: async () => unwrap(await api.GET("/api/v1/views", { params: { query: { entity } } })) });
}
export function useScoreRules() {
  return useQuery({ queryKey: ["score-rules"], queryFn: async () => unwrap(await api.GET("/api/v1/score-rules")) });
}
export function useScoreSettings() {
  return useQuery({ queryKey: ["score-settings"], queryFn: async () => unwrap(await api.GET("/api/v1/score-settings")) });
}
export function useLeadScore(leadId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["lead-score", leadId],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/leads/{lead_id}/score", { params: { path: { lead_id: leadId } } })),
  });
}
export function useAutomations() {
  return useQuery({ queryKey: ["automations"], queryFn: async () => unwrap(await api.GET("/api/v1/automations")) });
}
export function useAutomationRuns(id: string | null) {
  return useQuery({
    queryKey: ["automation-runs", id],
    enabled: Boolean(id),
    refetchInterval: 10_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/automations/{auto_id}/runs", { params: { path: { auto_id: id! } } })),
  });
}

/** After tags change on anything: refresh lists, records and the tag list. */
export function useRefreshTags() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["tags", "leads", "lead", "deals", "deal", "timeline", "deal-timeline", "lead-score"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

// Plain words for conditions and actions (the builder and the list both use them).
export const OPS: [string, string][] = [
  ["is", "is"],
  ["is_not", "is not"],
  ["any_of", "is any of"],
  ["none_of", "is none of"],
  ["contains", "contains"],
  ["empty", "is empty"],
  ["not_empty", "is not empty"],
  ["gt", "is more than"],
  ["lt", "is less than"],
];
export const NO_VALUE_OPS = new Set(["empty", "not_empty"]);
export const LIST_OPS = new Set(["any_of", "none_of"]);

export const BAND_LABEL: Record<string, string> = { hot: "Hot", warm: "Warm", cold: "Cold" };
export const BAND_STYLE: Record<string, string> = {
  hot: "bg-red-500/15 text-red-700 dark:text-red-400",
  warm: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  cold: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
};
