"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { CopyInAddress } from "@/components/crm/copy-in";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { relative, useSources } from "@/lib/crm";
import { useCompanyCopyIn, useExclusions, useMailboxes } from "@/lib/mailboxes";

const STATUS: Record<string, [string, "secondary" | "destructive" | "outline"]> = {
  active: ["Syncing", "secondary"],
  error: ["Needs attention", "destructive"],
  off: ["Disconnected", "outline"],
};

export default function InboxesSettingsPage() {
  return (
    <>
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Connected inboxes" />
      <div className="mx-auto w-full max-w-3xl space-y-8 p-4 sm:p-8">
        <p className="text-muted-foreground">
          Each person connects their own mailbox under My account. Only emails with known leads are kept. Who sees an email follows who can see the lead,
          unless the person made the conversation private.
        </p>
        <Mailboxes />
        <CompanyCopyIn />
        <Exclusions />
      </div>
    </>
  );
}

function Mailboxes() {
  const list = useMailboxes();
  const qc = useQueryClient();
  const act = async (fn: () => Promise<unknown>, done: (r: unknown) => string) => {
    try {
      const r = await fn();
      toast.success(done(r));
      await qc.invalidateQueries({ queryKey: ["mailbox"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const rows = list.data ?? [];
  return (
    <section className="space-y-3">
      <h2 className="font-semibold">Who is connected</h2>
      <div className="divide-y surface">
        {rows.length === 0 && <p className="p-4 text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "Nobody has connected a mailbox yet."}</p>}
        {rows.map((m) => (
          <div key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm" data-mailbox-row={m.email_address}>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{m.user_name}</span>
                <span className="break-all text-muted-foreground">{m.email_address}</span>
                <Badge variant={STATUS[m.status]?.[1] ?? "outline"}>{STATUS[m.status]?.[0] ?? m.status}</Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                {m.synced} email{m.synced === 1 ? "" : "s"} kept · last checked {m.last_sync_at ? relative(m.last_sync_at) : "not yet"}
                {m.last_error && ` · ${m.last_error}`}
              </p>
            </div>
            <div className="ml-auto flex gap-1">
              {m.status !== "off" ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    confirm(`Disconnect ${m.email_address}? Syncing stops and its password is forgotten.`) &&
                    act(async () => unwrap(await api.POST("/api/v1/mailboxes/{mb_id}/disconnect", { params: { path: { mb_id: m.id } } })), () => "Disconnected")
                  }
                >
                  Disconnect
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    confirm(`Remove the emails ${m.email_address} brought in from mail apps? They go from every lead's timeline. Emails written in Core stay.`) &&
                    act(
                      async () => unwrap(await api.DELETE("/api/v1/mailboxes/{mb_id}/emails", { params: { path: { mb_id: m.id } } })),
                      (r) => `${(r as { removed: number }).removed} emails removed`,
                    )
                  }
                >
                  Remove its emails
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function CompanyCopyIn() {
  const data = useCompanyCopyIn();
  const sources = useSources();
  const qc = useQueryClient();
  const [create, setCreate] = useState<boolean | null>(null);
  const [source, setSource] = useState<string | null>(null);
  if (!data.data) return null;
  const d = data.data;
  const createLeads = create ?? d.create_leads;
  const sourceId = source ?? d.source_id ?? "";
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
      setCreate(null);
      setSource(null);
      await qc.invalidateQueries({ queryKey: ["copy-in"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-semibold">Company copy-in address</h2>
        <p className="text-sm text-muted-foreground">
          For shared mailboxes like sales@ or info@: auto-forward them here, or CC it, and emails land on the right lead. Each person also has their own under My account.
        </p>
      </div>
      <CopyInAddress
        address={d.address}
        live={d.live}
        onReset={() => run(async () => unwrap(await api.POST("/api/v1/copy-in/reset")), "New address made. Update your forwarding.")}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="ci-unknown">When an email is with nobody we know</Label>
          <NativeSelect id="ci-unknown" value={createLeads ? "create" : "drop"} onChange={(e) => setCreate(e.target.value === "create")}>
            <option value="drop">Don&apos;t keep it</option>
            <option value="create">Create a lead for them</option>
          </NativeSelect>
        </div>
        {createLeads && (
          <div className="space-y-1.5">
            <Label htmlFor="ci-source">Source for those leads</Label>
            <NativeSelect id="ci-source" value={sourceId} onChange={(e) => setSource(e.target.value)}>
              <option value="">Choose…</option>
              {(sources.data ?? []).filter((x) => x.is_active).map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </NativeSelect>
          </div>
        )}
      </div>
      <Button
        variant="outline"
        onClick={() =>
          run(
            async () => unwrap(await api.PUT("/api/v1/copy-in", { body: { create_leads: createLeads, source_id: createLeads ? sourceId || null : null } })),
            "Saved",
          )
        }
      >
        Save
      </Button>
    </section>
  );
}

function Exclusions() {
  const current = useExclusions();
  const qc = useQueryClient();
  const [text, setText] = useState<string | null>(null);
  const value = text ?? (current.data?.items ?? []).join("\n");
  const save = async () => {
    try {
      const items = value.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
      const out = unwrap(await api.PUT("/api/v1/mailboxes/exclusions", { body: { items } }));
      setText(out.items.join("\n"));
      toast.success("Saved");
      await qc.invalidateQueries({ queryKey: ["mailbox", "exclusions"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-semibold">Never sync</h2>
        <p className="text-sm text-muted-foreground">
          Addresses or domains whose emails are never brought in from anyone&apos;s mailbox, even if they are leads: your lawyers, auditors, family. One per line, like
          name@firm.com or @firm.com.
        </p>
      </div>
      <Label htmlFor="exclusions" className="sr-only">
        Never sync
      </Label>
      <Textarea id="exclusions" rows={5} value={value} onChange={(e) => setText(e.target.value)} placeholder="@lawfirm.com" />
      <Button onClick={save}>Save</Button>
    </section>
  );
}
