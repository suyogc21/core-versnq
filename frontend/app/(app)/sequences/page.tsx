"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { useLeads } from "@/lib/crm";
import { type Template, useRefreshSequences, useSequences, useTemplates, VARIABLES } from "@/lib/sequences";
import { cn } from "@/lib/utils";

type Tab = "sequences" | "templates" | "sending";

export default function SequencesPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("sequences");
  if (!can("sequences.manage")) return <p className="p-8 text-center text-muted-foreground">Ask your admin to set up sequences.</p>;
  const tabs: [Tab, string][] = [
    ["sequences", "Sequences"],
    ["templates", "Email templates"],
    ["sending", "Sending hours"],
  ];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Sequences" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-4xl p-4 sm:p-6">
          <p className="mb-4 text-sm text-muted-foreground">
            Follow-ups that run themselves: emails, waits and tasks for the owner. Anyone who replies, opts out, pays or becomes a customer is taken out
            automatically.
          </p>
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
          {tab === "sequences" && <SequenceList />}
          {tab === "templates" && <Templates />}
          {tab === "sending" && <Sending />}
        </div>
      </div>
    </div>
  );
}

function SequenceList() {
  const list = useSequences();
  const refresh = useRefreshSequences();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  return (
    <div className="space-y-4">
      <div className="divide-y surface">
        {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "No sequences yet."}</p>}
        {(list.data ?? []).map((s) => (
          <div key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm" data-sequence={s.name}>
            <Switch
              aria-label={`${s.name} on`}
              checked={s.is_active}
              onCheckedChange={async (on) => {
                if (!on && s.active && !confirm(`Switch off ${s.name}? The ${s.active} people in it stop now.`)) return;
                try {
                  unwrap(await api.PATCH("/api/v1/sequences/{s_id}", { params: { path: { s_id: s.id } }, body: { is_active: on } }));
                  refresh();
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            />
            <Link href={`/sequences/${s.id}`} className="font-medium hover:underline">
              {s.name}
            </Link>
            <span className="text-xs text-muted-foreground">
              {s.steps.length} step{s.steps.length === 1 ? "" : "s"} · {s.active} in it now · {s.completed} finished · {s.stopped} stopped
            </span>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        {adding ? (
          <>
            <Input autoFocus aria-label="Sequence name" placeholder="e.g. New enquiry follow-up" className="h-8 max-w-72" value={name} onChange={(e) => setName(e.target.value)} />
            <Button
              size="sm"
              disabled={!name.trim()}
              onClick={async () => {
                try {
                  const s = unwrap(await api.POST("/api/v1/sequences", { body: { name, allow_with_others: false, stop_on: ["reply", "customer", "deal_won", "payment", "closed"] } }));
                  refresh();
                  window.location.href = `/sequences/${s.id}`;
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            >
              Create
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <Button size="sm" onClick={() => setAdding(true)}>
            <Plus /> New sequence
          </Button>
        )}
      </div>
    </div>
  );
}

// ---------- templates ----------
function Templates() {
  const list = useTemplates();
  const [editing, setEditing] = useState<Template | "new" | null>(null);
  return (
    <div className="space-y-4">
      <div className="divide-y surface">
        {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "No templates yet."}</p>}
        {(list.data ?? []).map((t) => (
          <button key={t.id} className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-muted/50" onClick={() => setEditing(t)} data-template={t.name}>
            <span className={cn("font-medium", !t.is_active && "text-muted-foreground line-through")}>{t.name}</span>
            <span className="min-w-0 truncate text-xs text-muted-foreground">{t.subject}</span>
          </button>
        ))}
      </div>
      <Button size="sm" onClick={() => setEditing("new")}>
        <Plus /> New template
      </Button>
      {editing && <TemplateDialog template={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function TemplateDialog({ template, onClose }: { template: Template | null; onClose: () => void }) {
  const refresh = useRefreshSequences();
  const [name, setName] = useState(template?.name ?? "");
  const [subject, setSubject] = useState(template?.subject ?? "");
  const [body, setBody] = useState(template?.body ?? "Hi {{lead.first_name|there}},\n\n\n\n{{owner.name|The team}}\n{{company.name}}");
  const [q, setQ] = useState("");
  const leads = useLeads({ q: q || undefined, limit: 5 });
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);
  const insert = (v: string) => setBody((b) => `${b}${b.endsWith(" ") || b.endsWith("\n") || !b ? "" : " "}${v}`);

  async function save() {
    try {
      if (template) unwrap(await api.PATCH("/api/v1/templates/{t_id}", { params: { path: { t_id: template.id } }, body: { name, subject, body } }));
      else unwrap(await api.POST("/api/v1/templates", { body: { name, subject, body, channel: "email", is_active: true } }));
      refresh();
      toast.success("Template saved");
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function showPreview(leadId: string) {
    if (!template) return toast.error("Save the template first, then preview it");
    try {
      setPreview(unwrap(await api.POST("/api/v1/templates/{t_id}/preview", { params: { path: { t_id: template.id } }, body: { lead_id: leadId } })));
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{template ? template.name : "New email template"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="space-y-1">
            <Label htmlFor="t-name">Name (only your team sees it)</Label>
            <Input id="t-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Welcome" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="t-subject">Subject</Label>
            <Input id="t-subject" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Hi {{lead.first_name|there}}, your brochure" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="t-body">Message</Label>
            <Textarea id="t-body" rows={10} value={body} onChange={(e) => setBody(e.target.value)} />
            <div className="flex flex-wrap gap-1">
              {VARIABLES.map(([v, l]) => (
                <button key={v} type="button" className="rounded border px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-accent" onClick={() => insert(v)}>
                  + {l}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Text after | is used when the value is empty. Links are tracked; an unsubscribe link is added to every email.
            </p>
          </div>
          {template && (
            <div className="space-y-1 rounded-lg border p-3">
              <Label htmlFor="t-preview">Preview with a lead</Label>
              <Input id="t-preview" placeholder="Search a name…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8" />
              {q && (
                <div className="flex flex-wrap gap-1">
                  {(leads.data?.items ?? []).map((l) => (
                    <button key={l.id} type="button" className="rounded border px-1.5 py-0.5 text-xs hover:bg-accent" onClick={() => showPreview(l.id)}>
                      {l.display_name}
                    </button>
                  ))}
                </div>
              )}
              {preview && (
                <div className="mt-2 space-y-1 rounded bg-muted p-3 text-xs" data-preview>
                  <div className="font-semibold">{preview.subject}</div>
                  <div className="whitespace-pre-wrap">{preview.body}</div>
                </div>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          {template && (
            <Button
              variant="ghost"
              className="mr-auto text-destructive"
              onClick={async () => {
                if (!confirm(`Delete the template ${template.name}?`)) return;
                try {
                  unwrap(await api.DELETE("/api/v1/templates/{t_id}", { params: { path: { t_id: template.id } } }));
                  refresh();
                  onClose();
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            >
              Delete
            </Button>
          )}
          <Button disabled={!name.trim() || !subject.trim() || !body.trim()} onClick={save}>
            Save template
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- sending hours ----------
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function Sending() {
  const qc = useQueryClient();
  const s = useQuery({ queryKey: ["engage-settings"], queryFn: async () => unwrap(await api.GET("/api/v1/engage/settings")) });
  if (!s.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return <SendingForm key={JSON.stringify(s.data)} initial={s.data} onSaved={() => qc.invalidateQueries({ queryKey: ["engage-settings"] })} />;
}

function SendingForm({ initial, onSaved }: { initial: { from: string; to: string; days: number[]; daily_cap: number }; onSaved: () => void }) {
  const [v, setV] = useState(initial);
  return (
    <div className="max-w-md space-y-4 text-sm">
      <p className="text-muted-foreground">Emails go out only inside these hours (your company&apos;s time zone). Anything due outside waits for the next window.</p>
      <div className="flex items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="s-from">From</Label>
          <Input id="s-from" type="time" value={v.from} onChange={(e) => setV({ ...v, from: e.target.value })} className="h-8 w-32" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="s-to">Until</Label>
          <Input id="s-to" type="time" value={v.to === "24:00" ? "23:59" : v.to} onChange={(e) => setV({ ...v, to: e.target.value })} className="h-8 w-32" />
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {DAYS.map((d, i) => (
          <label key={d} className="flex items-center gap-1">
            <input type="checkbox" checked={v.days.includes(i)} onChange={(e) => setV({ ...v, days: e.target.checked ? [...v.days, i] : v.days.filter((x) => x !== i) })} /> {d}
          </label>
        ))}
      </div>
      <div className="space-y-1">
        <Label htmlFor="s-cap">Most emails a day</Label>
        <Input id="s-cap" type="number" min={1} value={v.daily_cap} onChange={(e) => setV({ ...v, daily_cap: Number(e.target.value) })} className="h-8 w-32" />
        <p className="text-xs text-muted-foreground">Start low with a new sending address and raise it over a few weeks.</p>
      </div>
      <Button
        onClick={async () => {
          try {
            unwrap(await api.PUT("/api/v1/engage/settings", { body: v }));
            toast.success("Sending hours saved");
            onSaved();
          } catch (e) {
            toast.error((e as Error).message);
          }
        }}
      >
        Save
      </Button>
    </div>
  );
}
