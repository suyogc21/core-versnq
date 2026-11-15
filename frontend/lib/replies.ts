import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type ReplyCategory = components["schemas"]["CategoryOut"];
export type ReplyRule = components["schemas"]["RuleIO"];
export type Sorting = components["schemas"]["SortingOut"];
export type Draft = components["schemas"]["DraftOut"];

export const ACTION_LABEL: Record<ReplyRule["action"], string> = {
  convert: "Convert to lead (campaign replies)",
  draft: "Ask ACE for a draft",
  stop: "Stop (the campaign, or the lead's sequences)",
  unsubscribe: "Unsubscribe (never email them again)",
  notify: "Tell the owner",
};

export function useReplyCategories(enabled = true) {
  return useQuery({
    queryKey: ["reply-categories"],
    enabled,
    staleTime: 60_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/reply-categories")),
  });
}

export function useSorting(convId: string) {
  return useQuery({
    queryKey: ["sorting", convId],
    refetchInterval: 20_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/conversations/{conv_id}/sorting", { params: { path: { conv_id: convId } } })),
  });
}

export function useRefreshSorting() {
  const qc = useQueryClient();
  return (convId: string) => qc.invalidateQueries({ queryKey: ["sorting", convId] });
}
