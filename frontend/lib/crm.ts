"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components, paths } from "@/lib/api/schema";

export type Lead = components["schemas"]["LeadOut"];
export type Stage = components["schemas"]["StageOut"];
export type Source = components["schemas"]["SourceOut"];
export type FieldDef = components["schemas"]["FieldOut"];
export type ActivityType = components["schemas"]["TypeOut"];
export type ActivityItem = components["schemas"]["ActivityOut"];
export type TaskItem = components["schemas"]["TaskOut"];
export type FieldOption = { value: string; label: string; parent?: string };
export type LeadQuery = NonNullable<paths["/api/v1/leads"]["get"]["parameters"]["query"]>;
type IdentityIn = components["schemas"]["IdentityIn"];

/** Identity payload with the defaults the API expects. */
export function identity(type: IdentityIn["type"], value: string, extra: Partial<IdentityIn> = {}): IdentityIn {
  return { type, value, is_primary: false, is_whatsapp: false, ...extra };
}

const STALE = 60_000;

export function useStages() {
  return useQuery({ queryKey: ["stages"], staleTime: STALE, queryFn: async () => unwrap(await api.GET("/api/v1/lead-stages")) });
}
export function useSources() {
  return useQuery({ queryKey: ["sources"], staleTime: STALE, queryFn: async () => unwrap(await api.GET("/api/v1/lead-sources")) });
}
export function useFields() {
  return useQuery({ queryKey: ["fields"], staleTime: STALE, queryFn: async () => unwrap(await api.GET("/api/v1/custom-fields")) });
}
export function useActivityTypes() {
  return useQuery({ queryKey: ["activity-types"], staleTime: STALE, queryFn: async () => unwrap(await api.GET("/api/v1/activity-types")) });
}
export function useLeads(query: LeadQuery) {
  return useQuery({
    queryKey: ["leads", query],
    queryFn: async () => unwrap(await api.GET("/api/v1/leads", { params: { query } })),
  });
}
export function useLead(id: string | null) {
  return useQuery({
    queryKey: ["lead", id],
    enabled: Boolean(id),
    queryFn: async () => unwrap(await api.GET("/api/v1/leads/{lead_id}", { params: { path: { lead_id: id! } } })),
  });
}
export function useTimeline(id: string | null) {
  return useQuery({
    queryKey: ["timeline", id],
    enabled: Boolean(id),
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/leads/{lead_id}/activities", { params: { path: { lead_id: id! } } })),
  });
}
export function useLeadTasks(id: string | null) {
  return useQuery({
    queryKey: ["lead-tasks", id],
    enabled: Boolean(id),
    queryFn: async () => unwrap(await api.GET("/api/v1/tasks", { params: { query: { lead_id: id! } } })),
  });
}
export function useMyDay() {
  return useQuery({ queryKey: ["my-day"], queryFn: async () => unwrap(await api.GET("/api/v1/me/day")) });
}

/** After any change to a lead: refresh everything that shows it. */
export function useRefreshLead() {
  const qc = useQueryClient();
  return (lead?: Lead) => {
    if (lead) qc.setQueryData(["lead", lead.id], lead);
    for (const key of ["leads", "timeline", "lead-tasks", "my-day", "lead"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

// ---------- time ----------
const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

/** "in 2 hours", "3 days ago". */
export function relative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  const [value, unit]: [number, Intl.RelativeTimeFormatUnit] =
    abs < 60 ? [diff, "second"] : abs < 3600 ? [diff / 60, "minute"] : abs < 86400 ? [diff / 3600, "hour"] : [diff / 86400, "day"];
  return rtf.format(Math.round(value), unit);
}

/** "Today 4:00 PM", "Tomorrow 11:00 AM", "Fri 10:00 AM", "12 Nov". */
export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const today = new Date();
  const days = Math.round((startOfDay(d) - startOfDay(today)) / 86400000);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (days === 0) return `Today ${time}`;
  if (days === 1) return `Tomorrow ${time}`;
  if (days === -1) return `Yesterday ${time}`;
  if (days > 1 && days < 7) return `${d.toLocaleDateString(undefined, { weekday: "short" })} ${time}`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: days < -300 || days > 300 ? "numeric" : undefined });
}

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export const isOverdue = (iso: string | null | undefined) => Boolean(iso && new Date(iso).getTime() < Date.now());

/** <input type="datetime-local"> value <-> ISO string in the browser's time zone. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
export const fromLocalInput = (value: string) => (value ? new Date(value).toISOString() : null);

/** Quick follow-up choices: tomorrow 10:00, in 2 days 10:00, next week 10:00, in 2 hours. */
export function quickFollowUps(): { label: string; value: string }[] {
  const at = (days: number, hour = 10) => {
    const d = new Date();
    d.setDate(d.getDate() + days);
    d.setHours(hour, 0, 0, 0);
    return toLocalInput(d.toISOString());
  };
  const inTwoHours = new Date(Date.now() + 2 * 3600_000);
  inTwoHours.setMinutes(0, 0, 0);
  return [
    { label: "In 2 hours", value: toLocalInput(inTwoHours.toISOString()) },
    { label: "Tomorrow", value: at(1) },
    { label: "In 2 days", value: at(2) },
    { label: "Next week", value: at(7) },
  ];
}

export function initials(name: string) {
  return name.replace(/[^\p{L}\s]/gu, "").split(/\s+/).filter(Boolean).map((p) => p[0]).join("").slice(0, 2).toUpperCase() || "#";
}

/** Readable value of a custom field. */
export function fieldValue(field: FieldDef, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const options = field.options as FieldOption[];
  if (field.type === "select") return options.find((o) => o.value === value)?.label ?? String(value);
  if (field.type === "multi_select") {
    return (value as string[]).map((v) => options.find((o) => o.value === v)?.label ?? v).join(", ");
  }
  return String(value);
}

/** Readable phone for the common country codes we serve; anything else is shown as stored. */
export function phone(e164: string | null | undefined): string {
  if (!e164) return "";
  const m91 = /^\+91(\d{5})(\d{5})$/.exec(e164);
  if (m91) return `+91 ${m91[1]} ${m91[2]}`;
  const m971 = /^\+971(\d{1,2})(\d{3})(\d{4})$/.exec(e164);
  if (m971) return `+971 ${m971[1]} ${m971[2]} ${m971[3]}`;
  const m1 = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(e164);
  if (m1) return `+1 ${m1[1]} ${m1[2]} ${m1[3]}`;
  return e164;
}
