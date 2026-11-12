"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Star, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { type Layout, useLayout } from "@/lib/layouts";
import { cn } from "@/lib/utils";

type Section = { name: string; fields: string[] };
const MAX_HIGHLIGHTS = 4;

/** Settings → Records and fields → Page layout (step 8): sections and their order, up to 4
 * highlights under the name, and which fields the "add" form asks for. */
export function LayoutSettings({ entity }: { entity: string }) {
  const layout = useLayout(entity);
  if (!layout.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return <LayoutEditor key={`${layout.data.updated_at ?? "default"}-${layout.data.fields.length}`} entity={entity} layout={layout.data} />;
}

function LayoutEditor({ entity, layout }: { entity: string; layout: Layout }) {
  const qc = useQueryClient();
  const [sections, setSections] = useState<Section[]>(layout.sections.map((s) => ({ name: s.name, fields: [...s.fields] })));
  const [highlights, setHighlights] = useState<string[]>(layout.highlights ?? []);
  const [addForm, setAddForm] = useState<string[]>(layout.add_form ?? []);
  const [newSection, setNewSection] = useState("");
  // a standard field and a custom one can share a name ("Company size"): tell them apart
  const label = new Map(layout.fields.map((f) => [f.key, f.builtin ? `${f.label} (standard)` : f.label]));
  const required = new Set(layout.fields.filter((f) => f.required).map((f) => f.key));
  const placed = new Set(sections.flatMap((s) => s.fields));
  const offPage = layout.fields.filter((f) => !placed.has(f.key));

  const update = (i: number, fn: (s: Section) => Section) => setSections(sections.map((s, j) => (j === i ? fn(s) : s)));
  const move = (i: number, k: number, by: number) =>
    update(i, (s) => {
      const f = [...s.fields];
      [f[k], f[k + by]] = [f[k + by], f[k]];
      return { ...s, fields: f };
    });
  const moveTo = (key: string, target: number) =>
    setSections(sections.map((s, j) => ({ ...s, fields: j === target ? [...s.fields.filter((x) => x !== key), key] : s.fields.filter((x) => x !== key) })));
  const toggleHighlight = (key: string) => {
    if (highlights.includes(key)) setHighlights(highlights.filter((k) => k !== key));
    else if (highlights.length < MAX_HIGHLIGHTS) setHighlights([...highlights, key]);
    else toast.error(`Up to ${MAX_HIGHLIGHTS} highlights`);
  };

  async function save() {
    try {
      unwrap(await api.PUT("/api/v1/layouts/{entity}", { params: { path: { entity } }, body: { sections, highlights, add_form: addForm } }));
      qc.invalidateQueries({ queryKey: ["layout", entity] });
      toast.success("Layout saved");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function reset() {
    if (!confirm("Go back to the standard page? Your sections, highlights and add-form choices are removed.")) return;
    try {
      unwrap(await api.DELETE("/api/v1/layouts/{entity}", { params: { path: { entity } } }));
      qc.invalidateQueries({ queryKey: ["layout", entity] });
      toast.success("Back to the standard page");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const fieldRow = (key: string, i: number, k: number, count: number) => (
    <li key={key} className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-sm" data-layout-field={label.get(key)}>
      <button
        type="button"
        aria-label={`Highlight ${label.get(key)}`}
        aria-pressed={highlights.includes(key)}
        onClick={() => toggleHighlight(key)}
        className={cn("text-muted-foreground hover:text-foreground", highlights.includes(key) && "text-amber-500 hover:text-amber-600")}
      >
        <Star className={cn("size-4", highlights.includes(key) && "fill-current")} />
      </button>
      <span className="min-w-0 flex-1 truncate">{label.get(key)}</span>
      {key.startsWith("cf.") && (
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            aria-label={`${label.get(key)} on the add form`}
            checked={required.has(key) || addForm.includes(key)}
            disabled={required.has(key)}
            onChange={(e) => setAddForm(e.target.checked ? [...addForm, key] : addForm.filter((x) => x !== key))}
          />
          Add form
        </label>
      )}
      <Button type="button" size="icon-sm" variant="ghost" aria-label={`Move ${label.get(key)} up`} disabled={k === 0} onClick={() => move(i, k, -1)}>
        <ArrowUp />
      </Button>
      <Button type="button" size="icon-sm" variant="ghost" aria-label={`Move ${label.get(key)} down`} disabled={k === count - 1} onClick={() => move(i, k, 1)}>
        <ArrowDown />
      </Button>
      <NativeSelect
        aria-label={`Section for ${label.get(key)}`}
        className="h-7 w-36"
        value={String(i)}
        onChange={(e) => (e.target.value === "off" ? update(i, (s) => ({ ...s, fields: s.fields.filter((x) => x !== key) })) : moveTo(key, Number(e.target.value)))}
      >
        {sections.map((s, j) => (
          <option key={j} value={j}>
            {s.name}
          </option>
        ))}
        <option value="off">Not on the page</option>
      </NativeSelect>
    </li>
  );

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Arrange the record page for everyone. ★ puts a field under the record&apos;s name (up to {MAX_HIGHLIGHTS}). What each role may see or change is set
        under Field access.
        {layout.is_default && " You are looking at the standard page; save to make it yours."}
      </p>
      {sections.map((s, i) => (
        <div key={i} className="surface" data-section={s.name}>
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <Input aria-label={`Section ${i + 1} name`} className="h-7 max-w-60 font-medium" value={s.name} onChange={(e) => update(i, (x) => ({ ...x, name: e.target.value }))} />
            <Button type="button" size="icon-sm" variant="ghost" aria-label={`Move section ${s.name} up`} disabled={i === 0} onClick={() => setSections(swap(sections, i, i - 1))}>
              <ArrowUp />
            </Button>
            <Button type="button" size="icon-sm" variant="ghost" aria-label={`Move section ${s.name} down`} disabled={i === sections.length - 1} onClick={() => setSections(swap(sections, i, i + 1))}>
              <ArrowDown />
            </Button>
            <Button type="button" size="icon-sm" variant="ghost" className="ml-auto" aria-label={`Remove section ${s.name}`} onClick={() => setSections(sections.filter((_, j) => j !== i))}>
              <Trash2 />
            </Button>
          </div>
          <ul className="divide-y">
            {s.fields.length === 0 && <li className="px-3 py-2 text-xs text-muted-foreground">Empty: move fields here.</li>}
            {s.fields.map((key, k) => fieldRow(key, i, k, s.fields.length))}
          </ul>
        </div>
      ))}
      <div className="flex gap-2">
        <Input aria-label="New section name" placeholder="New section, e.g. Requirement" className="h-8 max-w-64" value={newSection} onChange={(e) => setNewSection(e.target.value)} />
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!newSection.trim()}
          onClick={() => {
            setSections([...sections, { name: newSection.trim(), fields: [] }]);
            setNewSection("");
          }}
        >
          <Plus /> Add section
        </Button>
      </div>
      {offPage.length > 0 && (
        <div className="surface">
          <div className="border-b px-3 py-2 text-sm font-medium">Not on the page</div>
          <ul className="divide-y">
            {offPage.map((f) => (
              <li key={f.key} className="flex items-center gap-2 px-3 py-1.5 text-sm" data-off-page={f.label}>
                <span className="flex-1 truncate text-muted-foreground">{label.get(f.key)}</span>
                <NativeSelect aria-label={`Place ${label.get(f.key)}`} className="h-7 w-40" value="" onChange={(e) => e.target.value && moveTo(f.key, Number(e.target.value))}>
                  <option value="">Place in…</option>
                  {sections.map((s, j) => (
                    <option key={j} value={j}>
                      {s.name}
                    </option>
                  ))}
                </NativeSelect>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex gap-2">
        <Button onClick={save} disabled={sections.some((s) => !s.name.trim())}>
          Save layout
        </Button>
        {!layout.is_default && (
          <Button variant="ghost" onClick={reset}>
            Back to standard page
          </Button>
        )}
      </div>
    </div>
  );
}

function swap<T>(list: T[], a: number, b: number): T[] {
  const out = [...list];
  [out[a], out[b]] = [out[b], out[a]];
  return out;
}

// ---------- field access ----------
const CHOICE: Record<string, string> = { edit: "Edit", view: "View only", hidden: "Hidden" };

/** Settings → Records and fields → Field access (step 8): for each role and field, Edit,
 * View only or Hidden. Owner and Admin always edit everything. */
export function FieldAccessSettings({ entity }: { entity: string }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const grid = useQuery({
    queryKey: ["field-access", entity],
    enabled: can("roles.manage"),
    queryFn: async () => unwrap(await api.GET("/api/v1/field-access/{entity}", { params: { path: { entity } } })),
  });
  if (!can("roles.manage")) return <p className="text-sm text-muted-foreground">Ask someone who manages roles to change field access.</p>;
  if (!grid.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const roles = grid.data.roles;

  async function setCell(roleId: string, field: string, value: string) {
    const role = roles.find((r) => r.id === roleId)!;
    const access: Record<string, "edit" | "view" | "hidden"> = { ...(role.access as Record<string, "view" | "hidden">), [field]: value as "edit" | "view" | "hidden" };
    try {
      unwrap(await api.PUT("/api/v1/field-access/{entity}/{role_id}", { params: { path: { entity, role_id: roleId } }, body: { access } }));
      qc.invalidateQueries({ queryKey: ["field-access", entity] });
      qc.invalidateQueries({ queryKey: ["layout", entity] });
      toast.success(`${role.name}: ${CHOICE[value].toLowerCase()}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Hidden fields never leave the server for that role: not on the page, in lists, search, exports or the API. View only fields can be seen but not
        changed. Phone and email can be view only at most, so people can still reach the lead.
      </p>
      <div className="overflow-x-auto surface">
        <table className="w-full text-sm" data-access-grid>
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-3 py-2 font-medium">Field</th>
              {roles.map((r) => (
                <th key={r.id} className="px-2 py-2 font-medium whitespace-nowrap">
                  {r.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {grid.data.fields.map((f) => (
              <tr key={f.key}>
                <td className="px-3 py-1.5 whitespace-nowrap">
                  {f.label}
                  {f.builtin && <span className="ml-1.5 text-[10px] text-muted-foreground uppercase">standard</span>}
                </td>
                {roles.map((r) => (
                  <td key={r.id} className="px-2 py-1">
                    {r.locked ? (
                      <span className="text-xs text-muted-foreground">Edit</span>
                    ) : (
                      <NativeSelect
                        aria-label={`${f.label}${f.builtin ? " (standard)" : ""} for ${r.name}`}
                        className="h-7 w-28"
                        value={(r.access as Record<string, string>)[f.key] ?? "edit"}
                        onChange={(e) => setCell(r.id, f.key, e.target.value)}
                      >
                        {f.choices.map((c) => (
                          <option key={c} value={c}>
                            {CHOICE[c]}
                          </option>
                        ))}
                      </NativeSelect>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
