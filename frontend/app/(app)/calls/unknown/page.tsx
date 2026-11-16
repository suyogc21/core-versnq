"use client";

import { useQuery } from "@tanstack/react-query";
import { PhoneIncoming, PhoneOutgoing } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { phoneApp, type UnknownCall } from "@/components/app/phone-app";
import { AddLeadDialog } from "@/components/crm/lead-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { useLeads } from "@/lib/crm";

/** Unknown calls (phone app): calls with numbers that aren't a lead. Nothing is created by
 * itself; the rep says who it was, and until then the call stays only on the phone. */
export default function UnknownCallsPage() {
  const [phone] = useState(phoneApp);
  const [calls, setCalls] = useState<UnknownCall[] | null>(null);
  const load = async () => (phone ? (await phone.unknownCalls()).calls : []);
  useEffect(() => {
    load()
      .then(setCalls)
      .catch(() => setCalls([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const reload = async () => setCalls(await load());

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader back={{ href: "/calls", label: "Calls" }} title="Calls not in Core" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-2xl space-y-3 p-4 sm:p-6">
          {!phone ? (
            <p className="text-sm text-muted-foreground">This list is on your phone: open it in the Versnq app.</p>
          ) : calls === null ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : calls.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing to review. Calls with numbers that aren&apos;t a lead show up here, and only on this phone.</p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                Who was it? Personal calls never go to Core, and calls you don&apos;t sort out are forgotten after 7 days.
              </p>
              {calls.map((c) => (
                <UnknownRow key={c.id} call={c} onDone={reload} />
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function UnknownRow({ call, onDone }: { call: UnknownCall; onDone: () => Promise<void> }) {
  const phone = phoneApp()!;
  const [mode, setMode] = useState<"" | "new" | "existing">("");
  const when = new Date(call.date);
  const length = call.seconds ? `${Math.floor(call.seconds / 60)}m ${call.seconds % 60}s` : call.direction === "in" ? "missed" : "not answered";

  async function send(ok: string) {
    const r = await phone.sendUnknown({ id: call.id });
    if (r.tracked) toast.success(ok);
    else toast.error("Couldn't put the call on the lead yet. It's kept here; try again when you're online.");
    await onDone();
  }

  return (
    <div className="surface space-y-3 p-3 text-sm">
      <div className="flex items-center gap-2">
        {call.direction === "in" ? <PhoneIncoming className="size-4" /> : <PhoneOutgoing className="size-4" />}
        <span className="font-medium">{call.number}</span>
        <span className="text-muted-foreground">
          {when.toLocaleString()} · {length}
        </span>
      </div>
      {mode === "" && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setMode("new")}>
            New lead
          </Button>
          <Button size="sm" variant="outline" onClick={() => setMode("existing")}>
            A lead&apos;s other number
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={async () => {
              await phone.dismissUnknown({ id: call.id });
              await onDone();
            }}
          >
            Personal
          </Button>
        </div>
      )}
      {mode === "new" && (
        <AddLeadDialog phone={call.number} onClose={() => setMode("")} onCreated={() => send("Lead added, with this call on it.")} />
      )}
      {mode === "existing" && <PickLead call={call} onCancel={() => setMode("")} onPicked={() => send("Number added to the lead, with this call on it.")} />}
    </div>
  );
}

/** Which lead was it? The leads you called just before come first ("we'll call you back from
 * another number"); otherwise search. The number is then added to that lead. */
function PickLead({ call, onCancel, onPicked }: { call: UnknownCall; onCancel: () => void; onPicked: () => Promise<void> }) {
  const { me } = useAuth();
  const [q, setQ] = useState("");
  const found = useLeads({ q: q || undefined, limit: 8 });
  const recent = useQuery({
    queryKey: ["calls-before", call.id],
    queryFn: async () => {
      const mine = unwrap(await api.GET("/api/v1/calls", { params: { query: { user_id: me!.id, limit: 50 } } }));
      const since = call.date - 3 * 3600_000;
      const seen = new Map<string, string>();
      for (const c of mine) {
        const t = new Date(c.started_at).getTime();
        if (c.lead_id && c.lead_name && t >= since && t <= call.date && !seen.has(c.lead_id)) seen.set(c.lead_id, c.lead_name);
      }
      return [...seen].map(([id, name]) => ({ id, name }));
    },
    enabled: Boolean(me),
  });

  async function pick(leadId: string) {
    try {
      unwrap(await api.POST("/api/v1/leads/{lead_id}/numbers", { params: { path: { lead_id: leadId } }, body: { number: call.number } }));
      await onPicked();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const items = (found.data?.items ?? []).map((l) => ({ id: l.id, name: l.display_name }));
  return (
    <div className="space-y-2">
      {(recent.data ?? []).length > 0 && (
        <div className="space-y-1">
          <p className="text-muted-foreground">You called them just before:</p>
          {recent.data!.map((l) => (
            <Button key={l.id} size="sm" variant="outline" className="mr-2" onClick={() => pick(l.id)}>
              {l.name}
            </Button>
          ))}
        </div>
      )}
      <Input placeholder="Search leads by name, email or phone" value={q} onChange={(e) => setQ(e.target.value)} />
      {q && (
        <ul className="divide-y rounded-md border">
          {items.map((l) => (
            <li key={l.id}>
              <button type="button" className="w-full px-3 py-2 text-left hover:bg-accent" onClick={() => pick(l.id)}>
                {l.name}
              </button>
            </li>
          ))}
          {items.length === 0 && <li className="px-3 py-2 text-muted-foreground">No leads found</li>}
        </ul>
      )}
      <Button size="sm" variant="ghost" onClick={onCancel}>
        Back
      </Button>
    </div>
  );
}
