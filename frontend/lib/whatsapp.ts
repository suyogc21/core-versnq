import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type WaTemplate = components["schemas"]["WaTemplateOut"];
export type WaAccount = components["schemas"]["WaAccountOut"];
export type WaSettings = components["schemas"]["WaSettingsIO"];

/** The company number's templates (anyone who answers the inbox may list them). */
export function useWaTemplates(enabled = true) {
  return useQuery({
    queryKey: ["wa", "templates"],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/whatsapp/templates")),
  });
}

export const WA_STATUS: Record<string, [string, string]> = {
  approved: ["Approved", "text-emerald-700 dark:text-emerald-300"],
  pending: ["Waiting for WhatsApp", "text-amber-700 dark:text-amber-300"],
  rejected: ["Rejected", "text-destructive"],
  paused: ["Paused by WhatsApp", "text-amber-700 dark:text-amber-300"],
  disabled: ["Disabled by WhatsApp", "text-destructive"],
};
