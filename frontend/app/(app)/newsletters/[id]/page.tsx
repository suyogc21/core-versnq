"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { type Audience, type Newsletter, pct, STATUS_LABELS, useNewsletter } from "@/lib/newsletters";
import { useMailboxes } from "@/lib/mailboxes";
import { useTags, useViews } from "@/lib/organise";
import { VARIABLES } from "@/lib/sequences";

/** One newsletter: write it, choose who gets it, test it, send or schedule it, see results. */
export default function NewsletterPage() {
  const { id } = useParams<{ id: string }>();
  const nl = useNewsletter(id);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader back={{ href: "/newsletters", label: "Newsletters" }} title={nl.data?.name ?? "Newsletter"} />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-3xl space-y-6 p-4 sm:p-6">
          {!nl.data ? (
            <p className="text-sm text-muted-foreground">{nl.isError ? "Not found" : "Loading…"}</p>
          ) : nl.data.status === "draft" ? (
            <Editor key={nl.data.updated_at} nl={nl.data} />
          ) : (
            <Results nl={nl.data} />
          )}
        </div>
      </div>
    </div>
  );
}

function Editor({ nl }: { nl: Newsletter }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const router = useRouter();
  const tags = useTags();
  const views = useViews("leads");
  const mailboxes = useMailboxes(can("mailboxes.manage"));
  const [v, setV] = useState({
    name: nl.name,
    subject: nl.subject,
    preheader: nl.preheader ?? "",
    body: nl.body,
    path: nl.path as "mailboxes" | "postmark",
    mailbox_id: nl.mailbox_id ?? "",
    from_name: nl.from_name ?? "",
    from_email: nl.from_email ?? "",
  });
  const start = nl.audience as { view_id?: string | null; filter?: { tag?: string[] }; customers_only?: boolean };
  const [viewId, setViewId] = useState(start.view_id ?? "");
  const [tagIds, setTagIds] = useState<string[]>(start.filter?.tag ?? []);
  const [customersOnly, setCustomersOnly] = useState(Boolean(start.customers_only));
  const [sendAt, setSendAt] = useState("");
  const [busy, setBusy] = useState(false);
  const audience: Audience = { view_id: viewId || null, filter: tagIds.length ? { tag: tagIds } : {}, customers_only: customersOnly };
  const count = useQuery({
    queryKey: ["newsletter-count", audience],
    queryFn: async () => unwrap(await api.POST("/api/v1/newsletters/audience-count", { body: audience })),
  });

  async function save(quiet = false) {
    unwrap(
      await api.PATCH("/api/v1/newsletters/{nl_id}", {
        params: { path: { nl_id: nl.id } },
        body: {
          ...v,
          preheader: v.preheader || null,
          mailbox_id: v.mailbox_id || null,
          from_name: v.from_name || null,
          from_email: v.from_email || null,
          audience,
        },
      }),
    );
    if (!quiet) {
      toast.success("Saved");
      qc.invalidateQueries({ queryKey: ["newsletter", nl.id] });
    }
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const test = () =>
    run(async () => {
      await save(true);
      unwrap(await api.POST("/api/v1/newsletters/{nl_id}/test", { params: { path: { nl_id: nl.id } } }));
      toast.success("A test copy is on its way to you");
    });
  const send = () =>
    run(async () => {
      const n = count.data?.reachable ?? 0;
      if (!confirm(sendAt ? `Schedule this newsletter for ${n} people?` : `Send this newsletter to ${n} people now?`)) return;
      await save(true);
      unwrap(
        await api.POST("/api/v1/newsletters/{nl_id}/send", {
          params: { path: { nl_id: nl.id } },
          body: { send_at: sendAt ? new Date(sendAt).toISOString() : null },
        }),
      );
      toast.success(sendAt ? "Scheduled" : "Sending");
      qc.invalidateQueries({ queryKey: ["newsletter", nl.id] });
      qc.invalidateQueries({ queryKey: ["newsletters"] });
    });
  const remove = () =>
    run(async () => {
      if (!confirm(`Delete the draft ${nl.name}?`)) return;
      unwrap(await api.DELETE("/api/v1/newsletters/{nl_id}", { params: { path: { nl_id: nl.id } } }));
      router.push("/newsletters");
    });

  const pool = (mailboxes.data ?? []).filter((m) => m.status === "active");
  return (
    <>
      <section className="surface space-y-4 p-4 text-sm">
        <h2 className="font-semibold">The email</h2>
        <div className="space-y-1.5">
          <Label htmlFor="nl-name">Name (only you see it)</Label>
          <Input id="nl-name" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="nl-subject">Subject</Label>
          <Input id="nl-subject" value={v.subject} onChange={(e) => setV({ ...v, subject: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="nl-pre">Preview text (shown after the subject in the inbox)</Label>
          <Input id="nl-pre" value={v.preheader} onChange={(e) => setV({ ...v, preheader: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="nl-body">Message</Label>
          <Textarea id="nl-body" rows={12} value={v.body} onChange={(e) => setV({ ...v, body: e.target.value })} />
          <p className="text-muted-foreground">
            Plain text: a blank line starts a new paragraph, links become clickable. Every email ends with an unsubscribe link. Insert:{" "}
            {VARIABLES.map(([code, label]) => (
              <button key={code} type="button" className="me-2 underline" onClick={() => setV({ ...v, body: `${v.body}${code}` })}>
                {label}
              </button>
            ))}
          </p>
        </div>
      </section>

      <section className="surface space-y-4 p-4 text-sm">
        <h2 className="font-semibold">Who gets it</h2>
        <div className="space-y-1.5">
          <Label htmlFor="nl-view">A saved view of leads</Label>
          <select id="nl-view" className="h-9 w-full rounded-md border bg-background px-2" value={viewId} onChange={(e) => setViewId(e.target.value)}>
            <option value="">— none —</option>
            {(views.data ?? []).map((sv) => (
              <option key={sv.id} value={sv.id}>
                {sv.name}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label>With any of these tags</Label>
          <div className="flex flex-wrap gap-1.5">
            {(tags.data ?? []).map((t) => {
              const on = tagIds.includes(t.id);
              return (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={on}
                  className={`rounded-full border px-2.5 py-1 text-xs ${on ? "bg-foreground text-background" : ""}`}
                  onClick={() => setTagIds(on ? tagIds.filter((x) => x !== t.id) : [...tagIds, t.id])}
                >
                  {t.name}
                </button>
              );
            })}
            {(tags.data ?? []).length === 0 && <span className="text-muted-foreground">No tags yet.</span>}
          </div>
        </div>
        <label className="flex items-center gap-3">
          <Switch aria-label="Only customers" checked={customersOnly} onCheckedChange={setCustomersOnly} />
          Only customers
        </label>
        <p data-testid="audience-count">
          {count.data ? (
            <>
              <span className="font-medium">{count.data.reachable}</span> of {count.data.matching} people can get it (the others have no email address,
              unsubscribed or opted out).
            </>
          ) : (
            "Counting…"
          )}
        </p>
      </section>

      <section className="surface space-y-4 p-4 text-sm">
        <h2 className="font-semibold">Sending</h2>
        <label className="flex items-start gap-3">
          <input type="radio" name="path" checked={v.path === "mailboxes"} onChange={() => setV({ ...v, path: "mailboxes" })} className="mt-1" />
          <span>
            <span className="font-medium">Your own inboxes</span>
            <span className="block text-muted-foreground">
              For small lists: each inbox&apos;s daily limit holds, so a big list goes out over several days. Gmail and Zoho block inboxes that send too much.
            </span>
          </span>
        </label>
        {v.path === "mailboxes" && pool.length > 0 && (
          <select aria-label="From inbox" className="h-9 w-full rounded-md border bg-background px-2" value={v.mailbox_id} onChange={(e) => setV({ ...v, mailbox_id: e.target.value })}>
            <option value="">The sending pool (each lead&apos;s owner first)</option>
            {pool.map((m) => (
              <option key={m.id} value={m.id}>
                {m.email_address}
              </option>
            ))}
          </select>
        )}
        <label className="flex items-start gap-3">
          <input type="radio" name="path" checked={v.path === "postmark"} onChange={() => setV({ ...v, path: "postmark" })} className="mt-1" />
          <span>
            <span className="font-medium">Postmark (bulk sending)</span>
            <span className="block text-muted-foreground">For big lists, once Postmark is set up. The From address must be verified in Postmark.</span>
          </span>
        </label>
        {v.path === "postmark" && (
          <div className="grid gap-2 sm:grid-cols-2">
            <Input aria-label="From name" placeholder="From name" value={v.from_name} onChange={(e) => setV({ ...v, from_name: e.target.value })} />
            <Input aria-label="From address" placeholder="news@yourcompany.com" value={v.from_email} onChange={(e) => setV({ ...v, from_email: e.target.value })} />
          </div>
        )}
        <div className="space-y-1.5">
          <Label htmlFor="nl-at">Send later (empty = now)</Label>
          <Input id="nl-at" type="datetime-local" value={sendAt} onChange={(e) => setSendAt(e.target.value)} className="max-w-64" />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => run(() => save())}>
            Save
          </Button>
          <Button variant="outline" disabled={busy} onClick={test}>
            Send me a test
          </Button>
          <Button disabled={busy || !count.data?.reachable} onClick={send}>
            {sendAt ? "Schedule" : "Send now"}
          </Button>
          <Button variant="ghost" className="ms-auto" disabled={busy} onClick={remove}>
            Delete draft
          </Button>
        </div>
      </section>
    </>
  );
}

function Results({ nl }: { nl: Newsletter }) {
  const qc = useQueryClient();
  const r = nl.report;
  const people = useQuery({
    queryKey: ["newsletter-recipients", nl.id, r.sent],
    queryFn: async () => unwrap(await api.GET("/api/v1/newsletters/{nl_id}/recipients", { params: { path: { nl_id: nl.id } } })),
  });
  async function cancel() {
    if (!confirm("Stop this newsletter? Copies not sent yet won't be sent.")) return;
    try {
      unwrap(await api.POST("/api/v1/newsletters/{nl_id}/cancel", { params: { path: { nl_id: nl.id } } }));
      qc.invalidateQueries({ queryKey: ["newsletter", nl.id] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  const tiles: [string, string][] = [
    ["Sent", `${r.sent} of ${r.recipients}`],
    ["Opened", `${r.opened} · ${pct(r.opened, r.sent)}`],
    ["Clicked", `${r.clicked} · ${pct(r.clicked, r.sent)}`],
    ["Unsubscribed", `${r.unsubscribed}`],
    ["Bounced", `${r.bounced}`],
    ["Not sent", `${r.failed + r.skipped}`],
  ];
  return (
    <>
      <section className="surface space-y-3 p-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{STATUS_LABELS[nl.status] ?? nl.status}</span>
          <span className="text-muted-foreground">
            {nl.status === "scheduled" && nl.send_at ? `Goes out ${new Date(nl.send_at).toLocaleString()}` : nl.subject}
          </span>
          {["scheduled", "sending"].includes(nl.status) && (
            <Button size="sm" variant="outline" className="ms-auto" onClick={cancel}>
              Cancel
            </Button>
          )}
        </div>
        {nl.status === "sending" && r.queued > 0 && (
          <p className="text-muted-foreground">{r.queued} still waiting. Through your own inboxes, the rest goes out as each inbox&apos;s daily limit allows.</p>
        )}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {tiles.map(([label, value]) => (
            <div key={label} className="rounded-md border p-3">
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className="text-lg font-semibold">{value}</div>
            </div>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">Opens are estimates: some mail apps block the tracking image, others open every email.</p>
      </section>
      <section className="surface space-y-2 p-4 text-sm">
        <h2 className="font-semibold">People</h2>
        <ul className="divide-y">
          {(people.data ?? []).map((p) => (
            <li key={p.email} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="font-medium">{p.name ?? p.email}</span>
              <span className="text-muted-foreground">{p.email}</span>
              <span className="ms-auto text-xs text-muted-foreground">
                {p.status === "sent"
                  ? [p.bounced && "bounced", p.unsubscribed && "unsubscribed", p.clicked ? "clicked" : p.opened && "opened"].filter(Boolean).join(" · ") || "sent"
                  : p.status === "queued"
                    ? "waiting"
                    : `${p.status}${p.reason ? `: ${p.reason}` : ""}`}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
