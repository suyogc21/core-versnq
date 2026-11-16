"use client";

import { Download } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Avatar } from "@/components/crm/bits";
import { type Column, DataTable, type Paging, TableTools, useTablePrefs } from "@/components/data-table/data-table";
import { FilterChip } from "@/components/data-table/filters";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { phone, relative, when } from "@/lib/crm";
import { type Customer, type CustomerQuery, useCustomers } from "@/lib/customers";
import { useUsers } from "@/lib/directory";
import { exportCsv } from "@/lib/reports";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Filters = { status: string[]; documents: string[]; owner: string[] };
const NONE: Filters = { status: ["active"], documents: [], owner: [] };

function Docs({ c }: { c: Customer }) {
  if (!c.docs_required) return <span className="text-muted-foreground">—</span>;
  const done = c.docs_done >= c.docs_required;
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium tabular-nums", done ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "bg-amber-500/10 text-amber-700 dark:text-amber-300")}>
      {c.docs_done} of {c.docs_required}
    </span>
  );
}

export default function CustomersPage() {
  const { me, can } = useAuth();
  const router = useRouter();
  const label = useLabels();
  const users = useUsers(can("users.read"));
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<Filters>(NONE);
  const [paging, setPaging] = useState<Paging>({ page: 1, size: 50, sort: "since", dir: "desc" });
  const plural = label("customer", true);
  const reset = () => setPaging((p) => ({ ...p, page: 1 }));

  useEffect(() => {
    const t = setTimeout(() => {
      if (search.trim() === q) return;
      setQ(search.trim());
      setPaging((p) => ({ ...p, page: 1 }));
    }, 250);
    return () => clearTimeout(t);
  }, [search, q]);

  const sort = (paging.sort === "since" && paging.dir === "desc" ? "-since" : paging.sort) as CustomerQuery["sort"];
  const query: CustomerQuery = {
    q: q || undefined,
    status: filters.status.length === 1 ? (filters.status[0] as "active" | "inactive") : undefined,
    documents: filters.documents.length === 1 ? (filters.documents[0] as "missing" | "complete") : undefined,
    owner: filters.owner.length ? filters.owner : undefined,
    sort,
    page: paging.page,
    page_size: paging.size,
  };
  const list = useCustomers(query, can("customers.read"));
  const rows = useMemo(() => list.data?.items ?? [], [list.data]);

  const columns: Column<Customer>[] = [
    {
      key: "name",
      label: "Name",
      sort: "name",
      pinned: true,
      cell: (c) => (
        <span className="flex items-center gap-2 font-medium">
          <Avatar name={c.name ?? "?"} colour="#10b981" />
          {c.name}
        </span>
      ),
    },
    { key: "number", label: "Number", sort: "number", cell: (c) => <span className="tabular-nums">{c.number}</span> },
    { key: "phone", label: "Phone", cell: (c) => (c.phone ? phone(c.phone) : c.email ?? "—") },
    { key: "documents", label: "Documents", cell: (c) => <Docs c={c} /> },
    { key: "owner", label: "Owner", cell: (c) => c.owner_name ?? <span className="text-muted-foreground">Unassigned</span> },
    {
      key: "since",
      label: "Since",
      sort: "since",
      cell: (c) => (
        <span className="text-muted-foreground" title={when(c.since)}>
          {relative(c.since)}
        </span>
      ),
    },
    { key: "status", label: "Status", hiddenByDefault: true, cell: (c) => (c.status === "active" ? "Active" : "Inactive") },
  ];
  const prefs = useTablePrefs("customers", columns as Column<unknown>[]);
  const ownerOptions = [
    { value: "me", label: "Me" },
    { value: "none", label: "Unassigned" },
    ...(users.data ?? []).filter((u) => u.id !== me?.id && u.status === "active").map((u) => ({ value: u.id, label: u.name })),
  ];
  const anyFilter = q || filters.documents.length || filters.owner.length || filters.status.join() !== "active";
  // People who work leads open the full record; Finance opens the customer page.
  const open = (c: Customer) => router.push(can("leads.edit") ? `/leads/${c.lead_id}` : `/customers/${c.id}`);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title={plural}
        count={list.data?.total}
        actions={<Input data-table-search placeholder={`Search ${plural.toLowerCase()}…  ( / )`} className="h-7 w-full sm:w-72" value={search} onChange={(e) => setSearch(e.target.value)} />}
      />
      <div className="flex flex-wrap items-center gap-1.5 border-b px-4 py-2 sm:px-6">
        <FilterChip
          label="Status"
          options={[
            { value: "active", label: "Active" },
            { value: "inactive", label: "Inactive" },
          ]}
          values={filters.status}
          onChange={(v) => (setFilters({ ...filters, status: v }), reset())}
        />
        <FilterChip
          label="Documents"
          options={[
            { value: "missing", label: "Missing some" },
            { value: "complete", label: "All received" },
          ]}
          values={filters.documents}
          onChange={(v) => (setFilters({ ...filters, documents: v }), reset())}
        />
        {can("users.read") && <FilterChip label="Owner" options={ownerOptions} values={filters.owner} onChange={(v) => (setFilters({ ...filters, owner: v }), reset())} />}
        {anyFilter ? (
          <Button size="sm" variant="ghost" onClick={() => (setFilters(NONE), setSearch(""), reset())}>
            Clear all
          </Button>
        ) : null}
        <div className="ms-auto hidden items-center gap-1 md:flex">
          {can("customers.export") && (
            <Button size="sm" variant="ghost" onClick={() => exportCsv("/api/v1/customers/export", { q: query.q, status: query.status, documents: query.documents, owner: query.owner }, plural.toLowerCase()).catch((e) => toast.error(e.message))}>
              <Download /> Export
            </Button>
          )}
          <TableTools columns={columns} prefs={prefs} />
        </div>
      </div>
      <DataTable
        columns={columns}
        rows={rows}
        total={list.data?.total ?? 0}
        loading={list.isFetching}
        error={list.isError ? list.error.message : null}
        getId={(c) => c.id}
        paging={paging}
        onPaging={setPaging}
        onOpen={open}
        prefs={prefs}
        noun={plural.toLowerCase()}
        empty={
          anyFilter
            ? "Nothing matches these filters."
            : `No ${plural.toLowerCase()} yet. Win a ${label("deal").toLowerCase()} or open a ${label("lead").toLowerCase()} and choose “Make ${label("customer").toLowerCase()}”.`
        }
        card={(c) => (
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="truncate font-medium">{c.name}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{c.number}</span>
              <span className="ms-auto">
                <Docs c={c} />
              </span>
            </div>
            <div className="text-xs text-muted-foreground">
              {c.owner_name ?? "Unassigned"} · {relative(c.since)}
            </div>
          </div>
        )}
      />
    </div>
  );
}
