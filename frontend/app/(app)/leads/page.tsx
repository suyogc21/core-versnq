"use client";

import { Plus, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Avatar, StagePill } from "@/components/crm/bits";
import { AddLeadDialog } from "@/components/crm/lead-form";
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
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Filters = { stage_id: string[]; source_id: string[]; owner: string[]; cf: Record<string, string[]> };
const NO_FILTERS: Filters = { stage_id: [], source_id: [], owner: [], cf: {} };

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

  const [view, setView] = useState(isManager ? "all" : "mine");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [paging, setPaging] = useState<Paging>({ page: 1, size: 50, sort: "follow_up", dir: "asc" });
  const [selection, setSelection] = useState<Selection>(emptySelection);
  const [preview, setPreview] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

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
  const viewOwns = Boolean(VIEW_QUERY[view].owner);
  const filter: LeadQuery = {
    ...VIEW_QUERY[view],
    q: q || undefined,
    stage_id: filters.stage_id.length ? filters.stage_id : undefined,
    source_id: filters.source_id.length ? filters.source_id : undefined,
    ...(!viewOwns && filters.owner.length ? { owner: filters.owner } : {}),
    cf: Object.entries(filters.cf).flatMap(([k, vs]) => vs.map((v) => `${k}:${v}`)),
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
  const anyFilter = q || filters.stage_id.length || filters.source_id.length || filters.owner.length || Object.values(filters.cf).some((v) => v.length);

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
        {anyFilter ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setFilters(NO_FILTERS);
              setSearch("");
              reset();
            }}
          >
            Clear all
          </Button>
        ) : null}
        <div className="ml-auto hidden md:block">
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
