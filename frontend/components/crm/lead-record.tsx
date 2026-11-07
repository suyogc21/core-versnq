"use client";

import { Check, Mail, MessageCircle, Phone, StickyNote, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Popover, PopoverHeading, PopoverItem } from "@/components/data-table/popover";
import { Avatar, StagePill } from "@/components/crm/bits";
import { ActionButton, EditLead, Facts, LeadTasks, Timeline, TIMELINE_FILTERS } from "@/components/crm/lead-panel";
import { LogActivityForm } from "@/components/crm/log-activity";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import {
  isOverdue,
  type Lead,
  phone as formatPhone,
  relative,
  type Stage,
  useFields,
  useLead,
  useRefreshLead,
  useStages,
  when,
} from "@/lib/crm";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

/** Move a lead to a stage, asking for a reason when the stage needs one. */
export function useMoveStage(lead: Lead | undefined) {
  const refresh = useRefreshLead();
  return async (stage: Stage, reason?: string) => {
    if (!lead || stage.id === lead.stage_id) return true;
    try {
      const updated = unwrap(
        await api.PATCH("/api/v1/leads/{lead_id}", {
          params: { path: { lead_id: lead.id } },
          body: { version: lead.version, stage_id: stage.id, unqualified_reason: reason ?? lead.unqualified_reason },
        }),
      );
      refresh(updated);
      toast.success(`Moved to ${stage.name}`);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      refresh();
      return false;
    }
  };
}

/** Open stages (and the won stage) as a clickable path; other closing stages under "Close". */
export function StageStepper({ lead }: { lead: Lead }) {
  const { can } = useAuth();
  const stages = useStages();
  const move = useMoveStage(lead);
  const [reasonFor, setReasonFor] = useState<Stage | null>(null);
  const [reason, setReason] = useState("");
  const all = stages.data ?? [];
  const path = all.filter((s) => s.is_open || s.is_converted);
  const closers = all.filter((s) => !s.is_open && !s.is_converted);
  const currentIndex = path.findIndex((s) => s.id === lead.stage_id);
  const current = all.find((s) => s.id === lead.stage_id);
  const editable = can("leads.edit");

  return (
    <div className="space-y-2">
      <div className="flex overflow-x-auto rounded-lg border text-xs [scrollbar-width:none]">
        {path.map((s, i) => {
          const done = currentIndex > -1 && i < currentIndex;
          const here = s.id === lead.stage_id;
          return (
            <button
              key={s.id}
              type="button"
              disabled={!editable}
              onClick={() => move(s)}
              title={`Move to ${s.name}`}
              className={cn(
                "min-w-28 flex-1 border-r px-3 py-1.5 whitespace-nowrap text-muted-foreground hover:bg-accent",
                done && "bg-primary/10 text-foreground",
                here && "bg-primary font-semibold text-primary-foreground hover:bg-primary",
              )}
            >
              {done && <Check className="mr-1 inline size-3" />}
              {s.name}
            </button>
          );
        })}
        <Popover
          align="end"
          trigger={({ toggle }) => (
            <button
              type="button"
              disabled={!editable}
              onClick={toggle}
              className={cn(
                "min-w-28 px-3 py-1.5 whitespace-nowrap text-muted-foreground hover:bg-accent",
                current && closers.some((c) => c.id === current.id) && "bg-muted font-semibold text-foreground",
              )}
            >
              {current && closers.some((c) => c.id === current.id) ? current.name : "Close"} ▾
            </button>
          )}
        >
          {(close) => (
            <>
              <PopoverHeading>Close as</PopoverHeading>
              {closers.map((s) => (
                <PopoverItem
                  key={s.id}
                  onClick={() => {
                    close();
                    if (s.is_unqualified) setReasonFor(s);
                    else move(s);
                  }}
                >
                  <StagePill stage={s} />
                </PopoverItem>
              ))}
            </>
          )}
        </Popover>
      </div>
      {reasonFor && (
        <form
          className="flex flex-wrap items-center gap-2 rounded-lg border p-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await move(reasonFor, reason.trim())) {
              setReasonFor(null);
              setReason("");
            }
          }}
        >
          <span className="text-xs">Why move to {reasonFor.name}?</span>
          <Input autoFocus aria-label="Reason" className="h-7 max-w-xs flex-1" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button size="sm" type="submit" disabled={!reason.trim()}>
            Move
          </Button>
          <Button size="sm" type="button" variant="ghost" onClick={() => setReasonFor(null)}>
            Cancel
          </Button>
        </form>
      )}
      {lead.unqualified_reason && !lead.is_open && <p className="text-xs text-muted-foreground">Reason: {lead.unqualified_reason}</p>}
    </div>
  );
}

function ContactActions({ lead, onLog }: { lead: Lead; onLog: (type: string) => void }) {
  const wa = lead.identities.find((i) => i.type === "phone" && i.is_whatsapp)?.value_normalized ?? lead.primary_phone;
  return (
    <div className="flex flex-wrap gap-1.5">
      <ActionButton icon={Phone} label="Call" primary href={lead.primary_phone ? `tel:${lead.primary_phone}` : undefined} onClick={() => onLog("call")} />
      {wa && <ActionButton icon={MessageCircle} label="WhatsApp" href={`https://wa.me/${wa.replace("+", "")}`} external />}
      {lead.primary_email && <ActionButton icon={Mail} label="Email" href={`mailto:${lead.primary_email}`} />}
      <ActionButton icon={StickyNote} label="Note" onClick={() => onLog("note")} />
    </div>
  );
}

function FollowUpCard({ lead }: { lead: Lead }) {
  const label = useLabels();
  if (!lead.is_open) return <p className="text-xs text-muted-foreground">Closed — no follow-up needed.</p>;
  const missing = !lead.next_follow_up_at;
  const late = isOverdue(lead.next_follow_up_at);
  return (
    <div className={cn("rounded-lg border p-3 text-xs", (missing || late) && "border-destructive/40 bg-destructive/5")}>
      <div className={cn("text-sm font-semibold", (missing || late) && "text-destructive")}>{missing ? "Not set" : when(lead.next_follow_up_at)}</div>
      <div className="text-muted-foreground">
        {missing ? `Every open ${label("lead").toLowerCase()} needs one. Log what happened and set it.` : late ? "Overdue" : relative(lead.next_follow_up_at)}
      </div>
    </div>
  );
}

function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="flex items-center justify-between text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        {title}
        {action}
      </h4>
      {children}
    </section>
  );
}

/** The full record (mockup v2): details · timeline with logging · follow-up and tasks. */
export function LeadRecord({ leadId }: { leadId: string }) {
  const lead = useLead(leadId);
  const label = useLabels();
  const fields = useFields();
  const [logType, setLogType] = useState("call");
  const [filter, setFilter] = useState("All");
  const [editing, setEditing] = useState(false);
  if (lead.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (lead.isError || !lead.data) return <p className="p-6 text-destructive">{lead.error?.message ?? "Not found"}</p>;
  const l = lead.data;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="space-y-3 border-b px-4 py-3 md:px-6">
        <div className="text-xs text-muted-foreground">
          <Link href="/leads" className="hover:underline">
            {label("lead", true)}
          </Link>{" "}
          / {l.display_name}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Avatar name={l.display_name} colour="#6366f1" size={9} />
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold">{l.display_name}</h2>
            <div className="text-xs text-muted-foreground">
              {[l.primary_phone && formatPhone(l.primary_phone), l.primary_email, l.city, `added ${relative(l.created_at)}`].filter(Boolean).join(" · ")}
            </div>
          </div>
          <div className="ml-auto">
            <ContactActions lead={l} onLog={setLogType} />
          </div>
        </div>
        <StageStepper lead={l} />
      </div>
      <div className="grid min-h-0 flex-1 lg:grid-cols-[300px_minmax(0,1fr)_300px]">
        <div className="space-y-5 border-b p-4 lg:border-r lg:border-b-0">
          <Section
            title="About"
            action={
              <button className="normal-case" onClick={() => setEditing(!editing)}>
                {editing ? "Done" : "Edit"}
              </button>
            }
          >
            {editing ? <EditLead key={l.version} lead={l} /> : <Facts lead={l} showStage={false} />}
          </Section>
          {!editing && (fields.data ?? []).length === 0 && <p className="text-xs text-muted-foreground">No custom fields yet.</p>}
        </div>
        <div className="space-y-4 border-b p-4 lg:border-b-0">
          <LogActivityForm lead={l} type={logType} onTypeChange={setLogType} />
          <div className="flex flex-wrap gap-1.5">
            {Object.keys(TIMELINE_FILTERS).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn("rounded-full border px-2.5 py-0.5 text-xs", filter === f && "border-primary bg-primary text-primary-foreground")}
              >
                {f}
              </button>
            ))}
          </div>
          <Timeline leadId={l.id} filter={filter} />
        </div>
        <div className="space-y-5 p-4 lg:border-l">
          <Section title="Next follow-up">
            <FollowUpCard lead={l} />
          </Section>
          <Section title="Tasks">
            <LeadTasks lead={l} />
          </Section>
          <Section title={label("deal", true)}>
            <p className="text-xs text-muted-foreground">None yet.</p>
          </Section>
        </div>
      </div>
    </div>
  );
}

/** Quick look from a list: slides over it (the list keeps its full width). */
export function LeadPreview({ leadId, onClose, onLogged }: { leadId: string; onClose: () => void; onLogged?: (lead: Lead) => void }) {
  const lead = useLead(leadId);
  const [logType, setLogType] = useState("call");
  const l = lead.data;
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/10" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-label="Preview" className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[480px] flex-col border-l bg-background shadow-2xl">
        {!l ? (
          <p className="p-6 text-muted-foreground">Loading…</p>
        ) : (
          <>
            <div className="space-y-2 border-b p-4">
              <div className="flex items-center gap-2">
                <PreviewStage lead={l} />
                <span className="ml-auto hidden text-[11px] text-muted-foreground sm:inline">J / K next · Esc close</span>
                <button aria-label="Close preview" className="rounded p-1 hover:bg-accent" onClick={onClose}>
                  <X className="size-4" />
                </button>
              </div>
              <h2 className="truncate text-lg font-semibold">{l.display_name}</h2>
              <div className="text-xs text-muted-foreground">{l.primary_phone ? formatPhone(l.primary_phone) : l.primary_email}</div>
              <div className="flex flex-wrap items-center gap-1.5">
                <ContactActions lead={l} onLog={setLogType} />
                <Link href={`/leads/${l.id}`} className="ml-auto text-xs font-medium text-primary hover:underline">
                  Open full record ↗
                </Link>
              </div>
            </div>
            <div className="flex-1 space-y-4 overflow-auto p-4">
              <FollowUpCard lead={l} />
              <LogActivityForm lead={l} type={logType} onTypeChange={setLogType} onLogged={onLogged} />
              <Facts lead={l} />
              <Section title="Recent activity">
                <Timeline leadId={l.id} />
              </Section>
            </div>
          </>
        )}
      </aside>
    </>
  );
}

function PreviewStage({ lead }: { lead: Lead }) {
  const stages = useStages();
  return <StagePill stage={stages.data?.find((s) => s.id === lead.stage_id)} />;
}
