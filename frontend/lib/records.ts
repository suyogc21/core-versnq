"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components, paths } from "@/lib/api/schema";

export type RecordType = components["schemas"]["RecordTypeOut"];
export type RecordStage = components["schemas"]["RecordStageOut"];
export type RecordItem = components["schemas"]["RecordOut"];
export type RecordActivity = components["schemas"]["RecordActivityOut"];
export type LinkType = components["schemas"]["LinkTypeOut"];
export type LinkItem = components["schemas"]["LinkOut"];
export type RoleAccess = components["schemas"]["RoleAccess"];
export type RecordQuery = NonNullable<paths["/api/v1/records"]["get"]["parameters"]["query"]>;

/** The record types you may view (the sidebar shows these). */
export function useRecordTypes() {
  return useQuery({ queryKey: ["record-types"], staleTime: 60_000, queryFn: async () => unwrap(await api.GET("/api/v1/record-types")) });
}
/** Admin view: every type, including switched-off ones. */
export function useAllRecordTypes(enabled = true) {
  return useQuery({
    queryKey: ["record-types", "all"],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/record-types", { params: { query: { include_hidden: true } } })),
  });
}
export function useRecordStages(typeId: string | undefined) {
  return useQuery({
    queryKey: ["record-stages", typeId],
    enabled: Boolean(typeId),
    queryFn: async () => unwrap(await api.GET("/api/v1/record-types/{type_id}/stages", { params: { path: { type_id: typeId! } } })),
  });
}
export function useRecordFields(typeKey: string | undefined) {
  return useQuery({
    queryKey: ["fields", `rt:${typeKey}`],
    enabled: Boolean(typeKey),
    queryFn: async () => unwrap(await api.GET("/api/v1/custom-fields", { params: { query: { entity: `rt:${typeKey}` } } })),
  });
}
export function useRecords(query: RecordQuery) {
  return useQuery({ queryKey: ["records", query], queryFn: async () => unwrap(await api.GET("/api/v1/records", { params: { query } })) });
}
export function useRecord(id: string | null) {
  return useQuery({
    queryKey: ["record", id],
    enabled: Boolean(id),
    queryFn: async () => unwrap(await api.GET("/api/v1/records/{record_id}", { params: { path: { record_id: id! } } })),
  });
}
export function useRecordTimeline(id: string) {
  return useQuery({
    queryKey: ["record-timeline", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/records/{record_id}/activities", { params: { path: { record_id: id } } })),
  });
}
export function useRecordTasks(id: string) {
  return useQuery({
    queryKey: ["record-tasks", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/tasks", { params: { query: { record_id: id } } })),
  });
}
export function useLinkTypes() {
  return useQuery({ queryKey: ["link-types"], staleTime: 60_000, queryFn: async () => unwrap(await api.GET("/api/v1/link-types")) });
}
export function useLinks(end: { lead_id?: string; record_id?: string; deal_id?: string }) {
  return useQuery({
    queryKey: ["links", end],
    queryFn: async () => unwrap(await api.GET("/api/v1/links", { params: { query: end } })),
  });
}

/** After any change to records or links: refresh what shows them. */
export function useRefreshRecords() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["records", "record", "record-timeline", "record-tasks", "links", "timeline", "lead", "deal-timeline"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}
