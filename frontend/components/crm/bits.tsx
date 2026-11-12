"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/app/native-select";
import { type FieldDef, type FieldOption, initials, type Stage } from "@/lib/crm";
import { accessOf, addFormFields, customSections, type Layout } from "@/lib/layouts";
import { cn } from "@/lib/utils";

export function StagePill({ stage, className }: { stage: Stage | undefined; className?: string }) {
  if (!stage) return <span className="text-muted-foreground">—</span>;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs whitespace-nowrap", className)}>
      <span className="size-2 rounded-full" style={{ background: stage.colour ?? "#94a3b8" }} />
      {stage.name}
    </span>
  );
}

export function Avatar({ name, colour, size = 6 }: { name: string; colour?: string | null; size?: number }) {
  return (
    <span
      title={name}
      className="grid shrink-0 place-items-center rounded-full text-[10px] font-semibold text-white"
      style={{ background: colour ?? "#64748b", width: size * 4, height: size * 4, fontSize: Math.max(10, size * 1.4) }}
    >
      {initials(name)}
    </span>
  );
}

/** One input for one custom field. Linked dropdowns only offer options of the chosen parent. */
export function CustomFieldInput({
  field,
  value,
  parentValue,
  onChange,
}: {
  field: FieldDef;
  value: unknown;
  parentValue?: unknown;
  onChange: (value: unknown) => void;
}) {
  const id = `cf-${field.key}`;
  let options = field.options as FieldOption[];
  if (field.depends_on) options = options.filter((o) => o.parent === parentValue);
  const waiting = Boolean(field.depends_on) && !parentValue;
  let input: React.ReactNode;
  if (field.type === "select") {
    input = (
      <NativeSelect id={id} value={(value as string) ?? ""} disabled={waiting} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">{waiting ? "Choose the field above first" : "—"}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </NativeSelect>
    );
  } else if (field.type === "multi_select") {
    const selected = new Set((value as string[]) ?? []);
    input = (
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <button
            type="button"
            key={o.value}
            onClick={() => {
              const next = new Set(selected);
              if (next.has(o.value)) next.delete(o.value);
              else next.add(o.value);
              onChange(next.size ? [...next] : null);
            }}
            className={cn("rounded-full border px-2 py-0.5 text-xs", selected.has(o.value) && "border-primary bg-primary/10")}
          >
            {o.label}
          </button>
        ))}
      </div>
    );
  } else {
    const type = { number: "number", date: "date", email: "email", url: "url", phone: "tel" }[field.type] ?? "text";
    input = <Input id={id} type={type} value={(value as string | number) ?? ""} onChange={(e) => onChange(e.target.value || null)} />;
  }
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {field.label}
        {field.required && <span className="text-destructive"> *</span>}
      </Label>
      {input}
    </div>
  );
}

/** Custom fields grouped by their group name, with linked dropdowns wired to their parent. */
export function CustomFieldsEditor({
  fields,
  values,
  onChange,
  layout,
  mode = "edit",
}: {
  fields: FieldDef[];
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  /** The company's layout (step 8): sections and order, hidden and view-only fields. */
  layout?: Layout;
  /** "add": only the fields the layout puts on the add form. */
  mode?: "edit" | "add";
}) {
  // Calculated fields fill themselves in; they are shown on the record, not edited.
  const editable = fields.filter((x) => x.type !== "calculated");
  const groups: [string, FieldDef[]][] =
    mode === "add" ? [["", addFormFields(layout, editable)]] : customSections(layout, editable);
  const set = (key: string, value: unknown) => {
    const next = { ...values, [key]: value };
    for (const child of fields.filter((f) => f.depends_on === key)) next[child.key] = null; // parent changed
    onChange(next);
  };
  return (
    <div className="space-y-4">
      {groups
        .filter(([, list]) => list.length > 0)
        .map(([group, list]) => (
          <div key={group} className="space-y-3">
            {group && <div className="text-[11px] tracking-wide text-muted-foreground uppercase">{group}</div>}
            <div className="grid gap-3 sm:grid-cols-2">
              {list.map((f) => (
                <fieldset key={f.key} disabled={accessOf(layout, `cf.${f.key}`) === "view"} className="min-w-0" title={accessOf(layout, `cf.${f.key}`) === "view" ? "View only" : undefined}>
                  <CustomFieldInput field={f} value={values[f.key]} parentValue={f.depends_on ? values[f.depends_on] : undefined} onChange={(v) => set(f.key, v)} />
                </fieldset>
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}
