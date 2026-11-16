"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type Newsletter = components["schemas"]["NewsletterOut"];
export type Audience = components["schemas"]["Audience"];
export type Recipient = components["schemas"]["RecipientOut"];

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  scheduled: "Scheduled",
  sending: "Sending",
  sent: "Sent",
  cancelled: "Cancelled",
};

export function useNewsletters() {
  return useQuery({ queryKey: ["newsletters"], queryFn: async () => unwrap(await api.GET("/api/v1/newsletters")) });
}

export function useNewsletter(id: string) {
  return useQuery({
    queryKey: ["newsletter", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/newsletters/{nl_id}", { params: { path: { nl_id: id } } })),
    refetchInterval: (q) => (q.state.data && ["sending", "scheduled"].includes(q.state.data.status) ? 5000 : false),
  });
}

export function pct(part: number, whole: number): string {
  return whole ? `${Math.round((100 * part) / whole)}%` : "—";
}
