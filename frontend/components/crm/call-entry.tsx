"use client";

import { Play } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type FieldDef, fromLocalInput, quickFollowUps, useActivityTypes, useLead, useRefreshLead } from "@/lib/crm";
import { useWorkspaceSettings } from "@/lib/settings";

type CallData = { call_id?: string; recording?: boolean; recording_removed?: boolean; summary?: string };

/** A reported call on the timeline (step C1): the recording, ACE's summary, and the Outcome. */
export function CallEntry({ leadId, data, outcome }: { leadId: string; data: CallData; outcome: string | null }) {
  const [audio, setAudio] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  if (!data.call_id) return null;
  const callId = data.call_id;

  async function play() {
    setLoading(true);
    try {
      const r = await api.GET("/api/v1/calls/{call_id}/recording", { params: { path: { call_id: callId } }, parseAs: "blob" });
      if (!r.data) throw new Error("The recording could not be loaded");
      setAudio(URL.createObjectURL(r.data as Blob));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-1 space-y-1.5">
      {data.summary && (
        <div className="rounded-md border border-primary/20 bg-primary/5 px-2 py-1 whitespace-pre-wrap">
          <span className="font-medium">ACE summary: </span>
          {data.summary}
        </div>
      )}
      {data.recording &&
        (audio ? (
          <audio controls autoPlay src={audio} className="h-8 w-full max-w-sm" />
        ) : (
          <Button type="button" size="sm" variant="outline" disabled={loading} onClick={play}>
            <Play /> {loading ? "Loading…" : "Play recording"}
          </Button>
        ))}
      {data.recording_removed && <p className="text-muted-foreground">Recording removed after the company&apos;s keep period.</p>}
      {!outcome && <CallOutcome leadId={leadId} callId={callId} />}
    </div>
  );
}

/** The Outcome and next follow-up for a reported call, in one tap (one-step logging). */
function CallOutcome({ leadId, callId }: { leadId: string; callId: string }) {
  const types = useActivityTypes();
  const lead = useLead(leadId);
  const settings = useWorkspaceSettings();
  const refresh = useRefreshLead();
  const [choice, setChoice] = useState<string | null>(null);
  const [followUp, setFollowUp] = useState("");
  const [saving, setSaving] = useState(false);
  const field = ((types.data ?? []).find((t) => t.key === "call")?.fields as FieldDef[] | undefined)?.find((f) => f.key === "disposition");
  const options = (field?.options ?? []) as { value: string; label: string }[];
  const open = lead.data?.is_open ?? false;
  const needsFollowUp = open && (settings.data?.follow_up_required ?? true);

  async function save() {
    if (!choice) return;
    if (needsFollowUp && !followUp) return toast.error("Set the next follow-up — every open lead needs one");
    setSaving(true);
    try {
      unwrap(
        await api.POST("/api/v1/calls/{call_id}/outcome", {
          params: { path: { call_id: callId } },
          body: { disposition: choice, next_follow_up_at: open ? fromLocalInput(followUp) : null },
        }),
      );
      toast.success("Outcome saved");
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-1.5 rounded-md border border-dashed p-2" data-testid="call-outcome">
      <div className="text-muted-foreground">How did it go?</div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => setChoice(o.value)}
            className={`rounded-full border px-2.5 py-0.5 ${choice === o.value ? "border-primary bg-primary text-primary-foreground" : "bg-card"}`}
          >
            {o.label}
          </button>
        ))}
      </div>
      {choice && open && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Input aria-label="Next follow-up" type="datetime-local" className="h-7 w-auto text-xs" value={followUp} onChange={(e) => setFollowUp(e.target.value)} />
          {quickFollowUps().map((q) => (
            <button key={q.label} type="button" className="rounded border px-1.5 py-0.5" onClick={() => setFollowUp(q.value)}>
              {q.label}
            </button>
          ))}
        </div>
      )}
      {choice && (
        <Button type="button" size="sm" disabled={saving} onClick={save}>
          Save outcome
        </Button>
      )}
    </div>
  );
}
