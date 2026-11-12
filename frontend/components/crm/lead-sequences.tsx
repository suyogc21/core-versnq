"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { relative } from "@/lib/crm";
import { enrolLeads, useLeadSequences, useRefreshSequences, useSequences } from "@/lib/sequences";

/** The lead's sequences: where they are, when the next step runs, stop; add to one (9a). */
export function LeadSequences({ leadId }: { leadId: string }) {
  const { can } = useAuth();
  const list = useLeadSequences(leadId);
  const sequences = useSequences();
  const refresh = useRefreshSequences();
  const [pick, setPick] = useState("");
  const active = (list.data ?? []).filter((e) => e.status === "active");
  const recent = (list.data ?? []).filter((e) => e.status !== "active").slice(0, 2);
  const choices = (sequences.data ?? []).filter((s) => s.is_active && !active.some((e) => e.sequence_id === s.id));
  return (
    <div className="space-y-2 text-xs" data-lead-sequences>
      {active.length === 0 && recent.length === 0 && <p className="text-muted-foreground">Not in any sequence.</p>}
      {active.map((e) => (
        <div key={e.id} className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">{e.sequence_name}</div>
            <div className="text-muted-foreground">
              next: step {Math.min(e.position, e.steps)} of {e.steps}
              {e.next_run_at ? `, ${relative(e.next_run_at)}` : ""}
            </div>
          </div>
          {can("leads.edit") && (
            <Button
              size="sm"
              variant="ghost"
              onClick={async () => {
                try {
                  unwrap(await api.POST("/api/v1/enrolments/{e_id}/stop", { params: { path: { e_id: e.id } } }));
                  refresh();
                } catch (err) {
                  toast.error((err as Error).message);
                }
              }}
            >
              Stop
            </Button>
          )}
        </div>
      ))}
      {recent.map((e) => (
        <div key={e.id} className="text-muted-foreground">
          {e.sequence_name}: {e.status === "completed" ? "finished" : `stopped (${e.ended_reason})`}
        </div>
      ))}
      {can("leads.edit") && choices.length > 0 && (
        <div className="flex gap-1.5 pt-1">
          <NativeSelect aria-label="Sequence" className="h-7 min-w-0 flex-1" value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Add to a sequence…</option>
            {choices.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </NativeSelect>
          <Button
            size="sm"
            disabled={!pick}
            onClick={async () => {
              try {
                const r = await enrolLeads(pick, [leadId]);
                (r.ok ? toast.success : toast.error)(r.text);
                setPick("");
                refresh();
              } catch (err) {
                toast.error((err as Error).message);
              }
            }}
          >
            Add
          </Button>
        </div>
      )}
      {can("sequences.manage") && (
        <Link href="/sequences" className="block text-muted-foreground hover:underline">
          Manage sequences
        </Link>
      )}
    </div>
  );
}
