"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Plus, Trash2 } from "lucide-react";
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
import { relative } from "@/lib/crm";
import { useRoles } from "@/lib/directory";
import { cn } from "@/lib/utils";

type Tab = "keys" | "webhooks" | "logs";
type Endpoint = components["schemas"]["EndpointOut"];
type Delivery = components["schemas"]["DeliveryOut"];

const KEYS = ["api-keys", "webhooks", "deliveries", "api-log", "archives"];

function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      for (const k of KEYS) qc.invalidateQueries({ queryKey: [k] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast.success("Copied"));
const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export default function DevelopersPage() {
  const [tab, setTab] = useState<Tab>("keys");
  const tabs: [Tab, string][] = [
    ["keys", "API keys"],
    ["webhooks", "Webhooks"],
    ["logs", "Logs"],
  ];
  return (
    <>
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Developers" />
      <div className="mx-auto w-full max-w-3xl p-4 sm:p-8">
        <p className="mb-4 text-muted-foreground">Connect your website, other tools and AI to your records, and see every call and message between them.</p>
        <div className="mb-6 flex gap-4 overflow-x-auto border-b text-sm" role="tablist">
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
        {tab === "keys" && <Keys />}
        {tab === "webhooks" && <Webhooks />}
        {tab === "logs" && <Logs />}
      </div>
    </>
  );
}

// ---------- API keys ----------
function useKeys() {
  return useQuery({ queryKey: ["api-keys"], queryFn: async () => unwrap(await api.GET("/api/v1/integrations/keys")) });
}

function Keys() {
  const list = useKeys();
  const roles = useRoles();
  const save = useSave();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [roleId, setRoleId] = useState("");
  const [shown, setShown] = useState<{ name: string; key: string } | null>(null);
  const choosable = (roles.data ?? []).filter((r) => r.key !== "owner");
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        A key lets another system use your records through the API. It can do exactly what its role allows, and makes up to 300 requests a minute.
      </p>
      <div className="divide-y surface">
        {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">No keys yet.</p>}
        {(list.data ?? []).map((k) => (
          <div key={k.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm" data-key={k.name}>
            <span className={cn("font-medium", k.revoked_at && "text-muted-foreground line-through")}>{k.name}</span>
            <span className="text-xs text-muted-foreground">
              {k.role_name} · {k.prefix}… · {k.revoked_at ? `revoked ${relative(k.revoked_at)}` : k.last_used_at ? `last used ${relative(k.last_used_at)}` : "never used"}
            </span>
            {!k.revoked_at && (
              <Button
                size="sm"
                variant="ghost"
                className="ms-auto"
                onClick={() =>
                  confirm(`Revoke ${k.name}? Anything using it stops working at once.`) &&
                  save(async () => unwrap(await api.POST("/api/v1/integrations/keys/{key_id}/revoke", { params: { path: { key_id: k.id } } })), "Revoked")
                }
              >
                Revoke
              </Button>
            )}
          </div>
        ))}
      </div>
      <Button
        onClick={() => {
          setName("");
          setRoleId(choosable.find((r) => r.key === "admin")?.id ?? "");
          setAdding(true);
        }}
      >
        <Plus /> New key
      </Button>
      {adding && (
        <Dialog open onOpenChange={(o) => !o && setAdding(false)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>New API key</DialogTitle>
            </DialogHeader>
            <div className="space-y-3 text-sm">
              <div className="space-y-1">
                <Label htmlFor="key-name">Name</Label>
                <Input id="key-name" placeholder="Website, ACE, Zapier…" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="key-role">Role</Label>
                <NativeSelect id="key-role" value={roleId} onChange={(e) => setRoleId(e.target.value)}>
                  <option value="">Choose…</option>
                  {choosable.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </NativeSelect>
                <p className="text-xs text-muted-foreground">The key sees and does what this role may. Give it the narrowest role that works.</p>
              </div>
            </div>
            <DialogFooter>
              <Button
                disabled={!name.trim() || !roleId}
                onClick={() =>
                  save(async () => {
                    const r = unwrap(await api.POST("/api/v1/integrations/keys", { body: { name, role_id: roleId } }));
                    setAdding(false);
                    setShown({ name: r.name, key: r.key });
                  })
                }
              >
                Create key
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
      {shown && <SecretDialog title={`${shown.name}: your API key`} value={shown.key} label="API key" onClose={() => setShown(null)} usage={<KeyUsage secret={shown.key} />} />}
    </div>
  );
}

function KeyUsage({ secret }: { secret: string }) {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const sample = `curl ${origin}/api/v1/leads/upsert \\
  -H "Authorization: Bearer ${secret}" \\
  -H "Content-Type: application/json" \\
  -d '{"phones": ["98765 43210"], "first_name": "Rahul", "source": "Website"}'`;
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">Send it in the Authorization header. For example, to add a lead (or find them if they already exist):</p>
      <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">{sample}</pre>
    </div>
  );
}

function SecretDialog({ title, value, label, onClose, usage }: { title: string; value: string; label: string; onClose: () => void; usage?: React.ReactNode }) {
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 text-sm">
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs">Copy it now and keep it somewhere safe: it is shown only once.</p>
          <div className="flex gap-2">
            <Input readOnly value={value} aria-label={label} className="font-mono text-xs" />
            <Button type="button" variant="outline" onClick={() => copy(value)}>
              <Copy /> Copy
            </Button>
          </div>
          {usage}
        </div>
        <DialogFooter>
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- webhooks ----------
function useWebhooks() {
  return useQuery({ queryKey: ["webhooks"], queryFn: async () => unwrap(await api.GET("/api/v1/integrations/webhooks")) });
}

function Webhooks() {
  const list = useWebhooks();
  const save = useSave();
  const [editing, setEditing] = useState<Endpoint | "new" | null>(null);
  const [secret, setSecret] = useState<{ name: string; secret: string } | null>(null);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        When something happens here (a lead is created, a deal is won, a payment arrives), we send a signed message to your address straight away.
        If your server is down we try again for about two days.
      </p>
      <div className="divide-y surface">
        {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">No webhooks yet.</p>}
        {(list.data ?? []).map((w) => (
          <div key={w.id} className="space-y-1 px-3 py-2.5 text-sm" data-webhook={w.name}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <Switch
                aria-label={`${w.name} on`}
                checked={w.is_active}
                onCheckedChange={(on) =>
                  save(async () => unwrap(await api.PATCH("/api/v1/integrations/webhooks/{ep_id}", { params: { path: { ep_id: w.id } }, body: { is_active: on } })))
                }
              />
              <button className="font-medium hover:underline" onClick={() => setEditing(w)}>
                {w.name}
              </button>
              <span className="min-w-0 truncate text-xs text-muted-foreground">{w.url}</span>
              <span className="ms-auto flex gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    save(async () => {
                      const d = unwrap(await api.POST("/api/v1/integrations/webhooks/{ep_id}/test", { params: { path: { ep_id: w.id } } }));
                      if (d.status === "ok") toast.success(`Test delivered (${d.last_status_code})`);
                      else toast.error(`Test failed: ${d.last_error}`);
                    })
                  }
                >
                  Send test
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    save(async () => {
                      const r = unwrap(await api.GET("/api/v1/integrations/webhooks/{ep_id}/secret", { params: { path: { ep_id: w.id } } }));
                      setSecret({ name: w.name, secret: r.secret });
                    })
                  }
                >
                  Signing secret
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Delete ${w.name}`}
                  onClick={() =>
                    confirm(`Delete the webhook ${w.name}? Its log goes with it.`) &&
                    save(async () => unwrap(await api.DELETE("/api/v1/integrations/webhooks/{ep_id}", { params: { path: { ep_id: w.id } } })), "Deleted")
                  }
                >
                  <Trash2 />
                </Button>
              </span>
            </div>
            <div className="text-xs text-muted-foreground">
              {w.events.includes("*") ? "Every event" : w.events.join(", ")}
              {w.switched_off_reason && !w.is_active && <span className="ms-2 text-destructive">{w.switched_off_reason}</span>}
              {w.failing_since && w.is_active && <span className="ms-2 text-amber-700 dark:text-amber-300">Failing since {when(w.failing_since)}</span>}
            </div>
          </div>
        ))}
      </div>
      <Button onClick={() => setEditing("new")}>
        <Plus /> New webhook
      </Button>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">How to check our signature</summary>
        <pre className="mt-2 overflow-x-auto rounded-lg bg-muted p-3 text-xs">{`// Node.js: reject the message unless this is true
const crypto = require("crypto");
const ts = req.headers["x-versnq-timestamp"];
const expected = "sha256=" + crypto.createHmac("sha256", SECRET).update(ts + "." + rawBody).digest("hex");
const ok = crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(req.headers["x-versnq-signature"]))
  && Math.abs(Date.now() / 1000 - Number(ts)) < 300;
// The body's "id" is the event id: if you have seen it before, ignore the repeat.`}</pre>
      </details>
      {editing && (
        <WebhookDialog
          hook={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onCreated={(name, s) => setSecret({ name, secret: s })}
        />
      )}
      {secret && <SecretDialog title={`${secret.name}: signing secret`} value={secret.secret} label="Signing secret" onClose={() => setSecret(null)} />}
    </div>
  );
}

function WebhookDialog({ hook, onClose, onCreated }: { hook: Endpoint | null; onClose: () => void; onCreated: (name: string, secret: string) => void }) {
  const types = useQuery({ queryKey: ["event-types"], queryFn: async () => unwrap(await api.GET("/api/v1/integrations/event-types")) });
  const save = useSave();
  const [name, setName] = useState(hook?.name ?? "");
  const [url, setUrl] = useState(hook?.url ?? "https://");
  const [all, setAll] = useState(hook ? hook.events.includes("*") : false);
  const [events, setEvents] = useState<string[]>(hook && !hook.events.includes("*") ? hook.events : []);
  const toggle = (t: string) => setEvents((e) => (e.includes(t) ? e.filter((x) => x !== t) : [...e, t]));
  const picked = all ? ["*"] : events;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{hook ? hook.name : "New webhook"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="space-y-1">
            <Label htmlFor="hook-name">Name</Label>
            <Input id="hook-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Accounting sync" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="hook-url">Address</Label>
            <Input id="hook-url" value={url} onChange={(e) => setUrl(e.target.value)} className="font-mono text-xs" />
            <p className="text-xs text-muted-foreground">Must start with https:// and be on the public internet.</p>
          </div>
          <div className="space-y-2">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Every event
            </label>
            {!all && (
              <div className="grid gap-1 sm:grid-cols-2" aria-label="Events">
                {(types.data ?? []).map((t) => (
                  <label key={t.type} className="flex items-center gap-2 font-mono text-xs">
                    <input type="checkbox" checked={events.includes(t.type)} onChange={() => toggle(t.type)} aria-label={t.type} /> {t.type}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button
            disabled={!name.trim() || !url.trim() || picked.length === 0}
            onClick={() =>
              save(async () => {
                if (hook) {
                  unwrap(await api.PATCH("/api/v1/integrations/webhooks/{ep_id}", { params: { path: { ep_id: hook.id } }, body: { name, url, events: picked } }));
                } else {
                  const r = unwrap(await api.POST("/api/v1/integrations/webhooks", { body: { name, url, events: picked, is_active: true } }));
                  onCreated(r.name, r.secret);
                }
                onClose();
              }, hook ? "Saved" : undefined)
            }
          >
            {hook ? "Save" : "Create webhook"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- logs ----------
function Logs() {
  const [which, setWhich] = useState<"api" | "webhooks" | "archive">("api");
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">The last 30 days are here. Older entries are kept in monthly archive files for 12 months.</p>
      <NativeSelect aria-label="Which log" className="h-8 w-48" value={which} onChange={(e) => setWhich(e.target.value as typeof which)}>
        <option value="api">API calls</option>
        <option value="webhooks">Webhook messages</option>
        <option value="archive">Archives</option>
      </NativeSelect>
      {which === "api" && <ApiLog />}
      {which === "webhooks" && <WebhookLog />}
      {which === "archive" && <Archives />}
    </div>
  );
}

const tone = (code: number | null | undefined) => (code && code < 300 ? "text-emerald-700 dark:text-emerald-300" : "text-destructive");

function ApiLog() {
  const keys = useKeys();
  const [keyId, setKeyId] = useState("");
  const [errors, setErrors] = useState(false);
  const log = useQuery({
    queryKey: ["api-log", keyId, errors],
    queryFn: async () => unwrap(await api.GET("/api/v1/integrations/api-log", { params: { query: { key_id: keyId || undefined, errors_only: errors, limit: 100 } } })),
  });
  const keyName = (id: string) => keys.data?.find((k) => k.id === id)?.name ?? "—";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <NativeSelect aria-label="Key" className="h-8 w-48" value={keyId} onChange={(e) => setKeyId(e.target.value)}>
          <option value="">All keys</option>
          {(keys.data ?? []).map((k) => (
            <option key={k.id} value={k.id}>
              {k.name}
            </option>
          ))}
        </NativeSelect>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={errors} onChange={(e) => setErrors(e.target.checked)} /> Only errors
        </label>
      </div>
      <div className="divide-y surface" data-api-log>
        {(log.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">{log.isLoading ? "Loading…" : "Nothing yet."}</p>}
        {(log.data ?? []).map((r) => (
          <div key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-xs">
            <span className="text-muted-foreground tabular-nums">{when(r.at)}</span>
            <span className="font-medium">{keyName(r.key_id)}</span>
            <span className="min-w-0 truncate font-mono">
              {r.method} {r.path}
            </span>
            <span className={cn("ms-auto font-medium tabular-nums", tone(r.status))}>{r.status}</span>
            <span className="text-muted-foreground tabular-nums">{r.duration_ms} ms</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const STATUS: Record<string, string> = { ok: "Delivered", pending: "Will retry", failed: "Failed" };

function WebhookLog() {
  const hooks = useWebhooks();
  const [epId, setEpId] = useState("");
  const [open, setOpen] = useState<Delivery | null>(null);
  const log = useQuery({
    queryKey: ["deliveries", epId],
    queryFn: async () => unwrap(await api.GET("/api/v1/integrations/deliveries", { params: { query: { endpoint_id: epId || undefined, limit: 100 } } })),
  });
  const hookName = (id: string) => hooks.data?.find((h) => h.id === id)?.name ?? "—";
  return (
    <div className="space-y-2">
      <NativeSelect aria-label="Webhook" className="h-8 w-48" value={epId} onChange={(e) => setEpId(e.target.value)}>
        <option value="">All webhooks</option>
        {(hooks.data ?? []).map((h) => (
          <option key={h.id} value={h.id}>
            {h.name}
          </option>
        ))}
      </NativeSelect>
      <div className="divide-y surface" data-webhook-log>
        {(log.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">{log.isLoading ? "Loading…" : "Nothing yet."}</p>}
        {(log.data ?? []).map((d) => (
          <button key={d.id} className="flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-start text-xs hover:bg-muted/50" onClick={() => setOpen(d)} data-delivery={d.event_type}>
            <span className="text-muted-foreground tabular-nums">{when(d.created_at)}</span>
            <span className="font-mono">{d.event_type}</span>
            <span className="text-muted-foreground">→ {hookName(d.endpoint_id)}</span>
            <span className={cn("ms-auto font-medium", d.status === "ok" ? tone(200) : d.status === "failed" ? tone(500) : "text-amber-700 dark:text-amber-300")}>
              {STATUS[d.status]}
              {d.attempts > 1 ? ` · ${d.attempts} tries` : ""}
            </span>
          </button>
        ))}
      </div>
      {open && <DeliveryDialog id={open.id} onClose={() => setOpen(null)} />}
    </div>
  );
}

function DeliveryDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const save = useSave();
  const d = useQuery({
    queryKey: ["deliveries", "one", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/integrations/deliveries/{d_id}", { params: { path: { d_id: id } } })),
  });
  const x = d.data;
  let pretty = x?.body ?? "";
  try {
    pretty = JSON.stringify(JSON.parse(pretty), null, 2);
  } catch {}
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{x?.event_type ?? "Message"}</DialogTitle>
        </DialogHeader>
        {x && (
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-1 text-xs">
              <span className="text-muted-foreground">Status</span>
              <span>{STATUS[x.status]}</span>
              <span className="text-muted-foreground">Tries</span>
              <span>{x.attempts}</span>
              <span className="text-muted-foreground">Last answer</span>
              <span>{x.last_status_code ?? "—"}{x.last_error ? ` · ${x.last_error}` : ""}</span>
              {x.next_try_at && x.status === "pending" && (
                <>
                  <span className="text-muted-foreground">Next try</span>
                  <span>{when(x.next_try_at)}</span>
                </>
              )}
            </div>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">What we sent</div>
              <pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs" data-payload>{pretty}</pre>
            </div>
            {x.response_snippet && (
              <div>
                <div className="mb-1 text-xs text-muted-foreground">What they answered</div>
                <pre className="max-h-40 overflow-auto rounded-lg bg-muted p-3 text-xs">{x.response_snippet}</pre>
              </div>
            )}
          </div>
        )}
        <DialogFooter>
          {x && x.event_type !== "ping" && (
            <Button
              variant="outline"
              onClick={() =>
                save(async () => {
                  unwrap(await api.POST("/api/v1/integrations/deliveries/{d_id}/resend", { params: { path: { d_id: id } } }));
                  onClose();
                }, "Sending again")
              }
            >
              Resend
            </Button>
          )}
          <Button onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Archives() {
  const list = useQuery({ queryKey: ["archives"], queryFn: async () => unwrap(await api.GET("/api/v1/integrations/archives")) });
  const download = async (name: string) => {
    const res = await api.GET("/api/v1/integrations/archives/{name}", { params: { path: { name } }, parseAs: "blob" });
    if (res.error || !res.data) return toast.error("Could not download");
    const href = URL.createObjectURL(res.data as Blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(href), 30_000);
  };
  return (
    <div className="divide-y surface">
      {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">No archives yet. Entries move here after 30 days.</p>}
      {(list.data ?? []).map((a) => (
        <div key={a.name} className="flex items-center gap-3 px-3 py-2 text-sm">
          <span className="font-medium">{a.kind === "api" ? "API calls" : "Webhook messages"}</span>
          <span className="text-muted-foreground">{a.month}</span>
          <span className="text-xs text-muted-foreground">{Math.max(1, Math.round(a.size / 1024))} KB</span>
          <Button size="sm" variant="ghost" className="ms-auto" onClick={() => download(a.name)}>
            Download
          </Button>
        </div>
      ))}
    </div>
  );
}
