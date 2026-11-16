"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { CategoryChip, DraftPanel } from "@/components/crm/reply-tools";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { relative } from "@/lib/crm";
import { useModuleOn } from "@/lib/modules";
import {
  STATE_LABEL,
  STATUS_LABEL,
  useCampaigns,
  useOutreachConversation,
  useOutreachInbox,
  useRefreshOutreach,
} from "@/lib/outreach";
import { useSorting } from "@/lib/replies";
import { cn } from "@/lib/utils";

type Tab = "campaigns" | "replies";

export default function OutreachPage() {
  const { can } = useAuth();
  const on = useModuleOn("outreach");
  const [tab, setTab] = useState<Tab>("campaigns");
  if (!on) return <p className="p-8 text-center text-muted-foreground">Outreach is not switched on for your company yet.</p>;
  if (!can("outreach.reply") && !can("campaigns.manage")) {
    return <p className="p-8 text-center text-muted-foreground">You don&apos;t have permission to do that.</p>;
  }
  const tabs: [Tab, string][] = [
    ["campaigns", "Campaigns"],
    ["replies", "Replies"],
  ];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Outreach" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-5xl p-4 sm:p-6">
          <p className="mb-4 text-sm text-muted-foreground">
            Cold email from your sending inboxes. <strong className="font-medium text-foreground">Already your lead? Never a cold email:</strong> anyone
            who is a lead or customer is skipped, and anyone who becomes one stops at once.
          </p>
          <div className="mb-5 flex gap-4 overflow-x-auto border-b text-sm" role="tablist">
            {tabs.map(([key, name]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={cn("-mb-px border-b-2 border-transparent pb-2 whitespace-nowrap text-muted-foreground", tab === key && "border-primary font-medium text-foreground")}
              >
                {name}
              </button>
            ))}
          </div>
          {tab === "campaigns" ? <CampaignList /> : <Replies />}
        </div>
      </div>
    </div>
  );
}

function CampaignList() {
  const { can } = useAuth();
  const list = useCampaigns();
  const router = useRouter();
  const refresh = useRefreshOutreach();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <div className="space-y-4">
      <div className="divide-y surface">
        {(list.data ?? []).length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "No campaigns yet."}</p>
        )}
        {(list.data ?? []).map((c) => (
          <div key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm" data-campaign={c.name}>
            <Link href={`/outreach/${c.id}`} className="font-medium hover:underline">
              {c.name}
            </Link>
            <Badge variant={c.status === "running" ? "secondary" : "outline"}>{STATUS_LABEL[c.status] ?? c.status}</Badge>
            <span className="text-xs text-muted-foreground tabular-nums">
              {c.counts.contacts} contacts · {c.counts.sent} sent · {c.counts.replied} replies · {c.counts.bounced} bounced ·{" "}
              {c.counts.unsubscribed} unsubscribed
            </span>
            {c.owner_name && <span className="ms-auto text-xs text-muted-foreground">{c.owner_name}</span>}
          </div>
        ))}
      </div>
      {can("campaigns.manage") &&
        (adding ? (
          <div className="space-y-2 surface p-3">
            <Input autoFocus aria-label="Campaign name" placeholder="e.g. Founders in Pune, November" value={name} onChange={(e) => setName(e.target.value)} />
            <Textarea
              aria-label="What you offer"
              placeholder="What you offer, in a few lines (optional). ACE uses it to understand replies."
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={!name.trim()}
                onClick={async () => {
                  try {
                    const c = unwrap(await api.POST("/api/v1/campaigns", { body: { name, description: description || null, daily_cap: 500, mailbox_ids: [], track_opens: false, track_clicks: false } }));
                    refresh();
                    router.push(`/outreach/${c.id}`);
                  } catch (e) {
                    toast.error((e as Error).message);
                  }
                }}
              >
                Create
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <Button size="sm" onClick={() => setAdding(true)}>
            <Plus /> New campaign
          </Button>
        ))}
    </div>
  );
}

// ---------- replies: the outreach inbox ----------
function Replies() {
  const campaigns = useCampaigns();
  const [campaignId, setCampaignId] = useState("");
  const [state, setState] = useState("");
  const [auto, setAuto] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const list = useOutreachInbox({ campaign_id: campaignId, state, include_auto: auto });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect aria-label="Campaign" className="w-auto" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
          <option value="">All campaigns</option>
          {(campaigns.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="State" className="w-auto" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">Every reply</option>
          {["new", "replied", "not_interested"].map((s) => (
            <option key={s} value={s}>
              {STATE_LABEL[s]}
            </option>
          ))}
        </NativeSelect>
        <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Show out-of-office replies
        </label>
      </div>
      <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className={cn("divide-y surface", open && "hidden md:block")}>
          {(list.data ?? []).length === 0 && (
            <p className="p-4 text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "No replies yet. They appear here as people write back."}</p>
          )}
          {(list.data ?? []).map((c) => (
            <button
              key={c.id}
              onClick={() => setOpen(c.id)}
              className={cn("block w-full px-3 py-2.5 text-start text-sm hover:bg-muted/50", open === c.id && "bg-muted/60")}
              data-reply={c.contact.email}
            >
              <div className="flex items-center gap-2">
                <span className="truncate font-medium">{[c.contact.first_name, c.contact.last_name].filter(Boolean).join(" ") || c.contact.email}</span>
                <Badge variant={c.state === "new" ? "secondary" : "outline"} className="ms-auto shrink-0">
                  {STATE_LABEL[c.state] ?? c.state}
                </Badge>
              </div>
              <div className="truncate text-xs text-muted-foreground">
                {c.contact.company ? `${c.contact.company} · ` : ""}
                {c.campaign_name} · {c.last_message_at ? relative(c.last_message_at) : ""}
              </div>
            </button>
          ))}
        </div>
        <div className={cn(!open && "hidden md:block")}>
          {open ? <Thread id={open} onBack={() => setOpen(null)} /> : <p className="p-4 text-sm text-muted-foreground">Choose a reply.</p>}
        </div>
      </div>
    </div>
  );
}

function Thread({ id, onBack }: { id: string; onBack: () => void }) {
  const { can } = useAuth();
  const conv = useOutreachConversation(id);
  const sorting = useSorting(id); // categories and the waiting draft (step O3)
  const refresh = useRefreshOutreach();
  const router = useRouter();
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  if (!conv.data) return <p className="p-4 text-sm text-muted-foreground">{conv.isError ? "Not found" : "Loading…"}</p>;
  const c = conv.data;
  const reload = async () => {
    await conv.refetch();
    refresh();
  };
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await fn();
      toast.success(done);
      await reload();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3 surface p-3" data-thread={c.contact.email}>
      <button className="text-xs text-muted-foreground md:hidden" onClick={onBack}>
        ← All replies
      </button>
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0">
          <div className="font-semibold">{[c.contact.first_name, c.contact.last_name].filter(Boolean).join(" ") || c.contact.email}</div>
          <div className="break-all text-xs text-muted-foreground">
            {c.contact.email}
            {c.contact.title ? ` · ${c.contact.title}` : ""}
            {c.contact.company ? ` · ${c.contact.company}` : ""} · {c.campaign_name}
          </div>
        </div>
        <div className="ms-auto flex flex-wrap gap-1.5">
          {can("leads.create") && c.contact.status !== "converted" && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  const r = unwrap(await api.POST("/api/v1/contacts/{contact_id}/convert", { params: { path: { contact_id: c.contact.id } } }));
                  router.push(`/leads/${r.lead_id}`);
                }, "Converted to a lead")
              }
            >
              Convert to lead
            </Button>
          )}
          {c.contact.status === "converted" && c.contact.lead_id && (
            <Button size="sm" variant="outline" onClick={() => router.push(`/leads/${c.contact.lead_id}`)}>
              Open lead
            </Button>
          )}
          {c.state !== "not_interested" && c.contact.status !== "converted" && c.campaign_id && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() =>
                act(
                  async () =>
                    unwrap(
                      await api.POST("/api/v1/campaigns/{campaign_id}/contacts/{contact_id}/stop", {
                        params: { path: { campaign_id: c.campaign_id as string, contact_id: c.contact.id } },
                      }),
                    ),
                  "Marked not interested",
                )
              }
            >
              Not interested
            </Button>
          )}
          {c.contact.status === "active" && (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                if (!confirm(`Never email ${c.contact.email} again, from any campaign?`)) return;
                act(async () => unwrap(await api.POST("/api/v1/contacts/{contact_id}/unsubscribe", { params: { path: { contact_id: c.contact.id } } })), "Unsubscribed");
              }}
            >
              Unsubscribe
            </Button>
          )}
        </div>
      </div>
      <div className="space-y-2">
        {c.messages.map((m) => (
          <div key={m.id} className={cn("rounded-lg border p-2.5 text-sm", m.direction === "in" ? "bg-card" : "bg-muted/40")}>
            <div className="mb-1 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
              <span>{m.direction === "in" ? m.from_address : `You · ${m.from_address}`}</span>
              {m.auto_submitted && <Badge variant="outline">Out of office</Badge>}
              {m.direction === "in" && !m.auto_submitted && (
                <CategoryChip
                  convId={id}
                  messageId={m.id}
                  sorting={sorting.data?.sortings.find((x) => x.message_id === m.id)}
                  onChanged={reload}
                />
              )}
              {m.status === "failed" && <Badge variant="destructive">Not sent</Badge>}
              <span className="ms-auto">{m.sent_at ? relative(m.sent_at) : ""}</span>
            </div>
            {m.subject && <div className="mb-1 font-medium">{m.subject}</div>}
            <div className="whitespace-pre-wrap break-words">{m.body}</div>
          </div>
        ))}
      </div>
      <DraftPanel convId={id} onSent={reload} />
      {can("outreach.reply") && (
        <div className="space-y-2">
          <Textarea aria-label="Your answer" placeholder="Write your answer…" rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
          <Button
            size="sm"
            disabled={!body.trim() || busy}
            onClick={() =>
              act(async () => {
                unwrap(await api.POST("/api/v1/outreach/conversations/{conv_id}/reply", { params: { path: { conv_id: id } }, body: { body } }));
                setBody("");
              }, "Sent from the same inbox")
            }
          >
            Send answer
          </Button>
        </div>
      )}
    </div>
  );
}
