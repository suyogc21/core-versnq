"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { ConditionRow, describeCondition, useFieldChoices } from "@/components/crm/rule-builder";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { relative, useActivityTypes, useFields, useStages } from "@/lib/crm";
import { useDealFields, useLostReasons, usePipelines } from "@/lib/deals";
import { useUsers } from "@/lib/directory";
import { type Automation, type Condition, useAutomationRuns, useAutomations, useTags } from "@/lib/organise";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";
import { useSequences } from "@/lib/sequences";

type Action = Record<string, unknown> & { type: string };
type Draft = { id?: string; name: string; trigger: Record<string, unknown> & { type: string }; conditions: Condition[]; actions: Action[]; is_active: boolean };

const TRIGGERS: [string, string, "lead" | "deal"][] = [
  ["lead.created", "A lead is added", "lead"],
  ["lead.stage_changed", "A lead moves stage", "lead"],
  ["lead.field_changed", "A lead field changes", "lead"],
  ["lead.assigned", "A lead gets a new owner", "lead"],
  ["activity.logged", "An activity is logged", "lead"],
  ["task.overdue", "A task falls due", "lead"],
  ["lead.no_response", "Nobody responds within some hours", "lead"],
  ["deal.created", "A deal is added", "deal"],
  ["deal.stage_changed", "A deal moves stage", "deal"],
  ["deal.won", "A deal is won", "deal"],
  ["deal.lost", "A deal is lost", "deal"],
  ["customer.created", "A lead becomes a customer", "lead"],
  ["document.received", "A customer sends a document", "lead"],
];
const ACTIONS: [string, string][] = [
  ["create_task", "Create a task"],
  ["update_field", "Set a field"],
  ["add_tag", "Add a tag"],
  ["remove_tag", "Remove a tag"],
  ["change_owner", "Change the owner"],
  ["change_stage", "Move to a stage"],
  ["notify", "Send a notification"],
  ["webhook", "Send a webhook"],
  ["enrol", "Put into a sequence"],
];
const subjectOf = (t: string) => TRIGGERS.find(([k]) => k === t)?.[2] ?? "lead";
const triggerLabel = (t: string) => TRIGGERS.find(([k]) => k === t)?.[1] ?? t;

function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      qc.invalidateQueries({ queryKey: ["automations"] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

export default function AutomationsPage() {
  const words = useWords();
  const autos = useAutomations();
  const save = useSave();
  const [editing, setEditing] = useState<Draft | null>(null);
  const [runsOf, setRunsOf] = useState<Automation | null>(null);
  const list = autos.data ?? [];
  const order = (i: number, d: -1 | 1) => {
    const ids = list.map((a) => a.id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    save(async () => unwrap(await api.PUT("/api/v1/automations/order", { body: { ids } })));
  };
  return (
    <>
      <PageHeader
        back={{ href: "/settings", label: "Settings" }}
        title="Automations"
        count={list.length}
        actions={
          <Button size="sm" onClick={() => (setRunsOf(null), setEditing({ name: "", trigger: { type: "lead.created" }, conditions: [], actions: [{ type: "create_task", title: "", due_hours: 1, assign_to: "owner" }], is_active: true }))}>
            <Plus /> New automation
          </Button>
        }
      />
      <div className="mx-auto w-full max-w-4xl space-y-4 p-4 sm:p-8">
        {!editing && (
          <>
            <p className="text-sm text-muted-foreground">
              When something happens, check a few conditions, then do the work. Automations follow the same rules as people, and everything they do shows on the
              timeline as “Automation: name”.
            </p>
            <div className="divide-y surface">
              {autos.isLoading && <p className="p-4 text-muted-foreground">Loading…</p>}
              {autos.data?.length === 0 && <p className="p-4 text-sm text-muted-foreground">No automations yet.</p>}
              {list.map((a, i) => (
                <div key={a.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
                  <div className="flex flex-col">
                    <button aria-label={`Move ${a.name} up`} disabled={i === 0} className="text-muted-foreground disabled:opacity-30" onClick={() => order(i, -1)}>
                      <ArrowUp className="size-3" />
                    </button>
                    <button aria-label={`Move ${a.name} down`} disabled={i === list.length - 1} className="text-muted-foreground disabled:opacity-30" onClick={() => order(i, 1)}>
                      <ArrowDown className="size-3" />
                    </button>
                  </div>
                  <Switch
                    aria-label={`${a.name} on`}
                    checked={a.is_active}
                    onCheckedChange={(on) => save(async () => unwrap(await api.PATCH("/api/v1/automations/{auto_id}", { params: { path: { auto_id: a.id } }, body: { is_active: on } })))}
                  />
                  <button className="min-w-0 flex-1 text-start" onClick={() => (setRunsOf(null), setEditing({ id: a.id, name: a.name, trigger: a.trigger as Draft["trigger"], conditions: a.conditions as Condition[], actions: a.actions as Action[], is_active: a.is_active }))}>
                    <div className="truncate font-medium">{a.name}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      When {words(triggerLabel((a.trigger as { type: string }).type)).toLowerCase()} → {a.actions.length} action{a.actions.length === 1 ? "" : "s"}
                    </div>
                  </button>
                  <span className="text-xs text-muted-foreground">
                    {a.runs_7d} runs this week
                    {a.failed_7d > 0 && <span className="text-destructive"> · {a.failed_7d} failed</span>}
                    {a.last_run_at && ` · last ${relative(a.last_run_at)}`}
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => setRunsOf(a)}>
                    History
                  </Button>
                </div>
              ))}
            </div>
            {runsOf && <Runs auto={runsOf} onClose={() => setRunsOf(null)} />}
          </>
        )}
        {editing && <Builder key={editing.id ?? "new"} draft={editing} onDone={() => setEditing(null)} />}
      </div>
    </>
  );
}

// ---------- builder ----------
function Builder({ draft, onDone }: { draft: Draft; onDone: () => void }) {
  const save = useSave();
  const [d, setD] = useState<Draft>(draft);
  const subject = subjectOf(d.trigger.type);
  const choices = useFieldChoices(subject);
  const setTrigger = (t: Draft["trigger"]) => {
    const switched = subjectOf(t.type) !== subject;
    setD({ ...d, trigger: t, ...(switched ? { conditions: [], actions: [{ type: "notify", to: "owner", message: "" }] } : {}) });
  };

  async function submit() {
    const body = { name: d.name, trigger: d.trigger, conditions: d.conditions, actions: d.actions, is_active: d.is_active };
    const ok = await save(
      async () =>
        d.id
          ? unwrap(await api.PATCH("/api/v1/automations/{auto_id}", { params: { path: { auto_id: d.id } }, body }))
          : unwrap(await api.POST("/api/v1/automations", { body })),
      "Automation saved",
    );
    if (ok) onDone();
  }
  async function remove() {
    if (!d.id || !confirm(`Delete "${d.name}"? Its run history goes too.`)) return;
    if (await save(async () => unwrap(await api.DELETE("/api/v1/automations/{auto_id}", { params: { path: { auto_id: d.id! } } })), "Deleted")) onDone();
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1.5">
        <Label htmlFor="a-name">Name</Label>
        <Input id="a-name" placeholder="e.g. Call new website enquiries within the hour" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} maxLength={120} />
      </div>
      <Step title="When">
        <TriggerEditor value={d.trigger} onChange={setTrigger} />
      </Step>
      <Step title="If (all must match)">
        {d.conditions.length === 0 && <p className="text-sm text-muted-foreground">Always — add a condition to narrow it down.</p>}
        {d.conditions.map((c, i) => (
          <ConditionRow
            key={i}
            choices={choices}
            value={c}
            onChange={(nc) => setD({ ...d, conditions: d.conditions.map((x, j) => (j === i ? nc : x)) })}
            onRemove={() => setD({ ...d, conditions: d.conditions.filter((_, j) => j !== i) })}
          />
        ))}
        <Button size="sm" variant="outline" onClick={() => setD({ ...d, conditions: [...d.conditions, { field: "", op: "is" }] })}>
          <Plus /> Condition
        </Button>
      </Step>
      <Step title="Then">
        {d.actions.map((a, i) => (
          <ActionEditor
            key={i}
            subject={subject}
            value={a}
            onChange={(na) => setD({ ...d, actions: d.actions.map((x, j) => (j === i ? na : x)) })}
            onRemove={d.actions.length > 1 ? () => setD({ ...d, actions: d.actions.filter((_, j) => j !== i) }) : undefined}
          />
        ))}
        {d.actions.length < 10 && (
          <Button size="sm" variant="outline" onClick={() => setD({ ...d, actions: [...d.actions, { type: "notify", to: "owner", message: "" }] })}>
            <Plus /> Action
          </Button>
        )}
      </Step>
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={d.is_active} onCheckedChange={(v) => setD({ ...d, is_active: v })} aria-label="Switched on" /> Switched on
      </label>
      {d.id && <TestBox autoId={d.id} subject={subject} conditions={d.conditions} choices={choices} />}
      <div className="flex gap-2">
        <Button onClick={submit} disabled={!d.name.trim()}>
          Save
        </Button>
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
        {d.id && (
          <Button variant="ghost" className="ms-auto text-muted-foreground hover:text-destructive" onClick={remove}>
            Delete
          </Button>
        )}
      </div>
    </div>
  );
}

function Step({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="surface space-y-2 p-4">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      {children}
    </section>
  );
}

/** "A lead is added" in the company's own words ("A student is added"). */
function useWords() {
  const label = useLabels();
  return (text: string) =>
    text
      .replace(/\blead\b/g, label("lead").toLowerCase())
      .replace(/\bdeal\b/g, label("deal").toLowerCase())
      .replace(/\bcustomer\b/g, label("customer").toLowerCase());
}

function TriggerEditor({ value, onChange }: { value: Draft["trigger"]; onChange: (t: Draft["trigger"]) => void }) {
  const words = useWords();
  const stages = useStages();
  const pipelines = usePipelines();
  const fields = useFields();
  const types = useActivityTypes();
  const t = value.type;
  const leadFieldOpts: [string, string][] = [
    ["owner_user_id", "Owner"],
    ["stage_id", "Stage"],
    ["city", "City"],
    ["tags", "Tags"],
    ["score", "Score"],
    ...(fields.data ?? []).map((f) => [f.key, f.label] as [string, string]),
  ];
  const outcomes =
    ((types.data ?? []).find((x) => x.key === value.type_key)?.fields as { key: string; options?: { value: string; label: string }[] }[] | undefined)?.find(
      (f) => f.key === "disposition",
    )?.options ?? [];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <NativeSelect aria-label="Trigger" className="h-8 w-auto" value={t} onChange={(e) => onChange({ type: e.target.value, ...(e.target.value === "lead.no_response" ? { hours: 2 } : {}) })}>
        {TRIGGERS.map(([k, l]) => (
          <option key={k} value={k}>
            {words(l)}
          </option>
        ))}
      </NativeSelect>
      {t === "lead.stage_changed" && (
        <NativeSelect aria-label="To stage" className="h-8 w-auto" value={String(value.to_stage_id ?? "")} onChange={(e) => onChange({ ...value, to_stage_id: e.target.value || undefined })}>
          <option value="">to any stage</option>
          {(stages.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              to {s.name}
            </option>
          ))}
        </NativeSelect>
      )}
      {t === "deal.stage_changed" && (
        <NativeSelect aria-label="To stage" className="h-8 w-auto" value={String(value.to_stage_id ?? "")} onChange={(e) => onChange({ ...value, to_stage_id: e.target.value || undefined })}>
          <option value="">to any stage</option>
          {(pipelines.data ?? []).flatMap((p) =>
            (p.stages ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                to {p.name} · {s.name}
              </option>
            )),
          )}
        </NativeSelect>
      )}
      {t === "lead.field_changed" && (
        <NativeSelect aria-label="Which field" className="h-8 w-auto" value={String(value.field ?? "")} onChange={(e) => onChange({ ...value, field: e.target.value })}>
          <option value="">Choose a field…</option>
          {leadFieldOpts.map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </NativeSelect>
      )}
      {t === "activity.logged" && (
        <>
          <NativeSelect aria-label="Activity type" className="h-8 w-auto" value={String(value.type_key ?? "")} onChange={(e) => onChange({ type: t, type_key: e.target.value || undefined })}>
            <option value="">of any type</option>
            {(types.data ?? [])
              .filter((x) => x.is_loggable)
              .map((x) => (
                <option key={x.key} value={x.key}>
                  {x.label}
                </option>
              ))}
          </NativeSelect>
          {outcomes.length > 0 && (
            <NativeSelect aria-label="Outcome" className="h-8 w-auto" value={String(value.disposition ?? "")} onChange={(e) => onChange({ ...value, disposition: e.target.value || undefined })}>
              <option value="">with any outcome</option>
              {outcomes.map((o) => (
                <option key={o.value} value={o.value}>
                  with outcome {o.label}
                </option>
              ))}
            </NativeSelect>
          )}
        </>
      )}
      {t === "lead.no_response" && (
        <span className="flex items-center gap-1.5 text-sm">
          within
          <Input aria-label="Hours" type="number" min={1} max={720} className="h-8 w-20" value={String(value.hours ?? 2)} onChange={(e) => onChange({ ...value, hours: Number(e.target.value) })} />
          hours of being added
        </span>
      )}
    </div>
  );
}

function ActionEditor({ subject, value, onChange, onRemove }: { subject: "lead" | "deal"; value: Action; onChange: (a: Action) => void; onRemove?: () => void }) {
  const label = useLabels();
  const users = useUsers();
  const tags = useTags();
  const stages = useStages();
  const pipelines = usePipelines();
  const reasons = useLostReasons();
  const leadFields = useFields();
  const dealFields = useDealFields();
  const people = (users.data ?? []).filter((u) => u.status === "active");
  const fields = (subject === "lead" ? leadFields.data : dealFields.data)?.filter((f) => f.type !== "calculated") ?? [];
  const set = (patch: Record<string, unknown>) => onChange({ ...value, ...patch });
  const sequences = useSequences(value.type === "enrol");
  const dealStages = (pipelines.data ?? []).flatMap((p) => (p.stages ?? []).map((s) => ({ ...s, label: `${p.name} · ${s.name}` })));
  const chosenLeadStage = (stages.data ?? []).find((s) => s.id === value.stage_id);
  const chosenDealStage = dealStages.find((s) => s.id === value.stage_id);
  const field = fields.find((f) => f.key === value.field);
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border p-1.5">
      <NativeSelect
        aria-label="Action"
        className="h-8 w-auto"
        value={value.type}
        onChange={(e) =>
          onChange(
            ({
              create_task: { type: "create_task", title: "", due_hours: 1, assign_to: "owner" },
              notify: { type: "notify", to: "owner", message: "" },
            } as Record<string, Action>)[e.target.value] ?? { type: e.target.value },
          )
        }
      >
        {ACTIONS.map(([k, l]) => (
          <option key={k} value={k}>
            {l}
          </option>
        ))}
      </NativeSelect>
      {value.type === "create_task" && (
        <>
          <Input aria-label="Task title" placeholder="Task title" className="h-8 w-56" value={String(value.title ?? "")} onChange={(e) => set({ title: e.target.value })} />
          <span className="text-sm">due in</span>
          <Input aria-label="Due in hours" type="number" min={0} className="h-8 w-16" value={String(value.due_hours ?? 0)} onChange={(e) => set({ due_hours: Number(e.target.value) })} />
          <span className="text-sm">hours for</span>
          <NativeSelect aria-label="Task for" className="h-8 w-auto" value={String(value.assign_to ?? "owner")} onChange={(e) => set({ assign_to: e.target.value })}>
            <option value="owner">the owner</option>
            {people.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </NativeSelect>
        </>
      )}
      {value.type === "update_field" && (
        <>
          <NativeSelect aria-label="Field to set" className="h-8 w-auto" value={String(value.field ?? "")} onChange={(e) => set({ field: e.target.value, value: "" })}>
            <option value="">Choose a field…</option>
            {subject === "lead" &&
              [
                ["city", "City"],
                ["region", "Region"],
                ["preferred_language", "Language"],
                ["campaign", "Campaign"],
              ].map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            {fields.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </NativeSelect>
          <span className="text-sm">to</span>
          {field && (field.type === "select" || field.type === "multi_select") ? (
            <NativeSelect aria-label="New value" className="h-8 w-auto" value={String(value.value ?? "")} onChange={(e) => set({ value: e.target.value })}>
              <option value="">Choose…</option>
              {(field.options as { value: string; label: string }[]).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </NativeSelect>
          ) : (
            <Input
              aria-label="New value"
              type={field?.type === "number" ? "number" : field?.type === "date" ? "date" : "text"}
              className="h-8 w-44"
              value={String(value.value ?? "")}
              onChange={(e) => set({ value: e.target.value })}
            />
          )}
        </>
      )}
      {(value.type === "add_tag" || value.type === "remove_tag") && (
        <NativeSelect aria-label="Tag" className="h-8 w-auto" value={String(value.tag_id ?? "")} onChange={(e) => set({ tag_id: e.target.value })}>
          <option value="">Choose a tag…</option>
          {(tags.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </NativeSelect>
      )}
      {value.type === "change_owner" && (
        <NativeSelect aria-label="New owner" className="h-8 w-auto" value={String(value.user_id ?? "")} onChange={(e) => set({ user_id: e.target.value })}>
          <option value="">Choose…</option>
          {subject === "lead" && <option value="rules">By assignment rules</option>}
          {people.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </NativeSelect>
      )}
      {value.type === "change_stage" && (
        <>
          <NativeSelect aria-label="Stage" className="h-8 w-auto" value={String(value.stage_id ?? "")} onChange={(e) => set({ stage_id: e.target.value })}>
            <option value="">Choose a stage…</option>
            {subject === "lead"
              ? (stages.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))
              : dealStages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
          </NativeSelect>
          {subject === "lead" && chosenLeadStage?.is_unqualified && (
            <Input aria-label="Reason" placeholder="Reason" className="h-8 w-44" value={String(value.reason ?? "")} onChange={(e) => set({ reason: e.target.value })} />
          )}
          {subject === "deal" && chosenDealStage?.kind === "lost" && (
            <NativeSelect aria-label="Lost reason" className="h-8 w-auto" value={String(value.lost_reason_id ?? "")} onChange={(e) => set({ lost_reason_id: e.target.value })}>
              <option value="">Why lost…</option>
              {(reasons.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </NativeSelect>
          )}
        </>
      )}
      {value.type === "notify" && (
        <>
          <NativeSelect aria-label="Notify" className="h-8 w-auto" value={String(value.to ?? "owner")} onChange={(e) => set({ to: e.target.value })}>
            <option value="owner">the owner</option>
            <option value="managers">their managers</option>
            {people.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </NativeSelect>
          <Input aria-label="Message" placeholder={`e.g. New ${label("lead").toLowerCase()} waiting`} className="h-8 w-64" value={String(value.message ?? "")} onChange={(e) => set({ message: e.target.value })} />
        </>
      )}
      {value.type === "enrol" && (
        <NativeSelect aria-label="Sequence" className="h-8 w-56" value={String(value.sequence_id ?? "")} onChange={(e) => set({ sequence_id: e.target.value })}>
          <option value="">Choose a sequence…</option>
          {(sequences.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.is_active ? "" : " (off)"}
            </option>
          ))}
        </NativeSelect>
      )}
      {value.type === "webhook" && (
        <>
          <Input aria-label="Webhook address" placeholder="https://…" className="h-8 w-72" value={String(value.url ?? "")} onChange={(e) => set({ url: e.target.value })} />
          {typeof value.secret === "string" && (
            <span className="text-xs text-muted-foreground" title="Check the X-Versnq-Signature header with this secret">
              Signing secret: <code className="select-all">{value.secret}</code>
            </span>
          )}
        </>
      )}
      {onRemove && (
        <button type="button" aria-label="Remove action" className="ms-auto p-1.5 text-muted-foreground hover:text-destructive" onClick={onRemove}>
          <X className="size-3.5" />
        </button>
      )}
    </div>
  );
}

function TestBox({ autoId, subject, conditions, choices }: { autoId: string; subject: "lead" | "deal"; conditions: Condition[]; choices: ReturnType<typeof useFieldChoices> }) {
  const label = useLabels();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ id: string; name: string }[]>([]);
  const [result, setResult] = useState<{ name: string; matches: boolean; conditions: (Condition & { ok: boolean })[] } | null>(null);
  async function search(term: string) {
    setQ(term);
    if (term.trim().length < 2) return setHits([]);
    if (subject === "lead") {
      const page = unwrap(await api.GET("/api/v1/leads", { params: { query: { q: term, limit: 8 } } }));
      setHits(page.items.map((x) => ({ id: x.id, name: x.display_name })));
    } else {
      const page = unwrap(await api.GET("/api/v1/deals", { params: { query: { q: term, limit: 8 } } }));
      setHits(page.items.map((x) => ({ id: x.id, name: x.name })));
    }
  }
  async function run(hit: { id: string; name: string }) {
    try {
      const out = unwrap(
        await api.POST("/api/v1/automations/{auto_id}/test", { params: { path: { auto_id: autoId }, query: subject === "lead" ? { lead_id: hit.id } : { deal_id: hit.id } } }),
      );
      setResult({ name: hit.name, matches: out.matches, conditions: out.conditions as (Condition & { ok: boolean })[] });
      setHits([]);
      setQ("");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <Step title="Test (saved version, changes nothing)">
      <Input aria-label="Test on" placeholder={`Find a ${subject === "lead" ? label("lead").toLowerCase() : label("deal").toLowerCase()} to test with…`} className="h-8" value={q} onChange={(e) => search(e.target.value)} />
      {hits.map((h) => (
        <button key={h.id} className="block w-full rounded px-2 py-1 text-start text-sm hover:bg-accent" onClick={() => run(h)}>
          {h.name}
        </button>
      ))}
      {result && (
        <div className="space-y-1 text-sm">
          <div className={cn("font-medium", result.matches ? "text-emerald-600" : "text-destructive")}>
            {result.name}: {result.matches ? "would run" : "would not run"}
          </div>
          {conditions.length === 0 && <div className="text-muted-foreground">No conditions: runs every time.</div>}
          {result.conditions.map((c, i) => (
            <div key={i} className={c.ok ? "text-emerald-600" : "text-destructive"}>
              {c.ok ? "✓" : "✗"} {describeCondition(c, choices)}
            </div>
          ))}
        </div>
      )}
    </Step>
  );
}

function Runs({ auto, onClose }: { auto: Automation; onClose: () => void }) {
  const runs = useAutomationRuns(auto.id);
  return (
    <section className="surface space-y-2 p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">History · {auto.name}</h3>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
      {runs.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {runs.data?.length === 0 && <p className="text-sm text-muted-foreground">It has not run yet.</p>}
      <div className="divide-y">
        {(runs.data ?? []).map((r) => (
          <div key={r.id} className="space-y-0.5 py-2 text-sm">
            <div className="flex items-center gap-2">
              <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", r.status === "done" ? "bg-emerald-500/15 text-emerald-700" : "bg-red-500/15 text-red-700")}>
                {r.status}
              </span>
              {r.deal_id ? (
                <Link className="font-medium hover:underline" href={`/deals/${r.deal_id}`}>
                  {r.subject_name ?? "Deal"}
                </Link>
              ) : r.lead_id ? (
                <Link className="font-medium hover:underline" href={`/leads/${r.lead_id}`}>
                  {r.subject_name ?? "Lead"}
                </Link>
              ) : null}
              <span className="ms-auto text-xs text-muted-foreground">{relative(r.created_at)}</span>
            </div>
            {r.error && <div className="text-xs text-destructive">{r.error}</div>}
            <div className="text-xs text-muted-foreground">{r.detail.map((x) => String((x as { result?: string }).result)).join(" · ")}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

