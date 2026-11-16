"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { useModules } from "@/lib/modules";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { relative, useSources } from "@/lib/crm";
import { cn } from "@/lib/utils";
import { type WaSettings, useWaTemplates, WA_STATUS } from "@/lib/whatsapp";

type Tab = "number" | "templates" | "rules";

function useAccount() {
  return useQuery({ queryKey: ["wa", "account"], queryFn: async () => unwrap(await api.GET("/api/v1/whatsapp/account")) });
}

function useRun() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) toast.success(ok);
      await qc.invalidateQueries({ queryKey: ["wa"] });
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast.success("Copied"));

export default function WhatsAppSettingsPage() {
  const modules = useModules();
  if (modules && !modules.whatsapp_number) {
    return (
      <>
        <PageHeader back={{ href: "/settings", label: "Settings" }} title="WhatsApp" />
        <p className="mx-auto max-w-3xl p-8 text-muted-foreground" data-wa-off>
          The company WhatsApp number isn&apos;t switched on for your company yet. Your team can already save chats from their own WhatsApp with the Versnq extension.
        </p>
      </>
    );
  }
  return <WhatsAppSettings />;
}

function WhatsAppSettings() {
  const [tab, setTab] = useState<Tab>("number");
  const account = useAccount();
  const tabs: [Tab, string][] = [
    ["number", "Number"],
    ["templates", "Templates"],
    ["rules", "Automatic replies & rules"],
  ];
  return (
    <>
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="WhatsApp" />
      <div className="mx-auto w-full max-w-3xl p-4 sm:p-8">
        <p className="mb-4 text-muted-foreground">
          The company&apos;s official WhatsApp number, through Meta&apos;s own API: sequences, payment reminders and automatic replies go from here. Your
          salespeople keep chatting from their own WhatsApp with the Versnq extension.
        </p>
        {account.data?.test_mode && (
          <p className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs" data-wa-test-mode>
            Test mode: nothing is sent to WhatsApp yet. Messages are kept in Core and templates are approved at once, so everything can be tried before your
            Meta Business verification is done.
          </p>
        )}
        <div className="mb-6 flex gap-4 overflow-x-auto border-b text-sm" role="tablist">
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
        {tab === "number" && <NumberTab />}
        {tab === "templates" && <TemplatesTab connected={!!account.data?.connected} />}
        {tab === "rules" && <RulesTab />}
      </div>
    </>
  );
}

// ---------- the number ----------
function NumberTab() {
  const account = useAccount();
  const run = useRun();
  const a = account.data;
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ phone_number_id: "", waba_id: "", access_token: "", app_secret: "", app_id: "" });
  if (!a) return null;
  const showForm = !a.connected || editing;
  return (
    <div className="space-y-5">
      {a.connected && (
        <div className="space-y-2 surface p-4 text-sm" data-wa-number>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-semibold">{a.display_number ?? "Connected"}</span>
            {a.verified_name && <span className="text-muted-foreground">{a.verified_name}</span>}
            <span className={cn("ms-auto text-xs", a.status === "active" ? "text-emerald-700 dark:text-emerald-300" : "text-destructive")}>
              {a.status === "active" ? "Connected" : "Needs attention"}
            </span>
          </div>
          <dl className="grid grid-cols-[9rem_1fr] gap-y-1 text-xs">
            <dt className="text-muted-foreground">Quality</dt>
            <dd className={cn(a.quality_rating === "RED" && "text-destructive", a.quality_rating === "YELLOW" && "text-amber-700 dark:text-amber-300")}>
              {{ GREEN: "High", YELLOW: "Medium: some people block or report", RED: "Low: fix templates and who gets them" }[a.quality_rating ?? ""] ?? "—"}
            </dd>
            <dt className="text-muted-foreground">Daily limit</dt>
            <dd>{a.messaging_limit ? a.messaging_limit.replace("TIER_", "").replace("K", ",000") + " new people a day" : "—"}</dd>
            <dt className="text-muted-foreground">Last checked</dt>
            <dd>{a.health_checked_at ? relative(a.health_checked_at) : "—"}</dd>
          </dl>
          {a.last_error && <p className="text-xs text-destructive">{a.last_error}</p>}
          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" variant="outline" onClick={() => run(async () => unwrap(await api.POST("/api/v1/whatsapp/account/check")), "Checked")}>
              <RefreshCw /> Check now
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(!editing)}>
              {editing ? "Cancel" : "Change keys"}
            </Button>
          </div>
        </div>
      )}
      {a.connected && (
        <div className="space-y-2 text-sm">
          <h2 className="font-semibold">Webhook (in your Meta app → WhatsApp → Configuration)</h2>
          <p className="text-xs text-muted-foreground">So messages and delivery receipts reach Core. Subscribe to &quot;messages&quot; and &quot;message_template_status_update&quot;.</p>
          {[
            ["Callback URL", a.webhook_url],
            ["Verify token", a.verify_token],
          ].map(([k, v]) => (
            <div key={k} className="flex flex-wrap items-center gap-2">
              <span className="w-28 text-xs text-muted-foreground">{k}</span>
              <code className="rounded bg-muted px-2 py-1 text-xs break-all">{v}</code>
              <Button size="sm" variant="ghost" onClick={() => copy(v ?? "")}>
                <Copy className="size-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}
      {showForm && (
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            const ok = await run(
              async () =>
                unwrap(
                  await api.PUT("/api/v1/whatsapp/account", {
                    body: { ...form, access_token: form.access_token || null, app_secret: form.app_secret || null, app_id: form.app_id.trim() || null },
                  }),
                ),
              "WhatsApp number connected",
            );
            if (ok) setEditing(false);
          }}
        >
          <h2 className="font-semibold">{a.connected ? "Change keys" : "Connect your number"}</h2>
          <p className="text-xs text-muted-foreground">
            From Meta for Developers → your app → WhatsApp → API setup. Use a permanent (system user) access token. Keys are stored encrypted and never shown
            again.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                ["phone_number_id", "Phone number ID", a.phone_number_id],
                ["waba_id", "WhatsApp Business Account ID", a.waba_id],
                ["access_token", "Access token", null],
                ["app_secret", "App secret", null],
                ["app_id", "App ID (only for templates with a photo, video or PDF)", a.app_id],
              ] as const
            ).map(([k, label, now]) => (
              <div key={k} className="space-y-1.5">
                <Label htmlFor={`wa-${k}`}>{label}</Label>
                <Input
                  id={`wa-${k}`}
                  type={k === "access_token" || k === "app_secret" ? "password" : "text"}
                  placeholder={now ?? (a.connected && (k === "access_token" || k === "app_secret") ? "Leave empty to keep" : "")}
                  value={form[k]}
                  onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                />
              </div>
            ))}
          </div>
          <Button type="submit">{a.connected ? "Save" : "Connect"}</Button>
        </form>
      )}
    </div>
  );
}

// ---------- templates ----------
type HeaderFormat = "" | "text" | "image" | "video" | "document";
type WaButton = { type: "quick_reply" | "url" | "phone"; text: string; url?: string; phone?: string };
const HEADER_ACCEPT: Record<string, string> = { image: "image/jpeg,image/png", video: "video/mp4", document: "application/pdf" };
const BUTTON_KIND: Record<WaButton["type"], string> = { quick_reply: "Quick reply", url: "Website", phone: "Call" };

function TemplatesTab({ connected }: { connected: boolean }) {
  const list = useWaTemplates();
  const run = useRun();
  const [form, setForm] = useState({ name: "", category: "utility" as "utility" | "marketing", language: "en", body: "", footer: "" });
  const [header, setHeader] = useState<{ format: HeaderFormat; text: string; key: string | null; name: string | null }>({ format: "", text: "", key: null, name: null });
  const [buttons, setButtons] = useState<WaButton[]>([]);
  const [uploading, setUploading] = useState(false);

  async function uploadHeader(file: File) {
    setUploading(true);
    try {
      const out = unwrap(
        await api.POST("/api/v1/whatsapp/templates/header-file", {
          body: file as unknown as undefined, // the raw file (the API reads the request body)
          bodySerializer: (b: unknown) => b as BodyInit,
          headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name).slice(0, 200) },
        }),
      );
      setHeader((h) => ({ ...h, key: out.key, name: out.name }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setUploading(false);
    }
  }
  const headerBody = header.format === "" ? null : header.format === "text" ? { format: header.format, text: header.text } : { format: header.format, file_key: header.key };
  const headerReady = header.format === "" || (header.format === "text" ? !!header.text.trim() : !!header.key);
  if (!connected) return <p className="text-sm text-muted-foreground">Connect the number first (Number tab).</p>;
  return (
    <div className="space-y-6">
      <div className="divide-y surface">
        {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">No templates yet.</p>}
        {(list.data ?? []).map((t) => (
          <div key={t.id} className="space-y-1 px-3 py-2.5 text-sm" data-wa-template={t.name}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{t.name}</span>
              <span className="text-xs text-muted-foreground">
                {t.category} · {t.language}
              </span>
              <span className={cn("text-xs", WA_STATUS[t.status]?.[1])}>{WA_STATUS[t.status]?.[0] ?? t.status}</span>
              <div className="ms-auto flex gap-1">
                <Button size="icon-sm" variant="ghost" aria-label={`Refresh ${t.name}`} onClick={() => run(async () => unwrap(await api.POST("/api/v1/whatsapp/templates/{tpl_id}/refresh", { params: { path: { tpl_id: t.id } } })))}>
                  <RefreshCw />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Delete ${t.name}`}
                  onClick={() => confirm(`Delete ${t.name} from Core? Remove it in Meta's WhatsApp Manager too if it should go there.`) && run(async () => unwrap(await api.DELETE("/api/v1/whatsapp/templates/{tpl_id}", { params: { path: { tpl_id: t.id } } })), "Deleted")}
                >
                  <Trash2 />
                </Button>
              </div>
            </div>
            {t.header && (
              <p className="text-xs font-medium text-muted-foreground">
                Header: {t.header.format === "text" ? t.header.text : `${t.header.format} (${t.header.name ?? "file"})`}
              </p>
            )}
            <p className="text-xs whitespace-pre-wrap text-muted-foreground">{t.body}</p>
            {(t.buttons ?? []).length > 0 && (
              <div className="flex flex-wrap gap-1">
                {(t.buttons ?? []).map((b, i) => (
                  <span key={i} className="rounded-full border px-2 py-0.5 text-xs" title={b.url ?? b.phone ?? undefined}>
                    {b.text}
                  </span>
                ))}
              </div>
            )}
            {t.reason && <p className="text-xs text-muted-foreground italic">{t.reason}</p>}
          </div>
        ))}
      </div>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await run(
            async () => unwrap(await api.POST("/api/v1/whatsapp/templates", { body: { ...form, footer: form.footer || null, header: headerBody, buttons } })),
            "Sent to WhatsApp for approval",
          );
          if (ok) {
            setForm({ ...form, name: "", body: "", footer: "" });
            setHeader({ format: "", text: "", key: null, name: null });
            setButtons([]);
          }
        }}
      >
        <h2 className="font-semibold">New template</h2>
        <p className="text-xs text-muted-foreground">
          WhatsApp checks every template before it can be used, usually within minutes, sometimes a day. Utility: reminders, confirmations, updates. Marketing:
          offers and news; only people who opted in to WhatsApp get those. Variables like {"{{lead.first_name|there}}"} work; payment reminders can also use{" "}
          {"{{invoice.number}}, {{invoice.amount_due}}, {{invoice.due_date}}, {{invoice.pay_link}}"}.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="wt-name">Name</Label>
            <Input id="wt-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="demo_confirmation" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wt-cat">Kind</Label>
            <NativeSelect id="wt-cat" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as "utility" | "marketing" })}>
              <option value="utility">Utility (reminders, updates)</option>
              <option value="marketing">Marketing (offers)</option>
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wt-lang">Language</Label>
            <NativeSelect id="wt-lang" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
              <option value="en">English</option>
              <option value="en_US">English (US)</option>
              <option value="hi">Hindi</option>
              <option value="mr">Marathi</option>
              <option value="ar">Arabic</option>
            </NativeSelect>
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wt-header">Header (optional)</Label>
          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect id="wt-header" className="w-48" value={header.format} onChange={(e) => setHeader({ format: e.target.value as HeaderFormat, text: "", key: null, name: null })}>
              <option value="">No header</option>
              <option value="text">Text</option>
              <option value="image">Photo</option>
              <option value="video">Video</option>
              <option value="document">PDF</option>
            </NativeSelect>
            {header.format === "text" && (
              <Input aria-label="Header text" className="max-w-xs" maxLength={60} value={header.text} onChange={(e) => setHeader({ ...header, text: e.target.value })} placeholder="Your demo is booked" />
            )}
            {header.format !== "" && header.format !== "text" && (
              <label className="inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-accent">
                {uploading ? "Uploading…" : header.name ? `Example: ${header.name} (change)` : "Choose the example file"}
                <input
                  type="file"
                  className="sr-only"
                  aria-label="Header example file"
                  accept={HEADER_ACCEPT[header.format]}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) uploadHeader(f);
                  }}
                />
              </label>
            )}
          </div>
          {header.format !== "" && header.format !== "text" && (
            <p className="text-xs text-muted-foreground">This file goes with every message. WhatsApp checks it with the template; your Meta app ID must be saved on the Number tab.</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wt-body">Message</Label>
          <Textarea id="wt-body" rows={4} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} placeholder="Hi {{lead.first_name|there}}, your demo with {{owner.name}} is confirmed for tomorrow." />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wt-footer">Footer (optional)</Label>
          <Input id="wt-footer" maxLength={60} value={form.footer} onChange={(e) => setForm({ ...form, footer: e.target.value })} placeholder="Reply STOP to opt out" />
        </div>
        <div className="space-y-2">
          <Label>Buttons (optional)</Label>
          {buttons.map((b, i) => {
            const set = (patch: Partial<WaButton>) => setButtons(buttons.map((x, j) => (j === i ? { ...x, ...patch } : x)));
            return (
              <div key={i} className="flex flex-wrap items-center gap-2" data-wa-button>
                <span className="w-24 text-xs text-muted-foreground">{BUTTON_KIND[b.type]}</span>
                <Input aria-label="Button text" className="w-40" maxLength={25} value={b.text} onChange={(e) => set({ text: e.target.value })} placeholder="Button text" />
                {b.type === "url" && (
                  <Input aria-label="Website address" className="min-w-56 flex-1" value={b.url ?? ""} onChange={(e) => set({ url: e.target.value })} placeholder="https://example.com/pay/{{lead.cf.ref}}" />
                )}
                {b.type === "phone" && <Input aria-label="Phone number" className="w-44" value={b.phone ?? ""} onChange={(e) => set({ phone: e.target.value })} placeholder="+91 98200 11122" />}
                <Button type="button" size="icon-sm" variant="ghost" aria-label="Remove button" onClick={() => setButtons(buttons.filter((_, j) => j !== i))}>
                  <Trash2 />
                </Button>
              </div>
            );
          })}
          {buttons.length < 10 && (
            <div className="flex flex-wrap gap-2">
              {(Object.keys(BUTTON_KIND) as WaButton["type"][]).map((type) => (
                <Button key={type} type="button" size="sm" variant="outline" onClick={() => setButtons([...buttons, { type, text: "" }])}>
                  + {BUTTON_KIND[type]}
                </Button>
              ))}
            </div>
          )}
          <p className="text-xs text-muted-foreground">Up to 10 buttons: at most 2 websites and 1 phone number. A website address may end with one variable.</p>
        </div>
        <Button type="submit" disabled={!form.name.trim() || !form.body.trim() || !headerReady || uploading || buttons.some((b) => !b.text.trim())}>
          Send for approval
        </Button>
      </form>
    </div>
  );
}

// ---------- automatic replies and rules ----------
function RulesTab() {
  const current = useQuery({ queryKey: ["wa", "settings"], queryFn: async () => unwrap(await api.GET("/api/v1/whatsapp/settings")) });
  const sources = useSources();
  const templates = useWaTemplates();
  const run = useRun();
  const [draft, setDraft] = useState<(WaSettings & { stopText: string }) | null>(null);
  if (!current.data) return null;
  const d = draft ?? { ...current.data, stopText: (current.data.stop_words ?? []).join("\n") };
  const set = (patch: Partial<typeof d>) => setDraft({ ...d, ...patch });
  return (
    <form
      className="space-y-6"
      onSubmit={async (e) => {
        e.preventDefault();
        const { stopText, ...body } = d;
        const ok = await run(async () => unwrap(await api.PUT("/api/v1/whatsapp/settings", { body: { ...body, stop_words: stopText.split("\n") } })), "Saved");
        if (ok) setDraft(null);
      }}
    >
      <section className="space-y-2">
        <h2 className="font-semibold">Automatic replies</h2>
        <p className="text-xs text-muted-foreground">
          On this number only, never on your salespeople&apos;s own WhatsApp. At most two automatic replies per person a day, and none after a STOP.
        </p>
        {(
          [
            ["welcome", "Welcome", "Sent to someone writing for the first time."],
            ["away", "Away", "Sent outside your sending hours (Sequences → Sending hours), at most every 12 hours."],
          ] as const
        ).map(([k, label, hint]) => (
          <div key={k} className="space-y-1.5 surface p-3">
            <div className="flex items-center gap-2">
              <Switch aria-label={`${label} reply on`} checked={d[k].on} onCheckedChange={(on) => set({ [k]: { ...d[k], on } })} />
              <span className="text-sm font-medium">{label}</span>
              <span className="text-xs text-muted-foreground">{hint}</span>
            </div>
            <Textarea aria-label={`${label} reply`} rows={2} value={d[k].text} onChange={(e) => set({ [k]: { ...d[k], text: e.target.value } })} />
          </div>
        ))}
      </section>
      <section className="space-y-2">
        <h2 className="font-semibold">Someone new writes</h2>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <Switch aria-label="Create a lead" checked={d.create_leads} onCheckedChange={(on) => set({ create_leads: on })} />
            <span className="text-sm">Create a lead for them</span>
          </div>
          {d.create_leads && (
            <NativeSelect aria-label="Source for those leads" className="h-8 w-56" value={d.source_id ?? ""} onChange={(e) => set({ source_id: e.target.value || null })}>
              <option value="">&quot;WhatsApp&quot; source (or the first one)</option>
              {(sources.data ?? []).filter((s) => s.is_active).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          )}
        </div>
      </section>
      <section className="space-y-2">
        <h2 className="font-semibold">STOP words</h2>
        <p className="text-xs text-muted-foreground">A message that is exactly one of these opts the person out of WhatsApp at once. One per line.</p>
        <Textarea aria-label="STOP words" rows={4} value={d.stopText} onChange={(e) => set({ stopText: e.target.value })} />
      </section>
      <section className="space-y-2">
        <h2 className="font-semibold">Payment reminders on WhatsApp</h2>
        <p className="text-xs text-muted-foreground">Sent with the email reminder (Settings → Money), using this utility template.</p>
        <NativeSelect aria-label="Reminder template" className="h-8 w-72" value={d.reminder_template_id ?? ""} onChange={(e) => set({ reminder_template_id: e.target.value || null })}>
          <option value="">Off</option>
          {(templates.data ?? []).filter((t) => t.category === "utility").map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} {t.status !== "approved" ? `(${WA_STATUS[t.status]?.[0] ?? t.status})` : ""}
            </option>
          ))}
        </NativeSelect>
      </section>
      <Button type="submit">Save</Button>
    </form>
  );
}
