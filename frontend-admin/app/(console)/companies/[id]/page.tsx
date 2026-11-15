"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { AuditTable } from "@/components/app/audit-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

// Display names for module keys (the backend's MODULES in app/core/modules.py). "crm" is core and always on.
const MODULES: Record<string, string> = {
  crm: "Leads, deals, tasks, customers",
  email: "Email channel",
  whatsapp: "WhatsApp channel",
  sequences: "Email and WhatsApp sequences",
  inbox: "Unified inbox",
  api: "Public API and webhooks",
  money: "Invoices and payments (parked)",
  ace: "Versnq ACE add-on",
  key_accounts: "Key accounts add-on",
  whatsapp_number: "Company WhatsApp number (turn on once live with Meta)",
  copy_in: "Copy-in email addresses (turn on once inbound mail is live)",
  outreach: "Outreach: cold email campaigns from the sending inboxes",
};
const CORE_MODULES = new Set(["crm"]);

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const path = { params: { path: { tenant_id: id } } };
  const company = useQuery({
    queryKey: ["tenant", id],
    queryFn: async () => unwrap(await api.GET("/platform/tenants/{tenant_id}", path)),
  });
  const modules = useQuery({
    queryKey: ["tenant-modules", id],
    queryFn: async () => unwrap(await api.GET("/platform/tenants/{tenant_id}/modules", path)),
  });
  const audit = useQuery({
    queryKey: ["audit", id],
    queryFn: async () => unwrap(await api.GET("/platform/audit", { params: { query: { target_id: id, limit: 50 } } })),
  });
  const [name, setName] = useState<string | null>(null);

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["tenant", id] }),
      queryClient.invalidateQueries({ queryKey: ["tenants"] }),
      queryClient.invalidateQueries({ queryKey: ["audit", id] }),
    ]);

  async function run(action: () => Promise<unknown>, success: string) {
    try {
      await action();
      await refresh();
      toast.success(success);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  if (company.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (company.isError || !company.data) return <p className="text-destructive">{company.error?.message}</p>;
  const t = company.data;
  const suspended = t.status === "suspended";

  return (
    <div className="space-y-8">
      <div>
        <Link href="/" className="text-xs text-muted-foreground hover:underline">
          ← Companies
        </Link>
        <div className="mt-1 flex items-center gap-2">
          <h1 className="text-base font-semibold">{t.name}</h1>
          <Badge variant={suspended ? "destructive" : "secondary"} className="capitalize">
            {t.status}
          </Badge>
        </div>
        <p className="text-muted-foreground">
          <span className="font-mono">{t.slug}</span>.core.versnq.in · {t.industry_pack} · created{" "}
          {new Date(t.created_at).toLocaleDateString()}
        </p>
      </div>

      <section className="space-y-2">
        <h2 className="font-semibold">Name</h2>
        <form
          className="flex max-w-md gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name?.trim() || name === t.name) return;
            run(async () => {
              unwrap(await api.PATCH("/platform/tenants/{tenant_id}", { ...path, body: { name: name.trim() } }));
              setName(null);
            }, "Company renamed.");
          }}
        >
          <Input aria-label="Company name" value={name ?? t.name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" variant="outline" disabled={name === null || name === t.name}>
            Rename
          </Button>
        </form>
        <p className="text-xs text-muted-foreground">The address cannot be changed.</p>
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold">Access</h2>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() =>
              run(async () => {
                const r = unwrap(await api.POST("/platform/tenants/{tenant_id}/resend-owner-invite", path));
                if (!r.invite_sent) throw new Error("The invite email could not be sent. Try again later.");
              }, "Owner invite sent.")
            }
          >
            Resend Owner invite
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              const email = prompt("Owner's email: their authenticator app is removed (lost phone). Check who is asking first.");
              if (!email?.trim()) return;
              run(
                async () => unwrap(await api.POST("/platform/tenants/{tenant_id}/owner-2fa-reset", { ...path, body: { email: email.trim() } })),
                "The Owner's authenticator app is removed; they were emailed.",
              );
            }}
          >
            Reset Owner&apos;s authenticator
          </Button>
          {suspended ? (
            <Button
              onClick={() =>
                run(async () => unwrap(await api.POST("/platform/tenants/{tenant_id}/reactivate", path)), "Company reactivated.")
              }
            >
              Reactivate
            </Button>
          ) : (
            <Button
              variant="destructive"
              onClick={() =>
                window.confirm(`Suspend ${t.name}? Nobody at the company can sign in until it is reactivated.`) &&
                run(async () => unwrap(await api.POST("/platform/tenants/{tenant_id}/suspend", path)), "Company suspended.")
              }
            >
              Suspend
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Suspending stops everyone at the company from signing in. Their data is kept.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold">Modules</h2>
        <ul className="max-w-md divide-y rounded-lg border">
          {Object.entries(modules.data ?? {}).map(([key, enabled]) => (
            <li key={key} className="flex items-center gap-3 px-3 py-2">
              <div className="flex-1">
                <div>{MODULES[key] ?? key}</div>
                <div className="font-mono text-xs text-muted-foreground">{key}</div>
              </div>
              <Switch
                aria-label={MODULES[key] ?? key}
                checked={enabled}
                disabled={CORE_MODULES.has(key)}
                onCheckedChange={(on) =>
                  run(async () => {
                    const data = unwrap(await api.PUT("/platform/tenants/{tenant_id}/modules", { ...path, body: { [key]: on } }));
                    queryClient.setQueryData(["tenant-modules", id], data);
                  }, `${MODULES[key] ?? key} ${on ? "on" : "off"}.`)
                }
              />
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold">Staff actions on this company</h2>
        <AuditTable rows={audit.data ?? []} />
      </section>
    </div>
  );
}
