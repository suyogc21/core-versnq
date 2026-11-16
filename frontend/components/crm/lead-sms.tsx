"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useRefreshLead, type Lead } from "@/lib/crm";
import { useSmsTemplates } from "@/lib/sms";

const STATUS: Record<string, string> = { sent: "Sent", delivered: "Delivered", failed: "Not sent", received: "Received", queued: "Sending" };

/** SMS on the lead (batch 5d): send a text or a saved SMS text; the last few in and out. */
export function LeadSms({ lead }: { lead: Lead }) {
  const qc = useQueryClient();
  const refresh = useRefreshLead();
  const templates = useSmsTemplates();
  const history = useQuery({
    queryKey: ["lead-sms", lead.id],
    queryFn: async () => unwrap(await api.GET("/api/v1/leads/{lead_id}/sms", { params: { path: { lead_id: lead.id } } })),
  });
  const [body, setBody] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [busy, setBusy] = useState(false);
  if (lead.sms_consent === "opted_out") return <p className="text-xs text-muted-foreground">Opted out of SMS.</p>;

  async function send() {
    setBusy(true);
    try {
      const out = unwrap(
        await api.POST("/api/v1/leads/{lead_id}/sms", {
          params: { path: { lead_id: lead.id } },
          body: templateId ? { template_id: templateId } : { body },
        }),
      );
      if (out.status === "failed") toast.error(out.error ?? "Not sent");
      else toast.success("SMS sent");
      setBody("");
      setTemplateId("");
      qc.invalidateQueries({ queryKey: ["lead-sms", lead.id] });
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const active = (templates.data ?? []).filter((t) => t.is_active);
  return (
    <div className="space-y-2 text-sm">
      {active.length > 0 && (
        <select aria-label="SMS text" className="h-8 w-full rounded-md border bg-background px-2 text-sm" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
          <option value="">Write my own</option>
          {active.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      )}
      {!templateId && <Textarea aria-label="SMS" rows={2} placeholder="Hi {{lead.first_name}}…" value={body} onChange={(e) => setBody(e.target.value)} />}
      <Button size="sm" disabled={busy || (!templateId && !body.trim())} onClick={send}>
        Send SMS
      </Button>
      {(history.data ?? []).slice(0, 5).map((m) => (
        <div key={m.id} className="rounded-md border px-2 py-1 text-xs">
          <span className="text-muted-foreground">
            {m.direction === "in" ? "From them" : "You"} · {new Date(m.created_at).toLocaleString()} · {STATUS[m.status] ?? m.status}
          </span>
          <p className="whitespace-pre-wrap">{m.body}</p>
        </div>
      ))}
    </div>
  );
}
