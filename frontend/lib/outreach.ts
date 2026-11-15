import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type Campaign = components["schemas"]["CampaignOut"];
export type CampaignStep = components["schemas"]["CampaignStepOut"];
export type CampaignStepIn = components["schemas"]["CampaignStepIn"];
export type ImportReport = components["schemas"]["ContactImportOut"];
export type CampaignContact = components["schemas"]["CampaignContactOut"];
export type OutreachConversation = components["schemas"]["OutreachConversation"];
export type OutreachDetail = components["schemas"]["OutreachDetail"];
export type CampaignStats = components["schemas"]["CampaignStatsOut"];

export const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  running: "Running",
  paused: "Paused",
  finished: "Finished",
};

export const PLACE_LABEL: Record<string, string> = {
  pending: "Waiting for launch",
  active: "In progress",
  replied: "Replied",
  finished: "All steps sent",
  stopped: "Stopped",
  bounced: "Bounced",
  unsubscribed: "Unsubscribed",
};

export const REASON_LABEL: Record<string, string> = {
  already_lead: "already a lead",
  converted: "converted to a lead",
  not_interested: "not interested",
  suppressed: "on the do-not-contact list",
  replied: "replied",
  unsubscribed: "unsubscribed",
  bounced: "bounced",
  complaint: "marked as spam",
  all_steps_sent: "all steps sent",
};

export const STATE_LABEL: Record<string, string> = {
  new: "New reply",
  replied: "Answered",
  converted: "Lead",
  not_interested: "Not interested",
  waiting: "Waiting",
};

/** Variables every contact has; CSV columns add more. */
export const CONTACT_VARIABLES = ["first_name", "last_name", "name", "company", "title", "email", "phone", "website", "sender_name", "my_company"];

export function useCampaigns(enabled = true) {
  return useQuery({ queryKey: ["campaigns"], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/campaigns")) });
}

export function useCampaign(id: string) {
  return useQuery({
    queryKey: ["campaigns", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/campaigns/{campaign_id}", { params: { path: { campaign_id: id } } })),
  });
}

export function useCampaignSteps(id: string) {
  return useQuery({
    queryKey: ["campaigns", id, "steps"],
    queryFn: async () => unwrap(await api.GET("/api/v1/campaigns/{campaign_id}/steps", { params: { path: { campaign_id: id } } })),
  });
}

export function useCampaignContacts(id: string, status?: string) {
  return useQuery({
    queryKey: ["campaigns", id, "contacts", status ?? ""],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/campaigns/{campaign_id}/contacts", {
          params: { path: { campaign_id: id }, query: { status: status || undefined, limit: 500 } },
        }),
      ),
  });
}

export function useCampaignStats(id: string) {
  return useQuery({
    queryKey: ["campaigns", id, "stats"],
    queryFn: async () => unwrap(await api.GET("/api/v1/campaigns/{campaign_id}/stats", { params: { path: { campaign_id: id } } })),
  });
}

export function useOutreachInbox(filters: { campaign_id?: string; state?: string; include_auto?: boolean }) {
  return useQuery({
    queryKey: ["outreach-inbox", filters],
    refetchInterval: 30_000,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/outreach/conversations", {
          params: { query: { campaign_id: filters.campaign_id || undefined, state: filters.state || undefined, include_auto: filters.include_auto, limit: 200 } },
        }),
      ),
  });
}

export function useOutreachConversation(id: string | null) {
  return useQuery({
    queryKey: ["outreach-inbox", "one", id],
    enabled: !!id,
    queryFn: async () => unwrap(await api.GET("/api/v1/outreach/conversations/{conv_id}", { params: { path: { conv_id: id as string } } })),
  });
}

export function useRefreshOutreach() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["campaigns"] });
    qc.invalidateQueries({ queryKey: ["outreach-inbox"] });
  };
}
