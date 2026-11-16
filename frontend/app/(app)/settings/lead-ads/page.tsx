"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type Source = components["schemas"]["LeadAdSourceOut"];

/** Settings → Lead ads (batch 5d): Facebook/Instagram Pages and Google Ads lead forms. Leads go
 * through the same rules as every other lead (routing, duplicates). */
export default function LeadAdsPage() {
  const list = useQuery({ queryKey: ["lead-ad-sources"], queryFn: async () => unwrap(await api.GET("/api/v1/lead-ads/sources")) });
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Lead ads" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-2xl space-y-6 p-4 sm:p-6">
          <p className="text-sm text-muted-foreground">
            People who fill in a lead form on your Facebook, Instagram or Google ads become leads here within seconds, with the ad and campaign they came from.
          </p>
          {(list.data ?? []).map((s) => (
            <SourceCard key={s.id} source={s} />
          ))}
          <AddFacebook />
          <AddGoogle />
        </div>
      </div>
    </div>
  );
}

function Copy({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input readOnly value={value} className="font-mono text-xs" />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            navigator.clipboard.writeText(value);
            toast.success("Copied");
          }}
        >
          Copy
        </Button>
      </div>
    </div>
  );
}

function SourceCard({ source }: { source: Source }) {
  const qc = useQueryClient();
  async function toggle(on: boolean) {
    try {
      unwrap(
        await api.PATCH("/api/v1/lead-ads/sources/{source_id}", {
          params: { path: { source_id: source.id } },
          body: { provider: source.provider as "facebook" | "google", name: source.name, page_id: source.page_id, source_id: source.source_id, stage_id: source.stage_id, is_active: on },
        }),
      );
      qc.invalidateQueries({ queryKey: ["lead-ad-sources"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function remove() {
    if (!confirm(`Remove ${source.name}? New leads from it will stop arriving.`)) return;
    unwrap(await api.DELETE("/api/v1/lead-ads/sources/{source_id}", { params: { path: { source_id: source.id } } }));
    qc.invalidateQueries({ queryKey: ["lead-ad-sources"] });
  }
  return (
    <section className="surface space-y-3 p-4 text-sm">
      <div className="flex items-center gap-2">
        <h2 className="font-semibold">
          {source.provider === "facebook" ? "Facebook / Instagram" : "Google Ads"}: {source.name}
        </h2>
        <label className="ml-auto flex items-center gap-2 text-muted-foreground">
          <Switch aria-label={`${source.name} on`} checked={source.is_active} onCheckedChange={toggle} /> On
        </label>
      </div>
      <p className="text-muted-foreground">
        {source.leads} leads so far{source.failed ? ` · ${source.failed} couldn't be read` : ""}
        {source.last_lead_at ? ` · last ${new Date(source.last_lead_at).toLocaleString()}` : ""}
      </p>
      <Copy label="Webhook address" value={source.webhook_url} />
      {source.verify_token && <Copy label="Verify token (Meta asks for it once)" value={source.verify_token} />}
      <Button variant="ghost" size="sm" onClick={remove}>
        Remove
      </Button>
    </section>
  );
}

function AddFacebook() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [v, setV] = useState({ name: "", page_id: "", page_token: "", app_secret: "" });
  async function save() {
    try {
      unwrap(
        await api.POST("/api/v1/lead-ads/sources", {
          body: { provider: "facebook", name: v.name, page_id: v.page_id, page_token: v.page_token, app_secret: v.app_secret || null, is_active: true },
        }),
      );
      qc.invalidateQueries({ queryKey: ["lead-ad-sources"] });
      toast.success("Page connected. Paste the webhook address and verify token in your Meta app.");
      setOpen(false);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  if (!open)
    return (
      <Button variant="outline" onClick={() => setOpen(true)}>
        Connect a Facebook / Instagram Page
      </Button>
    );
  return (
    <section className="surface space-y-3 p-4 text-sm">
      <h2 className="font-semibold">Connect a Facebook / Instagram Page</h2>
      <p className="text-muted-foreground">
        For now, paste the Page&apos;s id and a Page access token with the leads_retrieval permission (from Meta&apos;s Business settings). Signing in with Facebook here comes
        later.
      </p>
      {(
        [
          ["name", "Name in Core", "Main page"],
          ["page_id", "Page id", "1234567890"],
          ["page_token", "Page access token", ""],
          ["app_secret", "Your Meta app's secret (only if you use your own app)", ""],
        ] as const
      ).map(([k, label, ph]) => (
        <div key={k} className="space-y-1">
          <Label htmlFor={`fb-${k}`}>{label}</Label>
          <Input id={`fb-${k}`} type={k === "page_token" || k === "app_secret" ? "password" : "text"} placeholder={ph} value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
        </div>
      ))}
      <div className="flex gap-2">
        <Button onClick={save}>Connect</Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </section>
  );
}

function AddGoogle() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [made, setMade] = useState<{ key: string; url: string } | null>(null);
  async function save() {
    try {
      const out = unwrap(await api.POST("/api/v1/lead-ads/sources", { body: { provider: "google", name: name || "Google Ads", is_active: true } }));
      qc.invalidateQueries({ queryKey: ["lead-ad-sources"] });
      setMade({ key: out.google_key ?? "", url: out.webhook_url });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <section className="surface space-y-3 p-4 text-sm">
      <h2 className="font-semibold">Add a Google Ads lead form</h2>
      {made ? (
        <>
          <p>In Google Ads, open the lead form → Lead delivery → Webhook integration, and paste these. The key is shown only now.</p>
          <Copy label="Webhook URL" value={made.url} />
          <Copy label="Key" value={made.key} />
        </>
      ) : (
        <div className="flex gap-2">
          <Input aria-label="Google form name" placeholder="Search campaign" value={name} onChange={(e) => setName(e.target.value)} />
          <Button variant="outline" onClick={save}>
            Add
          </Button>
        </div>
      )}
    </section>
  );
}
