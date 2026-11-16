"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { FieldSettings, slug } from "@/components/crm/field-settings";
import { FieldAccessSettings, LayoutSettings } from "@/components/crm/layout-settings";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type LinkType, type RecordStage, type RecordType, type RoleAccess, useAllRecordTypes, useLinkTypes, useRecordFields, useRecordStages } from "@/lib/records";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      for (const k of ["record-types", "record-stages", "record-access", "link-types", "fields"]) qc.invalidateQueries({ queryKey: [k] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

/** Settings → Records and fields: every kind of record (leads first), and how they link. */
export function RecordsIndex() {
  const label = useLabels();
  const types = useAllRecordTypes();
  const save = useSave();
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const list = types.data ?? [];
  const order = (ids: string[]) => save(async () => unwrap(await api.PUT("/api/v1/record-types/order", { body: { ids } })));

  return (
    <>
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Records and fields" />
      <div className="mx-auto w-full max-w-4xl space-y-8 p-4 sm:p-8">
        <p className="text-muted-foreground">
          Each kind of record has its own fields and stages. Add your own kinds (Properties, Batches, Vehicles, Policies…): each gets its own
          list in the sidebar, and they can be linked to {label("lead", true).toLowerCase()} and to each other.
        </p>
        <div className="divide-y surface">
          <Link href="/settings/records/lead" className="flex items-center gap-3 px-3 py-2.5 text-sm hover:bg-accent">
            <span className="w-3" />
            <span className="font-medium">{label("lead", true)}</span>
            <span className="text-xs text-muted-foreground">built in · stages, sources, fields, activity types, rules</span>
          </Link>
          <Link href="/settings/records/deal" className="flex items-center gap-3 px-3 py-2.5 text-sm hover:bg-accent">
            <span className="w-3" />
            <span className="font-medium">{label("deal", true)}</span>
            <span className="text-xs text-muted-foreground">built in · pipelines, stages, lost reasons, products, fields</span>
          </Link>
          <Link href="/settings/records/customer" className="flex items-center gap-3 px-3 py-2.5 text-sm hover:bg-accent">
            <span className="w-3" />
            <span className="font-medium">{label("customer", true)}</span>
            <span className="text-xs text-muted-foreground">built in · document checklist, fields, customer links</span>
          </Link>
          <Link href="/settings/records/tags" className="flex items-center gap-3 px-3 py-2.5 text-sm hover:bg-accent">
            <span className="w-3" />
            <span className="font-medium">Tags</span>
            <span className="text-xs text-muted-foreground">rename, recolour, merge or delete tags</span>
          </Link>
          {list.map((t, i) => (
            <div key={t.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
              <div className="flex flex-col">
                <button aria-label={`Move ${t.plural} up`} disabled={i === 0} className="text-muted-foreground disabled:opacity-30" onClick={() => order(swap(list, i, -1))}>
                  <ArrowUp className="size-3" />
                </button>
                <button aria-label={`Move ${t.plural} down`} disabled={i === list.length - 1} className="text-muted-foreground disabled:opacity-30" onClick={() => order(swap(list, i, 1))}>
                  <ArrowDown className="size-3" />
                </button>
              </div>
              <Link href={`/settings/records/${t.key}`} className="font-medium hover:underline">
                {t.plural}
              </Link>
              <span className="text-xs text-muted-foreground">
                {t.has_owner ? "has owners" : "shared"} · {t.has_stages ? "has stages" : "no stages"}
                {!t.is_active && " · switched off"}
              </span>
            </div>
          ))}
        </div>
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus /> Add a kind of record
        </Button>
        <LinkTypes types={list} />
      </div>
      {creating && <CreateType onClose={() => setCreating(false)} onCreated={(t) => (setCreating(false), router.push(`/settings/records/${t.key}`))} />}
    </>
  );
}

/** Settings → Records and fields → one record type. */
export function RecordTypeSettings({ typeKey }: { typeKey: string }) {
  const types = useAllRecordTypes();
  const router = useRouter();
  const rtype = types.data?.find((t) => t.key === typeKey);
  if (types.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!rtype) return <p className="p-6 text-destructive">Not found</p>;
  return (
    <>
      <PageHeader back={{ href: "/settings/records", label: "Records and fields" }} title={rtype.plural} />
      <div className="mx-auto w-full max-w-4xl p-4 sm:p-8">
        <TypeEditor rtype={rtype} onDeleted={() => router.push("/settings/records")} />
      </div>
    </>
  );
}

function swap<T extends { id: string }>(items: T[], i: number, dir: -1 | 1): string[] {
  const ids = items.map((x) => x.id);
  [ids[i], ids[i + dir]] = [ids[i + dir], ids[i]];
  return ids;
}

function CreateType({ onClose, onCreated }: { onClose: () => void; onCreated: (t: RecordType) => void }) {
  const save = useSave();
  const [singular, setSingular] = useState("");
  const [plural, setPlural] = useState("");
  const [key, setKey] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [hasOwner, setHasOwner] = useState(true);
  const [hasStages, setHasStages] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    let made: RecordType | null = null;
    const ok = await save(async () => {
      made = unwrap(
        await api.POST("/api/v1/record-types", {
          body: { key, singular, plural: plural || `${singular}s`, has_owner: hasOwner, has_stages: hasStages },
        }),
      );
    }, "Record type added");
    if (ok && made) onCreated(made);
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add a record type</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4 text-sm">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="t-singular">Name (one)</Label>
              <Input
                id="t-singular"
                autoFocus
                placeholder="Property"
                value={singular}
                onChange={(e) => {
                  setSingular(e.target.value);
                  if (!keyTouched) setKey(slug(e.target.value).slice(0, 40));
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="t-plural">Name (many)</Label>
              <Input id="t-plural" placeholder={singular ? `${singular}s` : "Properties"} value={plural} onChange={(e) => setPlural(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="t-key">Key</Label>
            <Input id="t-key" className="font-mono text-xs" value={key} onChange={(e) => (setKeyTouched(true), setKey(e.target.value))} />
            <p className="text-xs text-muted-foreground">Used by imports, the API and automations. It cannot change later; the names can.</p>
          </div>
          <label className="flex items-start gap-2">
            <Switch checked={hasOwner} onCheckedChange={setHasOwner} aria-label="Has owners" />
            <span>
              Each one has an owner
              <span className="block text-xs text-muted-foreground">Off = shared: everyone allowed to view sees all of them (e.g. a course batch).</span>
            </span>
          </label>
          <label className="flex items-start gap-2">
            <Switch checked={hasStages} onCheckedChange={setHasStages} aria-label="Has stages" />
            <span>
              Moves through stages
              <span className="block text-xs text-muted-foreground">e.g. Available → Reserved → Sold.</span>
            </span>
          </label>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!singular.trim() || !/^[a-z][a-z0-9_]{1,39}$/.test(key)}>
              Add
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type Tab = "details" | "fields" | "stages" | "access" | "layout" | "field-access";

function TypeEditor({ rtype, onDeleted }: { rtype: RecordType; onDeleted: () => void }) {
  const [tab, setTab] = useState<Tab>("fields");
  const tabs: [Tab, string][] = [
    ["fields", "Fields"],
    ["layout", "Page layout"],
    ["field-access", "Field access"],
    ...(rtype.has_stages ? ([["stages", "Stages"]] as [Tab, string][]) : []),
    ["access", "Who can do what"],
    ["details", "Details"],
  ];
  return (
    <div className="space-y-4">
      <div className="flex gap-4 overflow-x-auto border-b text-sm">
        {tabs.map(([key, name]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn("-mb-px border-b-2 border-transparent pb-2 whitespace-nowrap text-muted-foreground", tab === key && "border-primary font-medium text-foreground")}
          >
            {name}
          </button>
        ))}
      </div>
      {tab === "fields" && <FieldSettings entity={`rt:${rtype.key}`} />}
      {tab === "stages" && <Stages rtype={rtype} />}
      {tab === "access" && <Access rtype={rtype} />}
      {tab === "layout" && <LayoutSettings entity={`rt:${rtype.key}`} />}
      {tab === "field-access" && <FieldAccessSettings entity={`rt:${rtype.key}`} />}
      {tab === "details" && <Details rtype={rtype} onDeleted={onDeleted} />}
    </div>
  );
}

function Details({ rtype, onDeleted }: { rtype: RecordType; onDeleted: () => void }) {
  const save = useSave();
  const [singular, setSingular] = useState(rtype.singular);
  const [plural, setPlural] = useState(rtype.plural);
  const patch = (body: Record<string, unknown>, ok = "Saved") =>
    save(async () => unwrap(await api.PATCH("/api/v1/record-types/{type_id}", { params: { path: { type_id: rtype.id } }, body })), ok);
  return (
    <div className="space-y-6 text-sm">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="d-s">Name (one)</Label>
          <Input id="d-s" value={singular} onChange={(e) => setSingular(e.target.value)} onBlur={() => singular !== rtype.singular && patch({ singular })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="d-p">Name (many)</Label>
          <Input id="d-p" value={plural} onChange={(e) => setPlural(e.target.value)} onBlur={() => plural !== rtype.plural && patch({ plural })} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Key <span className="font-mono">{rtype.key}</span> (fixed).
      </p>
      {(
        [
          ["has_owner", "Each one has an owner", "Off = shared with everyone allowed to view."],
          ["has_stages", "Moves through stages", "Adds a Stages tab and a stage bar on each record."],
          ["is_active", "Switched on", "Off hides the list for everyone; nothing is deleted."],
        ] as const
      ).map(([k, title, hint]) => (
        <label key={k} className="flex items-start gap-2">
          <Switch checked={rtype[k]} aria-label={title} onCheckedChange={(on) => patch({ [k]: on })} />
          <span>
            {title}
            <span className="block text-xs text-muted-foreground">{hint}</span>
          </span>
        </label>
      ))}
      <div className="border-t pt-4">
        <Button
          variant="ghost"
          className="text-destructive"
          onClick={async () => {
            if (!confirm(`Delete the record type ${rtype.plural}? Only possible while there are none of them.`)) return;
            if (await save(async () => unwrap(await api.DELETE("/api/v1/record-types/{type_id}", { params: { path: { type_id: rtype.id } } })), "Deleted")) onDeleted();
          }}
        >
          <Trash2 /> Delete this record type
        </Button>
      </div>
    </div>
  );
}

function Stages({ rtype }: { rtype: RecordType }) {
  const stages = useRecordStages(rtype.id);
  const fields = useRecordFields(rtype.key);
  const save = useSave();
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<RecordStage | null>(null);
  const list = stages.data ?? [];
  const order = (ids: string[]) => save(async () => unwrap(await api.PUT("/api/v1/record-types/{type_id}/stages/order", { params: { path: { type_id: rtype.id } }, body: { ids } })));
  const requirable: [string, string][] = [...(rtype.has_owner ? ([["owner", "Owner"]] as [string, string][]) : []), ...(fields.data ?? []).map((f) => [f.key, f.label] as [string, string])];

  return (
    <div className="space-y-4 text-sm">
      <div className="divide-y surface">
        {list.map((s, i) => (
          <div key={s.id} className="flex items-center gap-3 px-3 py-2">
            <div className="flex flex-col">
              <button aria-label={`Move ${s.name} up`} disabled={i === 0} className="text-muted-foreground disabled:opacity-30" onClick={() => order(swap(list, i, -1))}>
                <ArrowUp className="size-3" />
              </button>
              <button aria-label={`Move ${s.name} down`} disabled={i === list.length - 1} className="text-muted-foreground disabled:opacity-30" onClick={() => order(swap(list, i, 1))}>
                <ArrowDown className="size-3" />
              </button>
            </div>
            <span className="size-2.5 rounded-full" style={{ background: s.colour ?? "#94a3b8" }} />
            <button className="font-medium hover:underline" onClick={() => setEditing(s)}>
              {s.name}
            </button>
            <span className="text-xs text-muted-foreground">
              {s.is_open ? "open" : "closed"}
              {s.required_fields.length > 0 && ` · needs ${s.required_fields.map((k) => requirable.find(([r]) => r === k)?.[1] ?? k).join(", ")}`}
            </span>
            <Button
              size="icon-sm"
              variant="ghost"
              className="ms-auto"
              aria-label={`Delete ${s.name}`}
              onClick={() => save(async () => unwrap(await api.DELETE("/api/v1/record-types/{type_id}/stages/{stage_id}", { params: { path: { type_id: rtype.id, stage_id: s.id } } })), "Deleted")}
            >
              <Trash2 />
            </Button>
          </div>
        ))}
      </div>
      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await save(async () => unwrap(await api.POST("/api/v1/record-types/{type_id}/stages", { params: { path: { type_id: rtype.id } }, body: { name, is_open: true, required_fields: [] } })), "Stage added")) setName("");
        }}
      >
        <Input aria-label="New stage" placeholder="Add a stage" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" variant="outline" disabled={!name.trim()}>
          Add
        </Button>
      </form>
      {editing && <StageDialog rtype={rtype} stage={editing} requirable={requirable} onClose={() => setEditing(null)} />}
    </div>
  );
}

function StageDialog({ rtype, stage, requirable, onClose }: { rtype: RecordType; stage: RecordStage; requirable: [string, string][]; onClose: () => void }) {
  const save = useSave();
  const [name, setName] = useState(stage.name);
  const [isOpen, setIsOpen] = useState(stage.is_open);
  const [colour, setColour] = useState(stage.colour ?? "#94a3b8");
  const [required, setRequired] = useState<string[]>(stage.required_fields);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit {stage.name}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4 text-sm"
          onSubmit={async (e) => {
            e.preventDefault();
            const ok = await save(
              async () =>
                unwrap(
                  await api.PATCH("/api/v1/record-types/{type_id}/stages/{stage_id}", {
                    params: { path: { type_id: rtype.id, stage_id: stage.id } },
                    body: { name, is_open: isOpen, colour, required_fields: required },
                  }),
                ),
              "Saved",
            );
            if (ok) onClose();
          }}
        >
          <div className="flex gap-2">
            <Input aria-label="Stage name" value={name} onChange={(e) => setName(e.target.value)} />
            <input type="color" aria-label="Colour" className="h-8 w-10 rounded border" value={colour} onChange={(e) => setColour(e.target.value)} />
          </div>
          <label className="flex items-center gap-2">
            <Switch checked={isOpen} onCheckedChange={setIsOpen} aria-label="Open stage" /> Open (still in progress)
          </label>
          {requirable.length > 0 && (
            <div className="space-y-1.5">
              <Label>Must be filled in before moving here</Label>
              {requirable.map(([k, l]) => (
                <label key={k} className="flex items-center gap-2 text-xs">
                  <input type="checkbox" className="accent-primary" checked={required.includes(k)} onChange={(e) => setRequired(e.target.checked ? [...required, k] : required.filter((x) => x !== k))} />
                  {l}
                </label>
              ))}
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim()}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Access({ rtype }: { rtype: RecordType }) {
  const save = useSave();
  const qc = useQueryClient();
  const access = useQuery({
    queryKey: ["record-access", rtype.id],
    queryFn: async () => unwrap(await api.GET("/api/v1/record-types/{type_id}/access", { params: { path: { type_id: rtype.id } } })),
  });
  const rows = access.data ?? [];
  async function update(row: RoleAccess, patch: Partial<RoleAccess>) {
    const next = { ...row, ...patch };
    if (patch.view === false) Object.assign(next, { create: false, edit: false, delete: false });
    if (patch.create || patch.edit || patch.delete) next.view = true;
    await save(async () => unwrap(await api.PUT("/api/v1/record-types/{type_id}/access", { params: { path: { type_id: rtype.id } }, body: [next] })));
    qc.invalidateQueries({ queryKey: ["record-access", rtype.id] });
  }
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">The Owner can always do everything. {rtype.has_owner ? "“Sees” works like leads: their own, their team's, or all." : "This type is shared: anyone who can view sees all of them."}</p>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-start text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Role</th>
              {["View", "Add", "Edit", "Delete"].map((h) => (
                <th key={h} className="px-3 py-2 text-center font-medium">
                  {h}
                </th>
              ))}
              {rtype.has_owner && <th className="px-3 py-2 font-medium">Sees</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.role_id} className="border-t">
                <td className="px-3 py-2 font-medium">{r.role_name}</td>
                {(["view", "create", "edit", "delete"] as const).map((k) => (
                  <td key={k} className="px-3 py-2 text-center">
                    <input type="checkbox" aria-label={`${r.role_name} ${k}`} className="accent-primary" checked={r[k]} onChange={(e) => update(r, { [k]: e.target.checked })} />
                  </td>
                ))}
                {rtype.has_owner && (
                  <td className="px-3 py-2">
                    <NativeSelect aria-label={`${r.role_name} sees`} className="w-auto" value={r.scope} onChange={(e) => update(r, { scope: e.target.value as RoleAccess["scope"] })}>
                      <option value="own">Their own</option>
                      <option value="team">Their team&apos;s</option>
                      <option value="all">All</option>
                    </NativeSelect>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- link types ----------
function LinkTypes({ types }: { types: RecordType[] }) {
  const label = useLabels();
  const linkTypes = useLinkTypes();
  const save = useSave();
  const [adding, setAdding] = useState(false);
  const kindOf = (k: string, id: string | null) => (k === "record" ? (types.find((t) => t.id === id)?.plural ?? "?") : label(k, true));
  return (
    <section className="space-y-3 border-t pt-6">
      <h3 className="font-medium">How things link</h3>
      <p className="text-xs text-muted-foreground">
        For example: a {label("lead").toLowerCase()} is <i>interested in</i> a property, and a property has <i>interested buyers</i>. Links show on
        both records.
      </p>
      <div className="divide-y surface text-sm">
        {(linkTypes.data ?? []).length === 0 && <p className="p-4 text-muted-foreground">No links set up yet.</p>}
        {(linkTypes.data ?? []).map((lt: LinkType) => (
          <div key={lt.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5">
            <Switch
              aria-label={`${lt.label} on`}
              checked={lt.is_active}
              onCheckedChange={(on) => save(async () => unwrap(await api.PATCH("/api/v1/link-types/{link_type_id}", { params: { path: { link_type_id: lt.id } }, body: { is_active: on } })))}
            />
            <span>
              {kindOf(lt.from_kind, lt.from_type_id)} <b>{lt.label}</b> {kindOf(lt.to_kind, lt.to_type_id)}
            </span>
            <span className="text-xs text-muted-foreground">
              · back: <b>{lt.inverse_label}</b> · {lt.many_to ? "many" : "one"} per {kindOf(lt.from_kind, lt.from_type_id).toLowerCase()}, {lt.many_from ? "many" : "one"} per{" "}
              {kindOf(lt.to_kind, lt.to_type_id).toLowerCase()}
            </span>
            <Button
              size="icon-sm"
              variant="ghost"
              className="ms-auto"
              aria-label={`Delete ${lt.label}`}
              onClick={() => confirm(`Delete "${lt.label}"?`) && save(async () => unwrap(await api.DELETE("/api/v1/link-types/{link_type_id}", { params: { path: { link_type_id: lt.id } } })), "Deleted")}
            >
              <Trash2 />
            </Button>
          </div>
        ))}
      </div>
      <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
        <Plus /> Add a link
      </Button>
      {adding && <LinkTypeDialog types={types} onClose={() => setAdding(false)} />}
    </section>
  );
}

export function LinkTypeDialog({ types, onClose }: { types: RecordType[]; onClose: () => void }) {
  const label = useLabels();
  const save = useSave();
  const [from, setFrom] = useState("lead");
  const [to, setTo] = useState(types[0]?.id ?? "lead");
  const [name, setName] = useState("");
  const [back, setBack] = useState("");
  const [manyTo, setManyTo] = useState(true);
  const [manyFrom, setManyFrom] = useState(true);
  // "lead" and "deal" are built in; anything else is a record type's id.
  const kinds: [string, string][] = [["lead", label("lead", true)], ["deal", label("deal", true)], ...types.map((t) => [t.id, t.plural] as [string, string])];
  const side = (v: string) => (v === "lead" || v === "deal" ? { kind: v as "lead" | "deal", type: null } : { kind: "record" as const, type: v });
  const kindName = (k: string) => kinds.find(([v]) => v === k)?.[1] ?? "";
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add a link</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4 text-sm"
          onSubmit={async (e) => {
            e.preventDefault();
            const ok = await save(
              async () =>
                unwrap(
                  await api.POST("/api/v1/link-types", {
                    body: {
                      from_kind: side(from).kind,
                      to_kind: side(to).kind,
                      from_type_id: side(from).type,
                      to_type_id: side(to).type,
                      label: name,
                      inverse_label: back,
                      many_to: manyTo,
                      many_from: manyFrom,
                    },
                  }),
                ),
              "Link added",
            );
            if (ok) onClose();
          }}
        >
          <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-2">
            <NativeSelect aria-label="From" value={from} onChange={(e) => setFrom(e.target.value)}>
              {kinds.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </NativeSelect>
            <span className="pb-1.5 text-muted-foreground">→</span>
            <NativeSelect aria-label="To" value={to} onChange={(e) => setTo(e.target.value)}>
              {kinds.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="lt-name">Seen from {kindName(from).toLowerCase()}</Label>
              <Input id="lt-name" placeholder="Interested in" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lt-back">Seen from {kindName(to).toLowerCase()}</Label>
              <Input id="lt-back" placeholder="Interested buyers" value={back} onChange={(e) => setBack(e.target.value)} />
            </div>
          </div>
          <label className="flex items-center gap-2">
            <Switch checked={manyTo} onCheckedChange={setManyTo} aria-label="Many per from" /> One {kindName(from).toLowerCase()} can have several
          </label>
          <label className="flex items-center gap-2">
            <Switch checked={manyFrom} onCheckedChange={setManyFrom} aria-label="Many per to" /> One {kindName(to).toLowerCase()} can have several
          </label>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || !back.trim()}>
              Add
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
