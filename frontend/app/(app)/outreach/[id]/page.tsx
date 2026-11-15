"use client";

import { Plus, Trash2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { useSendingInboxes } from "@/components/crm/sending-inboxes";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { relative } from "@/lib/crm";
import { useUsers } from "@/lib/directory";
import {
  type Campaign,
  type CampaignStep,
  type CampaignStepIn,
  CONTACT_VARIABLES,
  type ImportReport,
  PLACE_LABEL,
  REASON_LABEL,
  STATUS_LABEL,
  useCampaign,
  useCampaignContacts,
  useCampaignStats,
  useCampaignSteps,
  useRefreshOutreach,
} from "@/lib/outreach";
import { cn } from "@/lib/utils";

type Tab = "contacts" | "sequence" | "sending" | "settings" | "results";
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function CampaignPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const campaign = useCampaign(id);
  const refresh = useRefreshOutreach();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("contacts");
  const [problems, setProblems] = useState<string[]>([]);
  if (!campaign.data) return <p className="p-6 text-muted-foreground">{campaign.isError ? "Not found" : "Loading…"}</p>;
  const c = campaign.data;
  const manage = can("campaigns.manage");
  const reload = async () => {
    await campaign.refetch();
    refresh();
  };
  const call = async (path: "launch" | "pause" | "resume") => {
    setProblems([]);
    try {
      const p = { params: { path: { campaign_id: c.id } } };
      if (path === "launch") unwrap(await api.POST("/api/v1/campaigns/{campaign_id}/launch", p));
      if (path === "pause") unwrap(await api.POST("/api/v1/campaigns/{campaign_id}/pause", p));
      if (path === "resume") unwrap(await api.POST("/api/v1/campaigns/{campaign_id}/resume", p));
      toast.success(path === "launch" ? "Launched. The first emails go out within a minute." : path === "pause" ? "Paused" : "Running again");
      await reload();
    } catch (e) {
      const body = (e as ApiError).body as { problems?: string[] } | undefined;
      if (body?.problems) setProblems(body.problems);
      toast.error((e as Error).message);
    }
  };
  const tabs: [Tab, string][] = [
    ["contacts", `Contacts (${c.counts.contacts})`],
    ["sequence", "Sequence"],
    ["sending", "Inboxes and hours"],
    ["settings", "Settings"],
    ["results", "Results"],
  ];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        back={{ href: "/outreach", label: "Outreach" }}
        title={c.name}
        actions={
          <div className="flex items-center gap-2">
            <Badge variant={c.status === "running" ? "secondary" : "outline"}>{STATUS_LABEL[c.status]}</Badge>
            {manage && c.status === "draft" && (
              <Button size="sm" onClick={() => call("launch")}>
                Launch
              </Button>
            )}
            {manage && c.status === "running" && (
              <Button size="sm" variant="outline" onClick={() => call("pause")}>
                Pause
              </Button>
            )}
            {manage && c.status === "paused" && (
              <Button size="sm" onClick={() => call("resume")}>
                Resume
              </Button>
            )}
            {manage && c.status === "draft" && (
              <Button
                size="sm"
                variant="ghost"
                aria-label="Delete campaign"
                onClick={async () => {
                  if (!confirm(`Delete the draft ${c.name}?`)) return;
                  try {
                    unwrap(await api.DELETE("/api/v1/campaigns/{campaign_id}", { params: { path: { campaign_id: c.id } } }));
                    refresh();
                    router.push("/outreach");
                  } catch (e) {
                    toast.error((e as Error).message);
                  }
                }}
              >
                <Trash2 />
              </Button>
            )}
          </div>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-4xl p-4 sm:p-6">
          {problems.length > 0 && (
            <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm" role="alert">
              <div className="mb-1 font-medium">Before launching:</div>
              <ul className="list-disc pl-5">
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          )}
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
          {tab === "contacts" && <Contacts c={c} manage={manage} onChange={reload} />}
          {tab === "sequence" && <Sequence c={c} manage={manage} />}
          {tab === "sending" && <Sending c={c} manage={manage} onChange={reload} />}
          {tab === "settings" && <Settings c={c} manage={manage} onChange={reload} />}
          {tab === "results" && <Results id={c.id} />}
        </div>
      </div>
    </div>
  );
}

// ---------- contacts ----------
function Contacts({ c, manage, onChange }: { c: Campaign; manage: boolean; onChange: () => Promise<void> }) {
  const [status, setStatus] = useState("");
  const list = useCampaignContacts(c.id, status);
  const [csv, setCsv] = useState<{ text: string; name: string } | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const run = async (dry: boolean) => {
    if (!csv) return;
    setBusy(true);
    try {
      const r = unwrap(
        await api.POST("/api/v1/campaigns/{campaign_id}/contacts/import", {
          params: { path: { campaign_id: c.id } },
          body: { csv: csv.text, filename: csv.name, dry_run: dry, mapping: Object.keys(mapping).length ? (mapping as never) : null },
        }),
      );
      setReport(r);
      setMapping(r.mapping);
      if (!dry) {
        toast.success(`${r.added} contacts added`);
        setCsv(null);
        setReport(null);
        setMapping({});
        await list.refetch();
        await onChange();
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {manage && c.status !== "finished" && (
        <div className="space-y-3 surface p-3">
          <div className="text-sm font-medium">Add contacts from a CSV file</div>
          <p className="text-xs text-muted-foreground">
            One column must be the email address. Other columns (city, pain point…) become variables you can use in emails, like {"{{city}}"}. Up to 20,000
            rows. People who are already leads or customers, or who unsubscribed or bounced, are skipped.
          </p>
          <Input
            type="file"
            accept=".csv,text/csv"
            aria-label="CSV file"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              setCsv({ text: await f.text(), name: f.name });
              setReport(null);
              setMapping({});
            }}
          />
          {csv && !report && (
            <Button size="sm" disabled={busy} onClick={() => run(true)}>
              Check the file
            </Button>
          )}
          {report && (
            <div className="space-y-3">
              <div className="grid gap-2 sm:grid-cols-2">
                {Object.keys(report.mapping).map((col) => (
                  <label key={col} className="flex items-center gap-2 text-sm">
                    <span className="w-32 shrink-0 truncate" title={col}>
                      {col}
                    </span>
                    <NativeSelect aria-label={`Column ${col}`} value={mapping[col]} onChange={(e) => setMapping({ ...mapping, [col]: e.target.value })}>
                      {["email", "first_name", "last_name", "company", "title", "phone", "website", "variable", "ignore"].map((t) => (
                        <option key={t} value={t}>
                          {t === "variable" ? "Variable" : t === "ignore" ? "Ignore" : t.replace("_", " ")}
                        </option>
                      ))}
                    </NativeSelect>
                  </label>
                ))}
              </div>
              <ul className="text-sm" data-testid="import-report">
                <li>
                  <strong>{report.added}</strong> will be added
                </li>
                {report.already_lead > 0 && <li>{report.already_lead} already a lead or customer (skipped)</li>}
                {report.suppressed > 0 && <li>{report.suppressed} unsubscribed, bounced or blocked (skipped)</li>}
                {report.invalid_email > 0 && <li>{report.invalid_email} without a valid email (skipped)</li>}
                {report.duplicates_in_file > 0 && <li>{report.duplicates_in_file} repeated in the file (skipped)</li>}
                {report.already_in_campaign > 0 && <li>{report.already_in_campaign} already in this campaign</li>}
                {report.variables.length > 0 && <li>Variables: {report.variables.map((v) => `{{${v}}}`).join(", ")}</li>}
              </ul>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={busy} onClick={() => run(true)}>
                  Check again
                </Button>
                <Button size="sm" disabled={busy || report.added === 0} onClick={() => run(false)}>
                  Add {report.added} contacts
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
      <div className="flex items-center gap-2">
        <NativeSelect aria-label="Show" className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Everyone</option>
          {Object.entries(PLACE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="divide-y surface">
        {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "No contacts."}</p>}
        {(list.data ?? []).map((p) => (
          <div key={p.contact.id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-sm" data-contact={p.contact.email}>
            <span className="font-medium">{[p.contact.first_name, p.contact.last_name].filter(Boolean).join(" ") || p.contact.email}</span>
            <span className="break-all text-xs text-muted-foreground">
              {p.contact.email}
              {p.contact.company ? ` · ${p.contact.company}` : ""}
            </span>
            <span className="ml-auto text-xs text-muted-foreground">
              {PLACE_LABEL[p.status] ?? p.status}
              {p.ended_reason && p.status === "stopped" ? ` (${REASON_LABEL[p.ended_reason] ?? p.ended_reason})` : ""}
              {p.status === "active" && p.next_run_at ? ` · step ${p.position} ${relative(p.next_run_at)}` : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- sequence ----------
const EMPTY_STEP: CampaignStepIn = { wait_days: 3, variants: [{ subject: "", body: "" }] };

function Sequence({ c, manage }: { c: Campaign; manage: boolean }) {
  const steps = useCampaignSteps(c.id);
  if (!steps.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return <SequenceEditor c={c} manage={manage} saved={steps.data} onSaved={() => steps.refetch()} />;
}

function SequenceEditor({
  c,
  manage,
  saved,
  onSaved,
}: {
  c: Campaign;
  manage: boolean;
  saved: CampaignStep[];
  onSaved: () => Promise<unknown>;
}) {
  const steps = { data: saved, refetch: onSaved };
  const [draft, setDraft] = useState<CampaignStepIn[]>(() =>
    saved.length
      ? saved.map((s) => ({ wait_days: s.wait_days, variants: s.variants.map((v) => ({ subject: v.subject ?? "", body: v.body })) }))
      : [{ wait_days: 0, variants: [{ subject: "", body: "Hi {{first_name|there}},\n\n" }] }],
  );
  const [preview, setPreview] = useState<{ subject: string; body: string; missing: string[] } | null>(null);
  const locked = (steps.data?.length ?? 0) > 0 && c.status !== "draft"; // after launch: change or add, not remove
  const editable = manage && c.status !== "finished";
  const set = (i: number, step: CampaignStepIn) => setDraft(draft.map((s, n) => (n === i ? step : s)));
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Variables: {CONTACT_VARIABLES.map((v) => `{{${v}}}`).join(", ")} and your CSV columns. Add a fallback for empty ones: {"{{first_name|there}}"}. A
        step with no subject is sent as a reply in the same thread.
      </p>
      {draft.map((step, i) => (
        <div key={i} className="space-y-2 surface p-3" data-step={i + 1}>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">Step {i + 1}</span>
            {i > 0 && (
              <label className="flex items-center gap-1.5 text-muted-foreground">
                wait
                <Input
                  type="number"
                  min={0}
                  max={365}
                  aria-label={`Step ${i + 1} wait days`}
                  className="h-7 w-16"
                  disabled={!editable}
                  value={step.wait_days}
                  onChange={(e) => set(i, { ...step, wait_days: Number(e.target.value) })}
                />
                days after the previous step
              </label>
            )}
            {editable && !(locked && i < (steps.data?.length ?? 0)) && draft.length > 1 && (
              <Button size="sm" variant="ghost" className="ml-auto" aria-label={`Remove step ${i + 1}`} onClick={() => setDraft(draft.filter((_, n) => n !== i))}>
                <Trash2 />
              </Button>
            )}
          </div>
          {step.variants.map((v, k) => (
            <div key={k} className="space-y-1.5 rounded-lg border p-2">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>Version {String.fromCharCode(65 + k)}</span>
                <button
                  className="ml-auto hover:underline"
                  onClick={async () => {
                    try {
                      const r = unwrap(
                        await api.POST("/api/v1/campaigns/{campaign_id}/preview", {
                          params: { path: { campaign_id: c.id } },
                          body: { position: i + 1, variant: k },
                        }),
                      );
                      setPreview(r);
                    } catch (e) {
                      toast.error((e as Error).message === "Step not found" ? "Save the sequence first" : (e as Error).message);
                    }
                  }}
                >
                  Preview
                </button>
                {editable && step.variants.length > 1 && (
                  <button className="hover:underline" onClick={() => set(i, { ...step, variants: step.variants.filter((_, n) => n !== k) })}>
                    Remove
                  </button>
                )}
              </div>
              <Input
                aria-label={`Step ${i + 1} version ${String.fromCharCode(65 + k)} subject`}
                placeholder={i === 0 ? "Subject" : "Subject (empty: reply in the same thread)"}
                disabled={!editable}
                value={v.subject ?? ""}
                onChange={(e) => set(i, { ...step, variants: step.variants.map((x, n) => (n === k ? { ...x, subject: e.target.value } : x)) })}
              />
              <Textarea
                aria-label={`Step ${i + 1} version ${String.fromCharCode(65 + k)} body`}
                rows={6}
                disabled={!editable}
                value={v.body}
                onChange={(e) => set(i, { ...step, variants: step.variants.map((x, n) => (n === k ? { ...x, body: e.target.value } : x)) })}
              />
            </div>
          ))}
          {editable && step.variants.length < 5 && (
            <Button size="sm" variant="outline" onClick={() => set(i, { ...step, variants: [...step.variants, { subject: step.variants[0].subject, body: "" }] })}>
              <Plus /> Version {String.fromCharCode(65 + step.variants.length)} (A/B test)
            </Button>
          )}
        </div>
      ))}
      {preview && (
        <div className="space-y-1 rounded-lg border bg-muted/30 p-3 text-sm" data-testid="preview">
          <div className="text-xs text-muted-foreground">Preview with the first contact</div>
          <div className="font-medium">{preview.subject}</div>
          <div className="whitespace-pre-wrap">{preview.body}</div>
          {preview.missing.length > 0 && <div className="text-xs text-destructive">Empty for this contact: {preview.missing.join(", ")}</div>}
        </div>
      )}
      {editable && (
        <div className="flex gap-2">
          {draft.length < 10 && (
            <Button size="sm" variant="outline" onClick={() => setDraft([...draft, { ...EMPTY_STEP, variants: [{ subject: "", body: "" }] }])}>
              <Plus /> Add a follow-up
            </Button>
          )}
          <Button
            size="sm"
            onClick={async () => {
              try {
                unwrap(
                  await api.PUT("/api/v1/campaigns/{campaign_id}/steps", {
                    params: { path: { campaign_id: c.id } },
                    body: { steps: draft.map((s, i) => ({ ...s, wait_days: i === 0 ? 0 : s.wait_days })) },
                  }),
                );
                await steps.refetch();
                toast.success("Sequence saved");
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
          >
            Save sequence
          </Button>
        </div>
      )}
    </div>
  );
}

// ---------- inboxes and sending hours ----------
function Sending({ c, manage, onChange }: { c: Campaign; manage: boolean; onChange: () => Promise<void> }) {
  const inboxes = useSendingInboxes();
  const pool = inboxes.data ?? []; // the sending inboxes are the pool
  const [chosen, setChosen] = useState<string[]>(c.mailbox_ids);
  const sched = c.schedule as { timezone?: string; days?: number[]; from?: string; to?: string };
  const [days, setDays] = useState<number[]>(sched.days ?? [0, 1, 2, 3, 4]);
  const [from, setFrom] = useState(sched.from ?? "09:00");
  const [to, setTo] = useState(sched.to ?? "18:00");
  const [tz, setTz] = useState(sched.timezone ?? "");
  const [cap, setCap] = useState(c.daily_cap);
  const editable = manage && c.status !== "finished";
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <div className="text-sm font-medium">Send from</div>
        <p className="text-xs text-muted-foreground">
          Each person always gets every step from the same inbox, so the thread and the replies stay together. Each inbox&apos;s own daily limit and gap
          always apply.
        </p>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" disabled={!editable} checked={chosen.length === 0} onChange={() => setChosen([])} /> All sending inboxes ({pool.length})
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" disabled={!editable} checked={chosen.length > 0} onChange={() => setChosen(pool.slice(0, 1).map((m) => m.id))} /> Only these:
        </label>
        {chosen.length > 0 && (
          <div className="grid gap-1 pl-6 sm:grid-cols-2">
            {pool.map((m) => (
              <label key={m.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  disabled={!editable}
                  checked={chosen.includes(m.id)}
                  onChange={(e) => setChosen(e.target.checked ? [...chosen, m.id] : chosen.filter((x) => x !== m.id))}
                />
                <span className="truncate">{m.email_address}</span>
                {m.status !== "active" && <Badge variant="outline">{m.status}</Badge>}
              </label>
            ))}
          </div>
        )}
        {pool.length === 0 && <p className="text-sm text-destructive">No sending inboxes yet. Add them in Settings → Inboxes.</p>}
      </div>
      <div className="space-y-2">
        <div className="text-sm font-medium">Sending hours</div>
        <div className="flex flex-wrap gap-1.5">
          {DAYS.map((d, i) => (
            <label key={d} className={cn("rounded-md border px-2 py-1 text-sm", days.includes(i) && "border-primary bg-primary/10")}>
              <input
                type="checkbox"
                className="sr-only"
                disabled={!editable}
                checked={days.includes(i)}
                onChange={(e) => setDays(e.target.checked ? [...days, i].sort() : days.filter((x) => x !== i))}
              />
              {d}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          from <Input aria-label="From" type="time" className="h-8 w-28" disabled={!editable} value={from} onChange={(e) => setFrom(e.target.value)} />
          to <Input aria-label="To" type="time" className="h-8 w-28" disabled={!editable} value={to} onChange={(e) => setTo(e.target.value)} />
          <Input aria-label="Time zone" className="h-8 w-48" disabled={!editable} value={tz} onChange={(e) => setTz(e.target.value)} placeholder="Asia/Kolkata" />
        </div>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <Label htmlFor="cap">At most</Label>
        <Input id="cap" type="number" min={1} className="h-8 w-24" disabled={!editable} value={cap} onChange={(e) => setCap(Number(e.target.value))} />
        emails a day from this campaign
      </div>
      {editable && (
        <Button
          size="sm"
          onClick={async () => {
            try {
              unwrap(
                await api.PATCH("/api/v1/campaigns/{campaign_id}", {
                  params: { path: { campaign_id: c.id } },
                  body: { mailbox_ids: chosen, daily_cap: cap, schedule: { days, from, to, timezone: tz || null } },
                }),
              );
              await onChange();
              toast.success("Saved");
            } catch (e) {
              toast.error((e as Error).message);
            }
          }}
        >
          Save
        </Button>
      )}
    </div>
  );
}

// ---------- settings ----------
function Settings({ c, manage, onChange }: { c: Campaign; manage: boolean; onChange: () => Promise<void> }) {
  const { can } = useAuth();
  const users = useUsers(can("users.read"));
  const [name, setName] = useState(c.name);
  const [description, setDescription] = useState(c.description ?? "");
  const [owner, setOwner] = useState(c.owner_user_id ?? "");
  const [opens, setOpens] = useState(c.track_opens);
  const [clicks, setClicks] = useState(c.track_clicks);
  const editable = manage && c.status !== "finished";
  return (
    <div className="max-w-xl space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="cname">Name</Label>
        <Input id="cname" disabled={!editable} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="cdesc">What you offer</Label>
        <Textarea id="cdesc" rows={4} disabled={!editable} value={description} onChange={(e) => setDescription(e.target.value)} />
        <p className="text-xs text-muted-foreground">A few lines about the offer. ACE reads it to understand replies.</p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="cowner">Owner</Label>
        <NativeSelect id="cowner" disabled={!editable || !users.data} value={owner} onChange={(e) => setOwner(e.target.value)}>
          {!users.data && <option value={owner}>{c.owner_name ?? "—"}</option>}
          {(users.data ?? [])
            .filter((u) => u.status === "active")
            .map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
        </NativeSelect>
        <p className="text-xs text-muted-foreground">Replies go to the owner. Sales users see only campaigns they own.</p>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Switch disabled={!editable} checked={opens} onCheckedChange={setOpens} aria-label="Track opens" /> Track opens
      </label>
      <label className="flex items-center gap-2 text-sm">
        <Switch disabled={!editable} checked={clicks} onCheckedChange={setClicks} aria-label="Track link clicks" /> Track link clicks
      </label>
      <p className="text-xs text-muted-foreground">Both are off by default: cold emails without tracking land in the inbox more often.</p>
      {editable && (
        <Button
          size="sm"
          onClick={async () => {
            try {
              unwrap(
                await api.PATCH("/api/v1/campaigns/{campaign_id}", {
                  params: { path: { campaign_id: c.id } },
                  body: { name, description: description || null, owner_user_id: owner || null, track_opens: opens, track_clicks: clicks },
                }),
              );
              await onChange();
              toast.success("Saved");
            } catch (e) {
              toast.error((e as Error).message);
            }
          }}
        >
          Save
        </Button>
      )}
    </div>
  );
}

// ---------- results ----------
function Results({ id }: { id: string }) {
  const stats = useCampaignStats(id);
  if (!stats.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const s = stats.data;
  const pct = (n: number, of: number) => (of ? `${Math.round((n * 100) / of)}%` : "—");
  const table = (title: string, rows: typeof s.steps) => (
    <div className="space-y-1.5">
      <div className="text-sm font-medium">{title}</div>
      <div className="overflow-x-auto surface">
        <table className="w-full text-sm tabular-nums">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-normal"></th>
              <th className="px-3 py-2 text-right font-normal">Sent</th>
              <th className="px-3 py-2 text-right font-normal">Replied</th>
              <th className="px-3 py-2 text-right font-normal">Opened</th>
              <th className="px-3 py-2 text-right font-normal">Bounced</th>
              <th className="px-3 py-2 text-right font-normal">Unsubscribed</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-2 text-muted-foreground">
                  Nothing sent yet.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.key}>
                <td className="px-3 py-2">{r.label}</td>
                <td className="px-3 py-2 text-right">{r.sent}</td>
                <td className="px-3 py-2 text-right">
                  {r.replied} <span className="text-xs text-muted-foreground">{pct(r.replied, r.sent)}</span>
                </td>
                <td className="px-3 py-2 text-right">{r.opened || "—"}</td>
                <td className="px-3 py-2 text-right">{r.bounced}</td>
                <td className="px-3 py-2 text-right">{r.unsubscribed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
  const t = s.totals;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          ["Sent", t.sent],
          ["Replies", `${t.replied} (${pct(t.replied, t.sent)})`],
          ["Bounced", `${t.bounced} (${pct(t.bounced, t.sent)})`],
          ["Still to email", t.active],
        ].map(([k, v]) => (
          <div key={k} className="surface p-3">
            <div className="text-xs text-muted-foreground">{k}</div>
            <div className="text-lg font-semibold tabular-nums">{v}</div>
          </div>
        ))}
      </div>
      {table("By step", s.steps)}
      {table("By version (A/B)", s.variants)}
      {table("By inbox", s.inboxes)}
      <p className="text-xs text-muted-foreground">Opens show only when open tracking is on, and are estimates (some email apps hide them).</p>
    </div>
  );
}
