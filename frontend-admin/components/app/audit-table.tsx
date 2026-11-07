"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";

type Entry = components["schemas"]["app__platform__tenants__schemas__AuditOut"];
type Flat = Record<string, unknown>;

function flat(obj: Flat | null | undefined, prefix = "", out: Flat = {}): Flat {
  for (const [k, v] of Object.entries(obj ?? {})) {
    if (v && typeof v === "object" && !Array.isArray(v)) flat(v as Flat, `${prefix}${k}.`, out);
    else out[prefix + k] = v;
  }
  return out;
}

function changes(before: Flat | null | undefined, after: Flat | null | undefined) {
  const [b, a] = [flat(before), flat(after)];
  return [...new Set([...Object.keys(b), ...Object.keys(a)])]
    .filter((k) => JSON.stringify(b[k]) !== JSON.stringify(a[k]))
    .map((k) => ({ key: k, before: b[k], after: a[k] }));
}

const show = (v: unknown) => (v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v));

/** Platform audit entries; a row with changes expands to a before/after list. */
export function AuditTable({ rows }: { rows: Entry[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const staff = useQuery({ queryKey: ["staff"], queryFn: async () => unwrap(await api.GET("/platform/staff")) });
  const names = new Map((staff.data ?? []).map((s) => [s.id, s.name]));

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8" />
          <TableHead>When</TableHead>
          <TableHead>Staff</TableHead>
          <TableHead>What</TableHead>
          <TableHead>Company</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((e) => {
          const diff = changes(e.before as Flat | null, e.after as Flat | null);
          const isOpen = open === e.id;
          return (
            <Fragment key={e.id}>
              <TableRow
                className={cn(diff.length > 0 && "cursor-pointer")}
                onClick={() => diff.length > 0 && setOpen(isOpen ? null : e.id)}
              >
                <TableCell>
                  {diff.length > 0 && <ChevronRight className={cn("size-4 transition-transform", isOpen && "rotate-90")} />}
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">
                  {new Date(e.created_at).toLocaleString()}
                </TableCell>
                <TableCell>{(e.staff_id && names.get(e.staff_id)) || "—"}</TableCell>
                <TableCell className="font-mono text-xs">{e.action}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{e.tenant_slug_snapshot ?? "—"}</TableCell>
              </TableRow>
              {isOpen && (
                <TableRow className="hover:bg-transparent">
                  <TableCell />
                  <TableCell colSpan={4} className="pb-3">
                    <dl className="grid grid-cols-[12rem_1fr_1fr] gap-x-3 gap-y-1 text-xs">
                      <dt className="text-muted-foreground">Field</dt>
                      <dd className="text-muted-foreground">Before</dd>
                      <dd className="text-muted-foreground">After</dd>
                      {diff.map((d) => (
                        <Fragment key={d.key}>
                          <dt className="font-mono">{d.key}</dt>
                          <dd className="font-mono break-all whitespace-pre-wrap">{show(d.before)}</dd>
                          <dd className="font-mono break-all whitespace-pre-wrap">{show(d.after)}</dd>
                        </Fragment>
                      ))}
                    </dl>
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          );
        })}
        {rows.length === 0 && (
          <TableRow>
            <TableCell colSpan={5} className="py-6 text-center text-muted-foreground">
              Nothing recorded yet.
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}
