"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

/** The company's SMS texts (batch 5d). */
export function useSmsTemplates(enabled = true) {
  return useQuery({
    queryKey: ["sms-templates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sms/templates")),
    enabled,
  });
}
