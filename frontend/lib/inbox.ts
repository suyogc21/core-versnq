import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type ConversationRow = components["schemas"]["ConversationRow"];
export type ConversationDetail = components["schemas"]["ConversationDetail"];
export type InboxView = "mine" | "waiting" | "shared" | "unassigned" | "all" | "closed";

export function useInbox(view: InboxView, q: string, enabled = true) {
  return useQuery({
    queryKey: ["inbox", view, q],
    enabled,
    refetchInterval: 30_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/inbox", { params: { query: { view, q: q || undefined } } })),
  });
}

export function useInboxCounts(enabled = true) {
  return useQuery({
    queryKey: ["inbox", "counts"],
    enabled,
    refetchInterval: 60_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/inbox/counts")),
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: ["conversation", id],
    enabled: !!id,
    queryFn: async () => unwrap(await api.GET("/api/v1/conversations/{conv_id}", { params: { path: { conv_id: id! } } })),
  });
}

export function useLeadConversations(leadId: string) {
  return useQuery({
    queryKey: ["lead-conversations", leadId],
    queryFn: async () => unwrap(await api.GET("/api/v1/leads/{lead_id}/conversations", { params: { path: { lead_id: leadId } } })),
  });
}

export function usePeople(enabled = true) {
  return useQuery({ queryKey: ["inbox-people"], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/inbox/people")) });
}

export function useCanned() {
  return useQuery({ queryKey: ["canned-replies"], queryFn: async () => unwrap(await api.GET("/api/v1/canned-replies")) });
}

export function useRefreshInbox() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["inbox", "conversation", "lead-conversations", "timeline", "lead", "lead-sequences", "canned-replies"]) qc.invalidateQueries({ queryKey: [k] });
  };
}
