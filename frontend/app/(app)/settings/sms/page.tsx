"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useSmsTemplates } from "@/lib/sms";

type Account = components["schemas"]["SmsAccountOut"];
type Provider = "msg91" | "twilio" | "test";

/** Settings → SMS (batch 5d): the provider (MSG91 for India, Twilio elsewhere) and SMS texts. */
export default function SmsSettingsPage() {
  const account = useQuery({ queryKey: ["sms-account"], queryFn: async () => unwrap(await api.GET("/api/v1/sms/account")) });
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="SMS" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-2xl space-y-6 p-4 sm:p-6">
          {account.data ? <ProviderForm key={account.data.provider ?? "none"} account={account.data} /> : <p className="text-sm text-muted-foreground">Loading…</p>}
          <Templates provider={(account.data?.provider as Provider | undefined) ?? null} />
        </div>
      </div>
    </div>
  );
}

function ProviderForm({ account }: { account: Account }) {
  const qc = useQueryClient();
  const [v, setV] = useState({ provider: (account.provider as Provider) ?? "msg91", sender: account.sender ?? "", account_sid: account.account_sid ?? "", auth: "" });
  async function save() {
    try {
      unwrap(
        await api.PUT("/api/v1/sms/account", {
          body: { provider: v.provider, sender: v.sender, account_sid: v.provider === "twilio" ? v.account_sid : null, auth: v.auth || null },
        }),
      );
      qc.invalidateQueries({ queryKey: ["sms-account"] });
      toast.success("Saved");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <section className="surface space-y-4 p-4 text-sm">
      <h2 className="font-semibold">Provider</h2>
      {account.connected && account.test_mode && <p className="text-amber-600">Test mode: SMS are kept in Core and not really sent.</p>}
      <div className="space-y-1">
        <Label htmlFor="sms-provider">Send with</Label>
        <select id="sms-provider" className="h-9 rounded-md border bg-background px-2" value={v.provider} onChange={(e) => setV({ ...v, provider: e.target.value as Provider })}>
          <option value="msg91">MSG91 (India)</option>
          <option value="twilio">Twilio (other countries)</option>
          <option value="test">Test (nothing is sent)</option>
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="sms-sender">{v.provider === "msg91" ? "DLT sender id (6 letters)" : "Your Twilio number"}</Label>
        <Input id="sms-sender" placeholder={v.provider === "msg91" ? "VERSNQ" : "+14155550100"} value={v.sender} onChange={(e) => setV({ ...v, sender: e.target.value })} />
      </div>
      {v.provider === "twilio" && (
        <div className="space-y-1">
          <Label htmlFor="sms-sid">Account SID</Label>
          <Input id="sms-sid" value={v.account_sid} onChange={(e) => setV({ ...v, account_sid: e.target.value })} />
        </div>
      )}
      {v.provider !== "test" && (
        <div className="space-y-1">
          <Label htmlFor="sms-auth">{v.provider === "msg91" ? "MSG91 auth key" : "Twilio auth token"}</Label>
          <Input id="sms-auth" type="password" placeholder={account.connected ? "Saved (leave empty to keep)" : ""} value={v.auth} onChange={(e) => setV({ ...v, auth: e.target.value })} />
        </div>
      )}
      {v.provider === "msg91" && (
        <p className="text-muted-foreground">
          In India every SMS must use a template registered on DLT. Register your sender id and texts on a DLT portal, add them in MSG91, then add each text below with both ids.
        </p>
      )}
      <Button onClick={save}>Save</Button>
      {account.connected && (
        <div className="space-y-1 text-muted-foreground">
          <p>
            Delivery reports: <span className="font-mono text-xs break-all">{account.status_url}</span>
          </p>
          <p>
            Replies and STOP (Twilio: the number&apos;s &quot;A message comes in&quot;): <span className="font-mono text-xs break-all">{account.inbound_url}</span>
          </p>
        </div>
      )}
    </section>
  );
}

function Templates({ provider }: { provider: Provider | null }) {
  const qc = useQueryClient();
  const list = useSmsTemplates();
  const [v, setV] = useState({ name: "", body: "", dlt_template_id: "", provider_template_id: "" });
  async function add() {
    try {
      unwrap(
        await api.POST("/api/v1/sms/templates", {
          body: { name: v.name, body: v.body, dlt_template_id: v.dlt_template_id || null, provider_template_id: v.provider_template_id || null, is_active: true },
        }),
      );
      qc.invalidateQueries({ queryKey: ["sms-templates"] });
      setV({ name: "", body: "", dlt_template_id: "", provider_template_id: "" });
      toast.success("SMS text added");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <section className="surface space-y-4 p-4 text-sm">
      <h2 className="font-semibold">SMS texts</h2>
      <ul className="divide-y">
        {(list.data ?? []).map((t) => (
          <li key={t.id} className="py-2">
            <span className="font-medium">{t.name}</span>
            {t.dlt_template_id && <span className="ml-2 text-xs text-muted-foreground">DLT {t.dlt_template_id}</span>}
            <p className="text-muted-foreground">{t.body}</p>
          </li>
        ))}
      </ul>
      <div className="space-y-2">
        <Input aria-label="Text name" placeholder="Name, e.g. Class reminder" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
        <Textarea aria-label="Text" rows={3} placeholder="Hi {{lead.first_name}}, your class starts at 6 pm." value={v.body} onChange={(e) => setV({ ...v, body: e.target.value })} />
        {provider === "msg91" && (
          <div className="flex gap-2">
            <Input aria-label="DLT template id" placeholder="DLT template id" value={v.dlt_template_id} onChange={(e) => setV({ ...v, dlt_template_id: e.target.value })} />
            <Input aria-label="MSG91 template id" placeholder="MSG91 template id" value={v.provider_template_id} onChange={(e) => setV({ ...v, provider_template_id: e.target.value })} />
          </div>
        )}
        <Button variant="outline" onClick={add}>
          Add text
        </Button>
      </div>
    </section>
  );
}
