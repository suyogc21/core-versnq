"use client";

import { Lock, MessageCircle, Paperclip, Send, StickyNote, UserPlus, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { CategoryChip, DraftPanel } from "@/components/crm/reply-tools";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { when } from "@/lib/crm";
import { type ConversationDetail, type LeadConversation, useCanned, useConversation, usePeople, useRefreshInbox, waLink } from "@/lib/inbox";
import { type Sorting, useSorting } from "@/lib/replies";
import { useWaTemplates } from "@/lib/whatsapp";
import { cn } from "@/lib/utils";

type Item = { at: string; kind: "message"; m: ConversationDetail["messages"][number] } | { at: string; kind: "note"; n: ConversationDetail["notes"][number] };

/** One conversation: the whole trail, notes, people, and the reply box (step 9b). */
export function ConversationView({ id, onClose }: { id: string; onClose?: () => void }) {
  const conv = useConversation(id);
  if (conv.isLoading) return <p className="p-6 text-sm text-muted-foreground">Loading…</p>;
  if (!conv.data) return <p className="p-6 text-sm text-muted-foreground">This conversation is not available.</p>;
  const data = conv.data;
  if (!data.lead) return <p className="p-6 text-sm text-muted-foreground">This is a campaign reply: open it in Outreach → Replies.</p>;
  return <View c={{ ...data, lead: data.lead }} onClose={onClose} />;
}

function View({ c, onClose }: { c: LeadConversation; onClose?: () => void }) {
  const refresh = useRefreshInbox();
  const people = usePeople(c.can_manage);
  const sorting = useSorting(c.id); // categories and the waiting draft (step O3)
  const sorted = new Map((sorting.data?.sortings ?? []).map((x) => [x.message_id, x]));
  const [adding, setAdding] = useState(false);
  const items: Item[] = [
    ...c.messages.map((m) => ({ at: m.sent_at ?? m.created_at, kind: "message" as const, m })),
    ...c.notes.map((n) => ({ at: n.created_at, kind: "note" as const, n })),
  ].sort((a, b) => a.at.localeCompare(b.at));

  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      refresh();
      if (ok) toast.success(ok);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const path = { params: { path: { conv_id: c.id } } };

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-conversation={c.subject ?? ""}>
      <div className="space-y-2 border-b px-4 py-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2 className="flex items-center gap-1.5 truncate text-base font-semibold">
              {c.channel === "whatsapp" && <MessageCircle className="size-4 shrink-0 text-emerald-600" aria-hidden />}
              {c.subject || "(no subject)"}
            </h2>
            <div className="text-xs text-muted-foreground">
              {c.lead.can_open ? (
                <Link href={`/leads/${c.lead.id}`} className="font-medium text-foreground hover:underline">
                  {c.lead.name}
                </Link>
              ) : (
                <span className="font-medium text-foreground">{c.lead.name}</span>
              )}
              {c.channel === "whatsapp" ? c.lead.phone && ` · ${c.lead.phone}` : c.lead.email && ` · ${c.lead.email}`}
              {c.lead.stage && ` · ${c.lead.stage}`}
              {c.lead.owner_name && ` · owner ${c.lead.owner_name}`}
            </div>
          </div>
          {c.is_private && (
            <span className="flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-muted-foreground">
              <Lock className="size-3" /> Private
            </span>
          )}
          {onClose && (
            <Button size="icon-sm" variant="ghost" aria-label="Close conversation" onClick={onClose}>
              <X />
            </Button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">With</span>
          {c.can_manage ? (
            <NativeSelect
              aria-label="Who it belongs to"
              className="h-7 w-auto"
              value={c.assignee_id ?? ""}
              onChange={(e) => act(async () => unwrap(await api.PUT("/api/v1/conversations/{conv_id}/assignee", { ...path, body: { user_id: e.target.value || null } })), "Handed on")}
            >
              <option value="">The lead&apos;s owner</option>
              {(people.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </NativeSelect>
          ) : (
            <span className="font-medium">{c.assignee_name ?? "Unassigned"}</span>
          )}
          {c.members.map((m) => (
            <span key={m.user_id} className="flex items-center gap-1 rounded-full border bg-muted/40 px-2 py-0.5" data-member={m.name}>
              {m.name}
              {c.can_manage && (
                <button aria-label={`Remove ${m.name}`} onClick={() => act(async () => unwrap(await api.DELETE("/api/v1/conversations/{conv_id}/members/{user_id}", { params: { path: { conv_id: c.id, user_id: m.user_id } } })))}>
                  <X className="size-3" />
                </button>
              )}
            </span>
          ))}
          {c.can_manage &&
            (adding ? (
              <NativeSelect
                aria-label="Add a colleague"
                className="h-7 w-auto"
                value=""
                onChange={(e) => {
                  setAdding(false);
                  if (e.target.value) act(async () => unwrap(await api.POST("/api/v1/conversations/{conv_id}/members", { ...path, body: { user_id: e.target.value } })), "Colleague added");
                }}
              >
                <option value="">Choose…</option>
                {(people.data ?? [])
                  .filter((p) => !c.members.some((m) => m.user_id === p.id))
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </NativeSelect>
            ) : (
              <Button size="sm" variant="ghost" className="h-7" onClick={() => setAdding(true)}>
                <UserPlus /> Add colleague
              </Button>
            ))}
          <span className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" className="h-7" onClick={() => act(async () => unwrap(await api.PATCH("/api/v1/conversations/{conv_id}", { ...path, body: { is_private: !c.is_private } })))}>
              {c.is_private ? "Make shared" : "Make private"}
            </Button>
            <Button size="sm" variant="outline" className="h-7" onClick={() => act(async () => unwrap(await api.PATCH("/api/v1/conversations/{conv_id}", { ...path, body: { status: c.status === "open" ? "closed" : "open" } })), c.status === "open" ? "Closed" : "Reopened")}>
              {c.status === "open" ? "Close" : "Reopen"}
            </Button>
          </span>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-4">
        {items.map((it) =>
          it.kind === "message" ? <MessageBubble key={it.m.id} c={c} m={it.m} sorting={sorted.get(it.m.id)} /> : <NoteBubble key={it.n.id} n={it.n} />,
        )}
      </div>
      {c.channel === "email" && (
        <div className="px-4 pb-2">
          <DraftPanel convId={c.id} onSent={refresh} />
        </div>
      )}
      <Composer c={c} />
    </div>
  );
}

function MessageBubble({ c, m, sorting }: { c: LeadConversation; m: ConversationDetail["messages"][number]; sorting?: Sorting }) {
  const mine = m.direction === "out";
  return (
    <div className={cn("max-w-[92%] rounded-xl border p-3 text-sm", mine ? "ml-auto bg-primary/5" : "bg-card")} data-message={m.direction}>
      <div className="mb-1 flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground">
          {mine ? (m.sent_by_name ?? (m.from_sequence ? "Sequence" : c.official ? "Automatic" : "You")) : (m.from_address ?? c.lead.name)}
        </span>
        <span>→ {m.to_address}</span>
        {m.cc.length > 0 && <span>cc {m.cc.join(", ")}</span>}
        {!mine && <CategoryChip convId={c.id} messageId={m.id} sorting={sorting} />}
        <span className="ml-auto">{when(m.sent_at ?? m.created_at)}</span>
      </div>
      {m.subject && <div className="mb-1 text-xs font-medium">{m.subject}</div>}
      <div className="break-words whitespace-pre-wrap">{m.body}</div>
      {m.attachments.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {m.attachments.map((a) => (
            <Attachment key={a.file_id} conv={c} file={a} />
          ))}
        </div>
      )}
      {c.official && mine && m.status !== "failed" ? (
        <div className="mt-1 text-[11px] text-muted-foreground" data-wa-status={m.status}>
          {{ queued: "Sending…", sent: "Sent", delivered: "Delivered", read: "Read" }[m.status] ?? m.status}
        </div>
      ) : (
        (m.error || (mine && (m.opened_at || m.status === "failed"))) && (
          <div className={cn("mt-1 text-[11px]", m.status === "failed" ? "text-destructive" : "text-muted-foreground")}>
            {m.status === "failed" ? `Not sent: ${m.error}` : m.error}
            {mine && m.opened_at && `Opened ${when(m.opened_at)} (estimated)${m.clicked_at ? " · clicked a link" : ""}`}
          </div>
        )
      )}
    </div>
  );
}

function NoteBubble({ n }: { n: ConversationDetail["notes"][number] }) {
  return (
    <div className="mx-auto max-w-[92%] rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm" data-note>
      <div className="mb-1 flex text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground">{n.user_name ?? "—"}</span>
        <span className="ml-2">internal note — the lead never sees this</span>
        <span className="ml-auto">{when(n.created_at)}</span>
      </div>
      <div className="break-words whitespace-pre-wrap">{n.body}</div>
    </div>
  );
}

function Attachment({ conv, file }: { conv: LeadConversation; file: ConversationDetail["messages"][number]["attachments"][number] }) {
  const refresh = useRefreshInbox();
  const [docs, setDocs] = useState<{ id: string; name: string }[] | null>(null);
  async function download() {
    const res = await api.GET("/api/v1/conversations/{conv_id}/attachments/{file_id}", { params: { path: { conv_id: conv.id, file_id: file.file_id } }, parseAs: "blob" });
    if (res.error || !res.data) return toast.error("Could not download");
    const href = URL.createObjectURL(res.data as Blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = file.name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(href), 30_000);
  }
  async function loadDocs() {
    try {
      const customer = unwrap(await api.GET("/api/v1/leads/{lead_id}/customer", { params: { path: { lead_id: conv.lead.id } } }));
      if (!customer) return toast.error("Make this lead a customer first, then save documents to their checklist");
      const list = unwrap(await api.GET("/api/v1/customers/{customer_id}/documents", { params: { path: { customer_id: customer.id } } }));
      setDocs(list.documents.map((d) => ({ id: d.id, name: d.name })));
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <span className="flex flex-col gap-1">
      {file.content_type.startsWith("image/") && <PhotoPreview conv={conv} file={file} />}
    <span className="flex items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs" data-attachment={file.name}>
      <Paperclip className="size-3" />
      <button className="hover:underline" onClick={download}>
        {file.name}
      </button>
      <span className="text-muted-foreground">{Math.max(1, Math.round(file.size_bytes / 1024))} KB</span>
      {docs === null ? (
        <button className="ml-1 text-muted-foreground hover:text-foreground" onClick={loadDocs}>
          Save to checklist
        </button>
      ) : (
        <NativeSelect
          aria-label={`Save ${file.name} as`}
          className="h-6 w-auto text-xs"
          value=""
          onChange={async (e) => {
            if (!e.target.value) return;
            try {
              unwrap(await api.POST("/api/v1/conversations/{conv_id}/attachments/{file_id}/to-document", { params: { path: { conv_id: conv.id, file_id: file.file_id } }, body: { document_id: e.target.value } }));
              toast.success("Saved to the checklist");
              setDocs(null);
              refresh();
            } catch (err) {
              toast.error((err as Error).message);
            }
          }}
        >
          <option value="">Which document?</option>
          {docs.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </NativeSelect>
      )}
    </span>
    </span>
  );
}

/** A photo sent or received on WhatsApp, shown small; fetched with the signed-in person's access. */
function PhotoPreview({ conv, file }: { conv: LeadConversation; file: ConversationDetail["messages"][number]["attachments"][number] }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    api
      .GET("/api/v1/conversations/{conv_id}/attachments/{file_id}", { params: { path: { conv_id: conv.id, file_id: file.file_id } }, parseAs: "blob" })
      .then((res) => {
        if (res.data) {
          url = URL.createObjectURL(res.data as Blob);
          setSrc(url);
        }
      })
      .catch(() => {});
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [conv.id, file.file_id]);
  if (!src) return null;
  // eslint-disable-next-line @next/next/no-img-element -- a private blob URL, not an optimisable asset
  return <img src={src} alt={file.name} className="max-h-48 max-w-64 rounded-md border object-contain" />;
}

/** Photo (JPG/PNG) or document (PDF, Word, Excel) on the company number; the reply text is its caption. */
async function sendWhatsAppFile(convId: string, file: File, caption: string) {
  return unwrap(
    await api.POST("/api/v1/conversations/{conv_id}/whatsapp-media", {
      params: { path: { conv_id: convId }, query: caption.trim() ? { caption: caption.trim().slice(0, 1024) } : {} },
      body: file as unknown as undefined, // the raw file (the API reads the request body)
      bodySerializer: (b: unknown) => b as BodyInit,
      headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name).slice(0, 200) },
    }),
  );
}

function Composer({ c }: { c: LeadConversation }) {
  const { me } = useAuth();
  const refresh = useRefreshInbox();
  const canned = useCanned();
  const people = usePeople();
  const wa = c.channel === "whatsapp" && !c.official; // a rep's own WhatsApp (step 10a)
  const official = c.official; // the company number: free text only inside the 24-hour window
  const waTemplates = useWaTemplates(official);
  const [tplId, setTplId] = useState("");
  const windowOpen = !official || !!c.window_ends_at;
  const [mode, setMode] = useState<"reply" | "note">(wa ? "note" : "reply");
  const [body, setBody] = useState("");
  const [cc, setCc] = useState("");
  const [mentions, setMentions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const path = { params: { path: { conv_id: c.id } } };

  async function send() {
    setBusy(true);
    try {
      if (mode === "reply") {
        unwrap(await api.POST("/api/v1/conversations/{conv_id}/reply", { ...path, body: { body, cc: cc.split(",").map((x) => x.trim()).filter(Boolean) } }));
        toast.success("Sent");
      } else {
        unwrap(await api.POST("/api/v1/conversations/{conv_id}/notes", { ...path, body: { body, mention_ids: mentions } }));
      }
      setBody("");
      setCc("");
      setMentions([]);
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={cn("space-y-2 border-t p-3", mode === "note" && "bg-amber-500/5")}>
      {wa && (
        <p className="text-xs text-muted-foreground" data-wa-hint>
          Answer on WhatsApp; it is logged here automatically by the Versnq extension.{" "}
          {waLink(c.lead.phone) && (
            <a href={waLink(c.lead.phone)!} target="_blank" rel="noopener noreferrer" className="font-medium text-foreground underline">
              Open in WhatsApp
            </a>
          )}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <div className="flex rounded-md border p-0.5">
          {(wa ? (["note"] as const) : (["reply", "note"] as const)).map((m) => (
            <button key={m} onClick={() => setMode(m)} className={cn("rounded px-2 py-0.5", mode === m && "bg-foreground text-background")}>
              {m === "reply" ? "Reply" : "Internal note"}
            </button>
          ))}
        </div>
        {mode === "reply" ? (
          <>
            {official ? (
              <span className={cn("text-[11px]", windowOpen ? "text-muted-foreground" : "text-amber-700 dark:text-amber-300")} data-wa-window>
                {windowOpen
                  ? `WhatsApp: free text until ${new Date(c.window_ends_at!).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                  : "24 hours since their last message: WhatsApp allows only an approved template"}
              </span>
            ) : (
              <Input aria-label="Cc" placeholder="Cc (comma separated)" className="h-7 w-56" value={cc} onChange={(e) => setCc(e.target.value)} />
            )}
            {(canned.data ?? []).length > 0 && (
              <NativeSelect aria-label="Saved reply" className="h-7 w-44" value="" onChange={(e) => { const r = canned.data?.find((x) => x.id === e.target.value); if (r) setBody((b) => (b ? `${b}\n\n${r.body}` : r.body)); }}>
                <option value="">Saved replies…</option>
                {(canned.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </NativeSelect>
            )}
          </>
        ) : (
          <NativeSelect
            aria-label="Mention"
            className="h-7 w-44"
            value=""
            onChange={(e) => {
              const p = people.data?.find((x) => x.id === e.target.value);
              if (!p) return;
              setMentions((ms) => [...new Set([...ms, p.id])]);
              setBody((b) => `${b}${b && !b.endsWith(" ") ? " " : ""}@${p.name} `);
            }}
          >
            <option value="">@ Mention…</option>
            {(people.data ?? []).filter((p) => p.id !== me?.id).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </NativeSelect>
        )}
      </div>
      {official && mode === "reply" && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <NativeSelect aria-label="WhatsApp template" className="h-7 w-64" value={tplId} onChange={(e) => setTplId(e.target.value)}>
            <option value="">{windowOpen ? "Or send a template…" : "Choose an approved template…"}</option>
            {(waTemplates.data ?? []).filter((t) => t.status === "approved").map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.category === "marketing" ? " (marketing)" : ""}
              </option>
            ))}
          </NativeSelect>
          <Button
            size="sm"
            variant="outline"
            disabled={!tplId || busy}
            onClick={async () => {
              setBusy(true);
              try {
                unwrap(await api.POST("/api/v1/conversations/{conv_id}/whatsapp-template", { ...path, body: { template_id: tplId } }));
                toast.success("Template sent");
                setTplId("");
                refresh();
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Send /> Send template
          </Button>
        </div>
      )}
      <Textarea
        disabled={mode === "reply" && !windowOpen}
        aria-label={mode === "reply" ? "Your reply" : "Your note"}
        rows={4}
        placeholder={mode === "reply" ? `Write to ${c.lead.name}…` : "Only your team sees this"}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <div className="flex items-center justify-end gap-2">
        {official && mode === "reply" && windowOpen && (
          <label className={cn("inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-accent", busy && "pointer-events-none opacity-50")}>
            <Paperclip className="size-3" /> Photo or PDF
            <input
              type="file"
              className="sr-only"
              aria-label="Send a photo or PDF"
              accept="image/jpeg,image/png,application/pdf,.doc,.docx,.xls,.xlsx"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                setBusy(true);
                try {
                  await sendWhatsAppFile(c.id, f, body);
                  toast.success(body.trim() ? "Sent with your text as the caption" : "Sent");
                  setBody("");
                  refresh();
                } catch (err) {
                  toast.error((err as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            />
          </label>
        )}
        <Button size="sm" disabled={!body.trim() || busy} onClick={send}>
          {mode === "reply" ? (
            <>
              <Send /> Send
            </>
          ) : (
            <>
              <StickyNote /> Add note
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
