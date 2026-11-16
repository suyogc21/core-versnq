"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { PasswordInput } from "@/components/app/password-input";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { relative } from "@/lib/crm";
import { type Entity, type MoneySettings, type TaxRate, percent, toBp, useEntities, useGateways, useMailbox, useMoneyOn, useMoneySettings, useTaxRates } from "@/lib/money";
import { cn } from "@/lib/utils";

type Tab = "entities" | "taxes" | "gateways" | "mailbox" | "reminders";

function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      for (const k of ["entities", "tax-rates", "gateways", "mailbox", "money-settings", "invoice"]) qc.invalidateQueries({ queryKey: [k] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

export default function MoneySettingsPage() {
  const on = useMoneyOn();
  const [tab, setTab] = useState<Tab>("entities");
  const tabs: [Tab, string][] = [
    ["entities", "Billing entities"],
    ["taxes", "Taxes"],
    ["gateways", "Payment gateways"],
    ["mailbox", "Email mailbox"],
    ["reminders", "Reminders and emails"],
  ];
  return (
    <>
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Money" />
      <div className="mx-auto w-full max-w-3xl p-4 sm:p-8">
        {!on ? (
          <p className="text-muted-foreground">Money is switched off for your company. Ask Versnq support to switch it on.</p>
        ) : (
          <>
            <p className="mb-4 text-muted-foreground">Who bills, the taxes you charge, how customers pay online, and the mailbox invoices are emailed from.</p>
            <div className="mb-6 flex gap-4 overflow-x-auto border-b text-sm">
              {tabs.map(([key, name]) => (
                <button
                  key={key}
                  onClick={() => setTab(key)}
                  className={cn("-mb-px border-b-2 border-transparent pb-2 whitespace-nowrap text-muted-foreground", tab === key && "border-primary font-medium text-foreground")}
                >
                  {name}
                </button>
              ))}
            </div>
            {tab === "entities" && <Entities />}
            {tab === "taxes" && <Taxes />}
            {tab === "gateways" && <Gateways />}
            {tab === "mailbox" && <MailboxForm />}
            {tab === "reminders" && <Reminders />}
          </>
        )}
      </div>
    </>
  );
}

// ---------- billing entities ----------
const TEXT_FIELDS: [keyof Entity, string, boolean?][] = [
  ["name", "Short name (shown in Core)"],
  ["legal_name", "Legal name (on the invoice)"],
  ["tax_label", "Tax ID label (GSTIN, TRN…)"],
  ["tax_id", "Tax ID"],
  ["email", "Email on the invoice"],
  ["phone", "Phone on the invoice"],
  ["upi_id", "UPI ID (for the QR code)"],
  ["invoice_prefix", "Invoice number prefix"],
  ["receipt_prefix", "Receipt number prefix"],
  ["address", "Address", true],
  ["bank_details", "Bank details for transfers", true],
  ["terms", "Terms printed on invoices", true],
];

function Entities() {
  const entities = useEntities();
  const [adding, setAdding] = useState(false);
  return (
    <div className="space-y-4">
      {(entities.data ?? []).map((e) => (
        <EntityCard key={e.id} entity={e} />
      ))}
      {adding ? (
        <EntityForm onDone={() => setAdding(false)} />
      ) : (
        <Button variant="outline" onClick={() => setAdding(true)}>
          <Plus /> Add a billing entity
        </Button>
      )}
      <p className="text-xs text-muted-foreground">One entity per legal company that sends invoices (for example India and Dubai). Each has its own numbers, currency and payment gateway.</p>
    </div>
  );
}

function EntityCard({ entity }: { entity: Entity }) {
  const [editing, setEditing] = useState(false);
  if (editing) return <EntityForm entity={entity} onDone={() => setEditing(false)} />;
  return (
    <section className="surface flex flex-wrap items-start gap-3 p-4" data-entity={entity.name}>
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-2 font-medium">
          {entity.name}
          {entity.is_default && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">Default</span>}
          {!entity.is_active && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">Off</span>}
        </div>
        <div className="text-xs text-muted-foreground">
          {entity.legal_name} · {entity.country} · {entity.currency}
          {entity.tax_id && ` · ${entity.tax_label ?? "Tax ID"} ${entity.tax_id}`}
        </div>
        <div className="text-xs text-muted-foreground">
          Next invoice: <span className="font-medium text-foreground tabular-nums">{entity.next_number}</span>
          {entity.yearly_reset && " · numbers restart each financial year"}
        </div>
      </div>
      <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
        Edit
      </Button>
    </section>
  );
}

function EntityForm({ entity, onDone }: { entity?: Entity; onDone: () => void }) {
  const save = useSave();
  const [v, setV] = useState<Record<string, string | number | boolean | null>>(
    entity
      ? { ...entity }
      : { name: "", legal_name: "", country: "IN", currency: "INR", due_days: 7, invoice_prefix: "INV-", receipt_prefix: "RCT-", yearly_reset: false, year_start_month: 4, is_default: false, is_active: true },
  );
  const set = (k: string, value: string | number | boolean | null) => setV({ ...v, [k]: value });
  async function submit() {
    const clean = (k: string) => (typeof v[k] === "string" ? (v[k] as string).trim() || null : v[k]);
    const body = {
      name: clean("name"),
      legal_name: clean("legal_name"),
      country: String(v.country ?? "").toUpperCase(),
      currency: String(v.currency ?? "").toUpperCase(),
      tax_label: clean("tax_label"),
      tax_id: clean("tax_id"),
      address: clean("address"),
      email: clean("email"),
      phone: clean("phone"),
      bank_details: clean("bank_details"),
      upi_id: clean("upi_id"),
      terms: clean("terms"),
      due_days: Number(v.due_days),
      invoice_prefix: clean("invoice_prefix") ?? "INV-",
      receipt_prefix: clean("receipt_prefix") ?? "RCT-",
      yearly_reset: Boolean(v.yearly_reset),
      year_start_month: Number(v.year_start_month),
      is_default: Boolean(v.is_default),
      is_active: Boolean(v.is_active),
    } as never;
    const ok = await save(async () => {
      if (entity) unwrap(await api.PATCH("/api/v1/money/entities/{entity_id}", { params: { path: { entity_id: entity.id } }, body }));
      else unwrap(await api.POST("/api/v1/money/entities", { body }));
    }, "Saved");
    if (ok) onDone();
  }
  return (
    <section className="surface space-y-3 p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        {TEXT_FIELDS.map(([k, name, long]) => (
          <div key={k} className={cn("space-y-1", long && "sm:col-span-2")}>
            <Label className="text-xs">{name}</Label>
            {long ? (
              <Textarea rows={2} value={String(v[k] ?? "")} onChange={(e) => set(k, e.target.value)} />
            ) : (
              <Input value={String(v[k] ?? "")} onChange={(e) => set(k, e.target.value)} aria-label={name} />
            )}
          </div>
        ))}
        <div className="space-y-1">
          <Label className="text-xs">Country (2 letters)</Label>
          <Input value={String(v.country ?? "")} maxLength={2} onChange={(e) => set("country", e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Currency (3 letters)</Label>
          <Input value={String(v.currency ?? "")} maxLength={3} disabled={Boolean(entity)} onChange={(e) => set("currency", e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Days to pay</Label>
          <Input inputMode="numeric" value={String(v.due_days ?? "")} onChange={(e) => set("due_days", e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Financial year starts in</Label>
          <NativeSelect value={String(v.year_start_month)} onChange={(e) => set("year_start_month", Number(e.target.value))}>
            {["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"].map((m, i) => (
              <option key={m} value={i + 1}>
                {m}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2">
          <Switch checked={Boolean(v.yearly_reset)} onCheckedChange={(c) => set("yearly_reset", c)} /> Restart numbers each financial year
        </label>
        <label className="flex items-center gap-2">
          <Switch checked={Boolean(v.is_default)} onCheckedChange={(c) => set("is_default", c)} /> Default
        </label>
        <label className="flex items-center gap-2">
          <Switch checked={Boolean(v.is_active)} onCheckedChange={(c) => set("is_active", c)} /> Active
        </label>
      </div>
      <div className="flex gap-2">
        <Button onClick={submit}>Save</Button>
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </section>
  );
}

// ---------- taxes ----------
function Taxes() {
  const rates = useTaxRates();
  const [adding, setAdding] = useState(false);
  return (
    <div className="space-y-3">
      <div className="surface divide-y">
        {(rates.data ?? []).map((r) => (
          <TaxRow key={r.id} rate={r} />
        ))}
      </div>
      {adding ? (
        <TaxForm onDone={() => setAdding(false)} />
      ) : (
        <Button variant="outline" onClick={() => setAdding(true)}>
          <Plus /> Add a tax rate
        </Button>
      )}
      <p className="text-xs text-muted-foreground">
        A rate can have parts, each shown on the invoice: GST 18% is CGST 9% + SGST 9%. Changing a rate never changes invoices already made.
      </p>
      <CountryPresets />
    </div>
  );
}

/** Ready-made rates per country (finishing plan, batch 6). */
function CountryPresets() {
  const save = useSave();
  const presets = useQuery({ queryKey: ["tax-presets"], queryFn: async () => unwrap(await api.GET("/api/v1/money/tax-presets")) });
  const [country, setCountry] = useState("");
  const names = typeof Intl !== "undefined" && "DisplayNames" in Intl ? new Intl.DisplayNames(["en"], { type: "region" }) : null;
  const chosen = presets.data?.find((p) => p.country === country);
  if (!presets.data?.length) return null;
  return (
    <div className="surface space-y-2 p-3 text-sm">
      <div className="font-medium">Add a country&apos;s rates</div>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Country" className="h-9 rounded-md border bg-background px-2" value={country} onChange={(e) => setCountry(e.target.value)}>
          <option value="">Choose a country…</option>
          {presets.data.map((p) => (
            <option key={p.country} value={p.country}>
              {names?.of(p.country) ?? p.country}
            </option>
          ))}
        </select>
        <Button
          variant="outline"
          disabled={!country}
          onClick={() => save(async () => unwrap(await api.POST("/api/v1/money/tax-presets/{country}", { params: { path: { country } } })), "Rates added")}
        >
          Add
        </Button>
      </div>
      {chosen && (
        <p className="text-muted-foreground">
          {chosen.rates.map((r) => r.name).join(", ")}
          {chosen.tax_label ? ` · tax number shown as “${chosen.tax_label}”` : ""}. Rates you already have are left as they are.
        </p>
      )}
      <p className="text-xs text-muted-foreground">Standard rates as of November 2026. Check them with your accountant before invoicing; every rate can be edited.</p>
    </div>
  );
}

function TaxRow({ rate }: { rate: TaxRate }) {
  const save = useSave();
  const [editing, setEditing] = useState(false);
  if (editing) return <TaxForm rate={rate} onDone={() => setEditing(false)} />;
  const total = rate.parts.reduce((s, p) => s + p.rate_bp, 0);
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 text-sm" data-tax={rate.name}>
      <span className={cn("font-medium", !rate.is_active && "text-muted-foreground line-through")}>{rate.name}</span>
      <span className="text-xs text-muted-foreground">{rate.parts.length ? rate.parts.map((p) => `${p.name} ${percent(p.rate_bp)}%`).join(" + ") : "No tax"}</span>
      <span className="ml-auto text-xs tabular-nums">{percent(total)}%</span>
      <Switch
        checked={rate.is_active}
        aria-label={`${rate.name} active`}
        onCheckedChange={(c) => save(async () => unwrap(await api.PATCH("/api/v1/money/tax-rates/{rate_id}", { params: { path: { rate_id: rate.id } }, body: { is_active: c } })))}
      />
      <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
        Edit
      </Button>
    </div>
  );
}

function TaxForm({ rate, onDone }: { rate?: TaxRate; onDone: () => void }) {
  const save = useSave();
  const [name, setName] = useState(rate?.name ?? "");
  const [parts, setParts] = useState(rate?.parts.map((p) => ({ name: p.name, rate: percent(p.rate_bp) })) ?? [{ name: "", rate: "" }]);
  async function submit() {
    const out: { name: string; rate_bp: number }[] = [];
    for (const p of parts.filter((x) => x.name.trim() || x.rate.trim())) {
      const bp = toBp(p.rate);
      if (!p.name.trim() || bp === null) return toast.error("Each part needs a name and a rate like 9 or 2.5");
      out.push({ name: p.name.trim(), rate_bp: bp });
    }
    const ok = await save(async () => {
      if (rate) unwrap(await api.PATCH("/api/v1/money/tax-rates/{rate_id}", { params: { path: { rate_id: rate.id } }, body: { name, parts: out } }));
      else unwrap(await api.POST("/api/v1/money/tax-rates", { body: { name, parts: out } }));
    }, "Saved");
    if (ok) onDone();
  }
  return (
    <div className="space-y-2 p-4">
      <Input placeholder="Name, e.g. GST 18%" value={name} onChange={(e) => setName(e.target.value)} aria-label="Tax name" />
      {parts.map((p, i) => (
        <div key={i} className="flex gap-2">
          <Input placeholder="Part, e.g. CGST" value={p.name} onChange={(e) => setParts(parts.map((x, n) => (n === i ? { ...x, name: e.target.value } : x)))} aria-label="Part name" />
          <Input className="w-24" placeholder="%" inputMode="decimal" value={p.rate} onChange={(e) => setParts(parts.map((x, n) => (n === i ? { ...x, rate: e.target.value } : x)))} aria-label="Part rate" />
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" onClick={() => setParts([...parts, { name: "", rate: "" }])}>
          <Plus /> Add a part
        </Button>
        <Button size="sm" onClick={submit}>
          Save
        </Button>
        <Button size="sm" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

// ---------- gateways ----------
function Gateways() {
  const save = useSave();
  const entities = useEntities();
  const gateways = useGateways();
  const [form, setForm] = useState({ entity_id: "", gateway: "razorpay" as "razorpay" | "stripe", key_id: "", secret: "", webhook_secret: "", mode: "test" as "test" | "live" });
  const entityName = (id: string) => entities.data?.find((e) => e.id === id)?.name ?? "";
  return (
    <div className="space-y-4">
      {(gateways.data ?? []).map((g) => (
        <section key={g.id} className="surface space-y-2 p-4 text-sm" data-gateway={g.gateway}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium capitalize">{g.gateway}</span>
            <span className="text-xs text-muted-foreground">
              for {entityName(g.entity_id)} · {g.mode === "test" ? "test mode" : "live"} · key {g.key_id ? `${g.key_id} · ` : ""}
              {g.secret_hint}
            </span>
            <span className={cn("ml-auto text-xs", g.last_error ? "text-red-700 dark:text-red-300" : "text-emerald-700 dark:text-emerald-300")}>
              {!g.is_active ? "Disconnected" : g.last_error ? g.last_error : `Working · checked ${relative(g.last_checked_at)}`}
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Webhook address to paste into {g.gateway === "razorpay" ? "Razorpay" : "Stripe"}:</span>
            <code className="truncate rounded bg-muted px-1.5 py-0.5">{g.webhook_url}</code>
            <Button size="icon" variant="ghost" className="size-6" aria-label="Copy webhook address" onClick={() => navigator.clipboard?.writeText(g.webhook_url).then(() => toast.success("Copied"))}>
              <Copy />
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Events to send: {g.gateway === "razorpay" ? "payment_link.paid" : "checkout.session.completed"}.
          </p>
          {g.is_active && (
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => save(async () => unwrap(await api.POST("/api/v1/money/gateways/{account_id}/check", { params: { path: { account_id: g.id } } })), "Checked")}>
                Check connection
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-muted-foreground hover:text-destructive"
                onClick={() => confirm("Disconnect this gateway? Old links stop being checked.") && save(async () => unwrap(await api.DELETE("/api/v1/money/gateways/{account_id}", { params: { path: { account_id: g.id } } })), "Disconnected")}
              >
                Disconnect
              </Button>
            </div>
          )}
        </section>
      ))}
      <section className="surface space-y-3 p-4">
        <h4 className="text-[13px] font-semibold">Connect a gateway</h4>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">For entity</Label>
            <NativeSelect value={form.entity_id} onChange={(e) => setForm({ ...form, entity_id: e.target.value })}>
              <option value="">Choose…</option>
              {(entities.data ?? []).map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name} ({e.currency})
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Gateway</Label>
            <NativeSelect value={form.gateway} onChange={(e) => setForm({ ...form, gateway: e.target.value as "razorpay" | "stripe" })}>
              <option value="razorpay">Razorpay (India)</option>
              <option value="stripe">Stripe (UAE, US and others)</option>
            </NativeSelect>
          </div>
          {form.gateway === "razorpay" && (
            <div className="space-y-1">
              <Label className="text-xs">Key ID</Label>
              <Input value={form.key_id} onChange={(e) => setForm({ ...form, key_id: e.target.value })} placeholder="rzp_test_…" />
            </div>
          )}
          <div className="space-y-1">
            <Label className="text-xs">{form.gateway === "razorpay" ? "Key secret" : "Secret key"}</Label>
            <PasswordInput autoComplete="off" value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} placeholder={form.gateway === "stripe" ? "sk_test_…" : ""} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Webhook secret</Label>
            <PasswordInput autoComplete="off" value={form.webhook_secret} onChange={(e) => setForm({ ...form, webhook_secret: e.target.value })} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Mode</Label>
            <NativeSelect value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as "test" | "live" })}>
              <option value="test">Test (no real money)</option>
              <option value="live">Live</option>
            </NativeSelect>
          </div>
        </div>
        <Button
          disabled={!form.entity_id || !form.secret || !form.webhook_secret}
          onClick={async () => {
            const ok = await save(async () => unwrap(await api.POST("/api/v1/money/gateways", { body: { ...form, key_id: form.key_id || null } })), "Connected");
            if (ok) setForm({ ...form, key_id: "", secret: "", webhook_secret: "" });
          }}
        >
          Check and connect
        </Button>
        <p className="text-[11px] text-muted-foreground">
          Keys are checked with the gateway, then stored encrypted and never shown again. Customers pay on the gateway&apos;s own page; Core only hears when a payment is made.
        </p>
      </section>
    </div>
  );
}

// ---------- mailbox ----------
function MailboxForm() {
  const save = useSave();
  const mailbox = useMailbox();
  const m = mailbox.data;
  const [v, setV] = useState<{ host: string; port: 25 | 465 | 587 | 2525; security: "ssl" | "starttls"; username: string; password: string; from_name: string; from_email: string; reply_to: string } | null>(null);
  const form = v ?? {
    host: m?.host ?? "smtp.gmail.com",
    port: (m?.port ?? 587) as 25 | 465 | 587 | 2525,
    security: (m?.security ?? "starttls") as "ssl" | "starttls",
    username: m?.username ?? "",
    password: "",
    from_name: m?.from_name ?? "",
    from_email: m?.from_email ?? "",
    reply_to: m?.reply_to ?? "",
  };
  const set = (patch: Partial<typeof form>) => setV({ ...form, ...patch });
  if (mailbox.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  return (
    <div className="space-y-4">
      {m && (
        <p className={cn("text-sm", m.last_error ? "text-red-700 dark:text-red-300" : "text-emerald-700 dark:text-emerald-300")}>
          {m.last_error ? `Last problem: ${m.last_error}` : `Connected: emails go from ${m.from_name} <${m.from_email}>.`}
        </p>
      )}
      <section className="surface space-y-3 p-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">Mail server</Label>
            <Input value={form.host} onChange={(e) => set({ host: e.target.value })} aria-label="Mail server" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Port and security</Label>
            <NativeSelect
              value={`${form.port}-${form.security}`}
              onChange={(e) => {
                const [port, security] = e.target.value.split("-");
                set({ port: Number(port) as 587, security: security as "ssl" | "starttls" });
              }}
            >
              <option value="587-starttls">587 · STARTTLS (Gmail, Outlook)</option>
              <option value="465-ssl">465 · SSL (Zoho)</option>
              <option value="2525-starttls">2525 · STARTTLS</option>
              <option value="25-starttls">25 · STARTTLS</option>
            </NativeSelect>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">User name</Label>
            <Input value={form.username} onChange={(e) => set({ username: e.target.value })} placeholder="accounts@yourcompany.com" aria-label="User name" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Password {m && "(empty: keep the saved one)"}</Label>
            <PasswordInput autoComplete="off" value={form.password} onChange={(e) => set({ password: e.target.value })} aria-label="Password" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">From name</Label>
            <Input value={form.from_name} onChange={(e) => set({ from_name: e.target.value })} placeholder="Acme Accounts" aria-label="From name" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">From email</Label>
            <Input value={form.from_email} onChange={(e) => set({ from_email: e.target.value })} aria-label="From email" />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label className="text-xs">Replies go to (optional)</Label>
            <Input value={form.reply_to} onChange={(e) => set({ reply_to: e.target.value })} />
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() =>
              save(async () => {
                unwrap(await api.PUT("/api/v1/money/mailbox", { body: { ...form, password: form.password || null, reply_to: form.reply_to || null } }));
                setV(null);
              }, "Mailbox connected")
            }
          >
            Check and save
          </Button>
          {m && (
            <Button variant="ghost" className="text-muted-foreground hover:text-destructive" onClick={() => confirm("Remove the mailbox? Emails to customers stop.") && save(async () => unwrap(await api.DELETE("/api/v1/money/mailbox")), "Removed")}>
              Remove
            </Button>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground">
          Gmail or Google Workspace: turn on 2-step verification and create an app password (Google account → Security → App passwords). Core signs in once to check; the password is stored encrypted.
        </p>
      </section>
    </div>
  );
}

// ---------- reminders and emails ----------
function Reminders() {
  const save = useSave();
  const settings = useMoneySettings();
  const [v, setV] = useState<MoneySettings | null>(null);
  const s = v ?? settings.data;
  if (!s) return <p className="text-muted-foreground">Loading…</p>;
  const set = (patch: Partial<MoneySettings>) => setV({ ...s, ...patch });
  const kinds: [keyof MoneySettings["money_emails"], string][] = [
    ["invoice", "The invoice, when it is issued"],
    ["receipt", "A receipt for every payment"],
    ["reminder", "Payment reminders"],
    ["void", "A note when an invoice is voided"],
  ];
  return (
    <section className="surface space-y-4 p-4 text-sm">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label className="text-xs">Remind this many days before the due date (0: no)</Label>
          <Input inputMode="numeric" value={String(s.money_reminder_before_days)} onChange={(e) => set({ money_reminder_before_days: Number(e.target.value) || 0 })} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">While overdue, remind every (days)</Label>
          <Input inputMode="numeric" value={String(s.money_overdue_every_days)} onChange={(e) => set({ money_overdue_every_days: Number(e.target.value) || 1 })} />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label className="text-xs">New invoices are paid by</Label>
          <NativeSelect value={s.money_default_pay} onChange={(e) => set({ money_default_pay: e.target.value as MoneySettings["money_default_pay"] })}>
            <option value="both">Payment link or paying directly (bank / UPI)</option>
            <option value="link">Payment link only</option>
            <option value="direct">Paying directly only</option>
          </NativeSelect>
        </div>
      </div>
      <div className="space-y-2">
        <Label className="text-xs">Email the customer automatically</Label>
        {kinds.map(([k, name]) => (
          <label key={k} className="flex items-center justify-between gap-2">
            <span>{name}</span>
            <Switch checked={s.money_emails[k] ?? true} onCheckedChange={(c) => set({ money_emails: { ...s.money_emails, [k]: c } })} aria-label={name} />
          </label>
        ))}
        <p className="text-[11px] text-muted-foreground">Reminders also notify the customer&apos;s owner in Core and add a follow-up task when a payment is overdue. Customers who unsubscribed are never emailed.</p>
      </div>
      <Button onClick={() => save(async () => unwrap(await api.PUT("/api/v1/money/settings", { body: s })), "Saved").then((ok) => ok && setV(null))}>Save</Button>
    </section>
  );
}
