"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";

import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { useUsers } from "@/lib/directory";
import { cn } from "@/lib/utils";

const PAGE = 100;

type Flat = Record<string, unknown>;

/** Nested objects become dotted keys, e.g. labels.lead.singular. */
function flat(obj: Flat | null, prefix = "", out: Flat = {}): Flat {
  for (const [k, v] of Object.entries(obj ?? {})) {
    if (v && typeof v === "object" && !Array.isArray(v)) flat(v as Flat, `${prefix}${k}.`, out);
    else out[prefix + k] = v;
  }
  return out;
}

/** Fields whose value changed between two snapshots. */
function changes(before: Flat | null, after: Flat | null) {
  const [b, a] = [flat(before), flat(after)];
  const keys = new Set([...Object.keys(b), ...Object.keys(a)]);
  return [...keys]
    .filter((k) => JSON.stringify(b[k]) !== JSON.stringify(a[k]))
    .map((k) => ({ key: k, before: b[k], after: a[k] }));
}

const show = (v: unknown) => (v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v));

export default function AuditPage() {
  const { can } = useAuth();
  const users = useUsers(can("users.read"));
  const [open, setOpen] = useState<string | null>(null);
  const log = useInfiniteQuery({
    queryKey: ["audit"],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      unwrap(await api.GET("/api/v1/audit", { params: { query: { limit: PAGE, offset: pageParam } } })),
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
  });
  const names = new Map((users.data ?? []).map((u) => [u.id, u.name]));
  const actor = (type: string, id: string | null) =>
    type === "staff" ? "Versnq staff" : type === "system" ? "System" : type === "api" ? "API" : (id && names.get(id)) || "A user";
  const rows = log.data?.pages.flat() ?? [];

  return (
    <>
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Audit log" />
      <div className="p-4">
        {log.isLoading ? (
          <p className="text-muted-foreground">Loading…</p>
        ) : log.isError ? (
          <p className="text-destructive">{log.error.message}</p>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>When</TableHead>
                  <TableHead>Who</TableHead>
                  <TableHead>What</TableHead>
                  <TableHead>On</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((e) => {
                  const diff = changes(e.before ?? null, e.after ?? null);
                  const isOpen = open === e.id;
                  return (
                    <Fragment key={e.id}>
                      <TableRow
                        className={cn(diff.length > 0 && "cursor-pointer")}
                        onClick={() => diff.length > 0 && setOpen(isOpen ? null : e.id)}
                      >
                        <TableCell>
                          {diff.length > 0 && (
                            <ChevronRight className={cn("size-4 transition-transform", isOpen && "rotate-90")} />
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {new Date(e.created_at).toLocaleString()}
                        </TableCell>
                        <TableCell>{actor(e.actor_type, e.actor_id ?? null)}</TableCell>
                        <TableCell className="font-mono text-xs">{e.action}</TableCell>
                        <TableCell className="text-muted-foreground">{e.entity_type}</TableCell>
                      </TableRow>
                      {isOpen && (
                        <TableRow className="hover:bg-transparent">
                          <TableCell />
                          <TableCell colSpan={4} className="pb-3">
                            <dl className="grid grid-cols-[14rem_1fr_1fr] gap-x-3 gap-y-1 text-xs">
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
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                      Nothing recorded yet.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            {log.hasNextPage && (
              <div className="mt-4 flex justify-center">
                <Button variant="outline" onClick={() => log.fetchNextPage()} disabled={log.isFetchingNextPage}>
                  Load older entries
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
