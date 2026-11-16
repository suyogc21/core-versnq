"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { SignInTable } from "@/components/app/sign-ins";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import type { components } from "@/lib/api/schema";

type Settings = components["schemas"]["SecuritySettingsOut"];

const IDLE = [
  { value: 0, label: "Off" },
  { value: 30, label: "30 minutes" },
  { value: 60, label: "1 hour" },
  { value: 120, label: "2 hours" },
  { value: 480, label: "8 hours" },
  { value: 1440, label: "24 hours" },
];

/** Settings → Security (finishing plan, batch 1): sign-in rules, everyone's sign-ins, signing
 * everyone out, and data protection (export everything). */
export default function SecurityPage() {
  const { can } = useAuth();
  const current = useQuery({ queryKey: ["security-settings"], queryFn: async () => unwrap(await api.GET("/api/v1/security/settings")) });
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Security" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-3xl space-y-6 p-4 sm:p-6">
          {current.data ? <Rules initial={current.data} /> : <p className="text-sm text-muted-foreground">Loading…</p>}
          <SignOutEveryone />
          {can("audit.read") && <SignIns />}
          <Export />
        </div>
      </div>
    </div>
  );
}

function Rules({ initial }: { initial: Settings }) {
  const qc = useQueryClient();
  const [idle, setIdle] = useState(initial.idle_minutes ?? 0);
  const [ips, setIps] = useState((initial.ip_allowlist ?? []).join("\n"));
  const [alert, setAlert] = useState(initial.alert_failed_sign_ins ?? true);
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    try {
      const list = ips.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
      unwrap(await api.PUT("/api/v1/security/settings", { body: { idle_minutes: idle, ip_allowlist: list, alert_failed_sign_ins: alert } }));
      qc.invalidateQueries({ queryKey: ["security-settings"] });
      toast.success("Saved");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="surface space-y-5 p-4 text-sm">
      <h2 className="font-semibold">Sign-in rules</h2>
      <div className="space-y-1.5">
        <Label htmlFor="idle">Sign out after no activity</Label>
        <select id="idle" className="h-9 rounded-md border bg-background px-2" value={idle} onChange={(e) => setIdle(Number(e.target.value))}>
          {IDLE.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <p className="text-muted-foreground">People who leave Core unused for this long must sign in again.</p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="ips">Only allow sign-in from these addresses</Label>
        <Textarea id="ips" rows={4} placeholder={"One per line, e.g. 203.0.113.10 or 203.0.113.0/24\nEmpty = from anywhere"} value={ips} onChange={(e) => setIps(e.target.value)} />
        <p className="text-muted-foreground">
          Your address now: <span className="font-mono">{initial.your_ip}</span>{" "}
          <button type="button" className="underline" onClick={() => setIps((v) => (v.trim() ? `${v.trim()}\n${initial.your_ip}` : initial.your_ip))}>
            Add it
          </button>
          . It must be in the list, so you can&apos;t lock yourself out. API keys, the WhatsApp extension and the phone app still work from anywhere.
        </p>
      </div>
      <label className="flex items-start gap-3">
        <Switch aria-label="Email after failed sign-ins" checked={alert} onCheckedChange={setAlert} />
        <span>
          <span className="font-medium">Email after 5 failed sign-ins</span>
          <span className="block text-muted-foreground">The person and the company&apos;s admins get an email when someone keeps getting a password wrong.</span>
        </span>
      </label>
      <Button onClick={save} disabled={saving}>
        Save
      </Button>
    </section>
  );
}

function SignOutEveryone() {
  const [sure, setSure] = useState(false);
  async function go() {
    try {
      unwrap(await api.POST("/api/v1/security/sign-out-everyone"));
      toast.success("Everyone is signed out, including you.");
      window.location.href = "/login";
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <section className="surface space-y-3 p-4 text-sm">
      <h2 className="font-semibold">Sign out everyone</h2>
      <p className="text-muted-foreground">For a lost laptop or a suspected break-in: everyone in the company, including you, is signed out at once and must sign in again.</p>
      {sure ? (
        <div className="flex gap-2">
          <Button variant="destructive" onClick={go}>
            Yes, sign out everyone
          </Button>
          <Button variant="ghost" onClick={() => setSure(false)}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button variant="outline" onClick={() => setSure(true)}>
          Sign out everyone…
        </Button>
      )}
    </section>
  );
}

function SignIns() {
  const [failed, setFailed] = useState(false);
  const rows = useQuery({
    queryKey: ["sign-ins", failed],
    queryFn: async () => unwrap(await api.GET("/api/v1/security/sign-ins", { params: { query: { failed, limit: 100 } } })),
  });
  return (
    <section className="surface space-y-3 p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">Sign-ins</h2>
        <label className="flex items-center gap-2 text-muted-foreground">
          <Switch aria-label="Only failed" checked={failed} onCheckedChange={setFailed} /> Only failed
        </label>
      </div>
      {rows.data ? <SignInTable rows={rows.data} showPerson /> : <p className="text-muted-foreground">Loading…</p>}
    </section>
  );
}

function Export() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["data-exports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/data-exports")),
    refetchInterval: (q) => ((q.state.data ?? []).some((e) => e.status === "queued" || e.status === "running") ? 3000 : false),
  });
  async function start() {
    try {
      unwrap(await api.POST("/api/v1/data-exports"));
      qc.invalidateQueries({ queryKey: ["data-exports"] });
      toast.success("Making your export. It's ready in a few minutes.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function download(id: string) {
    const r = await api.GET("/api/v1/data-exports/{export_id}/download", { params: { path: { export_id: id } }, parseAs: "blob" });
    if (!r.data) return toast.error("This export isn't ready or has expired");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(r.data as Blob);
    a.download = "versnq-core-export.zip";
    a.click();
  }
  return (
    <section className="surface space-y-3 p-4 text-sm">
      <h2 className="font-semibold">Export everything</h2>
      <p className="text-muted-foreground">
        All your company&apos;s records and files in one zip: leads, deals, customers, money, the timeline, messages, calls and uploads. Passwords and keys are never included. Each
        export can be downloaded for 7 days.
      </p>
      <Button variant="outline" onClick={start}>
        Make an export
      </Button>
      {(list.data ?? []).length > 0 && (
        <ul className="divide-y">
          {list.data!.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-2 py-2">
              <span>{new Date(e.created_at).toLocaleString()}</span>
              <span className="text-muted-foreground">
                {e.status === "ready" ? `${((e.size_bytes ?? 0) / 1e6).toFixed(1)} MB` : e.status === "expired" ? "Expired" : e.status === "failed" ? "Failed" : "Being made…"}
              </span>
              {e.status === "ready" && (
                <Button size="sm" variant="ghost" className="ms-auto" onClick={() => download(e.id)}>
                  Download
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-muted-foreground">
        To erase one person on their request, open the lead and use <span className="font-medium">Erase this person</span>.
      </p>
    </section>
  );
}
