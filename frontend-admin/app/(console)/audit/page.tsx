"use client";

import { useQuery } from "@tanstack/react-query";

import { AuditTable } from "@/components/app/audit-table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

export default function AuditPage() {
  const audit = useQuery({
    queryKey: ["audit", "all"],
    queryFn: async () => unwrap(await api.GET("/platform/audit", { params: { query: { limit: 200 } } })),
  });
  return (
    <>
      <h1 className="mb-1 text-base font-semibold">Audit log</h1>
      <p className="mb-4 text-muted-foreground">Every staff action, newest first (last 200).</p>
      {audit.isLoading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : audit.isError ? (
        <p className="text-destructive">{audit.error.message}</p>
      ) : (
        <AuditTable rows={audit.data ?? []} />
      )}
    </>
  );
}
