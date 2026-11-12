"use client";

import { Lock, MessageCircle, Users } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { PageHeader } from "@/components/app/app-shell";
import { ConversationView } from "@/components/crm/conversation";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { relative } from "@/lib/crm";
import { type InboxView, useInbox } from "@/lib/inbox";
import { cn } from "@/lib/utils";

const VIEWS: [InboxView, string][] = [
  ["mine", "Mine"],
  ["waiting", "Waiting for us"],
  ["shared", "Shared with me"],
  ["unassigned", "Unassigned"],
  ["all", "All"],
  ["closed", "Closed"],
];

export default function InboxPage() {
  return (
    <Suspense>
      <Inbox />
    </Suspense>
  );
}

function Inbox() {
  const { can } = useAuth();
  const params = useSearchParams();
  const [view, setView] = useState<InboxView>("mine");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(params.get("c"));
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);
  const list = useInbox(view, q, can("inbox.reply"));
  if (!can("inbox.reply")) return <p className="p-8 text-center text-muted-foreground">You don&apos;t have the inbox.</p>;
  const rows = list.data ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Inbox" actions={<Input placeholder="Search name or subject…" className="h-7 w-full sm:w-64" value={search} onChange={(e) => setSearch(e.target.value)} />} />
      <div className="flex min-h-0 flex-1">
        <div className={cn("flex min-h-0 w-full flex-col border-r md:w-[360px] md:shrink-0", open && "hidden md:flex")}>
          <div className="flex gap-1 overflow-x-auto border-b px-2 py-2" role="tablist">
            {VIEWS.map(([k, l]) => (
              <button
                key={k}
                role="tab"
                aria-selected={view === k}
                onClick={() => setView(k)}
                className={cn("rounded-full px-2.5 py-1 text-xs whitespace-nowrap text-muted-foreground hover:bg-accent", view === k && "bg-foreground text-background hover:bg-foreground")}
              >
                {l}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 divide-y overflow-auto" data-inbox-list>
            {rows.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "Nothing here."}</p>}
            {rows.map((r) => (
              <button
                key={r.id}
                onClick={() => setOpen(r.id)}
                className={cn("block w-full px-3 py-2.5 text-left hover:bg-muted/50", open === r.id && "bg-muted")}
                data-row={r.lead_name}
              >
                <div className="flex items-center gap-1.5">
                  {r.unread && <span className="size-2 shrink-0 rounded-full bg-primary" aria-label="Unread" />}
                  {r.channel === "whatsapp" && <MessageCircle className="size-3 shrink-0 text-emerald-600" aria-label="WhatsApp" />}
                  <span className={cn("truncate text-sm", r.unread && "font-semibold")}>{r.lead_name}</span>
                  {r.shared && <Users className="size-3 text-muted-foreground" aria-label="Shared with you" />}
                  {r.is_private && <Lock className="size-3 text-muted-foreground" aria-label="Private" />}
                  <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">{relative(r.last_message_at)}</span>
                </div>
                <div className="truncate text-xs">{r.subject || "(no subject)"}</div>
                <div className="flex gap-2 text-[11px] text-muted-foreground">
                  <span className="min-w-0 flex-1 truncate">{r.snippet}</span>
                  {r.waiting && <span className="shrink-0 font-medium text-amber-700 dark:text-amber-300">waiting</span>}
                </div>
              </button>
            ))}
          </div>
        </div>
        <div className={cn("min-h-0 flex-1 flex-col", open ? "flex" : "hidden md:flex")}>
          {open ? (
            <ConversationView key={open} id={open} onClose={() => setOpen(null)} />
          ) : (
            <p className="m-auto p-8 text-center text-sm text-muted-foreground">Choose a conversation.</p>
          )}
        </div>
      </div>
    </div>
  );
}
