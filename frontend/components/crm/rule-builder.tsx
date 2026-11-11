"use client";

import { X } from "lucide-react";

import { NativeSelect } from "@/components/app/native-select";
import { Input } from "@/components/ui/input";
import { type FieldOption, useFields, useSources, useStages } from "@/lib/crm";
import { useDealFields, useLostReasons, usePipelines } from "@/lib/deals";
import { useUsers } from "@/lib/directory";
import { type Condition, LIST_OPS, NO_VALUE_OPS, OPS, useTags } from "@/lib/organise";
import { useLabels } from "@/lib/settings";

export type FieldChoice = { key: string; label: string; kind: "choice" | "text" | "number" | "date" | "bool"; options?: { value: string; label: string }[] };

/** Every field a condition can test, with the choices for dropdown-like ones. */
export function useFieldChoices(subject: "lead" | "deal", { forFit = false } = {}): FieldChoice[] {
  const label = useLabels();
  const sources = useSources();
  const stages = useStages();
  const users = useUsers();
  const tags = useTags();
  const leadFields = useFields();
  const dealFields = useDealFields();
  const pipelines = usePipelines();
  const reasons = useLostReasons();
  const userOpts = (users.data ?? []).filter((u) => u.status === "active").map((u) => ({ value: u.id, label: u.name }));
  const tagOpts = (tags.data ?? []).map((t) => ({ value: t.id, label: t.name }));
  const custom = (subject === "lead" ? leadFields.data : dealFields.data) ?? [];
  const customChoices: FieldChoice[] = custom.map((f) => ({
    key: f.key,
    label: f.label,
    kind: f.type === "select" || f.type === "multi_select" ? "choice" : f.type === "number" || f.type === "calculated" ? "number" : f.type === "date" ? "date" : "text",
    options: (f.options as FieldOption[]).map((o) => ({ value: o.value, label: o.label })),
  }));
  if (subject === "lead") {
    const out: FieldChoice[] = [
      { key: "source_id", label: "Source", kind: "choice", options: (sources.data ?? []).map((s) => ({ value: s.id, label: s.name })) },
      { key: "stage_id", label: "Stage", kind: "choice", options: (stages.data ?? []).map((s) => ({ value: s.id, label: s.name })) },
      { key: "owner_user_id", label: "Owner", kind: "choice", options: userOpts },
      { key: "tags", label: "Tags", kind: "choice", options: tagOpts },
      { key: "kind", label: `${label("lead")} type`, kind: "choice", options: [{ value: "person", label: "Person" }, { value: "organisation", label: "Organisation" }] },
      { key: "is_open", label: "Is open", kind: "bool" },
      { key: "city", label: "City", kind: "text" },
      { key: "region", label: "Region", kind: "text" },
      { key: "country_code", label: "Country code", kind: "text" },
      { key: "preferred_language", label: "Language", kind: "text" },
      { key: "campaign", label: "Campaign", kind: "text" },
      { key: "utm_source", label: "UTM source", kind: "text" },
      { key: "utm_campaign", label: "UTM campaign", kind: "text" },
      { key: "last_disposition", label: "Last call outcome", kind: "text" },
      ...(forFit
        ? []
        : ([
            { key: "score", label: "Score", kind: "number" },
            { key: "score_band", label: "Score band", kind: "choice", options: [{ value: "hot", label: "Hot" }, { value: "warm", label: "Warm" }, { value: "cold", label: "Cold" }] },
          ] as FieldChoice[])),
      ...customChoices,
    ];
    return out;
  }
  return [
    { key: "pipeline_id", label: label("pipeline"), kind: "choice", options: (pipelines.data ?? []).map((p) => ({ value: p.id, label: p.name })) },
    {
      key: "stage_id",
      label: "Stage",
      kind: "choice",
      options: (pipelines.data ?? []).flatMap((p) => (p.stages ?? []).map((s) => ({ value: s.id, label: `${p.name} · ${s.name}` }))),
    },
    { key: "status", label: "Status", kind: "choice", options: [{ value: "open", label: "Open" }, { value: "won", label: "Won" }, { value: "lost", label: "Lost" }] },
    { key: "owner_user_id", label: "Owner", kind: "choice", options: userOpts },
    { key: "amount_minor", label: "Value (in paise / cents)", kind: "number" },
    { key: "expected_close_on", label: "Expected close", kind: "date" },
    { key: "lost_reason_id", label: "Lost reason", kind: "choice", options: (reasons.data ?? []).map((r) => ({ value: r.id, label: r.name })) },
    { key: "tags", label: "Tags", kind: "choice", options: tagOpts },
    ...customChoices,
  ];
}

const KIND_OPS: Record<FieldChoice["kind"], string[]> = {
  choice: ["is", "is_not", "any_of", "none_of", "empty", "not_empty"],
  text: ["is", "is_not", "contains", "empty", "not_empty"],
  number: ["is", "gt", "lt", "empty", "not_empty"],
  date: ["is", "gt", "lt", "empty", "not_empty"],
  bool: ["is"],
};

export function ConditionRow({ choices, value, onChange, onRemove }: { choices: FieldChoice[]; value: Condition; onChange: (c: Condition) => void; onRemove: () => void }) {
  const field = choices.find((c) => c.key === value.field);
  const ops = OPS.filter(([o]) => (field ? KIND_OPS[field.kind] : []).includes(o));
  const list = LIST_OPS.has(value.op);
  return (
    <div className="flex flex-wrap items-start gap-1.5 rounded-md border p-1.5">
      <NativeSelect aria-label="Field" className="h-8 w-auto max-w-48" value={value.field} onChange={(e) => onChange({ field: e.target.value, op: "is", value: undefined })}>
        <option value="">Choose a field…</option>
        {choices.map((c) => (
          <option key={c.key} value={c.key}>
            {c.label}
          </option>
        ))}
      </NativeSelect>
      {field && (
        <NativeSelect aria-label="Comparison" className="h-8 w-auto" value={value.op} onChange={(e) => onChange({ ...value, op: e.target.value, value: LIST_OPS.has(e.target.value) ? [] : undefined })}>
          {ops.map(([o, w]) => (
            <option key={o} value={o}>
              {w}
            </option>
          ))}
        </NativeSelect>
      )}
      {field && !NO_VALUE_OPS.has(value.op) && (
        <ValueInput field={field} list={list} value={value.value} onChange={(v) => onChange({ ...value, value: v })} />
      )}
      <button type="button" aria-label="Remove condition" className="ml-auto p-1.5 text-muted-foreground hover:text-destructive" onClick={onRemove}>
        <X className="size-3.5" />
      </button>
    </div>
  );
}

function ValueInput({ field, list, value, onChange }: { field: FieldChoice; list: boolean; value: unknown; onChange: (v: unknown) => void }) {
  if (field.kind === "bool") {
    return (
      <NativeSelect aria-label="Value" className="h-8 w-auto" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </NativeSelect>
    );
  }
  if (field.kind === "choice" && list) {
    const chosen = (value as string[] | undefined) ?? [];
    return (
      <div className="flex max-h-32 min-w-40 flex-col overflow-auto rounded border p-1 text-xs">
        {(field.options ?? []).map((o) => (
          <label key={o.value} className="flex items-center gap-1.5">
            <input type="checkbox" className="accent-primary" checked={chosen.includes(o.value)} onChange={(e) => onChange(e.target.checked ? [...chosen, o.value] : chosen.filter((x) => x !== o.value))} />
            {o.label}
          </label>
        ))}
      </div>
    );
  }
  if (field.kind === "choice") {
    return (
      <NativeSelect aria-label="Value" className="h-8 w-auto max-w-56" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {(field.options ?? []).map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </NativeSelect>
    );
  }
  return (
    <Input
      aria-label="Value"
      type={field.kind === "number" ? "number" : field.kind === "date" ? "date" : "text"}
      className="h-8 w-40"
      value={String(value ?? "")}
      onChange={(e) => onChange(field.kind === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value)}
    />
  );
}

/** "Source is Website" for lists and summaries. */
export function describeCondition(c: Condition, choices: FieldChoice[]): string {
  const f = choices.find((x) => x.key === c.field);
  const op = OPS.find(([o]) => o === c.op)?.[1] ?? c.op;
  if (NO_VALUE_OPS.has(c.op)) return `${f?.label ?? c.field} ${op}`;
  const vals = (Array.isArray(c.value) ? c.value : [c.value]).map((v) => f?.options?.find((o) => o.value === String(v))?.label ?? String(v));
  return `${f?.label ?? c.field} ${op} ${vals.join(", ")}`;
}
