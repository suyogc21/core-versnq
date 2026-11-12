import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type Sequence = components["schemas"]["SequenceOut"];
export type SequenceStep = components["schemas"]["StepOut"];
export type StepIn = components["schemas"]["StepIn"];
export type Template = components["schemas"]["TemplateOut"];
export type Enrolment = components["schemas"]["EnrolmentOut"];

export function useSequences(enabled = true) {
  return useQuery({ queryKey: ["sequences"], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/sequences")) });
}

export function useSequence(id: string) {
  return useQuery({ queryKey: ["sequences", id], queryFn: async () => unwrap(await api.GET("/api/v1/sequences/{s_id}", { params: { path: { s_id: id } } })) });
}

export function useSequenceStats(id: string) {
  return useQuery({
    queryKey: ["sequences", id, "stats"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sequences/{s_id}/stats", { params: { path: { s_id: id } } })),
  });
}

export function useSequenceEnrolments(id: string) {
  return useQuery({
    queryKey: ["sequences", id, "enrolments"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sequences/{s_id}/enrolments", { params: { path: { s_id: id } } })),
  });
}

export function useTemplates(enabled = true) {
  return useQuery({ queryKey: ["templates"], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/templates")) });
}

export function useLeadSequences(leadId: string) {
  return useQuery({
    queryKey: ["lead-sequences", leadId],
    queryFn: async () => unwrap(await api.GET("/api/v1/leads/{lead_id}/sequences", { params: { path: { lead_id: leadId } } })),
  });
}

export function useRefreshSequences() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["sequences", "templates", "lead-sequences", "timeline", "lead"]) qc.invalidateQueries({ queryKey: [k] });
  };
}

/** Put leads into a sequence; returns a sentence for a toast. */
export async function enrolLeads(sequenceId: string, leadIds: string[]): Promise<{ ok: boolean; text: string }> {
  const r = unwrap(await api.POST("/api/v1/sequences/{s_id}/enrol", { params: { path: { s_id: sequenceId } }, body: { lead_ids: leadIds } }));
  if (!r.skipped.length) return { ok: true, text: `Added ${r.enrolled} to the sequence` };
  const first = r.skipped[0];
  return { ok: r.enrolled > 0, text: `Added ${r.enrolled}. Skipped ${r.skipped.length}: ${first.name ?? "one"} — ${first.reason}${r.skipped.length > 1 ? " …" : ""}` };
}

export const VARIABLES: [string, string][] = [
  ["{{lead.first_name|there}}", "First name"],
  ["{{lead.name}}", "Full name"],
  ["{{lead.company}}", "Company"],
  ["{{lead.city}}", "City"],
  ["{{owner.name}}", "Owner's name"],
  ["{{owner.phone}}", "Owner's phone"],
  ["{{company.name}}", "Your company"],
];

export const STOP_LABELS: Record<string, string> = {
  reply: "They reply",
  customer: "They become a customer",
  deal_won: "A deal is won",
  payment: "A payment arrives",
  closed: "The lead is closed",
};

export function describeStep(step: SequenceStep, templates: Template[] | undefined): string {
  const c = step.config as Record<string, unknown>;
  if (step.kind === "email") return `Email: ${templates?.find((t) => t.id === c.template_id)?.name ?? "template"}`;
  if (step.kind === "wait") {
    const h = Number(c.hours);
    return h % 24 === 0 ? `Wait ${h / 24} day${h === 24 ? "" : "s"}` : `Wait ${h} hour${h === 1 ? "" : "s"}`;
  }
  if (step.kind === "task") return `Task for the owner: ${c.title}`;
  if (step.kind === "check") return `Check: if ${c.if}, go to step ${c.go_to}`;
  return step.kind;
}
