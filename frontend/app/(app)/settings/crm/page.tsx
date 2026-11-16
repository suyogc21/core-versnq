"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type Conn = components["schemas"]["CrmConnectionOut"];
type Provider = "leadsquared" | "custom";

/** Settings → Connected CRM (docs/plans/crm-connectors-plan.md): calls and WhatsApp messages go
 * to the company's own CRM, on the right lead. */
export default function CrmSettingsPage() {
  const conn = useQuery({
    queryKey: ["crm-connection"],
    queryFn: async () => unwrap(await api.GET("/api/v1/crm-connection")),
  });
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        back={{ href: "/settings", label: "Settings" }}
        title="Connected CRM"
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-2xl space-y-6 p-4 sm:p-6">
          <p className="text-sm text-muted-foreground">
            Keep working in your own CRM: every call (from the phone app or
            Twilio) and every WhatsApp message also goes there, on the right
            lead.
          </p>
          {conn.data ? (
            <ConnectionForm
              key={`${conn.data.provider ?? "none"}`}
              conn={conn.data}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Loading…</p>
          )}
          {conn.data?.connected && <TestAndSends />}
        </div>
      </div>
    </div>
  );
}

function ConnectionForm({ conn }: { conn: Conn }) {
  const qc = useQueryClient();
  const [secret, setSecret] = useState<string | null>(null);
  const [v, setV] = useState({
    provider: (conn.provider as Provider) ?? "leadsquared",
    host: conn.host ?? "",
    access_key: "",
    secret_key: "",
    lookup_url: conn.lookup_url ?? "",
    create_url: conn.create_url ?? "",
    activity_url: conn.activity_url ?? "",
    activity_event: conn.activity_event ? String(conn.activity_event) : "",
    send_calls: conn.send_calls,
    send_whatsapp: conn.send_whatsapp,
    create_leads: conn.create_leads,
    is_active: conn.connected ? conn.is_active : true,
  });
  const set =
    (k: keyof typeof v) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setV({ ...v, [k]: e.target.value });
  const tick =
    (k: "send_calls" | "send_whatsapp" | "create_leads" | "is_active") =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setV({ ...v, [k]: e.target.checked });

  async function save() {
    try {
      const lsq = v.provider === "leadsquared";
      const out = unwrap(
        await api.PUT("/api/v1/crm-connection", {
          body: {
            provider: v.provider,
            host: lsq ? v.host : null,
            access_key: lsq ? v.access_key || null : null,
            secret_key: lsq ? v.secret_key || null : null,
            lookup_url: lsq ? null : v.lookup_url,
            create_url: lsq ? null : v.create_url,
            activity_url: lsq ? null : v.activity_url,
            activity_event:
              lsq && v.activity_event ? Number(v.activity_event) : null,
            send_calls: v.send_calls,
            send_whatsapp: v.send_whatsapp,
            create_leads: v.create_leads,
            is_active: v.is_active,
          },
        }),
      );
      if (out.signing_secret) setSecret(out.signing_secret);
      qc.invalidateQueries({ queryKey: ["crm-connection"] });
      toast.success("Saved");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function disconnect() {
    if (!confirm("Disconnect the CRM? Nothing more is sent to it.")) return;
    try {
      unwrap(await api.DELETE("/api/v1/crm-connection"));
      qc.invalidateQueries({ queryKey: ["crm-connection"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <section className="surface space-y-4 p-4 text-sm">
      {conn.last_error && (
        <p className="text-destructive">Last problem: {conn.last_error}</p>
      )}
      <div className="space-y-1">
        <Label htmlFor="crm-provider">Your CRM</Label>
        <NativeSelect
          id="crm-provider"
          value={v.provider}
          disabled={conn.connected}
          onChange={set("provider")}
        >
          <option value="leadsquared">LeadSquared</option>
          <option value="custom">
            Another CRM (your own addresses, or Zapier / Make)
          </option>
        </NativeSelect>
      </div>
      {v.provider === "leadsquared" ? (
        <>
          <div className="space-y-1">
            <Label htmlFor="crm-host">Region</Label>
            <NativeSelect id="crm-host" value={v.host} onChange={set("host")}>
              <option value="">Choose…</option>
              {Object.entries(conn.regions).map(([host, name]) => (
                <option key={host} value={host}>
                  {name} ({host})
                </option>
              ))}
            </NativeSelect>
            <p className="text-xs text-muted-foreground">
              In LeadSquared: My Account → Settings → API and Webhooks shows
              your host and keys.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="crm-access">Access key</Label>
              <Input
                id="crm-access"
                type="password"
                placeholder={conn.key_hint ? `Saved ${conn.key_hint}` : ""}
                value={v.access_key}
                onChange={set("access_key")}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="crm-secret">Secret key</Label>
              <Input
                id="crm-secret"
                type="password"
                placeholder={
                  conn.connected ? "Saved (leave empty to keep)" : ""
                }
                value={v.secret_key}
                onChange={set("secret_key")}
              />
            </div>
          </div>
          {conn.connected && (
            <div className="space-y-1">
              <Label htmlFor="crm-event">WhatsApp activity code</Label>
              <Input
                id="crm-event"
                inputMode="numeric"
                className="max-w-40"
                value={v.activity_event}
                onChange={set("activity_event")}
              />
              <p className="text-xs text-muted-foreground">
                Core made the activity type &quot;WhatsApp (Versnq)&quot; in
                LeadSquared; change the code only if LeadSquared shows another.
              </p>
            </div>
          )}
        </>
      ) : (
        <>
          {(["lookup_url", "create_url", "activity_url"] as const).map((k) => (
            <div key={k} className="space-y-1">
              <Label htmlFor={k}>
                {
                  {
                    lookup_url: "Find a lead by phone",
                    create_url: "Create a lead",
                    activity_url: "Log a call or message",
                  }[k]
                }
              </Label>
              <Input
                id={k}
                placeholder="https://…"
                value={v[k]}
                onChange={set(k)}
              />
            </div>
          ))}
          <p className="text-xs text-muted-foreground">
            Core sends JSON to these addresses, signed with X-Versnq-Signature
            like its webhooks. Find: {"{phone}"} → {"{lead_id}"}; create:{" "}
            {"{phone, name, email, owner_email}"} → {"{lead_id}"}; log:{" "}
            {"{lead_id, type, …}"}.
          </p>
        </>
      )}
      <div className="space-y-1.5">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={v.send_calls}
            onChange={tick("send_calls")}
          />{" "}
          Send calls
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={v.send_whatsapp}
            onChange={tick("send_whatsapp")}
          />{" "}
          Send WhatsApp messages
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={v.create_leads}
            onChange={tick("create_leads")}
          />{" "}
          Create the lead in the CRM when it isn&apos;t there yet
        </label>
        {conn.connected && (
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={v.is_active}
              onChange={tick("is_active")}
            />{" "}
            On
          </label>
        )}
      </div>
      {secret && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
          <p className="font-medium">
            Signing secret (shown once; keep it in your CRM to check requests)
          </p>
          <code className="break-all">{secret}</code>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button onClick={save}>{conn.connected ? "Save" : "Connect"}</Button>
        {conn.connected && (
          <Button variant="outline" onClick={disconnect}>
            Disconnect
          </Button>
        )}
      </div>
    </section>
  );
}

function TestAndSends() {
  const qc = useQueryClient();
  const [phone, setPhone] = useState("");
  const syncs = useQuery({
    queryKey: ["crm-syncs"],
    queryFn: async () => unwrap(await api.GET("/api/v1/crm-connection/syncs")),
    refetchInterval: 15_000,
  });

  async function test() {
    try {
      const r = unwrap(
        await api.POST("/api/v1/crm-connection/test", { body: { phone } }),
      );
      if (!r.ok) toast.error(r.error ?? "It didn't work");
      else
        toast.success(
          r.lead_id
            ? `Connected: that number is lead ${r.lead_id}`
            : "Connected: no lead with that number",
        );
      qc.invalidateQueries({ queryKey: ["crm-connection"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function retry(id: string) {
    try {
      unwrap(
        await api.POST("/api/v1/crm-connection/syncs/{sync_id}/retry", {
          params: { path: { sync_id: id } },
        }),
      );
      qc.invalidateQueries({ queryKey: ["crm-syncs"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <>
      <section className="surface space-y-2 p-4 text-sm">
        <h2 className="font-semibold">Test the connection</h2>
        <div className="flex gap-2">
          <Input
            placeholder="A phone number"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className="max-w-60"
          />
          <Button variant="outline" onClick={test} disabled={!phone}>
            Look it up
          </Button>
        </div>
      </section>
      <section className="surface space-y-2 p-4 text-sm">
        <h2 className="font-semibold">Latest sends</h2>
        {(syncs.data ?? []).length === 0 ? (
          <p className="text-muted-foreground">
            Nothing sent yet. New calls and WhatsApp messages appear here within
            a few seconds.
          </p>
        ) : (
          <ul className="divide-y">
            {syncs.data!.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2 py-2">
                <span className="font-medium">
                  {s.kind === "call" ? "Call" : "WhatsApp"}
                </span>
                <span
                  className={
                    s.status === "sent"
                      ? "text-emerald-600"
                      : s.status === "pending"
                        ? "text-muted-foreground"
                        : "text-destructive"
                  }
                >
                  {s.status}
                </span>
                <span className="text-muted-foreground">
                  {new Date(s.created_at).toLocaleString()}
                </span>
                {s.last_error && (
                  <span className="w-full text-xs text-muted-foreground">
                    {s.last_error}
                  </span>
                )}
                {(s.status === "failed" || s.status === "skipped") && (
                  <Button size="sm" variant="ghost" onClick={() => retry(s.id)}>
                    Try again
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
