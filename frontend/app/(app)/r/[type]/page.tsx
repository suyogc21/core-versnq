"use client";

import { Plus } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Avatar, CustomFieldsEditor, StagePill } from "@/components/crm/bits";
import { BulkButton, type Column, DataTable, emptySelection, type Paging, type Selection, TableTools, useTablePrefs } from "@/components/data-table/data-table";
import { FilterChip, OptionSearch } from "@/components/data-table/filters";
import { Popover, PopoverItem } from "@/components/data-table/popover";
import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { fieldValue, relative, type Stage } from "@/lib/crm";
import { useUsers } from "@/lib/directory";
import { type RecordItem, type RecordQuery, type RecordType, useRecordFields, useRecords, useRecordStages, useRecordTypes, useRefreshRecords } from "@/lib/records";
import { accessOf, useLayout } from "@/lib/layouts";

type Filters = { stage_id: string[]; owner: string[]; cf: Record<string, string[]> };
const NONE: Filters = { stage_id: [], owner: [], cf: {} };

export default function RecordsPage() {
  const { type: key } = useParams<{ type: string }>();
  const types = useRecordTypes();
  const rtype = types.data?.find((t) => t.key === key);
  if (types.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!rtype) {
    return (
      <>
        <PageHeader title="Not found" />
        <p className="p-8 text-center text-muted-foreground">This list doesn&apos;t exist or you don&apos;t have access to it.</p>
      </>
    );
  }
  return <RecordList key={rtype.id} rtype={rtype} />;
}

function RecordList({ rtype }: { rtype: RecordType }) {
  const { me, can } = useAuth();
  const router = useRouter();
  const stages = useRecordStages(rtype.has_stages ? rtype.id : undefined);
  const fields = useRecordFields(rtype.key);
  const users = useUsers(can("users.read"));
  const refresh = useRefreshRecords();
  const acc = rtype.my_access!;
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<Filters>(NONE);
  const [paging, setPaging] = useState<Paging>({ page: 1, size: 50, sort: "name", dir: "asc" });
  const [selection, setSelection] = useState<Selection>(emptySelection);
  const [adding, setAdding] = useState(false);

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

  const query: RecordQuery = {
    type: rtype.key,
    q: q || undefined,
    stage_id: filters.stage_id.length ? filters.stage_id : undefined,
    owner: filters.owner.length ? filters.owner : undefined,
    cf: Object.entries(filters.cf).flatMap(([k, vs]) => vs.map((v) => `${k}:${v}`)),
    sort: paging.sort as RecordQuery["sort"],
    dir: paging.dir,
    limit: paging.size,
    offset: (paging.page - 1) * paging.size,
  };
  const records = useRecords(query);
  const stageById = useMemo(() => new Map((stages.data ?? []).map((s) => [s.id, s])), [stages.data]);
  const layout = useLayout(`rt:${rtype.key}`);
  const fieldList = (fields.data ?? []).filter((f) => accessOf(layout.data, `cf.${f.key}`) !== "hidden"); // step 8
  const selectFields = fieldList.filter((f) => f.type === "select" || f.type === "multi_select");

  const columns: Column<RecordItem>[] = [
    { key: "name", label: "Name", sort: "name", pinned: true, cell: (r) => <span className="max-w-64 truncate font-medium">{r.name}</span> },
    ...(rtype.has_stages
      ? [{ key: "stage", label: "Stage", sort: "stage", cell: (r: RecordItem) => <StagePill stage={stageById.get(r.stage_id ?? "") as unknown as Stage} /> }]
      : []),
    ...(rtype.has_owner
      ? [
          {
            key: "owner",
            label: "Owner",
            sort: "owner",
            cell: (r: RecordItem) =>
              r.owner_name ? (
                <span className="flex items-center gap-1.5">
                  <Avatar name={r.owner_name} colour="#475569" size={5} />
                  {r.owner_name}
                </span>
              ) : (
                <span className="text-muted-foreground">Unassigned</span>
              ),
          },
        ]
      : []),
    ...fieldList.map(
      (f, i): Column<RecordItem> => ({
        key: `cf.${f.key}`,
        label: f.label,
        hiddenByDefault: i > 3,
        cell: (r) => <span className="text-muted-foreground">{fieldValue(f, (r.custom_fields as Record<string, unknown>)[f.key])}</span>,
      }),
    ),
    { key: "updated", label: "Updated", sort: "updated", cell: (r) => <span className="text-muted-foreground">{relative(r.updated_at)}</span> },
  ];
  const prefs = useTablePrefs(`records-${rtype.key}`, columns as Column<unknown>[]);
  const rows = useMemo(() => records.data?.items ?? [], [records.data]);
  const plural = rtype.plural;
  const ownerOptions = [
    { value: "me", label: "Me" },
    { value: "unassigned", label: "Unassigned" },
    ...(users.data ?? []).filter((u) => u.id !== me?.id && u.status === "active").map((u) => ({ value: u.id, label: u.name })),
  ];
  const anyFilter = q || filters.stage_id.length || filters.owner.length || Object.values(filters.cf).some((v) => v.length);

  async function bulk(body: Record<string, unknown>, verb: string) {
    try {
      const result = unwrap(await api.POST("/api/v1/records/bulk", { body: { ids: [...selection.ids], ...body } as never }));
      refresh();
      setSelection(emptySelection());
      if (result.skipped.length) toast.warning(`${verb} ${result.done}. Skipped ${result.skipped.length}: ${result.skipped[0].name} — ${result.skipped[0].reason}`);
      else toast.success(`${verb} ${result.done} ${plural.toLowerCase()}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title={plural}
        count={records.data?.total}
        actions={
          <>
            <Input data-table-search placeholder={`Search ${plural.toLowerCase()}…  ( / )`} className="h-7 w-full sm:w-72" value={search} onChange={(e) => setSearch(e.target.value)} />
            {acc.create && (
              <Button size="sm" onClick={() => setAdding(true)}>
                <Plus /> Add {rtype.singular.toLowerCase()}
              </Button>
            )}
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-1.5 border-b px-4 py-2">
        {rtype.has_stages && (
          <FilterChip
            label="Stage"
            options={(stages.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
            values={filters.stage_id}
            onChange={(v) => (setFilters({ ...filters, stage_id: v }), reset())}
          />
        )}
        {rtype.has_owner && acc.scope !== "own" && (
          <FilterChip label="Owner" options={ownerOptions} values={filters.owner} onChange={(v) => (setFilters({ ...filters, owner: v }), reset())} />
        )}
        {selectFields.map((f) => (
          <FilterChip
            key={f.key}
            label={f.label}
            options={(f.options as { value: string; label: string }[]).map((o) => ({ value: o.value, label: o.label }))}
            values={filters.cf[f.key] ?? []}
            onChange={(v) => (setFilters({ ...filters, cf: { ...filters.cf, [f.key]: v } }), reset())}
          />
        ))}
        {anyFilter ? (
          <Button size="sm" variant="ghost" onClick={() => (setFilters(NONE), setSearch(""), reset())}>
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
        total={records.data?.total ?? 0}
        loading={records.isFetching}
        error={records.isError ? records.error.message : null}
        getId={(r) => r.id}
        paging={paging}
        onPaging={setPaging}
        selection={acc.edit || acc.delete ? selection : undefined}
        onSelection={acc.edit || acc.delete ? setSelection : undefined}
        allowAllMatching={false}
        onOpen={(r) => router.push(`/r/${rtype.key}/${r.id}`)}
        prefs={prefs}
        noun={plural.toLowerCase()}
        empty={anyFilter ? "Nothing matches these filters." : `No ${plural.toLowerCase()} yet.`}
        card={(r) => (
          <div className="space-y-1">
            <div className="truncate font-medium">{r.name}</div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              {rtype.has_stages && <StagePill stage={stageById.get(r.stage_id ?? "") as unknown as Stage} />}
              {rtype.has_owner && (r.owner_name ?? "Unassigned")}
            </div>
          </div>
        )}
        bulk={() => (
          <>
            {acc.edit && rtype.has_owner && acc.scope !== "own" && (
              <Popover trigger={({ toggle }) => <BulkButton onClick={toggle}>Assign to ▾</BulkButton>}>
                {(close) => (
                  <OptionSearch options={ownerOptions}>
                    {(shown) =>
                      shown.map((o) => (
                        <PopoverItem key={o.value} onClick={() => (close(), bulk({ action: "assign", owner_user_id: o.value === "unassigned" ? null : o.value === "me" ? me!.id : o.value }, "Assigned"))}>
                          {o.label}
                        </PopoverItem>
                      ))
                    }
                  </OptionSearch>
                )}
              </Popover>
            )}
            {acc.edit && rtype.has_stages && (
              <Popover trigger={({ toggle }) => <BulkButton onClick={toggle}>Change stage ▾</BulkButton>}>
                {(close) =>
                  (stages.data ?? []).map((s) => (
                    <PopoverItem key={s.id} onClick={() => (close(), bulk({ action: "stage", stage_id: s.id }, "Moved"))}>
                      <StagePill stage={s as unknown as Stage} />
                    </PopoverItem>
                  ))
                }
              </Popover>
            )}
            {acc.delete && (
              <BulkButton danger onClick={() => window.confirm(`Delete ${selection.ids.size} ${plural.toLowerCase()} for good? Their timelines and links are removed too.`) && bulk({ action: "delete" }, "Deleted")}>
                Delete
              </BulkButton>
            )}
          </>
        )}
      />
      {adding && (
        <AddRecordDialog
          rtype={rtype}
          onClose={() => setAdding(false)}
          onCreated={(r) => {
            setAdding(false);
            router.push(`/r/${rtype.key}/${r.id}`);
          }}
        />
      )}
    </div>
  );
}

function AddRecordDialog({ rtype, onClose, onCreated }: { rtype: RecordType; onClose: () => void; onCreated: (r: RecordItem) => void }) {
  const { me, can } = useAuth();
  const fields = useRecordFields(rtype.key);
  const stages = useRecordStages(rtype.has_stages ? rtype.id : undefined);
  const acc = rtype.my_access!;
  const users = useUsers(rtype.has_owner && acc.scope !== "own" && can("users.read"));
  const refresh = useRefreshRecords();
  const [name, setName] = useState("");
  const [owner, setOwner] = useState(me?.id ?? "");
  const [stageId, setStageId] = useState("");
  const [custom, setCustom] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = unwrap(
        await api.POST("/api/v1/records", {
          body: {
            type: rtype.key,
            name,
            owner_user_id: rtype.has_owner && owner && owner !== "none" ? owner : null,
            assign_to_me: owner !== "none",
            stage_id: stageId || null,
            custom_fields: Object.fromEntries(Object.entries(custom).filter(([, x]) => x !== null && x !== "")),
          },
        }),
      );
      refresh();
      toast.success(`${rtype.singular} added`);
      onCreated(r);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add {rtype.singular.toLowerCase()}</DialogTitle>
        </DialogHeader>
        <form onSubmit={save} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="rec-name">Name</Label>
            <Input id="rec-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {rtype.has_stages && (
              <div className="space-y-1.5">
                <Label htmlFor="rec-stage">Stage</Label>
                <NativeSelect id="rec-stage" value={stageId} onChange={(e) => setStageId(e.target.value)}>
                  <option value="">{(stages.data ?? []).find((s) => s.is_open)?.name ?? "First stage"}</option>
                  {(stages.data ?? []).map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            )}
            {rtype.has_owner && acc.scope !== "own" && (
              <div className="space-y-1.5">
                <Label htmlFor="rec-owner">Owner</Label>
                <NativeSelect id="rec-owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
                  <option value={me?.id ?? ""}>Me</option>
                  <option value="none">Unassigned</option>
                  {(users.data ?? [])
                    .filter((u) => u.status === "active" && u.id !== me?.id)
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                </NativeSelect>
              </div>
            )}
          </div>
          {(fields.data ?? []).length > 0 && <CustomFieldsEditor fields={fields.data ?? []} values={custom} onChange={setCustom} />}
          {error && <p className="text-xs text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim()}>
              Add {rtype.singular.toLowerCase()}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
