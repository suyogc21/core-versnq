"use client";

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { relative, useFields } from "@/lib/crm";
import {
  type Sequence,
  STOP_LABELS,
  type StepIn,
  useRefreshSequences,
  useSequence,
  useSequenceEnrolments,
  useSequenceStats,
  useTemplates,
} from "@/lib/sequences";
import { useTags } from "@/lib/organise";
import { cn } from "@/lib/utils";
import { useModuleOn } from "@/lib/modules";
import { useWaTemplates, WA_STATUS } from "@/lib/whatsapp";

type Tab = "steps" | "results" | "people" | "settings";

export default function SequencePage() {
  const { id } = useParams<{ id: string }>();
  const seq = useSequence(id);
  const refresh = useRefreshSequences();
  const [tab, setTab] = useState<Tab>("steps");
  if (!seq.data) return <p className="p-6 text-muted-foreground">{seq.isError ? "Not found" : "Loading…"}</p>;
  const s = seq.data;
  const tabs: [Tab, string][] = [
    ["steps", "Steps"],
    ["results", "Results"],
    ["people", `People (${s.active})`],
    ["settings", "Settings"],
  ];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        back={{ href: "/sequences", label: "Sequences" }}
        title={s.name}
        actions={
          <label className="flex items-center gap-2 text-sm">
            <Switch
              aria-label="Sequence on"
              checked={s.is_active}
              onCheckedChange={async (on) => {
                if (!on && s.active && !confirm(`Switch off? The ${s.active} people in it stop now.`)) return;
                try {
                  unwrap(await api.PATCH("/api/v1/sequences/{s_id}", { params: { path: { s_id: s.id } }, body: { is_active: on } }));
                  refresh();
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            />
            {s.is_active ? "On" : "Off"}
          </label>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-4xl p-4 sm:p-6">
          <div className="mb-5 flex gap-4 overflow-x-auto border-b text-sm" role="tablist">
            {tabs.map(([key, name]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={cn("-mb-px border-b-2 border-transparent pb-2 whitespace-nowrap text-muted-foreground", tab === key && "border-primary font-medium text-foreground")}
              >
                {name}
              </button>
            ))}
          </div>
          {tab === "steps" && <Steps key={s.updated_at} seq={s} />}
          {tab === "results" && <Results seq={s} />}
          {tab === "people" && <People seq={s} />}
          {tab === "settings" && <Settings key={s.updated_at} seq={s} />}
        </div>
      </div>
    </div>
  );
}

// ---------- steps ----------
type Draft = StepIn & { _k: number };
let counter = 0;

function fromSaved(seq: Sequence): Draft[] {
  return seq.steps.map((st) => {
    const c = st.config as Record<string, unknown>;
    return {
      _k: ++counter,
      kind: st.kind as StepIn["kind"],
      template_id: (c.template_id as string) ?? null,
      title: (c.title as string) ?? null,
      task_type: ((c.task_type as StepIn["task_type"]) ?? "other") as StepIn["task_type"],
      due_in_hours: Number(c.due_in_hours ?? 0),
      hours: c.hours !== undefined ? Number(c.hours) : null,
      check_if: (c.if as StepIn["check_if"]) ?? null,
      tag_id: (c.tag_id as string) ?? null,
      field: (c.field as string) ?? null,
      value: (c.value as string) ?? null,
      go_to: c.go_to !== undefined ? Number(c.go_to) : null,
    };
  });
}

const NEW: Record<StepIn["kind"], Partial<StepIn>> = {
  email: {},
  whatsapp: {},
  wait: { hours: 48 },
  task: { title: "Call them", task_type: "call", due_in_hours: 0 },
  check: { check_if: "opened" },
};

function Steps({ seq }: { seq: Sequence }) {
  const templates = useTemplates();
  const waTemplates = useWaTemplates(useModuleOn("whatsapp_number"));
  const tags = useTags();
  const fields = useFields();
  const refresh = useRefreshSequences();
  const [steps, setSteps] = useState<Draft[]>(fromSaved(seq));
  const set = (i: number, patch: Partial<StepIn>) => setSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, by: number) => {
    const out = [...steps];
    [out[i], out[i + by]] = [out[i + by], out[i]];
    setSteps(out);
  };
  const add = (kind: StepIn["kind"]) => setSteps([...steps, { _k: ++counter, kind, due_in_hours: 0, task_type: "other", ...NEW[kind] } as Draft]);

  async function save() {
    try {
      unwrap(
        await api.PUT("/api/v1/sequences/{s_id}/steps", {
          params: { path: { s_id: seq.id } },
          body: steps.map((st) => Object.fromEntries(Object.entries(st).filter(([k]) => k !== "_k")) as StepIn),
        }),
      );
      refresh();
      toast.success("Steps saved");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-3">
      {(templates.data ?? []).length === 0 && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
          Make an email template first (Sequences → Email templates), then add email steps.
        </p>
      )}
      <ol className="space-y-2">
        {steps.map((st, i) => (
          <li key={st._k} className="surface flex flex-wrap items-center gap-2 p-3 text-sm" data-step={i + 1}>
            <span className="w-6 text-center text-xs font-semibold text-muted-foreground">{i + 1}</span>
            <span className="w-16 text-xs font-medium tracking-wide uppercase">{st.kind}</span>
            {st.kind === "email" && (
              <NativeSelect aria-label={`Step ${i + 1} template`} className="h-8 w-60" value={st.template_id ?? ""} onChange={(e) => set(i, { template_id: e.target.value || null })}>
                <option value="">Choose a template…</option>
                {(templates.data ?? []).filter((t) => t.is_active).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </NativeSelect>
            )}
            {st.kind === "whatsapp" && (
              <NativeSelect aria-label={`Step ${i + 1} WhatsApp template`} className="h-8 w-60" value={st.template_id ?? ""} onChange={(e) => set(i, { template_id: e.target.value || null })}>
                <option value="">Choose a WhatsApp template…</option>
                {(waTemplates.data ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {t.status !== "approved" ? ` (${WA_STATUS[t.status]?.[0] ?? t.status})` : ""}
                    {t.category === "marketing" ? " · marketing: opted-in people only" : ""}
                  </option>
                ))}
              </NativeSelect>
            )}
            {st.kind === "wait" && (
              <>
                <Input
                  aria-label={`Step ${i + 1} days`}
                  type="number"
                  min={0}
                  step={0.5}
                  className="h-8 w-20"
                  value={st.hours ? st.hours / 24 : ""}
                  onChange={(e) => set(i, { hours: Number(e.target.value) * 24 || null })}
                />
                <span className="text-xs text-muted-foreground">days</span>
              </>
            )}
            {st.kind === "task" && (
              <>
                <NativeSelect aria-label={`Step ${i + 1} task type`} className="h-8 w-40" value={st.task_type} onChange={(e) => set(i, { task_type: e.target.value as StepIn["task_type"] })}>
                  <option value="call">Call</option>
                  <option value="linkedin_connect">LinkedIn: connect</option>
                  <option value="linkedin_message">LinkedIn: message</option>
                  <option value="other">Other</option>
                </NativeSelect>
                <Input aria-label={`Step ${i + 1} task title`} className="h-8 w-56" value={st.title ?? ""} onChange={(e) => set(i, { title: e.target.value })} />
              </>
            )}
            {st.kind === "check" && (
              <>
                <span className="text-xs text-muted-foreground">if</span>
                <NativeSelect aria-label={`Step ${i + 1} check`} className="h-8 w-36" value={st.check_if ?? "opened"} onChange={(e) => set(i, { check_if: e.target.value as StepIn["check_if"] })}>
                  <option value="opened">they opened</option>
                  <option value="clicked">they clicked</option>
                  <option value="replied">they replied</option>
                  <option value="tag">they have a tag</option>
                  <option value="field">a field equals</option>
                </NativeSelect>
                {st.check_if === "tag" && (
                  <NativeSelect aria-label={`Step ${i + 1} tag`} className="h-8 w-36" value={st.tag_id ?? ""} onChange={(e) => set(i, { tag_id: e.target.value || null })}>
                    <option value="">Tag…</option>
                    {(tags.data ?? []).map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </NativeSelect>
                )}
                {st.check_if === "field" && (
                  <>
                    <NativeSelect aria-label={`Step ${i + 1} field`} className="h-8 w-36" value={st.field ?? ""} onChange={(e) => set(i, { field: e.target.value || null })}>
                      <option value="">Field…</option>
                      {(fields.data ?? []).map((f) => (
                        <option key={f.key} value={f.key}>
                          {f.label}
                        </option>
                      ))}
                    </NativeSelect>
                    <Input aria-label={`Step ${i + 1} value`} className="h-8 w-28" value={st.value ?? ""} onChange={(e) => set(i, { value: e.target.value })} />
                  </>
                )}
                <span className="text-xs text-muted-foreground">go to step</span>
                <NativeSelect aria-label={`Step ${i + 1} go to`} className="h-8 w-24" value={st.go_to ?? ""} onChange={(e) => set(i, { go_to: Number(e.target.value) || null })}>
                  <option value="">…</option>
                  {steps.map((_, j) => (j === i ? null : <option key={j} value={j + 1}>{j + 1}</option>))}
                  <option value={steps.length + 1}>the end</option>
                </NativeSelect>
                <span className="text-xs text-muted-foreground">otherwise the next step</span>
              </>
            )}
            <span className="ml-auto flex">
              <Button size="icon-sm" variant="ghost" aria-label={`Move step ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                <ArrowUp />
              </Button>
              <Button size="icon-sm" variant="ghost" aria-label={`Move step ${i + 1} down`} disabled={i === steps.length - 1} onClick={() => move(i, 1)}>
                <ArrowDown />
              </Button>
              <Button size="icon-sm" variant="ghost" aria-label={`Remove step ${i + 1}`} onClick={() => setSteps(steps.filter((_, j) => j !== i))}>
                <Trash2 />
              </Button>
            </span>
          </li>
        ))}
      </ol>
      {steps.length === 0 && <p className="text-sm text-muted-foreground">No steps yet. Add the first one below.</p>}
      <div className="flex flex-wrap gap-2">
        {(["email", "whatsapp", "wait", "task", "check"] as const)
          .filter((k) => k !== "whatsapp" || (waTemplates.data ?? []).length > 0)
          .map((k) => (
            <Button key={k} size="sm" variant="outline" onClick={() => add(k)}>
              <Plus /> {{ email: "Email", whatsapp: "WhatsApp", wait: "Wait", task: "Task", check: "Check" }[k]}
            </Button>
          ))}
        <Button size="sm" className="ml-auto" onClick={save}>
          Save steps
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        A wait of 2 days means the next step runs 2 days after the one before. People already in the sequence carry on from their step number.
      </p>
    </div>
  );
}

// ---------- results ----------
function Results({ seq }: { seq: Sequence }) {
  const stats = useSequenceStats(seq.id);
  const waTemplates = useWaTemplates(useModuleOn("whatsapp_number"));
  const templates = useTemplates();
  if (!stats.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const d = stats.data;
  const pct = (n: number, of: number) => (of ? `${Math.round((n * 100) / of)}%` : "—");
  const tiles: [string, number][] = [
    ["Added", d.enrolled],
    ["In it now", d.active],
    ["Finished", d.completed],
    ["Stopped", d.stopped],
    ["Got a deal", d.got_a_deal],
    ["Became customers", d.became_customers],
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-6">
        {tiles.map(([k, v]) => (
          <div key={k} className="surface p-3" data-tile={k}>
            <div className="text-[11px] text-muted-foreground">{k}</div>
            <div className="text-xl font-semibold tabular-nums">{v}</div>
          </div>
        ))}
      </div>
      <div className="overflow-x-auto surface">
        <table className="w-full text-sm" data-step-stats>
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-3 py-2 font-medium">Step</th>
              <th className="px-2 py-2 text-right font-medium">Sent</th>
              <th className="px-2 py-2 text-right font-medium" title="Estimated: some mail apps load images automatically">
                Opened*
              </th>
              <th className="px-2 py-2 text-right font-medium">Clicked</th>
              <th className="px-2 py-2 text-right font-medium">Replied</th>
              <th className="px-2 py-2 text-right font-medium">Bounced</th>
              <th className="px-2 py-2 text-right font-medium">Unsubscribed</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {d.steps.map((st) => {
              const saved = seq.steps.find((x) => x.position === st.position);
              const tid = (saved?.config as { template_id?: string } | undefined)?.template_id;
              const label =
                saved?.kind === "email"
                  ? (templates.data?.find((t) => t.id === tid)?.name ?? "Email")
                  : saved?.kind === "whatsapp"
                    ? `WhatsApp: ${waTemplates.data?.find((t) => t.id === tid)?.name ?? "template"}`
                    : st.kind;
              const email = st.kind === "email";
              const wa = st.kind === "whatsapp";
              return (
                <tr key={st.position}>
                  <td className="px-3 py-1.5 whitespace-nowrap">
                    {st.position}. {label}
                  </td>
                  {email ? (
                    <>
                      <td className="px-2 text-right tabular-nums">{st.sent}</td>
                      <td className="px-2 text-right tabular-nums">{pct(st.opened, st.sent)}</td>
                      <td className="px-2 text-right tabular-nums">{pct(st.clicked, st.sent)}</td>
                      <td className="px-2 text-right tabular-nums">{pct(st.replied, st.sent)}</td>
                      <td className="px-2 text-right tabular-nums">{st.bounced}</td>
                      <td className="px-2 text-right tabular-nums">{st.unsubscribed}</td>
                    </>
                  ) : wa ? (
                    <>
                      <td className="px-2 text-right tabular-nums">{st.sent}</td>
                      <td className="px-2 text-right tabular-nums" title="Read (WhatsApp tells us exactly)">
                        {pct(st.opened, st.sent)} read
                      </td>
                      <td className="px-2 text-right text-muted-foreground">—</td>
                      <td className="px-2 text-right tabular-nums">{pct(st.replied, st.sent)}</td>
                      <td colSpan={2} className="px-2 text-right text-muted-foreground">—</td>
                    </>
                  ) : (
                    <td colSpan={6} className="px-2 text-xs text-muted-foreground">
                      —
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">* Opens are estimated: some mail apps open every image, others block them.</p>
    </div>
  );
}

// ---------- people ----------
function People({ seq }: { seq: Sequence }) {
  const list = useSequenceEnrolments(seq.id);
  const refresh = useRefreshSequences();
  return (
    <div className="divide-y surface" data-people>
      {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "Nobody yet. Add people from a lead's page or the list."}</p>}
      {(list.data ?? []).map((e) => (
        <div key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
          <Link href={`/leads/${e.lead_id}`} className="font-medium hover:underline">
            {e.lead_name}
          </Link>
          <span className="text-xs text-muted-foreground">
            {e.status === "active"
              ? `next: step ${Math.min(e.position, e.steps)} of ${e.steps}${e.next_run_at ? `, ${relative(e.next_run_at)}` : ""}`
              : e.status === "completed"
                ? `finished ${relative(e.ended_at)}`
                : `stopped: ${e.ended_reason}`}
          </span>
          {e.status === "active" && (
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto"
              onClick={async () => {
                try {
                  unwrap(await api.POST("/api/v1/enrolments/{e_id}/stop", { params: { path: { e_id: e.id } } }));
                  refresh();
                  list.refetch();
                } catch (err) {
                  toast.error((err as Error).message);
                }
              }}
            >
              Stop
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------- settings ----------
function Settings({ seq }: { seq: Sequence }) {
  const refresh = useRefreshSequences();
  const [name, setName] = useState(seq.name);
  const [stopOn, setStopOn] = useState<string[]>(seq.stop_on);
  const [others, setOthers] = useState(seq.allow_with_others);
  return (
    <div className="max-w-lg space-y-4 text-sm">
      <div className="space-y-1">
        <label htmlFor="seq-name" className="font-medium">
          Name
        </label>
        <Input id="seq-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-2">
        <div className="font-medium">Take people out when…</div>
        {Object.entries(STOP_LABELS).map(([k, l]) => (
          <label key={k} className="flex items-center gap-2">
            <input type="checkbox" checked={stopOn.includes(k)} onChange={(e) => setStopOn(e.target.checked ? [...stopOn, k] : stopOn.filter((x) => x !== k))} /> {l}
          </label>
        ))}
        <p className="text-xs text-muted-foreground">People who unsubscribe, opt out or whose email bounces are always taken out.</p>
      </div>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={others} onChange={(e) => setOthers(e.target.checked)} /> People in this sequence can be in other sequences at the same time
      </label>
      <div className="flex gap-2">
        <Button
          onClick={async () => {
            try {
              unwrap(
                await api.PATCH("/api/v1/sequences/{s_id}", {
                  params: { path: { s_id: seq.id } },
                  body: { name, stop_on: stopOn as never, allow_with_others: others },
                }),
              );
              refresh();
              toast.success("Saved");
            } catch (e) {
              toast.error((e as Error).message);
            }
          }}
        >
          Save
        </Button>
        {seq.active + seq.completed + seq.stopped === 0 && (
          <Button
            variant="ghost"
            className="ml-auto text-destructive"
            onClick={async () => {
              if (!confirm(`Delete ${seq.name}?`)) return;
              try {
                unwrap(await api.DELETE("/api/v1/sequences/{s_id}", { params: { path: { s_id: seq.id } } }));
                window.location.href = "/sequences";
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
          >
            Delete
          </Button>
        )}
      </div>
    </div>
  );
}
