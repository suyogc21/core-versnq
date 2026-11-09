"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type FieldDef, type FieldOption } from "@/lib/crm";

/** Custom fields of one kind: "lead", or "rt:<record type key>". Same rules for both. */
export const TYPES: [string, string][] = [
  ["text", "Text"],
  ["number", "Number"],
  ["date", "Date"],
  ["select", "Dropdown"],
  ["multi_select", "Multi-choice"],
  ["phone", "Phone"],
  ["email", "Email"],
  ["url", "Link"],
];

export const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^(\d)/, "f_$1")
    .slice(0, 60);

function useFieldsOf(entity: string) {
  return useQuery({
    queryKey: entity === "lead" ? ["fields"] : ["fields", entity],
    queryFn: async () => unwrap(await api.GET("/api/v1/custom-fields", { params: { query: { entity } } })),
  });
}

function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      for (const k of ["fields", "stages", "record-stages"]) qc.invalidateQueries({ queryKey: [k] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

function move<T extends { id: string }>(items: T[], index: number, dir: -1 | 1): string[] {
  const ids = items.map((i) => i.id);
  const j = index + dir;
  if (j < 0 || j >= ids.length) return ids;
  [ids[index], ids[j]] = [ids[j], ids[index]];
  return ids;
}

export function FieldSettings({ entity }: { entity: string }) {
  const fields = useFieldsOf(entity);
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
              <button aria-label={`Move ${f.label} up`} className="text-muted-foreground" onClick={() => save(async () => unwrap(await api.PUT("/api/v1/custom-fields/order", { params: { query: { entity } }, body: { ids: move(list, i, -1) } })))}>
                <ArrowUp className="size-3" />
              </button>
              <button aria-label={`Move ${f.label} down`} className="text-muted-foreground" onClick={() => save(async () => unwrap(await api.PUT("/api/v1/custom-fields/order", { params: { query: { entity } }, body: { ids: move(list, i, 1) } })))}>
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
      {editing && <FieldDialog entity={entity} field={editing === "new" ? null : editing} all={list} onClose={() => setEditing(null)} />}
    </div>
  );
}

export function OptionsEditor({ options, onChange, parentOptions }: { options: FieldOption[]; onChange: (o: FieldOption[]) => void; parentOptions?: FieldOption[] }) {
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

function FieldDialog({ entity, field, all, onClose }: { entity: string; field: FieldDef | null; all: FieldDef[]; onClose: () => void }) {
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
    e.stopPropagation(); // opened from inside a record's edit form: don't submit that too
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
                params: { query: { entity } },
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


/** For admins, right where they work: add a field without going to Settings. */
export function AddFieldButton({ entity }: { entity: string }) {
  const fields = useFieldsOf(entity);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="text-xs text-primary hover:underline" onClick={() => setOpen(true)}>
        + Add a field
      </button>
      {open && <FieldDialog entity={entity} field={null} all={fields.data ?? []} onClose={() => setOpen(false)} />}
    </>
  );
}
