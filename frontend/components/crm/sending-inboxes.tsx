"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { relative } from "@/lib/crm";
import { useUsers } from "@/lib/directory";
import { type ProviderKey, PROVIDERS } from "@/lib/mailboxes";

export type SendingInbox = components["schemas"]["InboxOut"];

const STATUS: Record<string, [string, "secondary" | "destructive" | "outline"]> = {
  active: ["Sending", "secondary"],
  paused: ["Paused", "outline"],
  error: ["Needs attention", "destructive"],
};

export function useSendingInboxes(enabled = true) {
  return useQuery({
    queryKey: ["sending-inboxes"],
    enabled,
    refetchInterval: 60_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/sending-inboxes")),
  });
}

/** Settings → Connected inboxes: the company's pool of sending inboxes (step O1, Decision log #44). */
export function SendingInboxes() {
  const list = useSendingInboxes();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [editing, setEditing] = useState<SendingInbox | null>(null);
  const rows = list.data ?? [];
  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      toast.success(done);
      await qc.invalidateQueries({ queryKey: ["sending-inboxes"] });
      await qc.invalidateQueries({ queryKey: ["mailbox"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const path = (id: string) => ({ params: { path: { mb_id: id } } });
  const sentToday = rows.reduce((n, r) => n + r.sent_today, 0);
  const capacity = rows.filter((r) => r.status === "active").reduce((n, r) => n + r.daily_limit, 0);
  return (
    <section className="space-y-3" data-sending-inboxes>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="font-semibold">Sending inboxes</h2>
          <p className="text-sm text-muted-foreground">
            Sequences send from these, taking turns: the lead owner&apos;s inbox first, never over an inbox&apos;s daily limit or inside its gap. An
            inbox whose emails bounce too often is paused for you.
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setImporting(true)}>
            Import CSV
          </Button>
          <Button size="sm" onClick={() => setAdding(true)}>
            Add inbox
          </Button>
        </div>
      </div>
      {rows.length > 0 && (
        <p className="text-sm" data-pool-capacity>
          <span className="font-medium tabular-nums">{sentToday}</span> sent today of <span className="font-medium tabular-nums">{capacity}</span> a day
          across {rows.length} inbox{rows.length === 1 ? "" : "es"}
        </p>
      )}
      <div className="divide-y surface">
        {rows.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">
            {list.isLoading ? "Loading…" : "No sending inboxes yet. Until you add one, sequences send from the company mailbox (Settings → Money)."}
          </p>
        )}
        {rows.map((m) => (
          <div key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm" data-inbox-row={m.email_address}>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="break-all font-medium">{m.email_address}</span>
                {m.from_name && <span className="text-muted-foreground">as {m.from_name}</span>}
                <Badge variant={STATUS[m.status]?.[1] ?? "outline"}>{STATUS[m.status]?.[0] ?? m.status}</Badge>
                {m.personal && <Badge variant="outline">{m.user_name}&apos;s own</Badge>}
              </div>
              <p className="text-xs text-muted-foreground">
                <span className="tabular-nums">
                  {m.sent_today}/{m.daily_limit}
                </span>{" "}
                today · {m.min_gap_minutes} min gap · last 7 days: {m.sent_7d} sent, {m.replies_7d} replies, {m.bounces_7d} bounced
                {!m.personal && m.user_name && ` · ${m.user_name}'s`} · checked {m.last_sync_at ? relative(m.last_sync_at) : "not yet"}
              </p>
              {(m.paused_reason || m.last_error) && <p className="text-xs text-destructive">{m.paused_reason ?? m.last_error}</p>}
            </div>
            <div className="ms-auto flex flex-wrap gap-1">
              <Button size="sm" variant="ghost" onClick={() => setEditing(m)}>
                Edit
              </Button>
              {m.status === "active" && (
                <Button size="sm" variant="ghost" onClick={() => act(async () => unwrap(await api.POST("/api/v1/sending-inboxes/{mb_id}/pause", path(m.id))), "Paused")}>
                  Pause
                </Button>
              )}
              {m.status === "paused" && (
                <Button size="sm" variant="ghost" onClick={() => act(async () => unwrap(await api.POST("/api/v1/sending-inboxes/{mb_id}/resume", path(m.id))), "Sending again")}>
                  Resume
                </Button>
              )}
              {m.status === "error" && (
                <Button size="sm" variant="ghost" onClick={() => act(async () => unwrap(await api.POST("/api/v1/sending-inboxes/{mb_id}/check", path(m.id))), "Connected again")}>
                  Check again
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  confirm(
                    m.personal
                      ? `Stop sending sequences from ${m.email_address}? It stays connected as ${m.user_name}'s own mailbox.`
                      : `Remove ${m.email_address}? It is disconnected and its password forgotten. Emails already sent stay on the leads.`,
                  ) && act(async () => unwrap(await api.DELETE("/api/v1/sending-inboxes/{mb_id}", path(m.id))), "Removed")
                }
              >
                Remove
              </Button>
            </div>
          </div>
        ))}
      </div>
      {adding && <AddInbox onClose={() => setAdding(false)} onDone={() => qc.invalidateQueries({ queryKey: ["sending-inboxes"] })} />}
      {importing && <ImportInboxes onClose={() => setImporting(false)} onDone={() => qc.invalidateQueries({ queryKey: ["sending-inboxes"] })} />}
      {editing && <EditInbox inbox={editing} onClose={() => setEditing(null)} onDone={() => qc.invalidateQueries({ queryKey: ["sending-inboxes"] })} />}
    </section>
  );
}

function OwnerSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const users = useUsers();
  return (
    <NativeSelect id="si-owner" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">No one (a shared inbox)</option>
      {(users.data ?? [])
        .filter((u) => u.status === "active")
        .map((u) => (
          <option key={u.id} value={u.id}>
            {u.name}
          </option>
        ))}
    </NativeSelect>
  );
}

function AddInbox({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [provider, setProvider] = useState<ProviderKey>("gmail");
  const [f, setF] = useState({ email: "", password: "", fromName: "", owner: "", imap: "", smtp: "", limit: "30", gap: "6", signature: "" });
  const [busy, setBusy] = useState(false);
  const p = PROVIDERS[provider];
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add a sending inbox</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="si-provider">Provider</Label>
            <NativeSelect id="si-provider" value={provider} onChange={(e) => setProvider(e.target.value as ProviderKey)}>
              {(Object.keys(PROVIDERS) as ProviderKey[]).map((k) => (
                <option key={k} value={k}>
                  {PROVIDERS[k].label}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-1">
            <Label htmlFor="si-email">Email address</Label>
            <Input id="si-email" value={f.email} onChange={set("email")} autoComplete="off" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="si-password">App password</Label>
            <Input id="si-password" type="password" value={f.password} onChange={set("password")} autoComplete="new-password" />
          </div>
          {provider === "other" && (
            <>
              <div className="space-y-1">
                <Label htmlFor="si-imap">IMAP server</Label>
                <Input id="si-imap" value={f.imap} onChange={set("imap")} placeholder="imap.example.com" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="si-smtp">SMTP server</Label>
                <Input id="si-smtp" value={f.smtp} onChange={set("smtp")} placeholder="smtp.example.com" />
              </div>
            </>
          )}
          <div className="space-y-1">
            <Label htmlFor="si-from">Sender name</Label>
            <Input id="si-from" value={f.fromName} onChange={set("fromName")} placeholder="Riya from Brightlane" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="si-owner">Whose inbox</Label>
            <OwnerSelect value={f.owner} onChange={(v) => setF({ ...f, owner: v })} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="si-limit">Emails a day</Label>
            <Input id="si-limit" inputMode="numeric" value={f.limit} onChange={set("limit")} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="si-gap">Minutes between emails</Label>
            <Input id="si-gap" inputMode="numeric" value={f.gap} onChange={set("gap")} />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="si-signature">Signature (optional)</Label>
            <Textarea id="si-signature" rows={3} value={f.signature} onChange={set("signature")} />
          </div>
          <p className="text-xs text-muted-foreground sm:col-span-2">
            Use an app password (Gmail / Google Workspace: 2-Step Verification → App passwords). Core signs in to the inbox before saving it. Start new
            inboxes low (around 30 a day) and raise the limit once they are warmed up.
          </p>
        </div>
        <DialogFooter>
          <Button
            disabled={!f.email.trim() || !f.password || busy}
            onClick={async () => {
              setBusy(true);
              try {
                unwrap(
                  await api.POST("/api/v1/sending-inboxes", {
                    body: {
                      email_address: f.email.trim(),
                      password: f.password,
                      imap_host: provider === "other" ? f.imap.trim() : p.imap_host,
                      imap_port: p.imap_port,
                      smtp_host: provider === "other" ? f.smtp.trim() : p.smtp_host,
                      smtp_port: p.smtp_port,
                      smtp_security: p.smtp_security,
                      from_name: f.fromName.trim() || null,
                      user_id: f.owner || null,
                      daily_limit: Number(f.limit) || 30,
                      min_gap_minutes: Number(f.gap) || 0,
                      signature: f.signature.trim() || null,
                    },
                  }),
                );
                toast.success("Inbox added");
                onDone();
                onClose();
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Signing in…" : "Add inbox"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const SAMPLE = "email,password,provider,from_name,owner_email,daily_limit\nriya@outreach.example,abcd efgh ijkl mnop,gmail,Riya from Brightlane,riya@brightlane.example,30";

function ImportInboxes({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [csv, setCsv] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<components["schemas"]["ImportRow"][] | null>(null);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Import sending inboxes</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p className="text-muted-foreground">
            One inbox per line, with a header row. Needed: <code>email</code>, <code>password</code>, and either <code>provider</code> (gmail, zoho_in,
            zoho) or <code>imap_host</code> + <code>smtp_host</code>. Optional: <code>from_name</code>, <code>owner_email</code>,{" "}
            <code>daily_limit</code>, <code>min_gap_minutes</code>, <code>username</code>, ports, <code>smtp_security</code>. Each inbox is signed in to
            before it is saved.
          </p>
          <input
            type="file"
            accept=".csv,text/csv"
            aria-label="CSV file"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (file) setCsv(await file.text());
            }}
          />
          <Textarea aria-label="CSV" rows={7} value={csv} onChange={(e) => setCsv(e.target.value)} placeholder={SAMPLE} className="font-mono text-xs" />
          {report && (
            <div className="max-h-48 divide-y overflow-auto surface" data-import-report>
              {report.map((r) => (
                <p key={r.row} className="px-3 py-1.5 text-xs">
                  Row {r.row} · {r.email_address || "(no email)"} · {r.ok ? <span className="text-emerald-600">added</span> : <span className="text-destructive">{r.error}</span>}
                </p>
              ))}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            disabled={!csv.trim() || busy}
            onClick={async () => {
              setBusy(true);
              try {
                const r = unwrap(await api.POST("/api/v1/sending-inboxes/import", { body: { csv } }));
                setReport(r);
                const ok = r.filter((x) => x.ok).length;
                toast.success(`${ok} of ${r.length} inboxes added`);
                onDone();
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Signing in to each inbox…" : "Import"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EditInbox({ inbox, onClose, onDone }: { inbox: SendingInbox; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({
    fromName: inbox.from_name ?? "",
    owner: inbox.user_id ?? "",
    limit: String(inbox.daily_limit),
    gap: String(inbox.min_gap_minutes),
    signature: inbox.signature ?? "",
    password: "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="break-all">{inbox.email_address}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="ei-from">Sender name</Label>
            <Input id="ei-from" value={f.fromName} onChange={set("fromName")} />
          </div>
          {!inbox.personal && (
            <div className="space-y-1">
              <Label htmlFor="si-owner">Whose inbox</Label>
              <OwnerSelect value={f.owner} onChange={(v) => setF({ ...f, owner: v })} />
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="ei-limit">Emails a day</Label>
            <Input id="ei-limit" inputMode="numeric" value={f.limit} onChange={set("limit")} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ei-gap">Minutes between emails</Label>
            <Input id="ei-gap" inputMode="numeric" value={f.gap} onChange={set("gap")} />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="ei-signature">Signature</Label>
            <Textarea id="ei-signature" rows={3} value={f.signature} onChange={set("signature")} />
          </div>
          {!inbox.personal && (
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="ei-password">New app password (only to change it)</Label>
              <Input id="ei-password" type="password" value={f.password} onChange={set("password")} autoComplete="new-password" />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                unwrap(
                  await api.PATCH("/api/v1/sending-inboxes/{mb_id}", {
                    params: { path: { mb_id: inbox.id } },
                    body: {
                      from_name: f.fromName.trim() || null,
                      signature: f.signature.trim() || null,
                      daily_limit: Number(f.limit) || inbox.daily_limit,
                      min_gap_minutes: Number(f.gap) >= 0 ? Number(f.gap) : inbox.min_gap_minutes,
                      ...(inbox.personal ? {} : { user_id: f.owner || null }),
                      ...(f.password ? { password: f.password } : {}),
                    },
                  }),
                );
                toast.success("Saved");
                onDone();
                onClose();
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
