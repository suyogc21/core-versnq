"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { StagePill } from "@/components/crm/bits";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import {
  type ActivityType,
  type FieldDef,
  type FieldOption,
  type Stage,
  useActivityTypes,
  useFields,
  useSources,
  useStages,
} from "@/lib/crm";
import { useLabels, useWorkspaceSettings } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Tab = "stages" | "sources" | "fields" | "activities";
const TYPES: [string, string][] = [
  ["text", "Text"],
  ["number", "Number"],
  ["date", "Date"],
  ["select", "Dropdown"],
  ["multi_select", "Multi-choice"],
  ["phone", "Phone"],
  ["email", "Email"],
  ["url", "Link"],
];
const BUILTIN_REQUIRABLE: [string, string][] = [
  ["phone", "Phone"],
  ["email", "Email"],
  ["owner", "Owner"],
  ["first_name", "First name"],
  ["last_name", "Last name"],
  ["org_name", "Company name"],
  ["city", "City"],
];

/** Every request that changes setup: toast the error, refresh the lists. */
function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      for (const k of ["stages", "sources", "fields", "activity-types", "settings"]) qc.invalidateQueries({ queryKey: [k] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^(\d)/, "f_$1")
    .slice(0, 60);

export default function SetupPage() {
  const [tab, setTab] = useState<Tab>("stages");
  const label = useLabels();
  const tabs: [Tab, string][] = [
    ["stages", "Stages"],
    ["sources", "Sources"],
    ["fields", "Custom fields"],
    ["activities", "Activity types"],
  ];
  return (
    <>
      <PageHeader title="Pipeline setup" />
      <div className="mx-auto w-full max-w-3xl p-4 sm:p-8">
        <p className="mb-4 text-muted-foreground">
          How your team works {label("lead", true).toLowerCase()}. Changes apply to everyone in your workspace.
        </p>
        <div className="mb-6 flex gap-4 overflow-x-auto border-b text-sm">
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
        {tab === "stages" && <Stages />}
        {tab === "sources" && <Sources />}
        {tab === "fields" && <Fields />}
        {tab === "activities" && <ActivityTypes />}
      </div>
    </>
  );
}

function move<T extends { id: string }>(items: T[], index: number, dir: -1 | 1): string[] {
  const ids = items.map((i) => i.id);
  const j = index + dir;
  if (j < 0 || j >= ids.length) return ids;
  [ids[index], ids[j]] = [ids[j], ids[index]];
  return ids;
}

// ---------- stages ----------
function Stages() {
  const { can } = useAuth();
  const stages = useStages();
  const settings = useWorkspaceSettings();
  const save = useSave();
  const [editing, setEditing] = useState<Stage | "new" | null>(null);
  const list = stages.data ?? [];
  return (
    <div className="space-y-6">
      {can("settings.manage") && settings.data && (
        <div className="flex items-start gap-3 rounded-lg border p-3">
          <Switch
            aria-label="Follow-up rule"
            checked={settings.data.follow_up_required}
            onCheckedChange={(on) =>
              save(async () => unwrap(await api.PATCH("/api/v1/settings", { body: { follow_up_required: on } })), on ? "Follow-up rule: strict" : "Follow-up rule: warn only")
            }
          />
          <div>
            <div className="font-medium">Every open lead needs a next follow-up</div>
            <p className="text-xs text-muted-foreground">
              On: logging a call or note on an open lead requires the next follow-up date. Off: it is suggested but not required.
            </p>
          </div>
        </div>
      )}
      <ul className="divide-y rounded-lg border">
        {list.map((s, i) => (
          <li key={s.id} className="flex items-center gap-2 px-3 py-2">
            <div className="flex flex-col">
              <button aria-label={`Move ${s.name} up`} className="text-muted-foreground hover:text-foreground" onClick={() => save(async () => unwrap(await api.PUT("/api/v1/lead-stages/order", { body: { ids: move(list, i, -1) } })))}>
                <ArrowUp className="size-3" />
              </button>
              <button aria-label={`Move ${s.name} down`} className="text-muted-foreground hover:text-foreground" onClick={() => save(async () => unwrap(await api.PUT("/api/v1/lead-stages/order", { body: { ids: move(list, i, 1) } })))}>
                <ArrowDown className="size-3" />
              </button>
            </div>
            <button className="min-w-0 flex-1 text-left" onClick={() => setEditing(s)}>
              <StagePill stage={s} />
              <span className="ml-2 text-xs text-muted-foreground">
                {s.is_open ? "Open" : s.is_unqualified ? "Closed · needs a reason" : s.is_converted ? "Closed · won" : "Closed"}
                {s.required_fields.length > 0 && ` · requires ${s.required_fields.length} field${s.required_fields.length > 1 ? "s" : ""}`}
                {s.is_system && " · built-in"}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <Button size="sm" onClick={() => setEditing("new")}>
        <Plus /> Add stage
      </Button>
      {editing && <StageDialog stage={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function StageDialog({ stage, onClose }: { stage: Stage | null; onClose: () => void }) {
  const fields = useFields();
  const save = useSave();
  const [v, setV] = useState({
    name: stage?.name ?? "",
    colour: stage?.colour ?? "#64748b",
    status: stage ? (stage.is_open ? "open" : stage.is_unqualified ? "unqualified" : stage.is_converted ? "won" : "closed") : "open",
    required: new Set(stage?.required_fields ?? []),
  });
  const requirable: [string, string][] = [...BUILTIN_REQUIRABLE, ...(fields.data ?? []).map((f): [string, string] => [f.key, f.label])];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      name: v.name.trim(),
      colour: v.colour,
      ...(stage?.is_system ? {} : { is_open: v.status === "open", is_unqualified: v.status === "unqualified", is_converted: v.status === "won" }),
      required_fields: [...v.required],
    };
    const ok = await save(async () =>
      stage
        ? unwrap(await api.PATCH("/api/v1/lead-stages/{stage_id}", { params: { path: { stage_id: stage.id } }, body }))
        : unwrap(await api.POST("/api/v1/lead-stages", { body: { is_open: true, is_unqualified: false, is_converted: false, ...body } })),
      "Stage saved",
    );
    if (ok) onClose();
  }
  async function remove() {
    if (stage && window.confirm(`Delete the stage "${stage.name}"?`)) {
      if (await save(async () => unwrap(await api.DELETE("/api/v1/lead-stages/{stage_id}", { params: { path: { stage_id: stage.id } } })), "Stage deleted")) onClose();
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{stage ? `Edit ${stage.name}` : "New stage"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className="flex gap-3">
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="st-name">Name</Label>
              <Input id="st-name" required value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="st-colour">Colour</Label>
              <input id="st-colour" type="color" className="h-8 w-12 rounded border" value={v.colour} onChange={(e) => setV({ ...v, colour: e.target.value })} />
            </div>
          </div>
          {!stage?.is_system && (
            <div className="space-y-1.5">
              <Label htmlFor="st-status">Kind</Label>
              <NativeSelect id="st-status" value={v.status} onChange={(e) => setV({ ...v, status: e.target.value })}>
                <option value="open">Open — still being worked (needs follow-ups)</option>
                <option value="won">Closed — won / converted</option>
                <option value="unqualified">Closed — lost / unqualified (needs a reason)</option>
                <option value="closed">Closed — other</option>
              </NativeSelect>
            </div>
          )}
          <fieldset className="space-y-1.5">
            <legend className="text-sm font-medium">Must be filled before entering this stage</legend>
            <div className="flex flex-wrap gap-1.5">
              {requirable.map(([key, name]) => (
                <button
                  type="button"
                  key={key}
                  onClick={() => {
                    const next = new Set(v.required);
                    if (next.has(key)) next.delete(key);
                    else next.add(key);
                    setV({ ...v, required: next });
                  }}
                  className={cn("rounded-full border px-2 py-0.5 text-xs", v.required.has(key) && "border-primary bg-primary/10")}
                >
                  {name}
                </button>
              ))}
            </div>
          </fieldset>
          <DialogFooter>
            {stage && !stage.is_system && (
              <Button type="button" variant="ghost" className="mr-auto text-destructive" onClick={remove}>
                <Trash2 /> Delete
              </Button>
            )}
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">Save</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------- sources ----------
function Sources() {
  const sources = useSources();
  const save = useSave();
  const [name, setName] = useState("");
  const list = sources.data ?? [];
  return (
    <div className="space-y-4">
      <ul className="divide-y rounded-lg border">
        {list.map((s, i) => (
          <li key={s.id} className="flex items-center gap-2 px-3 py-2">
            <div className="flex flex-col">
              <button aria-label={`Move ${s.name} up`} className="text-muted-foreground" onClick={() => save(async () => unwrap(await api.PUT("/api/v1/lead-sources/order", { body: { ids: move(list, i, -1) } })))}>
                <ArrowUp className="size-3" />
              </button>
              <button aria-label={`Move ${s.name} down`} className="text-muted-foreground" onClick={() => save(async () => unwrap(await api.PUT("/api/v1/lead-sources/order", { body: { ids: move(list, i, 1) } })))}>
                <ArrowDown className="size-3" />
              </button>
            </div>
            <span className={cn("flex-1", !s.is_active && "text-muted-foreground line-through")}>{s.name}</span>
            <Switch
              aria-label={`${s.name} active`}
              checked={s.is_active}
              onCheckedChange={(on) => save(async () => unwrap(await api.PATCH("/api/v1/lead-sources/{source_id}", { params: { path: { source_id: s.id } }, body: { is_active: on } })))}
            />
            <button
              aria-label={`Delete ${s.name}`}
              className="text-muted-foreground hover:text-destructive"
              onClick={() => window.confirm(`Delete "${s.name}"?`) && save(async () => unwrap(await api.DELETE("/api/v1/lead-sources/{source_id}", { params: { path: { source_id: s.id } } })), "Source deleted")}
            >
              <Trash2 className="size-4" />
            </button>
          </li>
        ))}
      </ul>
      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await save(async () => unwrap(await api.POST("/api/v1/lead-sources", { body: { name } })), "Source added")) setName("");
        }}
      >
        <Input aria-label="New source" placeholder="e.g. Trade show" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" disabled={!name.trim()}>
          Add
        </Button>
      </form>
      <p className="text-xs text-muted-foreground">A source in use cannot be deleted; switch it off to hide it from new {useLabels()("lead", true).toLowerCase()}.</p>
    </div>
  );
}

// ---------- custom fields ----------
function Fields() {
  const fields = useFields();
  const save = useSave();
  const [editing, setEditing] = useState<FieldDef | "new" | null>(null);
  const list = fields.data ?? [];
  return (
    <div className="space-y-4">
      <ul className="divide-y rounded-lg border">
        {list.length === 0 && <li className="p-3 text-muted-foreground">No custom fields yet.</li>}
        {list.map((f, i) => (
          <li key={f.id} className="flex items-center gap-2 px-3 py-2">
            <div className="flex flex-col">
              <button aria-label={`Move ${f.label} up`} className="text-muted-foreground" onClick={() => save(async () => unwrap(await api.PUT("/api/v1/custom-fields/order", { body: { ids: move(list, i, -1) } })))}>
                <ArrowUp className="size-3" />
              </button>
              <button aria-label={`Move ${f.label} down`} className="text-muted-foreground" onClick={() => save(async () => unwrap(await api.PUT("/api/v1/custom-fields/order", { body: { ids: move(list, i, 1) } })))}>
                <ArrowDown className="size-3" />
              </button>
            </div>
            <button className="min-w-0 flex-1 text-left" onClick={() => setEditing(f)}>
              <div className="font-medium">
                {f.label}
                {f.required && <span className="text-destructive"> *</span>}
              </div>
              <div className="text-xs text-muted-foreground">
                <span className="font-mono">{f.key}</span> · {TYPES.find(([t]) => t === f.type)?.[1]}
                {f.is_unique && " · unique"}
                {f.depends_on && ` · depends on ${list.find((p) => p.key === f.depends_on)?.label ?? f.depends_on}`}
                {f.group_name && ` · ${f.group_name}`}
              </div>
            </button>
          </li>
        ))}
      </ul>
      <Button size="sm" onClick={() => setEditing("new")}>
        <Plus /> Add field
      </Button>
      {editing && <FieldDialog field={editing === "new" ? null : editing} all={list} onClose={() => setEditing(null)} />}
    </div>
  );
}

function OptionsEditor({ options, onChange, parentOptions }: { options: FieldOption[]; onChange: (o: FieldOption[]) => void; parentOptions?: FieldOption[] }) {
  const [label, setLabel] = useState("");
  const [parent, setParent] = useState(parentOptions?.[0]?.value ?? "");
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {options.map((o, i) => (
          <li key={o.value} className="flex items-center gap-2 text-sm">
            <span className="flex-1">
              {o.label}
              {o.parent && <span className="text-xs text-muted-foreground"> · under {parentOptions?.find((p) => p.value === o.parent)?.label ?? o.parent}</span>}
            </span>
            <button type="button" aria-label={`Remove ${o.label}`} className="text-muted-foreground hover:text-destructive" onClick={() => onChange(options.filter((_, j) => j !== i))}>
              <Trash2 className="size-3.5" />
            </button>
          </li>
        ))}
      </ul>
      <div className="flex gap-1.5">
        {parentOptions && (
          <NativeSelect aria-label="Under" className="w-auto" value={parent} onChange={(e) => setParent(e.target.value)}>
            {parentOptions.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </NativeSelect>
        )}
        <Input aria-label="New option" placeholder="Add an option" value={label} onChange={(e) => setLabel(e.target.value)} />
        <Button
          type="button"
          variant="outline"
          disabled={!label.trim()}
          onClick={() => {
            const value = slug(label) || label;
            if (options.some((o) => o.value === value)) return toast.error("That option already exists");
            onChange([...options, { value, label: label.trim(), ...(parentOptions ? { parent } : {}) }]);
            setLabel("");
          }}
        >
          Add
        </Button>
      </div>
    </div>
  );
}

function FieldDialog({ field, all, onClose }: { field: FieldDef | null; all: FieldDef[]; onClose: () => void }) {
  const save = useSave();
  const [v, setV] = useState({
    label: field?.label ?? "",
    key: field?.key ?? "",
    type: field?.type ?? "text",
    options: (field?.options as FieldOption[]) ?? [],
    required: field?.required ?? false,
    is_unique: field?.is_unique ?? false,
    depends_on: field?.depends_on ?? "",
    group_name: field?.group_name ?? "",
  });
  const [keyTouched, setKeyTouched] = useState(false);
  const isChoice = v.type === "select" || v.type === "multi_select";
  const parents = all.filter((f) => f.type === "select" && f.key !== v.key);
  const parent = all.find((f) => f.key === v.depends_on);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const ok = await save(
      async () =>
        field
          ? unwrap(
              await api.PATCH("/api/v1/custom-fields/{field_id}", {
                params: { path: { field_id: field.id } },
                body: { label: v.label, required: v.required, group_name: v.group_name || null, ...(isChoice ? { options: v.options } : {}) },
              }),
            )
          : unwrap(
              await api.POST("/api/v1/custom-fields", {
                body: {
                  key: v.key,
                  label: v.label,
                  type: v.type,
                  options: isChoice ? v.options : [],
                  required: v.required,
                  is_unique: v.is_unique,
                  depends_on: v.depends_on || null,
                  group_name: v.group_name || null,
                },
              }),
            ),
      "Field saved",
    );
    if (ok) onClose();
  }
  async function remove() {
    if (field && window.confirm(`Delete "${field.label}"? Its values are removed from every record.`)) {
      if (await save(async () => unwrap(await api.DELETE("/api/v1/custom-fields/{field_id}", { params: { path: { field_id: field.id } } })), "Field deleted")) onClose();
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{field ? `Edit ${field.label}` : "New field"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="f-label">Label</Label>
            <Input
              id="f-label"
              required
              value={v.label}
              onChange={(e) => setV({ ...v, label: e.target.value, key: field || keyTouched ? v.key : slug(e.target.value) })}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="f-key">Key</Label>
              <Input
                id="f-key"
                className="font-mono text-xs"
                disabled={Boolean(field)}
                value={v.key}
                onChange={(e) => {
                  setKeyTouched(true);
                  setV({ ...v, key: e.target.value });
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="f-type">Type</Label>
              <NativeSelect id="f-type" disabled={Boolean(field)} value={v.type} onChange={(e) => setV({ ...v, type: e.target.value, options: [], depends_on: "" })}>
                {TYPES.map(([t, name]) => (
                  <option key={t} value={t}>
                    {name}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>
          {!field && <p className="-mt-2 text-xs text-muted-foreground">The key, type and uniqueness cannot change later. The label can.</p>}
          {isChoice && (
            <>
              {!field && parents.length > 0 && (
                <div className="space-y-1.5">
                  <Label htmlFor="f-dep">Depends on (optional)</Label>
                  <NativeSelect id="f-dep" value={v.depends_on} onChange={(e) => setV({ ...v, depends_on: e.target.value, options: [] })}>
                    <option value="">— Not linked</option>
                    {parents.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.label}
                      </option>
                    ))}
                  </NativeSelect>
                  <p className="text-xs text-muted-foreground">Each option then belongs to one option of the other field.</p>
                </div>
              )}
              <div className="space-y-1.5">
                <Label>Options</Label>
                <OptionsEditor
                  options={v.options}
                  onChange={(options) => setV({ ...v, options })}
                  parentOptions={parent ? (parent.options as FieldOption[]) : undefined}
                />
              </div>
            </>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="f-group">Group (optional)</Label>
            <Input id="f-group" placeholder="e.g. Interest, KYC" value={v.group_name} onChange={(e) => setV({ ...v, group_name: e.target.value })} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-primary" checked={v.required} onChange={(e) => setV({ ...v, required: e.target.checked })} />
            Required
          </label>
          {!field && ["text", "number", "email", "phone", "url"].includes(v.type) && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="accent-primary" checked={v.is_unique} onChange={(e) => setV({ ...v, is_unique: e.target.checked })} />
              Unique — no two records can share a value
            </label>
          )}
          <DialogFooter>
            {field && (
              <Button type="button" variant="ghost" className="mr-auto text-destructive" onClick={remove}>
                <Trash2 /> Delete
              </Button>
            )}
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">Save</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------- activity types ----------
function ActivityTypes() {
  const types = useActivityTypes();
  const save = useSave();
  const [editing, setEditing] = useState<ActivityType | "new" | null>(null);
  const list = (types.data ?? []).filter((t) => t.is_loggable);
  return (
    <div className="space-y-4">
      <ul className="divide-y rounded-lg border">
        {list.map((t) => (
          <li key={t.id} className="flex items-center gap-2 px-3 py-2">
            <button className="min-w-0 flex-1 text-left" onClick={() => setEditing(t)}>
              <div className={cn("font-medium", !t.is_active && "text-muted-foreground line-through")}>{t.label}</div>
              <div className="text-xs text-muted-foreground">
                {t.is_system ? "Built-in" : "Custom"}
                {t.key === "call" && ` · outcomes: ${((t.fields as FieldDef[])[0]?.options as FieldOption[] | undefined)?.map((o) => o.label).join(", ")}`}
                {!t.is_system && (t.fields as FieldDef[]).length > 0 && ` · ${(t.fields as FieldDef[]).map((f) => f.label).join(", ")}`}
              </div>
            </button>
            {!t.is_system && (
              <Switch
                aria-label={`${t.label} active`}
                checked={t.is_active}
                onCheckedChange={(on) => save(async () => unwrap(await api.PATCH("/api/v1/activity-types/{type_id}", { params: { path: { type_id: t.id } }, body: { is_active: on } })))}
              />
            )}
          </li>
        ))}
      </ul>
      <Button size="sm" onClick={() => setEditing("new")}>
        <Plus /> Add activity type
      </Button>
      {editing && <TypeDialog kind={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function TypeDialog({ kind, onClose }: { kind: ActivityType | null; onClose: () => void }) {
  const save = useSave();
  const isCall = kind?.key === "call";
  const fields = (kind?.fields as FieldDef[] | undefined) ?? [];
  const [labelText, setLabelText] = useState(kind?.label ?? "");
  const [outcomes, setOutcomes] = useState<FieldOption[]>(isCall ? (fields[0]?.options as FieldOption[]) : []);
  const [extra, setExtra] = useState<{ key: string; label: string; type: string; options: FieldOption[]; required: boolean }[]>(
    isCall ? [] : fields.map((f) => ({ key: f.key, label: f.label, type: f.type, options: f.options as FieldOption[], required: f.required })),
  );
  const [newField, setNewField] = useState({ label: "", type: "text" });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const body = isCall
      ? { label: labelText, fields: [{ key: "disposition", label: "Outcome", type: "select", required: true, options: outcomes }] }
      : { label: labelText, fields: extra };
    const ok = await save(
      async () =>
        kind
          ? unwrap(await api.PATCH("/api/v1/activity-types/{type_id}", { params: { path: { type_id: kind.id } }, body }))
          : unwrap(await api.POST("/api/v1/activity-types", { body: { key: slug(labelText), label: labelText, fields: extra } })),
      "Activity type saved",
    );
    if (ok) onClose();
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{kind ? `Edit ${kind.label}` : "New activity type"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="t-label">Name</Label>
            <Input id="t-label" required placeholder="e.g. Site visit done, Demo given" value={labelText} onChange={(e) => setLabelText(e.target.value)} />
          </div>
          {isCall ? (
            <div className="space-y-1.5">
              <Label>Call outcomes</Label>
              <OptionsEditor options={outcomes} onChange={setOutcomes} />
            </div>
          ) : kind?.is_system ? (
            <p className="text-xs text-muted-foreground">Built-in type: only the name can change.</p>
          ) : (
            <div className="space-y-2">
              <Label>Fields to fill when logging</Label>
              <ul className="space-y-1">
                {extra.map((f, i) => (
                  <li key={f.key} className="flex items-center gap-2 text-sm">
                    <span className="flex-1">
                      {f.label} <span className="text-xs text-muted-foreground">· {TYPES.find(([t]) => t === f.type)?.[1]}</span>
                    </span>
                    <label className="flex items-center gap-1 text-xs">
                      <input type="checkbox" className="accent-primary" checked={f.required} onChange={(e) => setExtra(extra.map((x, j) => (j === i ? { ...x, required: e.target.checked } : x)))} />
                      required
                    </label>
                    <button type="button" aria-label={`Remove ${f.label}`} className="text-muted-foreground hover:text-destructive" onClick={() => setExtra(extra.filter((_, j) => j !== i))}>
                      <Trash2 className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex gap-1.5">
                <Input aria-label="Field name" placeholder="Field name" value={newField.label} onChange={(e) => setNewField({ ...newField, label: e.target.value })} />
                <NativeSelect aria-label="Field type" className="w-auto" value={newField.type} onChange={(e) => setNewField({ ...newField, type: e.target.value })}>
                  {TYPES.filter(([t]) => t !== "select" && t !== "multi_select").map(([t, name]) => (
                    <option key={t} value={t}>
                      {name}
                    </option>
                  ))}
                </NativeSelect>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!newField.label.trim()}
                  onClick={() => {
                    setExtra([...extra, { key: slug(newField.label), label: newField.label.trim(), type: newField.type, options: [], required: false }]);
                    setNewField({ label: "", type: "text" });
                  }}
                >
                  Add
                </Button>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">Save</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
