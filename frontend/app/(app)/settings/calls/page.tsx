"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { PhonesWithTheApp } from "@/components/app/phone-app";
import { TwilioSettings } from "@/components/crm/calling-settings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type CallSettings = components["schemas"]["CallSettings"];

/** Settings → Calls (step C1): recording, how long recordings are kept, unknown callers. */
export default function CallSettingsPage() {
  const current = useQuery({ queryKey: ["call-settings"], queryFn: async () => unwrap(await api.GET("/api/v1/call-settings")) });
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Calls" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-2xl p-4 sm:p-6">
          <p className="mb-4 text-sm text-muted-foreground">
            Calls from the Versnq phone app (your reps&apos; own SIMs) and your own calling account appear on the lead&apos;s timeline by themselves.
            Calls with numbers that aren&apos;t a lead&apos;s are not kept, so personal calls stay out of the CRM.
          </p>
          {current.data ? <Form initial={current.data} /> : <p className="text-sm text-muted-foreground">Loading…</p>}
          <PhonesWithTheApp />
          <TwilioSettings />
        </div>
      </div>
    </div>
  );
}

function Form({ initial }: { initial: CallSettings }) {
  const qc = useQueryClient();
  const [v, setV] = useState<CallSettings>(initial);
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    try {
      unwrap(await api.PUT("/api/v1/call-settings", { body: v }));
      qc.invalidateQueries({ queryKey: ["call-settings"] });
      toast.success("Saved");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="surface space-y-5 p-4 text-sm">
      <label className="flex items-start gap-3">
        <Switch aria-label="Keep call recordings" checked={v.record ?? true} onCheckedChange={(on) => setV({ ...v, record: on })} />
        <span>
          <span className="font-medium">Keep call recordings</span>
          <span className="block text-xs text-muted-foreground">
            Recordings are played on the lead by people who can see it, and ACE writes a summary. Tell callers their call is recorded; recording laws differ by
            country and are your company&apos;s responsibility.
          </span>
        </span>
      </label>
      <div className="space-y-1.5">
        <Label htmlFor="keep-days">Keep recordings for (days)</Label>
        <Input
          id="keep-days"
          type="number"
          min={1}
          max={3650}
          className="w-28"
          value={v.keep_days ?? 30}
          onChange={(e) => setV({ ...v, keep_days: Number(e.target.value) })}
        />
        <p className="text-xs text-muted-foreground">After this, the recording is removed; the call stays on the timeline.</p>
      </div>
      <label className="flex items-start gap-3">
        <Switch aria-label="New leads from unknown callers" checked={v.new_leads ?? false} onCheckedChange={(on) => setV({ ...v, new_leads: on })} />
        <span>
          <span className="font-medium">An incoming call from an unknown number makes a lead</span>
          <span className="block text-xs text-muted-foreground">Off: only calls with your leads are kept. Your reps&apos; own outgoing calls never make leads.</span>
        </span>
      </label>
      <Button onClick={save} disabled={saving}>
        Save
      </Button>
    </div>
  );
}
