"use client";

import { Play } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/app/app-shell";
import { LeadRecord } from "@/components/crm/lead-record";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { phone, type TaskItem, useMyDay, when } from "@/lib/crm";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";
import { amounts, useMyDashboard } from "@/lib/reports";

export default function MyDayPage() {
  const { me, can } = useAuth();
  const label = useLabels();
  const day = useMyDay();
  const [queue, setQueue] = useState<TaskItem[] | null>(null);
  const [position, setPosition] = useState(0);
  const leadsWord = label("lead", true).toLowerCase();

  // Calling queue (#21): overdue first, then today; one lead at a time.
  const workable = [...(day.data?.overdue ?? []), ...(day.data?.today ?? [])].filter((t) => t.lead_id);
  if (queue) {
    const item = queue[position];
    if (!item) {
      return (
        <>
          <PageHeader title="Working the queue" />
          <div className="p-8 text-center">
            <h2 className="text-lg font-semibold">All done. 🎉</h2>
            <p className="mt-1 text-muted-foreground">You worked through {queue.length} follow-ups.</p>
            <Button className="mt-4" onClick={() => setQueue(null)}>
              Back to My Day
            </Button>
          </div>
        </>
      );
    }
    return (
      <>
        <PageHeader
          title={`Working the queue · ${position + 1} of ${queue.length}`}
          actions={
            <>
              <Button size="sm" variant="outline" onClick={() => setPosition(position + 1)}>
                Skip
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setQueue(null)}>
                Stop
              </Button>
            </>
          }
        />
        <LeadRecord
          key={item.id}
          leadId={item.lead_id!}
          onLogged={() => setPosition(position + 1)} // logging the outcome moves to the next one
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="My Day"
        actions={
          workable.length > 0 && (
            <Button
              size="sm"
              onClick={() => {
                setQueue(workable);
                setPosition(0);
              }}
            >
              <Play /> Start working ({workable.length})
            </Button>
          )
        }
      />
      <div className="mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-8">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Good to see you, {me?.name.split(" ")[0]}.</h2>
          <p className="mt-1 text-sm text-muted-foreground">{day.data ? "Here is what needs you today." : "Loading your day…"}</p>
        </div>
        {day.data && (
          <div className="surface grid grid-cols-3 divide-x overflow-hidden">
            <Stat label="Overdue" value={day.data.overdue.length} danger={day.data.overdue.length > 0} />
            <Stat label="Due today" value={day.data.today.length} />
            <Stat label={`New ${leadsWord}`} value={day.data.new_leads.length} />
          </div>
        )}
        {can("leads.edit") && <MonthStrip />}
        {day.data?.unassigned_count ? (
          <Link href="/leads" className="surface flex items-center gap-2.5 px-4 py-3 text-[13px] hover:shadow-float">
            <span className="size-2 shrink-0 rounded-full bg-amber-500" />
            <span>
              <b>{day.data.unassigned_count}</b> open {leadsWord} have no owner yet. Assign them from the list (view “Unassigned”).
            </span>
          </Link>
        ) : null}
        <Bucket title="Overdue" tone="danger" tasks={day.data?.overdue} empty="Nothing overdue." />
        <Bucket title="Today" tasks={day.data?.today} empty="Nothing else due today." />
        {day.data && day.data.new_leads.length > 0 && (
          <section className="surface overflow-hidden">
            <h3 className="border-b px-4 py-3 text-[13px] font-semibold">New {leadsWord} — not contacted yet</h3>
            <ul className="divide-y">
              {day.data.new_leads.map((l) => (
                <li key={l.id}>
                  <Link href={`/leads/${l.id}`} className="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-accent/50">
                    <span className="font-medium">{l.display_name}</span>
                    <span className="text-muted-foreground">{l.primary_phone ? phone(l.primary_phone) : l.primary_email}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
        <Bucket title="Coming up this week" tasks={day.data?.upcoming} empty="Nothing scheduled." muted />
        {!can("leads.edit") && <p className="text-xs text-muted-foreground">Your role does not work {leadsWord}.</p>}
      </div>
    </>
  );
}

function Bucket({ title, tasks, empty, tone, muted }: { title: string; tasks?: TaskItem[]; empty: string; tone?: "danger"; muted?: boolean }) {
  return (
    <section className="surface overflow-hidden">
      <h3 className={cn("flex items-center gap-2 px-4 py-3 text-[13px] font-semibold", tasks?.length && "border-b", tone === "danger" && tasks?.length && "text-destructive")}>
        {title}
        {tasks?.length ? <span className="font-normal text-muted-foreground">{tasks.length}</span> : null}
      </h3>
      {!tasks ? null : tasks.length === 0 ? (
        <p className="-mt-1 px-4 pb-3 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className={cn("divide-y", muted && "opacity-80")}>
          {tasks.map((t) => (
            <li key={t.id}>
              <Link href={t.lead_id ? `/leads/${t.lead_id}` : "#"} className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-accent/50">
                <span className={cn("w-28 shrink-0 text-xs", tone === "danger" ? "text-destructive" : "text-muted-foreground")}>{when(t.due_at)}</span>
                <span className="min-w-0 flex-1 truncate">
                  <span className="font-medium">{t.lead_name ?? t.title}</span>
                  {t.lead_name && <span className="text-muted-foreground"> · {t.is_follow_up ? "follow-up" : t.title}</span>}
                </span>
                {t.lead_phone && <span className="hidden text-xs text-muted-foreground sm:inline">{phone(t.lead_phone)}</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Stat({ label, value, danger }: { label: string; value: number; danger?: boolean }) {
  return (
    <div className="px-4 py-4 sm:px-5">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-3xl font-semibold tracking-tight tabular-nums", danger && "text-destructive")}>{value}</div>
    </div>
  );
}

/** This month at a glance; the full view is Dashboards → My numbers. */
function MonthStrip() {
  const d = useMyDashboard({ period: "month" });
  if (!d.data) return null;
  const c = d.data.current;
  return (
    <Link href="/dashboards" className="surface flex flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2.5 text-[13px] hover:shadow-float" data-month-strip>
      <span className="font-medium">This month</span>
      <span>
        <b className="tabular-nums">{c.calls}</b> calls
      </span>
      <span>
        <b className="tabular-nums">{c.deals_won}</b> won
      </span>
      <span>
        Booked <b className="tabular-nums">{amounts(c.booked)}</b>
      </span>
      <span>
        Collected <b className="tabular-nums">{amounts(c.collected)}</b>
      </span>
      <span className="ml-auto text-xs text-muted-foreground">My numbers →</span>
    </Link>
  );
}
