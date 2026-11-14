"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Field } from "@/components/app/field";
import { NativeSelect } from "@/components/app/native-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { CopyInAddress } from "@/components/crm/copy-in";
import { relative } from "@/lib/crm";
import { type Mailbox, type ProviderKey, PROVIDERS, providerOf, useMyCopyIn, useMyMailbox } from "@/lib/mailboxes";
import { useModuleOn } from "@/lib/modules";

const STATUS: Record<string, [string, "secondary" | "destructive" | "outline"]> = {
  active: ["Syncing", "secondary"],
  error: ["Needs attention", "destructive"],
};

/** "Connected inbox" on My account (step 9b-3): the user's own mailbox, by app password. */
export function MyMailbox() {
  const copyOn = useModuleOn("copy_in");
  const mine = useMyMailbox();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const mb = mine.data ?? null;
  const refresh = () => qc.invalidateQueries({ queryKey: ["mailbox"] });

  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      toast.success(done);
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <section className="space-y-3 border-b pb-8 last:border-0" data-mailbox>
      <div>
        <h2 className="font-semibold">Connected inbox</h2>
        <p className="text-muted-foreground">
          Your emails with leads, from any device, appear on their timeline, and emails you write in Core go from your own address.
          Only emails with known leads are kept, never the rest of your mailbox.
        </p>
      </div>
      {mine.isLoading ? null : mb && !editing ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium break-all">{mb.email_address}</span>
            <Badge variant={STATUS[mb.status]?.[1] ?? "outline"}>{STATUS[mb.status]?.[0] ?? mb.status}</Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            Last checked {mb.last_sync_at ? relative(mb.last_sync_at) : "not yet"} · {mb.synced} email{mb.synced === 1 ? "" : "s"} with leads kept
          </p>
          {mb.last_error && <p className="text-sm text-destructive">{mb.last_error}</p>}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => act(async () => unwrap(await api.POST("/api/v1/me/mailbox/sync")), "Checking your mailbox now.")}>
              Sync now
            </Button>
            <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
              {mb.status === "error" ? "Reconnect" : "Change"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                window.confirm("Disconnect your mailbox? Syncing stops and the password is forgotten. Emails already on leads stay.") &&
                act(async () => unwrap(await api.DELETE("/api/v1/me/mailbox")), "Disconnected.")
              }
            >
              Disconnect
            </Button>
          </div>
        </div>
      ) : (
        <ConnectForm
          current={mb}
          onCancel={mb ? () => setEditing(false) : undefined}
          onDone={async () => {
            setEditing(false);
            await refresh();
          }}
        />
      )}
      {copyOn && <MyCopyIn />}
    </section>
  );
}

/** Works from any mail app, no mailbox connected: CC / BCC it or auto-forward to it. */
function MyCopyIn() {
  const copyIn = useMyCopyIn();
  const qc = useQueryClient();
  if (!copyIn.data) return null;
  return (
    <div className="space-y-2 pt-3">
      <h3 className="text-sm font-medium">Or: your copy-in address</h3>
      <p className="text-xs text-muted-foreground">
        From any mail app, add this address in CC or BCC (or have replies auto-forwarded to it), and the email is saved on the lead. Emails with nobody we know are dropped.
      </p>
      <CopyInAddress
        address={copyIn.data.address}
        live={copyIn.data.live}
        onReset={async () => {
          try {
            unwrap(await api.POST("/api/v1/me/copy-in/reset"));
            toast.success("New address made. Update it wherever you used the old one.");
            await qc.invalidateQueries({ queryKey: ["copy-in"] });
          } catch (e) {
            toast.error((e as Error).message);
          }
        }}
      />
    </div>
  );
}

function ConnectForm({ current, onCancel, onDone }: { current: Mailbox | null; onCancel?: () => void; onDone: () => Promise<void> }) {
  const [provider, setProvider] = useState<ProviderKey>(providerOf(current));
  const preset = PROVIDERS[provider];
  const [form, setForm] = useState({
    email_address: current?.email_address ?? "",
    password: "",
    imap_host: current?.imap_host ?? preset.imap_host,
    imap_port: current?.imap_port ?? preset.imap_port,
    smtp_host: current?.smtp_host ?? preset.smtp_host,
    smtp_port: current?.smtp_port ?? preset.smtp_port,
    smtp_security: (current?.smtp_security ?? preset.smtp_security) as "ssl" | "starttls",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form, v: string | number) => setForm((f) => ({ ...f, [k]: v }));

  const choose = (k: ProviderKey) => {
    setProvider(k);
    const p = PROVIDERS[k];
    setForm((f) => ({ ...f, imap_host: p.imap_host, imap_port: p.imap_port, smtp_host: p.smtp_host, smtp_port: p.smtp_port, smtp_security: p.smtp_security }));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.PUT("/api/v1/me/mailbox", { body: { ...form, password: form.password || null } }));
      toast.success("Connected. Your last 30 days of emails with leads are being brought in.");
      await onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="space-y-1.5">
        <Label htmlFor="mb-provider">Your email</Label>
        <NativeSelect id="mb-provider" value={provider} onChange={(e) => choose(e.target.value as ProviderKey)}>
          {(Object.keys(PROVIDERS) as ProviderKey[]).map((k) => (
            <option key={k} value={k}>
              {PROVIDERS[k].label}
            </option>
          ))}
        </NativeSelect>
        <p className="text-xs text-muted-foreground">
          {provider === "gmail"
            ? "Use an app password, not your normal one: turn on 2-Step Verification in your Google account, then create an app password there. Your Workspace admin may need to allow it."
            : provider.startsWith("zoho")
              ? "Use an app password from Zoho Mail → Settings → Security, and make sure IMAP access is on."
              : "Ask your email provider for its IMAP and SMTP server names; use an app password if they offer one."}{" "}
          Outlook / Microsoft 365 don&apos;t accept app passwords; they come later with one-click Microsoft sign-in.
        </p>
      </div>
      <Field id="mb-email" label="Email address" type="email" required value={form.email_address} onChange={(e) => set("email_address", e.target.value)} />
      <Field
        id="mb-password"
        label="App password"
        type="password"
        autoComplete="off"
        required={!current}
        hint={current ? "Leave empty to keep the saved one." : "Stored encrypted. Never shown again."}
        value={form.password}
        onChange={(e) => set("password", e.target.value)}
      />
      {provider === "other" && (
        <div className="grid grid-cols-[1fr_6rem] gap-2">
          <Field id="mb-imap" label="IMAP server (reading)" required value={form.imap_host} onChange={(e) => set("imap_host", e.target.value)} />
          <Field id="mb-imap-port" label="Port" type="number" value={form.imap_port} onChange={(e) => set("imap_port", Number(e.target.value))} />
          <Field id="mb-smtp" label="SMTP server (sending)" required value={form.smtp_host} onChange={(e) => set("smtp_host", e.target.value)} />
          <Field id="mb-smtp-port" label="Port" type="number" value={form.smtp_port} onChange={(e) => set("smtp_port", Number(e.target.value))} />
          <div className="col-span-2 space-y-1.5">
            <Label htmlFor="mb-sec">Sending security</Label>
            <NativeSelect id="mb-sec" value={form.smtp_security} onChange={(e) => set("smtp_security", e.target.value)}>
              <option value="starttls">STARTTLS (usually port 587)</option>
              <option value="ssl">SSL (usually port 465)</option>
            </NativeSelect>
          </div>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? "Checking…" : current ? "Save" : "Connect"}
        </Button>
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
