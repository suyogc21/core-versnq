"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Copy, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { relative, useCrmRules, useFields, useSources, useStages } from "@/lib/crm";
import { useTeams, useUsers } from "@/lib/directory";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Tab = "forms" | "assignment" | "sla" | "safety";
type CaptureSource = components["schemas"]["CaptureSourceOut"];
type AssignmentRule = components["schemas"]["AssignmentRuleOut"];
type SlaRule = components["schemas"]["SlaRuleOut"];
type Condition = components["schemas"]["Condition"];
type Strategy = "round_robin" | "user" | "unassigned";

function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      for (const k of ["capture-sources", "assignment-rules", "sla-rules", "settings", "crm-rules"]) qc.invalidateQueries({ queryKey: [k] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

export default function RoutingPage() {
  const [tab, setTab] = useState<Tab>("forms");
  const label = useLabels();
  const tabs: [Tab, string][] = [
    ["forms", "Web forms"],
    ["assignment", "Who gets new leads"],
    ["sla", "Response times"],
    ["safety", "Duplicates & safety"],
  ];
  return (
    <>
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Lead capture" />
      <div className="mx-auto w-full max-w-3xl p-4 sm:p-8">
        <p className="mb-4 text-muted-foreground">
          How new {label("lead", true).toLowerCase()} arrive, who gets them, and how fast they must be contacted.
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
        {tab === "forms" && <Forms />}
        {tab === "assignment" && <Assignment />}
        {tab === "sla" && <Sla />}
        {tab === "safety" && <Safety />}
      </div>
    </>
  );
}

// ---------- web forms ----------
function useCaptureSources() {
  return useQuery({ queryKey: ["capture-sources"], queryFn: async () => unwrap(await api.GET("/api/v1/capture-sources")) });
}

function Forms() {
  const list = useCaptureSources();
  const sources = useSources();
  const save = useSave();
  const [editing, setEditing] = useState<CaptureSource | "new" | null>(null);
  const [key, setKey] = useState<{ name: string; key: string } | null>(null);
  const sourceName = (id: string) => sources.data?.find((s) => s.id === id)?.name ?? "—";

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Each form gets its own secret link. Your website sends enquiries to it and they arrive here: duplicates are caught and the assignment rules
        pick the owner.
      </p>
      <div className="divide-y surface">
        {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">No forms yet.</p>}
        {(list.data ?? []).map((f) => (
          <div key={f.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm">
            <Switch
              aria-label={`${f.name} on`}
              checked={f.is_active}
              onCheckedChange={(on) =>
                save(async () =>
                  unwrap(await api.PATCH("/api/v1/capture-sources/{src_id}", { params: { path: { src_id: f.id } }, body: { is_active: on } })),
                )
              }
            />
            <button className="font-medium hover:underline" onClick={() => setEditing(f)}>
              {f.name}
            </button>
            <span className="text-xs text-muted-foreground">
              {sourceName(f.source_id)} · key {f.key_hint}… · {f.last_used_at ? `last lead ${relative(f.last_used_at)}` : "no leads yet"}
            </span>
            <span className="ml-auto flex gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={async () => {
                  if (!confirm("Make a new link? The old one stops working at once.")) return;
                  await save(async () => {
                    const r = unwrap(await api.POST("/api/v1/capture-sources/{src_id}/new-key", { params: { path: { src_id: f.id } } }));
                    setKey({ name: r.name, key: r.key });
                  });
                }}
              >
                New link
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`Delete ${f.name}`}
                onClick={() =>
                  confirm(`Delete the form ${f.name}? Websites using it will stop sending leads.`) &&
                  save(async () => unwrap(await api.DELETE("/api/v1/capture-sources/{src_id}", { params: { path: { src_id: f.id } } })), "Deleted")
                }
              >
                <Trash2 />
              </Button>
            </span>
          </div>
        ))}
      </div>
      <Button size="sm" onClick={() => setEditing("new")}>
        <Plus /> Add a form
      </Button>
      {editing && <FormDialog form={editing === "new" ? null : editing} onClose={() => setEditing(null)} onKey={setKey} />}
      {key && <KeyDialog name={key.name} formKey={key.key} onClose={() => setKey(null)} />}
    </div>
  );
}

function FormDialog({ form, onClose, onKey }: { form: CaptureSource | null; onClose: () => void; onKey: (k: { name: string; key: string }) => void }) {
  const sources = useSources();
  const stages = useStages();
  const fields = useFields();
  const save = useSave();
  const [name, setName] = useState(form?.name ?? "");
  const [sourceId, setSourceId] = useState(form?.source_id ?? "");
  const [stageId, setStageId] = useState(form?.stage_id ?? "");
  const [consent, setConsent] = useState(form?.consent_text ?? "");
  const [map, setMap] = useState<[string, string][]>(Object.entries((form?.field_map ?? {}) as Record<string, string>));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      name,
      source_id: sourceId,
      stage_id: stageId || null,
      consent_text: consent.trim() || null,
      field_map: Object.fromEntries(map.filter(([a, b]) => a.trim() && b)),
    };
    const ok = await save(async () => {
      if (form) {
        unwrap(await api.PATCH("/api/v1/capture-sources/{src_id}", { params: { path: { src_id: form.id } }, body }));
      } else {
        const r = unwrap(await api.POST("/api/v1/capture-sources", { body: { ...body, is_active: true } }));
        onKey({ name: r.name, key: r.key });
      }
    }, form ? "Saved" : undefined);
    if (ok) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{form ? `Edit ${form.name}` : "Add a web form"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="f-name">Name</Label>
            <Input id="f-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Contact us page" autoFocus />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="f-source">Source</Label>
              <NativeSelect id="f-source" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
                <option value="">Choose…</option>
                {(sources.data ?? [])
                  .filter((s) => s.is_active)
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
              </NativeSelect>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="f-stage">Start in stage</Label>
              <NativeSelect id="f-stage" value={stageId} onChange={(e) => setStageId(e.target.value)}>
                <option value="">First stage</option>
                {(stages.data ?? [])
                  .filter((s) => s.is_open)
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
              </NativeSelect>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="f-consent">Consent wording on your form (optional)</Label>
            <Input id="f-consent" value={consent} onChange={(e) => setConsent(e.target.value)} placeholder="I agree to be contacted by email and WhatsApp" />
            <p className="text-xs text-muted-foreground">Saved with every opt-in as proof of what the person agreed to.</p>
          </div>
          <div className="space-y-1.5">
            <Label>Your own form fields (optional)</Label>
            <p className="text-xs text-muted-foreground">
              Name, email, phone, company, city, message and UTM fields are recognised automatically. Add a row for any other question.
            </p>
            {map.map(([incoming, target], i) => (
              <div key={i} className="flex gap-2">
                <Input
                  aria-label="Field name on your form"
                  className="h-8"
                  placeholder="Field name on your form"
                  value={incoming}
                  onChange={(e) => setMap(map.map((m, j) => (j === i ? [e.target.value, m[1]] : m)))}
                />
                <NativeSelect aria-label="Saves into" value={target} onChange={(e) => setMap(map.map((m, j) => (j === i ? [m[0], e.target.value] : m)))}>
                  <option value="">Saves into…</option>
                  {(fields.data ?? []).map((f) => (
                    <option key={f.key} value={`cf.${f.key}`}>
                      {f.label}
                    </option>
                  ))}
                </NativeSelect>
                <Button type="button" size="icon-sm" variant="ghost" aria-label="Remove" onClick={() => setMap(map.filter((_, j) => j !== i))}>
                  <Trash2 />
                </Button>
              </div>
            ))}
            <Button type="button" size="sm" variant="outline" onClick={() => setMap([...map, ["", ""]])}>
              <Plus /> Add a field
            </Button>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || !sourceId}>
              {form ? "Save" : "Create form"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The secret link, shown once, with ready-to-paste code for a website. */
function KeyDialog({ name, formKey, onClose }: { name: string; formKey: string; onClose: () => void }) {
  const url = `${typeof window !== "undefined" ? window.location.origin : ""}/api/v1/capture/${formKey}`;
  const snippet = `<form id="enquiry">
  <input name="name" placeholder="Your name" required>
  <input name="phone" placeholder="Phone" required>
  <input name="email" type="email" placeholder="Email">
  <textarea name="message"></textarea>
  <label><input type="checkbox" name="consent_email" value="yes"> I agree to be contacted</label>
  <input name="_gotcha" style="display:none" tabindex="-1" autocomplete="off">
  <button>Send</button>
</form>
<script>
document.getElementById("enquiry").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  const params = new URLSearchParams(location.search);
  for (const k of ["utm_source","utm_medium","utm_campaign","utm_term","utm_content","gclid","fbclid"])
    if (params.get(k)) data[k] = params.get(k);
  data.page_url = location.href;
  const r = await fetch("${url}", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  });
  e.target.innerHTML = r.ok ? "Thank you! We'll be in touch." : "Something went wrong. Please call us.";
});
</script>`;
  const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast.success("Copied"));
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{name}: your form link</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 text-sm">
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
            Copy it now: for safety it is shown only once. If you lose it, make a new link (the old one then stops working).
          </p>
          <div className="flex gap-2">
            <Input readOnly value={url} aria-label="Form link" className="font-mono text-xs" />
            <Button type="button" variant="outline" onClick={() => copy(url)}>
              <Copy /> Copy
            </Button>
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label>Example for your website</Label>
              <Button type="button" size="sm" variant="ghost" onClick={() => copy(snippet)}>
                <Copy /> Copy code
              </Button>
            </div>
            <pre className="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-[11px] leading-relaxed">{snippet}</pre>
            <p className="text-xs text-muted-foreground">
              Tools like Zapier, Make or n8n can POST JSON to the same link. Send <code>external_id</code> with your own ID so retries never create
              duplicates.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- assignment rules ----------
const BUILTIN_CONDITIONS: [string, string][] = [
  ["source", "Source"],
  ["city", "City"],
  ["region", "State / region"],
  ["country_code", "Country code"],
  ["preferred_language", "Language"],
  ["origin", "Origin"],
  ["created_via", "Came in by"],
  ["kind", "Person or company"],
];
const OPS: [Condition["op"], string][] = [
  ["in", "is any of"],
  ["not_in", "is none of"],
  ["empty", "is empty"],
  ["not_empty", "is filled in"],
];
const FIXED_VALUES: Record<string, [string, string][]> = {
  origin: [
    ["inbound", "Inbound"],
    ["outbound_ace", "Outbound (ACE)"],
    ["outside", "Outside the CRM"],
  ],
  created_via: [
    ["form", "Web form"],
    ["csv", "Import"],
    ["manual", "Added by hand"],
    ["api", "API"],
  ],
  kind: [
    ["person", "Person"],
    ["organisation", "Company"],
  ],
};

function useRules() {
  return useQuery({ queryKey: ["assignment-rules"], queryFn: async () => unwrap(await api.GET("/api/v1/assignment-rules")) });
}

function Assignment() {
  const rules = useRules();
  const users = useUsers();
  const teams = useTeams();
  const save = useSave();
  const [editing, setEditing] = useState<AssignmentRule | "new" | null>(null);
  const list = rules.data ?? [];
  const who = (r: AssignmentRule) => {
    if (r.strategy === "unassigned") return "Leave unassigned for a manager";
    const names = r.user_ids.map((id) => users.data?.find((u) => u.id === id)?.name ?? "someone");
    if (r.strategy === "user") return `Give to ${names[0]}`;
    if (r.team_id) return `Take turns in ${teams.data?.find((t) => t.id === r.team_id)?.name ?? "a team"}`;
    return `Take turns: ${names.join(", ")}`;
  };
  const order = (ids: string[]) => save(async () => unwrap(await api.PUT("/api/v1/assignment-rules/order", { body: { ids } })));

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        For web forms, imports set to &quot;by assignment rules&quot; and anyone adding a lead that way. Rules are checked top to bottom; the first
        one that matches decides. If none match, the lead waits in the Unassigned tab. Turns skip anyone who is disabled.
      </p>
      <div className="divide-y surface">
        {list.length === 0 && <p className="p-4 text-sm text-muted-foreground">No rules yet: new leads stay unassigned.</p>}
        {list.map((r, i) => (
          <div key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm">
            <span className="w-5 text-xs text-muted-foreground tabular-nums">{i + 1}.</span>
            <Switch
              aria-label={`${r.name} on`}
              checked={r.is_active}
              onCheckedChange={(on) =>
                save(async () =>
                  unwrap(await api.PATCH("/api/v1/assignment-rules/{rule_id}", { params: { path: { rule_id: r.id } }, body: { is_active: on } })),
                )
              }
            />
            <button className="font-medium hover:underline" onClick={() => setEditing(r)}>
              {r.name}
            </button>
            <span className="text-xs text-muted-foreground">
              {r.conditions.length ? `${r.conditions.length} condition${r.conditions.length > 1 ? "s" : ""}` : "Every lead"} → {who(r)}
            </span>
            <span className="ml-auto flex">
              <Button size="icon-sm" variant="ghost" aria-label="Move up" disabled={i === 0} onClick={() => order(swap(list, i, -1))}>
                <ArrowUp />
              </Button>
              <Button size="icon-sm" variant="ghost" aria-label="Move down" disabled={i === list.length - 1} onClick={() => order(swap(list, i, 1))}>
                <ArrowDown />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`Delete ${r.name}`}
                onClick={() =>
                  confirm(`Delete the rule ${r.name}?`) &&
                  save(async () => unwrap(await api.DELETE("/api/v1/assignment-rules/{rule_id}", { params: { path: { rule_id: r.id } } })), "Deleted")
                }
              >
                <Trash2 />
              </Button>
            </span>
          </div>
        ))}
      </div>
      <Button size="sm" onClick={() => setEditing("new")}>
        <Plus /> Add a rule
      </Button>
      {editing && <RuleDialog rule={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function swap<T extends { id: string }>(items: T[], index: number, dir: -1 | 1): string[] {
  const ids = items.map((i) => i.id);
  const j = index + dir;
  [ids[index], ids[j]] = [ids[j], ids[index]];
  return ids;
}

function RuleDialog({ rule, onClose }: { rule: AssignmentRule | null; onClose: () => void }) {
  const users = useUsers();
  const teams = useTeams();
  const sources = useSources();
  const fields = useFields();
  const save = useSave();
  const [name, setName] = useState(rule?.name ?? "");
  const [conditions, setConditions] = useState<Condition[]>((rule?.conditions as Condition[]) ?? []);
  const [strategy, setStrategy] = useState<Strategy>((rule?.strategy as Strategy) ?? "round_robin");
  const [pool, setPool] = useState<"people" | "team">(rule?.team_id ? "team" : "people");
  const [userIds, setUserIds] = useState<string[]>(rule?.user_ids ?? []);
  const [teamId, setTeamId] = useState(rule?.team_id ?? "");
  const active = (users.data ?? []).filter((u) => u.status !== "disabled");

  const fieldOptions: [string, string][] = [...BUILTIN_CONDITIONS, ...(fields.data ?? []).map((f) => [f.key, f.label] as [string, string])];
  const choicesFor = (field: string): [string, string][] | null => {
    if (field === "source") return (sources.data ?? []).map((s) => [s.id, s.name]);
    if (FIXED_VALUES[field]) return FIXED_VALUES[field];
    const f = fields.data?.find((x) => x.key === field);
    if (f && (f.type === "select" || f.type === "multi_select")) return (f.options as { value: string; label: string }[]).map((o) => [o.value, o.label]);
    return null;
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      name,
      conditions,
      strategy,
      user_ids: strategy === "unassigned" || (strategy === "round_robin" && pool === "team") ? [] : userIds,
      team_id: strategy === "round_robin" && pool === "team" ? teamId || null : null,
    };
    const ok = await save(async () => {
      if (rule) unwrap(await api.PATCH("/api/v1/assignment-rules/{rule_id}", { params: { path: { rule_id: rule.id } }, body }));
      else unwrap(await api.POST("/api/v1/assignment-rules", { body: { ...body, is_active: true } }));
    }, "Saved");
    if (ok) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{rule ? `Edit ${rule.name}` : "Add an assignment rule"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-5 text-sm">
          <div className="space-y-1.5">
            <Label htmlFor="r-name">Name</Label>
            <Input id="r-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Hindi-speaking leads" autoFocus />
          </div>

          <div className="space-y-2">
            <Label>When</Label>
            {conditions.length === 0 && <p className="text-xs text-muted-foreground">Every lead (add a condition to narrow it).</p>}
            {conditions.map((c, i) => {
              const choices = choicesFor(c.field);
              const update = (patch: Partial<Condition>) => setConditions(conditions.map((x, j) => (j === i ? { ...x, ...patch } : x)));
              return (
                <div key={i} className="space-y-1.5 rounded-lg border p-2">
                  <div className="flex gap-2">
                    <NativeSelect aria-label="Field" value={c.field} onChange={(e) => update({ field: e.target.value, values: [] })}>
                      {fieldOptions.map(([k, l]) => (
                        <option key={k} value={k}>
                          {l}
                        </option>
                      ))}
                    </NativeSelect>
                    <NativeSelect aria-label="Test" value={c.op} onChange={(e) => update({ op: e.target.value as Condition["op"] })}>
                      {OPS.map(([k, l]) => (
                        <option key={k} value={k}>
                          {l}
                        </option>
                      ))}
                    </NativeSelect>
                    <Button type="button" size="icon-sm" variant="ghost" aria-label="Remove condition" onClick={() => setConditions(conditions.filter((_, j) => j !== i))}>
                      <Trash2 />
                    </Button>
                  </div>
                  {(c.op === "in" || c.op === "not_in") &&
                    (choices ? (
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {choices.map(([v, l]) => (
                          <label key={v} className="flex items-center gap-1.5 text-xs">
                            <input
                              type="checkbox"
                              className="accent-primary"
                              checked={(c.values ?? []).includes(v)}
                              onChange={(e) => update({ values: e.target.checked ? [...(c.values ?? []), v] : (c.values ?? []).filter((x) => x !== v) })}
                            />
                            {l}
                          </label>
                        ))}
                      </div>
                    ) : (
                      <Input
                        aria-label="Values"
                        className="h-8"
                        placeholder="Values, separated by commas (any case)"
                        value={(c.values ?? []).join(", ")}
                        onChange={(e) => update({ values: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })}
                      />
                    ))}
                </div>
              );
            })}
            <Button type="button" size="sm" variant="outline" onClick={() => setConditions([...conditions, { field: "source", op: "in", values: [] }])}>
              <Plus /> Add a condition
            </Button>
          </div>

          <div className="space-y-2">
            <Label>Then</Label>
            <NativeSelect aria-label="Then" value={strategy} onChange={(e) => setStrategy(e.target.value as Strategy)}>
              <option value="round_robin">Take turns (round-robin)</option>
              <option value="user">Give to one person</option>
              <option value="unassigned">Leave unassigned for a manager</option>
            </NativeSelect>
            {strategy === "round_robin" && (
              <div className="inline-flex rounded-lg border p-0.5 text-xs">
                {(["people", "team"] as const).map((p) => (
                  <button key={p} type="button" onClick={() => setPool(p)} className={cn("rounded-md px-3 py-1", pool === p ? "bg-accent font-medium" : "text-muted-foreground")}>
                    {p === "people" ? "These people" : "Everyone in a team"}
                  </button>
                ))}
              </div>
            )}
            {strategy === "round_robin" && pool === "team" && (
              <NativeSelect aria-label="Team" value={teamId} onChange={(e) => setTeamId(e.target.value)}>
                <option value="">Choose a team…</option>
                {(teams.data ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </NativeSelect>
            )}
            {strategy === "user" && (
              <NativeSelect aria-label="Person" value={userIds[0] ?? ""} onChange={(e) => setUserIds(e.target.value ? [e.target.value] : [])}>
                <option value="">Choose…</option>
                {active.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </NativeSelect>
            )}
            {strategy === "round_robin" && pool === "people" && (
              <div className="max-h-48 space-y-1 overflow-auto rounded-lg border p-2">
                {active.map((u) => (
                  <label key={u.id} className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      className="accent-primary"
                      checked={userIds.includes(u.id)}
                      onChange={(e) => setUserIds(e.target.checked ? [...userIds, u.id] : userIds.filter((x) => x !== u.id))}
                    />
                    {u.name} <span className="text-muted-foreground">{u.email}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
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

// ---------- response times ----------
const UNITS: [number, string][] = [
  [1, "minutes"],
  [60, "hours"],
  [1440, "days"],
];
function inUnits(minutes: number): [number, number] {
  const unit = minutes % 1440 === 0 ? 1440 : minutes % 60 === 0 ? 60 : 1;
  return [minutes / unit, unit];
}

function Sla() {
  const rules = useQuery({ queryKey: ["sla-rules"], queryFn: async () => unwrap(await api.GET("/api/v1/sla-rules")) });
  const stages = useStages();
  const save = useSave();
  const [editing, setEditing] = useState<SlaRule | "new" | null>(null);
  const stageName = (id: string | null) => stages.data?.find((s) => s.id === id)?.name ?? "a stage";
  const BREACH: Record<string, string> = { none: "do nothing", alert: "alert the manager", reassign: "give it to the next person" };
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        A clock starts when a lead arrives or enters a stage. The owner gets a task due at the deadline. A call (or any contact) stops the clock; if
        nobody reaches the lead in time, it is noted on the timeline and the manager is told.
      </p>
      <div className="divide-y surface">
        {(rules.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">No response-time rules yet.</p>}
        {(rules.data ?? []).map((r) => {
          const [n, unit] = inUnits(r.within_minutes);
          return (
            <div key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm">
              <Switch
                aria-label={`${r.name} on`}
                checked={r.is_active}
                onCheckedChange={(on) =>
                  save(async () => unwrap(await api.PATCH("/api/v1/sla-rules/{rule_id}", { params: { path: { rule_id: r.id } }, body: { is_active: on } })))
                }
              />
              <button className="font-medium hover:underline" onClick={() => setEditing(r)}>
                {r.name}
              </button>
              <span className="text-xs text-muted-foreground">
                {r.trigger === "lead_created" ? "New lead" : `Enters ${stageName(r.stage_id)}`} → contact within {n} {UNITS.find((u) => u[0] === unit)?.[1]}, else{" "}
                {BREACH[r.on_breach]}
              </span>
              <Button
                className="ml-auto"
                size="icon-sm"
                variant="ghost"
                aria-label={`Delete ${r.name}`}
                onClick={() =>
                  confirm(`Delete ${r.name}?`) &&
                  save(async () => unwrap(await api.DELETE("/api/v1/sla-rules/{rule_id}", { params: { path: { rule_id: r.id } } })), "Deleted")
                }
              >
                <Trash2 />
              </Button>
            </div>
          );
        })}
      </div>
      <Button size="sm" onClick={() => setEditing("new")}>
        <Plus /> Add a response time
      </Button>
      {editing && <SlaDialog rule={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function SlaDialog({ rule, onClose }: { rule: SlaRule | null; onClose: () => void }) {
  const stages = useStages();
  const save = useSave();
  const [initialN, initialUnit] = inUnits(rule?.within_minutes ?? 30);
  const [name, setName] = useState(rule?.name ?? "");
  const [trigger, setTrigger] = useState<"lead_created" | "stage_entered">((rule?.trigger as "lead_created") ?? "lead_created");
  const [stageId, setStageId] = useState(rule?.stage_id ?? "");
  const [n, setN] = useState(String(initialN));
  const [unit, setUnit] = useState(initialUnit);
  const [task, setTask] = useState(rule?.create_task ?? true);
  const [title, setTitle] = useState(rule?.task_title ?? "");
  const [breach, setBreach] = useState<"none" | "alert" | "reassign">((rule?.on_breach as "alert") ?? "alert");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const within = Math.round(Number(n) * unit);
    if (!within || within < 1) return toast.error("Enter how long they have");
    const common = { name, within_minutes: within, create_task: task, task_title: title.trim() || null, on_breach: breach };
    const ok = await save(async () => {
      if (rule) unwrap(await api.PATCH("/api/v1/sla-rules/{rule_id}", { params: { path: { rule_id: rule.id } }, body: common }));
      else unwrap(await api.POST("/api/v1/sla-rules", { body: { ...common, trigger, stage_id: trigger === "stage_entered" ? stageId || null : null, is_active: true } }));
    }, "Saved");
    if (ok) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{rule ? `Edit ${rule.name}` : "Add a response time"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4 text-sm">
          <div className="space-y-1.5">
            <Label htmlFor="s-name">Name</Label>
            <Input id="s-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="First call" autoFocus />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="s-trigger">Starts when</Label>
              <NativeSelect id="s-trigger" value={trigger} disabled={Boolean(rule)} onChange={(e) => setTrigger(e.target.value as typeof trigger)}>
                <option value="lead_created">A new lead arrives</option>
                <option value="stage_entered">A lead enters a stage</option>
              </NativeSelect>
            </div>
            {trigger === "stage_entered" && (
              <div className="space-y-1.5">
                <Label htmlFor="s-stage">Stage</Label>
                <NativeSelect id="s-stage" value={stageId} disabled={Boolean(rule)} onChange={(e) => setStageId(e.target.value)}>
                  <option value="">Choose…</option>
                  {(stages.data ?? [])
                    .filter((s) => s.is_open)
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                </NativeSelect>
              </div>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="s-n">Contact within</Label>
            <div className="flex gap-2">
              <Input id="s-n" type="number" min={1} className="w-24" value={n} onChange={(e) => setN(e.target.value)} />
              <NativeSelect aria-label="Unit" value={unit} onChange={(e) => setUnit(Number(e.target.value))}>
                {UNITS.map(([u, l]) => (
                  <option key={u} value={u}>
                    {l}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>
          <label className="flex items-center gap-2">
            <Switch checked={task} onCheckedChange={setTask} aria-label="Create a task" /> Give the owner a task due at the deadline
          </label>
          {task && <Input aria-label="Task title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Task title (optional)" />}
          <div className="space-y-1.5">
            <Label htmlFor="s-breach">If nobody reaches them in time</Label>
            <NativeSelect id="s-breach" value={breach} onChange={(e) => setBreach(e.target.value as typeof breach)}>
              <option value="alert">Alert the manager</option>
              <option value="reassign">Give it to the next person by the assignment rules</option>
              <option value="none">Only note it on the timeline</option>
            </NativeSelect>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || (trigger === "stage_entered" && !stageId)}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------- duplicates & safety ----------
function Safety() {
  const rules = useCrmRules();
  const save = useSave();
  const s = rules.data;
  const [hours, setHours] = useState<string | null>(null);
  if (!s) return <p className="text-muted-foreground">Loading…</p>;
  const patch = (body: Record<string, unknown>) => save(async () => unwrap(await api.PATCH("/api/v1/crm-rules", { body })), "Saved");
  const leakOn = Boolean(s.leakage_hours);

  return (
    <div className="space-y-8 text-sm">
      <section className="space-y-2">
        <h3 className="font-medium">When a web form or import brings a phone or email you already have</h3>
        {(
          [
            ["update", "Update the existing record (recommended)", "Empty details are filled in, nothing is overwritten, the owner is told they enquired again, and a closed record reopens."],
            ["flag", "Add a new record, marked as a possible duplicate", "Someone reviews it and merges."],
            ["create", "Always add a new record", "Use only if people often share a phone (e.g. siblings)."],
          ] as const
        ).map(([value, title, hint]) => (
          <label key={value} className="flex gap-2 rounded-lg border p-3">
            <input type="radio" name="dupes" className="mt-1 accent-primary" checked={s.duplicate_policy === value} onChange={() => patch({ duplicate_policy: value })} />
            <span>
              <span className="font-medium">{title}</span>
              <span className="block text-xs text-muted-foreground">{hint}</span>
            </span>
          </label>
        ))}
        <p className="text-xs text-muted-foreground">Adding by hand always warns you first when the person already exists.</p>
      </section>

      <section className="space-y-2">
        <h3 className="font-medium">Group people under their company</h3>
        <NativeSelect aria-label="Company grouping" value={s.org_grouping} onChange={(e) => patch({ org_grouping: e.target.value })}>
          <option value="off">Off</option>
          <option value="suggest">Suggest a company with the same email domain or name</option>
          <option value="auto">Link automatically when the email domain matches one company</option>
        </NativeSelect>
        <p className="text-xs text-muted-foreground">Gmail, Yahoo, Outlook and other free email addresses never count. Company names only ever suggest.</p>
      </section>

      <section className="space-y-2">
        <h3 className="font-medium">Leakage guard</h3>
        <p className="text-xs text-muted-foreground">Catches leads nobody called after they arrived, and follow-ups left overdue.</p>
        <label className="flex items-center gap-2">
          <Switch checked={leakOn} aria-label="Leakage guard" onCheckedChange={(on) => patch({ leakage_hours: on ? 24 : 0 })} />
          {leakOn ? "On" : "Off"}
        </label>
        {leakOn && (
          <div className="flex flex-wrap items-center gap-2">
            Flag after
            <Input
              aria-label="Hours"
              type="number"
              min={1}
              className="w-20"
              value={hours ?? String(s.leakage_hours)}
              onChange={(e) => setHours(e.target.value)}
              onBlur={() => hours && Number(hours) > 0 && patch({ leakage_hours: Number(hours) }).then(() => setHours(null))}
            />
            hours, then
            <NativeSelect aria-label="Leakage action" className="w-auto" value={s.leakage_action} onChange={(e) => patch({ leakage_action: e.target.value })}>
              <option value="alert">alert the manager and owner</option>
              <option value="reassign">give it to the next person by the rules</option>
            </NativeSelect>
          </div>
        )}
      </section>
    </div>
  );
}
