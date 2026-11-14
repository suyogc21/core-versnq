import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

/** The company's module switches (Versnq staff switch them; Decision log #44). Undefined while loading. */
export function useModules(): Record<string, boolean> | undefined {
  const q = useQuery({
    queryKey: ["modules"],
    staleTime: 60_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/modules")),
  });
  return q.data ? Object.fromEntries(q.data.map((m) => [m.key, Boolean(m.enabled)])) : undefined;
}

export function useModuleOn(key: string): boolean {
  return Boolean(useModules()?.[key]);
}
