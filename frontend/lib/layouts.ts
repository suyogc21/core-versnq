import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import type { FieldDef } from "@/lib/crm";

export type Layout = components["schemas"]["LayoutOut"];
export type Access = "edit" | "view" | "hidden";

/** The company's page layout for one kind of record, and what the reader may do with each
 * field (step 8). Kinds: "lead", "deal", "customer", "rt:<record type key>". */
export function useLayout(entity: string, enabled = true) {
  return useQuery({
    queryKey: ["layout", entity],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/layouts/{entity}", { params: { path: { entity } } })),
  });
}

export function accessOf(layout: Layout | undefined, key: string): Access {
  return (layout?.my_access[key] as Access | undefined) ?? "edit";
}

/** Custom fields grouped as the layout places them (hidden ones left out). Without a layout
 * yet, the fields' own groups. Fields the layout leaves off the page are not shown. */
export function customSections(layout: Layout | undefined, fields: FieldDef[]): [string, FieldDef[]][] {
  if (!layout) {
    const groups = new Map<string, FieldDef[]>();
    for (const f of fields) groups.set(f.group_name ?? "", [...(groups.get(f.group_name ?? "") ?? []), f]);
    return [...groups];
  }
  const byKey = new Map(fields.map((f) => [`cf.${f.key}`, f]));
  return layout.sections
    .map((s): [string, FieldDef[]] => [s.name, s.fields.map((k) => byKey.get(k)).filter((f): f is FieldDef => !!f && accessOf(layout, `cf.${f.key}`) !== "hidden")])
    .filter(([, list]) => list.length > 0);
}

/** Fields on the "add" form: the layout's choice, minus fields this person may not fill. */
export function addFormFields(layout: Layout | undefined, fields: FieldDef[]): FieldDef[] {
  if (!layout) return fields;
  const keep = new Set(layout.add_form);
  return fields.filter((f) => keep.has(`cf.${f.key}`) && accessOf(layout, `cf.${f.key}`) === "edit");
}
