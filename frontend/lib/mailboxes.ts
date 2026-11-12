import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type Mailbox = components["schemas"]["MailboxOut"];
export type MailboxIn = components["schemas"]["MailboxIn"];

/** Provider settings filled in for the user. Outlook / Microsoft 365 no longer accept app
 * passwords; they come with one-click Microsoft sign-in (step 9b-4). */
export const PROVIDERS = {
  gmail: { label: "Gmail / Google Workspace", imap_host: "imap.gmail.com", imap_port: 993, smtp_host: "smtp.gmail.com", smtp_port: 587, smtp_security: "starttls" },
  zoho_in: { label: "Zoho Mail (India)", imap_host: "imap.zoho.in", imap_port: 993, smtp_host: "smtp.zoho.in", smtp_port: 465, smtp_security: "ssl" },
  zoho: { label: "Zoho Mail", imap_host: "imap.zoho.com", imap_port: 993, smtp_host: "smtp.zoho.com", smtp_port: 465, smtp_security: "ssl" },
  other: { label: "Other mail server", imap_host: "", imap_port: 993, smtp_host: "", smtp_port: 587, smtp_security: "starttls" },
} as const;
export type ProviderKey = keyof typeof PROVIDERS;

export function providerOf(mb: Mailbox | null | undefined): ProviderKey {
  if (!mb) return "gmail";
  const hit = (Object.keys(PROVIDERS) as ProviderKey[]).find((k) => k !== "other" && PROVIDERS[k].imap_host === mb.imap_host);
  return hit ?? "other";
}

export function useMyMailbox(enabled = true) {
  return useQuery({
    queryKey: ["mailbox", "me"],
    enabled,
    refetchInterval: 30_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/me/mailbox")) ?? null,
  });
}

export function useMailboxes(enabled = true) {
  return useQuery({
    queryKey: ["mailbox", "all"],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/mailboxes")),
  });
}

export function useExclusions(enabled = true) {
  return useQuery({
    queryKey: ["mailbox", "exclusions"],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/mailboxes/exclusions")),
  });
}

export function useMyCopyIn(enabled = true) {
  return useQuery({
    queryKey: ["copy-in", "me"],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/me/copy-in")),
  });
}

export function useCompanyCopyIn(enabled = true) {
  return useQuery({
    queryKey: ["copy-in", "company"],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/copy-in")),
  });
}
