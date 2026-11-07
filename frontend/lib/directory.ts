"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type User = components["schemas"]["UserOut"];
export type Role = components["schemas"]["app__modules__roles__router__RoleOut"];
export type Team = components["schemas"]["TeamOut"];
export type Permission = components["schemas"]["PermissionOut"];

/** Users the signed-in person may see (the backend applies own / team / all). */
export function useUsers(enabled = true) {
  return useQuery({ queryKey: ["users"], queryFn: async () => unwrap(await api.GET("/api/v1/users")), enabled });
}

export function useRoles() {
  return useQuery({ queryKey: ["roles"], queryFn: async () => unwrap(await api.GET("/api/v1/roles")) });
}

export function useTeams() {
  return useQuery({ queryKey: ["teams"], queryFn: async () => unwrap(await api.GET("/api/v1/teams")) });
}

export function usePermissions(enabled = true) {
  return useQuery({
    queryKey: ["permissions"],
    queryFn: async () => unwrap(await api.GET("/api/v1/permissions")),
    enabled,
  });
}

export const SCOPE_LABEL: Record<string, string> = {
  own: "Own records",
  team: "Their team's records",
  all: "All records",
};
