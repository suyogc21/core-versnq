"use client";

import { useState } from "react";
import { toast } from "sonner";

import { CustomFieldInput } from "@/components/crm/bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import {
  type FieldDef,
  fromLocalInput,
  type Lead,
  quickFollowUps,
  useActivityTypes,
  useRefreshLead,
} from "@/lib/crm";
import { useWorkspaceSettings } from "@/lib/settings";

/**
 * One form to log what happened and set the next follow-up (one-step logging, #21).
 * Logging completes the lead's due follow-up; open leads must get the next one.
 */
export function LogActivityForm({
  lead,
  type,
  onTypeChange,
  onLogged,
}: {
  lead: Lead;
  type: string;
  onTypeChange: (key: string) => void;
  onLogged?: (lead: Lead) => void;
}) {
  const types = useActivityTypes();
  const settings = useWorkspaceSettings();
  const refresh = useRefreshLead();
  const [data, setData] = useState<Record<string, unknown>>({});
  const [body, setBody] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const loggable = (types.data ?? []).filter((t) => t.is_loggable && t.is_active);
  const kind = loggable.find((t) => t.key === type) ?? loggable[0];
  const needsFollowUp = lead.is_open && (settings.data?.follow_up_required ?? true);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!kind) return;
    setError(null);
    if (needsFollowUp && !followUp) return setError("Set the next follow-up — every open lead needs one");
    setSaving(true);
    try {
      const result = unwrap(
        await api.POST("/api/v1/leads/{lead_id}/activities", {
          params: { path: { lead_id: lead.id } },
          body: {
            type_key: kind.key,
            body: body || null,
            // Only this type's fields (values typed for another type are dropped).
            data: Object.fromEntries(
              Object.entries(data).filter(([k, v]) => v !== null && v !== "" && (kind.fields as FieldDef[]).some((f) => f.key === k)),
            ),
            next_follow_up_at: lead.is_open ? fromLocalInput(followUp) : null,
          },
        }),
      );
      refresh(result.lead);
      toast.success(`${kind.label} logged`);
      setBody("");
      setData({});
      setFollowUp("");
      onLogged?.(result.lead);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!kind) return null;
  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border bg-muted/30 p-3">
      <div className="flex flex-wrap gap-1">
        {loggable.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => onTypeChange(t.key)}
            className={`rounded-md border px-2 py-1 text-xs ${t.key === kind.key ? "border-primary bg-primary/10 font-medium" : "bg-background text-muted-foreground"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {(kind.fields as FieldDef[]).map((f) =>
        f.key === "disposition" ? (
          <div key={f.key} className="space-y-1.5">
            <Label>{f.label} *</Label>
            <div className="flex flex-wrap gap-1.5">
              {(f.options as { value: string; label: string }[]).map((o) => (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => setData({ ...data, disposition: o.value })}
                  className={`rounded-full border px-2.5 py-0.5 text-xs ${data.disposition === o.value ? "border-primary bg-primary text-primary-foreground" : "bg-background"}`}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <CustomFieldInput key={f.key} field={f} value={data[f.key]} onChange={(v) => setData({ ...data, [f.key]: v })} />
        ),
      )}
      <Textarea
        aria-label="Notes"
        placeholder={kind.key === "note" ? "Write a note…" : "What happened? (optional)"}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={2}
      />
      {lead.is_open && (
        <div className="space-y-1.5">
          <Label htmlFor={`fu-${lead.id}`}>Next follow-up{needsFollowUp && " *"}</Label>
          <div className="flex flex-wrap items-center gap-1.5">
            <Input
              id={`fu-${lead.id}`}
              type="datetime-local"
              className="w-auto"
              value={followUp}
              onChange={(e) => setFollowUp(e.target.value)}
            />
            {quickFollowUps().map((q) => (
              <button
                key={q.label}
                type="button"
                className="rounded border bg-background px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-accent"
                onClick={() => setFollowUp(q.value)}
              >
                {q.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
      <Button type="submit" size="sm" disabled={saving}>
        Log {kind.label.toLowerCase()}
      </Button>
    </form>
  );
}
