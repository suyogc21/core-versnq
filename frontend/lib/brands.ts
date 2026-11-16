import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type Brand = components["schemas"]["BrandOut"];

/** The company's active brands (default first). Everyone may read them. */
export function useBrands() {
  return useQuery({
    queryKey: ["brands"],
    queryFn: async () => unwrap(await api.GET("/api/v1/brands")),
    staleTime: 60_000,
  });
}

/** Brand choices show only in companies with two or more active brands (batch 4): a company
 * with one brand or none never sees them. */
export function useBrandChoices(): Brand[] {
  const brands = useBrands();
  const list = brands.data ?? [];
  return list.length > 1 ? list : [];
}
