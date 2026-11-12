"use client";

import { Download, Plus, Upload } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueries } from "@tanstack/react-query";
import { Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Avatar, StagePill } from "@/components/crm/bits";
import { AddLeadDialog } from "@/components/crm/lead-form";
import { BandPill, TagList, TagPicker } from "@/components/crm/tags";
import { SaveViewDialog } from "@/components/crm/save-view";
import { LeadPreview } from "@/components/crm/lead-record";
import {
  BulkButton,
  type Column,
  DataTable,
  emptySelection,
  type Paging,
  type Selection,
  TableTools,
  useTablePrefs,
} from "@/components/data-table/data-table";
import { FilterChip, OptionSearch, ViewTabs } from "@/components/data-table/filters";
import { Popover, PopoverHeading, PopoverItem } from "@/components/data-table/popover";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import {
  type BulkResult,
  fieldValue,
  fromLocalInput,
  isOverdue,
  type Lead,
  type LeadQuery,
  phone,
  quickFollowUps,
  relative,
  type Stage,
  useFields,
  useLeadCounts,
  useLeads,
  useRefreshLead,
  useSources,
  useStages,
  when,
} from "@/lib/crm";
import { useUsers } from "@/lib/directory";
import { useTags, useViews } from "@/lib/organise";
import { exportCsv } from "@/lib/reports";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Filters = { stage_id: string[]; source_id: string[]; owner: string[]; tag: string[]; band: string[]; cf: Record<string, string[]> };
const NO_FILTERS: Filters = { stage_id: [], source_id: [], owner: [], tag: [], band: [], cf: {} };

const VIEW_QUERY: Record<string, LeadQuery> = {
  mine: { owner: ["me"], status: "open" },
  today: { follow_up: "today" },
  overdue: { follow_up: "overdue" },
  none: { follow_up: "none" },
  unassigned: { owner: ["unassigned"], status: "open" },
  all: {},
};

function FollowUp({ lead }: { lead: Lead }) {
  if (!lead.is_open) return <span className="text-muted-foreground">—</span>;
  if (!lead.next_follow_up_at) return <span className="text-destructive">Not set</span>;
  return <span className={cn(isOverdue(lead.next_follow_up_at) && "text-destructive")}>{when(lead.next_follow_up_at)}</span>;
}

export default function LeadsPage() {
  return (
    <Suspense>
      <LeadsList />
    </Suspense>
  );
}

/** Dashboards open this list with filters in the address: ?source_id=…&owner=…&created_from=… */
function fromAddress(params: URLSearchParams): { filters: Filters; created: { from?: string; to?: string } } {
  return {
    filters: { ...NO_FILTERS, source_id: params.getAll("source_id"), owner: params.getAll("owner") },
    created: { from: params.get("created_from") ?? undefined, to: params.get("created_to") ?? undefined },
  };
}

function LeadsList() {
  const { me, can } = useAuth();
  const label = useLabels();
  const router = useRouter();
  const stages = useStages();
  const sources = useSources();
  const fields = useFields();
  const counts = useLeadCounts();
  const users = useUsers(can("users.read"));
  const refresh = useRefreshLead();
  const plural = label("lead", true);
  const isManager = me?.role.scope !== "own";

  const params = useSearchParams();
  const [initial] = useState(() => fromAddress(params));
  const fromDashboard = params.size > 0;
  const [view, setView] = useState(fromDashboard || isManager ? "all" : "mine");
  const [created, setCreated] = useState(initial.created);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<Filters>(initial.filters);
  const [paging, setPaging] = useState<Paging>({ page: 1, size: 50, sort: "follow_up", dir: "asc" });
  const [selection, setSelection] = useState<Selection>(emptySelection);
  const [preview, setPreview] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [savingView, setSavingView] = useState(false);
  const tags = useTags();
  const savedViews = useViews("leads");
  const savedCounts = useQueries({
    queries: (savedViews.data ?? []).map((v) => ({
      queryKey: ["leads", "count", v.id, v.filters],
      queryFn: async () => unwrap(await api.GET("/api/v1/leads", { params: { query: { ...(v.filters as LeadQuery), limit: 1 } } })).total,
    })),
  });

  // Any change to what is listed goes back to page 1 and clears the selection.
  const reset = () => {
    setPaging((p) => ({ ...p, page: 1 }));
    setSelection(emptySelection());
  };
  useEffect(() => {
    const t = setTimeout(() => {
      if (search.trim() === q) return;
      setQ(search.trim());
      setPaging((p) => ({ ...p, page: 1 }));
      setSelection(emptySelection());
    }, 250);
    return () => clearTimeout(t);
  }, [search, q]);
  const saved = view.startsWith("sv:") ? savedViews.data?.find((v) => `sv:${v.id}` === view) : undefined;
  const base: LeadQuery = saved ? (saved.filters as LeadQuery) : (VIEW_QUERY[view] ?? {});
  const viewOwns = Boolean(base.owner);
  const filter: LeadQuery = {
    ...base,
    ...(q ? { q } : {}),
    ...(filters.stage_id.length ? { stage_id: filters.stage_id } : {}),
    ...(filters.source_id.length ? { source_id: filters.source_id } : {}),
    ...(!viewOwns && filters.owner.length ? { owner: filters.owner } : {}),
    ...(filters.tag.length ? { tag: filters.tag } : {}),
    ...(created.from ? { created_from: created.from } : {}),
    ...(created.to ? { created_to: created.to } : {}),
    ...(filters.band.length ? { band: filters.band as LeadQuery["band"] } : {}),
    ...(Object.keys(filters.cf).some((k) => filters.cf[k].length)
      ? { cf: Object.entries(filters.cf).flatMap(([k, vs]) => vs.map((v) => `${k}:${v}`)) }
      : {}),
  };
  const leads = useLeads({ ...filter, sort: paging.sort as LeadQuery["sort"], dir: paging.dir, limit: paging.size, offset: (paging.page - 1) * paging.size });

  const stageById = useMemo(() => new Map((stages.data ?? []).map((s) => [s.id, s])), [stages.data]);
  const sourceById = useMemo(() => new Map((sources.data ?? []).map((s) => [s.id, s.name])), [sources.data]);
  const selectFields = (fields.data ?? []).filter((f) => f.type === "select" || f.type === "multi_select");

  const columns: Column<Lead>[] = [
    {
      key: "name",
      label: "Name",
      sort: "name",
      pinned: true,
      cell: (l) => (
        <span className="flex items-center gap-2">
          <span className="size-2 shrink-0 rounded-full" style={{ background: stageById.get(l.stage_id)?.colour ?? "#94a3b8" }} />
          <span className="max-w-56 truncate font-medium">{l.display_name}</span>
        </span>
      ),
    },
    { key: "phone", label: "Phone", cell: (l) => <span className="text-muted-foreground tabular-nums">{phone(l.primary_phone) || l.primary_email}</span> },
    { key: "stage", label: "Stage", sort: "stage", cell: (l) => <StagePill stage={stageById.get(l.stage_id)} /> },
    { key: "follow_up", label: "Next follow-up", sort: "follow_up", cell: (l) => <FollowUp lead={l} /> },
    {
      key: "owner",
      label: "Owner",
      sort: "owner",
      cell: (l) =>
        l.owner_name ? (
          <span className="flex items-center gap-1.5">
            <Avatar name={l.owner_name} colour="#475569" size={5} />
            {l.owner_name}
          </span>
        ) : (
          <span className="text-muted-foreground">Unassigned</span>
        ),
    },
    {
      key: "last_activity",
      label: "Last activity",
      sort: "last_activity",
      cell: (l) => (
        <span className="text-muted-foreground">
          {l.last_disposition ? `${l.last_disposition} · ` : ""}
          {relative(l.last_activity_at ?? l.created_at)}
        </span>
      ),
    },
    { key: "source", label: "Source", sort: "source", cell: (l) => <span className="text-muted-foreground">{sourceById.get(l.source_id)}</span> },
    { key: "score", label: "Score", sort: "score", cell: (l) => <BandPill band={l.score_band} score={l.score} /> },
    { key: "tags", label: "Tags", cell: (l) => <TagList tags={l.tags ?? []} /> },
    ...selectFields.map(
      (f, i): Column<Lead> => ({
        key: `cf.${f.key}`,
        label: f.label,
        hiddenByDefault: i > 0,
        cell: (l) => <span className="text-muted-foreground">{fieldValue(f, (l.custom_fields as Record<string, unknown>)[f.key])}</span>,
      }),
    ),
    { key: "city", label: "City", sort: "city", hiddenByDefault: true, cell: (l) => <span className="text-muted-foreground">{l.city ?? "—"}</span> },
    { key: "created", label: "Created", sort: "created", hiddenByDefault: true, cell: (l) => <span className="text-muted-foreground">{relative(l.created_at)}</span> },
  ];
  const prefs = useTablePrefs("leads", columns as Column<unknown>[]);

  const c = counts.data;
  const views = [
    { key: "mine", label: `My ${plural.toLowerCase()}`, count: c?.mine },
    { key: "today", label: "Due today", count: c?.today },
    { key: "overdue", label: "Overdue", count: c?.overdue, alert: true },
    { key: "none", label: "No follow-up", count: c?.none, alert: true },
    ...(isManager ? [{ key: "unassigned", label: "Unassigned", count: c?.unassigned, alert: true }] : []),
    { key: "all", label: "All", count: c?.all },
    ...(savedViews.data ?? []).map((v, i) => ({ key: `sv:${v.id}`, label: v.name, count: savedCounts[i]?.data })),
  ];

  const rows = useMemo(() => leads.data?.items ?? [], [leads.data]);
  const open = (lead: Lead) => {
    if (window.matchMedia("(min-width: 768px)").matches) setPreview(lead.id);
    else router.push(`/leads/${lead.id}`);
  };

  useEffect(() => {
    if (!preview) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      const i = rows.findIndex((r) => r.id === preview);
      if (e.key === "Escape") setPreview(null);
      if (e.key === "j" && rows[i + 1]) setPreview(rows[i + 1].id);
      if (e.key === "k" && i > 0) setPreview(rows[i - 1].id);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [preview, rows]);

  async function runBulk(body: Record<string, unknown>, verb: string) {
    try {
      const result: BulkResult = unwrap(
        await api.POST("/api/v1/leads/bulk", {
          body: {
            ...(selection.allMatching ? { filter: filter as never } : { ids: [...selection.ids] }),
            ...body,
          } as never,
        }),
      );
      refresh();
      setSelection(emptySelection());
      if (result.skipped.length) {
        toast.warning(`${verb} ${result.done}. Skipped ${result.skipped.length}: ${result.skipped[0].name} — ${result.skipped[0].reason}${result.skipped.length > 1 ? " …" : ""}`);
      } else toast.success(`${verb} ${result.done} ${plural.toLowerCase()}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const ownerOptions = [
    { value: "me", label: "Me" },
    { value: "unassigned", label: "Unassigned" },
    ...(users.data ?? []).filter((u) => u.id !== me?.id && u.status === "active").map((u) => ({ value: u.id, label: u.name })),
  ];
  const anyFilter =
    q || created.from || created.to || filters.stage_id.length || filters.source_id.length || filters.owner.length || filters.tag.length || filters.band.length || Object.values(filters.cf).some((v) => v.length);
  async function deleteView() {
    if (!saved || !window.confirm(`Delete the view "${saved.name}"?`)) return;
    try {
      unwrap(await api.DELETE("/api/v1/views/{view_id}", { params: { path: { view_id: saved.id } } }));
      savedViews.refetch();
      setView(isManager ? "all" : "mine");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title={plural}
        count={c?.all}
        actions={
          <>
            <Input data-table-search placeholder="Search name, phone, email…  ( / )" className="h-7 w-full sm:w-72" value={search} onChange={(e) => setSearch(e.target.value)} />
            {can("leads.import") && (
              <Button size="sm" variant="outline" onClick={() => router.push("/leads/import")}>
                <Upload /> Import
              </Button>
            )}
            {can("leads.create") && (
              <Button size="sm" onClick={() => setAdding(true)}>
                <Plus /> Add {label("lead").toLowerCase()}
              </Button>
            )}
          </>
        }
      />
      <ViewTabs
        views={views}
        active={view}
        onChange={(v) => {
          setView(v);
          reset();
        }}
      />
      <div className="flex flex-wrap items-center gap-1.5 border-b px-4 py-2">
        <FilterChip
          label="Stage"
          options={(stages.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
          values={filters.stage_id}
          onChange={(v) => {
            setFilters({ ...filters, stage_id: v });
            reset();
          }}
        />
        {isManager && !viewOwns && (
          <FilterChip
            label="Owner"
            options={ownerOptions}
            values={filters.owner}
            onChange={(v) => {
              setFilters({ ...filters, owner: v });
              reset();
            }}
          />
        )}
        <FilterChip
          label="Source"
          options={(sources.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
          values={filters.source_id}
          onChange={(v) => {
            setFilters({ ...filters, source_id: v });
            reset();
          }}
        />
        {selectFields.map((f) => (
          <FilterChip
            key={f.key}
            label={f.label}
            options={(f.options as { value: string; label: string }[]).map((o) => ({ value: o.value, label: o.label }))}
            values={filters.cf[f.key] ?? []}
            onChange={(v) => {
              setFilters({ ...filters, cf: { ...filters.cf, [f.key]: v } });
              reset();
            }}
          />
        ))}
        <FilterChip
          label="Tag"
          options={(tags.data ?? []).map((t) => ({ value: t.id, label: t.name }))}
          values={filters.tag}
          onChange={(v) => {
            setFilters({ ...filters, tag: v });
            reset();
          }}
        />
        <FilterChip
          label="Score"
          options={[
            { value: "hot", label: "Hot" },
            { value: "warm", label: "Warm" },
            { value: "cold", label: "Cold" },
          ]}
          values={filters.band}
          onChange={(v) => {
            setFilters({ ...filters, band: v });
            reset();
          }}
        />
        {anyFilter ? (
          <Button size="sm" variant="outline" onClick={() => setSavingView(true)}>
            Save view
          </Button>
        ) : null}
        {saved?.mine ? (
          <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={deleteView}>
            Delete view
          </Button>
        ) : null}
        {anyFilter ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setFilters(NO_FILTERS);
              setCreated({});
              setSearch("");
              reset();
            }}
          >
            Clear all
          </Button>
        ) : null}
        {created.from || created.to ? (
          <span className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
            Created {created.from ?? "…"} to {created.to ?? "…"}
          </span>
        ) : null}
        <div className="ml-auto hidden items-center gap-1 md:flex">
          {can("leads.export") && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                exportCsv("/api/v1/leads/export", { ...filter, sort: paging.sort, dir: paging.dir }, plural.toLowerCase()).catch((e) => toast.error(e.message))
              }
            >
              <Download /> Export
            </Button>
          )}
          <TableTools columns={columns} prefs={prefs} />
        </div>
      </div>
      <DataTable
        columns={columns}
        rows={rows}
        total={leads.data?.total ?? 0}
        loading={leads.isFetching}
        error={leads.isError ? leads.error.message : null}
        getId={(l) => l.id}
        paging={paging}
        onPaging={setPaging}
        selection={selection}
        onSelection={setSelection}
        onOpen={open}
        prefs={prefs}
        noun={plural.toLowerCase()}
        empty={anyFilter ? "Nothing matches these filters." : `No ${plural.toLowerCase()} here.`}
        card={(l) => (
          <div className="space-y-1">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-medium">{l.display_name}</span>
              <span className="shrink-0 text-xs">
                <FollowUp lead={l} />
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <StagePill stage={stageById.get(l.stage_id)} />
              {l.owner_name ?? "Unassigned"}
            </div>
          </div>
        )}
        bulk={() => (
          <>
            {can("leads.assign") && (
              <BulkMenu label="Assign to">
                {(close) => (
                  <OptionSearch options={ownerOptions}>
                    {(shown) =>
                      shown.map((o) => (
                        <PopoverItem
                          key={o.value}
                          onClick={() => {
                            close();
                            runBulk({ action: "assign", owner_user_id: o.value === "unassigned" ? null : o.value === "me" ? me!.id : o.value }, "Assigned");
                          }}
                        >
                          {o.label}
                        </PopoverItem>
                      ))
                    }
                  </OptionSearch>
                )}
              </BulkMenu>
            )}
            {can("leads.edit") && (
              <BulkMenu label="Change stage">
                {(close) => (stages.data ?? []).map((s) => <StageChoice key={s.id} stage={s} onPick={(reason) => { close(); runBulk({ action: "stage", stage_id: s.id, unqualified_reason: reason }, "Moved"); }} />)}
              </BulkMenu>
            )}
            {can("leads.edit") && (
              <BulkMenu label="Set follow-up">
                {(close) => (
                  <>
                    {quickFollowUps().map((qf) => (
                      <PopoverItem
                        key={qf.label}
                        onClick={() => {
                          close();
                          runBulk({ action: "follow_up", next_follow_up_at: fromLocalInput(qf.value) }, "Follow-up set for");
                        }}
                      >
                        {qf.label}
                      </PopoverItem>
                    ))}
                  </>
                )}
              </BulkMenu>
            )}
            {can("leads.edit") && (
              <BulkMenu label="Tag">
                {(close) => (
                  <TagPicker
                    chosen={[]}
                    onPick={(id) => (close(), runBulk({ action: "tag", tag_ids: [id] }, "Tagged"))}
                    onCreate={(name) => (close(), runBulk({ action: "tag", new_tags: [name] }, "Tagged"))}
                  />
                )}
              </BulkMenu>
            )}
            {can("leads.edit") && (tags.data ?? []).length > 0 && (
              <BulkMenu label="Remove tag">
                {(close) =>
                  (tags.data ?? []).map((t) => (
                    <PopoverItem key={t.id} onClick={() => (close(), runBulk({ action: "untag", tag_ids: [t.id] }, "Untagged"))}>
                      {t.name}
                    </PopoverItem>
                  ))
                }
              </BulkMenu>
            )}
            {can("leads.delete") && (
              <BulkButton
                danger
                onClick={() => {
                  const n = selection.allMatching ? leads.data?.total : selection.ids.size;
                  if (window.confirm(`Delete ${n} ${plural.toLowerCase()} for good? Their timelines are removed too.`)) runBulk({ action: "delete" }, "Deleted");
                }}
              >
                Delete
              </BulkButton>
            )}
          </>
        )}
      />
      {savingView && (
        <SaveViewDialog
          entity="leads"
          filters={filter as Record<string, unknown>}
          sort={paging.sort}
          dir={paging.dir}
          onClose={() => setSavingView(false)}
          onSaved={(id) => {
            setSavingView(false);
            setFilters(NO_FILTERS);
            setSearch("");
            setQ("");
            setView(`sv:${id}`);
            reset();
          }}
        />
      )}
      {preview && <LeadPreview key={preview} leadId={preview} onClose={() => setPreview(null)} />}
      {adding && (
        <AddLeadDialog
          onClose={() => setAdding(false)}
          onCreated={(lead) => {
            setAdding(false);
            open(lead);
          }}
        />
      )}
    </div>
  );
}

function BulkMenu({ label, children }: { label: string; children: (close: () => void) => React.ReactNode }) {
  return (
    <div className="text-foreground">
      <Popover
        className="bottom-full top-auto mb-2"
        trigger={({ toggle }) => <BulkButton onClick={toggle}>{label} ▾</BulkButton>}
      >
        {(close) => (
          <>
            <PopoverHeading>{label}</PopoverHeading>
            {children(close)}
          </>
        )}
      </Popover>
    </div>
  );
}

/** A stage in the bulk menu; stages that need a reason ask for it first. */
function StageChoice({ stage, onPick }: { stage: Stage; onPick: (reason?: string) => void }) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  if (!asking) {
    return (
      <PopoverItem onClick={() => (stage.is_unqualified ? setAsking(true) : onPick())}>
        <StagePill stage={stage} />
      </PopoverItem>
    );
  }
  return (
    <form
      className="flex gap-1 p-1"
      onSubmit={(e) => {
        e.preventDefault();
        if (reason.trim()) onPick(reason.trim());
      }}
    >
      <Input autoFocus aria-label="Reason" placeholder={`Why ${stage.name}?`} className="h-7" value={reason} onChange={(e) => setReason(e.target.value)} />
      <Button size="sm" type="submit" disabled={!reason.trim()}>
        Move
      </Button>
    </form>
  );
}
