"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useAuth } from "@/lib/auth";
import { applyAccent } from "@/lib/theme";

export type WorkspaceSettings = components["schemas"]["SettingsOut"];
type Label = { singular: string; plural: string };

/** Workspace settings, loaded once the user may use the app. Applies the brand colour. */
export function useWorkspaceSettings() {
  const { me } = useAuth();
  const enabled = Boolean(me && me.restrictions.length === 0);
  const query = useQuery({
    queryKey: ["settings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/settings")),
    enabled,
  });
  const colour = (query.data?.branding as { primary_color?: string } | undefined)?.primary_color;
  useEffect(() => applyAccent(colour), [colour]);
  return query;
}

/** Label for a record type, e.g. label("lead") -> "Student" in an EdTech workspace. */
export function useLabels() {
  const { data } = useWorkspaceSettings();
  const labels = (data?.labels ?? {}) as Record<string, Label>;
  return (key: string, plural = false): string => {
    const l = labels[key];
    if (!l) return key.charAt(0).toUpperCase() + key.slice(1) + (plural ? "s" : "");
    return plural ? l.plural : l.singular;
  };
}
