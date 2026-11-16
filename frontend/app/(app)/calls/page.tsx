"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/app/app-shell";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useUsers } from "@/lib/directory";
import { cn } from "@/lib/utils";

const FILTERS = [
  ["", "All"],
  ["missed", "Missed"],
  ["answered", "Answered"],
  ["no_answer", "No answer"],
] as const;
const WORD: Record<string, string> = { answered: "Answered", missed: "Missed", no_answer: "No answer", busy: "Busy", failed: "Failed" };

function length(s: number) {
  const m = Math.floor(s / 60);
  return m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}

/** Every call the person may see (step C1): from the phone app and the company's calling account. */
export default function CallsPage() {
  const [status, setStatus] = useState<(typeof FILTERS)[number][0]>("");
  const users = useUsers();
  const calls = useQuery({
    queryKey: ["calls", status],
    queryFn: async () => unwrap(await api.GET("/api/v1/calls", { params: { query: { status: status || undefined, limit: 200 } } })),
  });
  const userName = (id: string | null) => (users.data ?? []).find((u) => u.id === id)?.name ?? "—";
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Calls" />
      <div className="min-h-0 flex-1 overflow-auto p-4 sm:p-6">
        <div className="mb-3 flex flex-wrap gap-1">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              onClick={() => setStatus(key)}
              className={cn("rounded-md border px-2.5 py-1 text-xs", status === key ? "border-primary bg-primary/10 font-medium" : "bg-card text-muted-foreground")}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="surface divide-y text-sm">
          {calls.isLoading && <p className="p-4 text-muted-foreground">Loading…</p>}
          {calls.data?.length === 0 && (
            <p className="p-4 text-muted-foreground">No calls yet. Calls from the Versnq phone app and your calling account appear here by themselves.</p>
          )}
          {(calls.data ?? []).map((c) => (
            <div key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5">
              <span className={cn("w-20 text-xs", c.status === "missed" && "font-medium text-destructive")}>{WORD[c.status] ?? c.status}</span>
              <span className="text-xs text-muted-foreground">{c.direction === "in" ? "Incoming" : "Outgoing"}</span>
              {c.lead_id ? (
                <Link href={`/leads/${c.lead_id}`} className="font-medium hover:underline">
                  {c.lead_name ?? c.number}
                </Link>
              ) : (
                <span>{c.number}</span>
              )}
              <span className="text-xs text-muted-foreground">
                {new Date(c.started_at).toLocaleString()} · {c.status === "answered" ? length(c.duration_seconds) : "—"} · {userName(c.user_id)}
                {c.has_recording && " · recorded"}
                {c.outcome && ` · ${c.outcome}`}
              </span>
              {c.summary && <span className="w-full text-xs text-muted-foreground">ACE: {c.summary}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
