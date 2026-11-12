"use client";

import { Ban, Copy, Download, FileText, Link2, Mail, MessageCircle, Plus, Receipt, Repeat, Trash2, Undo2, Wallet } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { InvoiceStatus } from "@/components/crm/money";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { relative } from "@/lib/crm";
import { shrinkPhoto } from "@/lib/customers";
import { formatMoney, moneyInput, parseMoney } from "@/lib/deals";
import {
  INSTALLMENT_STATE,
  type Invoice,
  METHOD_LABEL,
  METHODS,
  day,
  openPdf,
  percent,
  todayIso,
  useEntities,
  useInvoice,
  useRefreshMoney,
  useTaxRates,
  whatsappLink,
} from "@/lib/money";
import { cn } from "@/lib/utils";

function Section({ title, action, children }: { title: React.ReactNode; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="surface space-y-3 p-4">
      <h4 className="flex items-center justify-between gap-2 text-[13px] font-semibold">
        {title}
        {action}
      </h4>
      {children}
    </section>
  );
}

async function run<T>(work: () => Promise<T>, done?: string): Promise<T | undefined> {
  try {
    const out = await work();
    if (done) toast.success(done);
    return out;
  } catch (e) {
    toast.error((e as Error).message);
    return undefined;
  }
}

export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  const invoice = useInvoice(id);
  const inv = invoice.data;
  if (invoice.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!inv) {
    return (
      <>
        <PageHeader back={{ href: "/money", label: "Money" }} title="Not found" />
        <p className="p-8 text-center text-muted-foreground">This invoice doesn&apos;t exist or you don&apos;t have access to it.</p>
      </>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <PageHeader back={{ href: "/money", label: "Money" }} title={inv.number ?? "Draft invoice"} actions={<InvoiceStatus status={inv.status} overdue={inv.overdue_minor} />} />
      <div className="px-4 pt-3 text-[13px] text-muted-foreground md:px-6">
        For{" "}
        <Link href={`/leads/${inv.lead_id}`} className="font-medium text-foreground hover:underline">
          {inv.customer_name}
        </Link>{" "}
        ({inv.customer_number}) · {inv.entity_name} · {inv.currency}
        {inv.issue_date && ` · issued ${day(inv.issue_date)}`}
        {inv.void_reason && <span className="text-red-700 dark:text-red-300"> · Void: {inv.void_reason}</span>}
      </div>
      {inv.status === "draft" ? <Draft key={inv.version} inv={inv} /> : <Issued inv={inv} />}
    </div>
  );
}

// ---------- a draft ----------
type LineDraft = { description: string; quantity: string; unit: string; discount: string; tax_rate_id: string; product_id: string | null };

function toDraft(inv: Invoice): LineDraft[] {
  return inv.lines.map((l) => ({
    description: l.description,
    quantity: String(l.quantity),
    unit: moneyInput(l.unit_price_minor, inv.currency),
    discount: l.discount_minor ? moneyInput(l.discount_minor, inv.currency) : "",
    tax_rate_id: l.tax_rate_id ?? "",
    product_id: l.product_id ?? null,
  }));
}

function Draft({ inv }: { inv: Invoice }) {
  const { can } = useAuth();
  const router = useRouter();
  const refresh = useRefreshMoney();
  const rates = useTaxRates();
  const entities = useEntities();
  const editable = can("invoices.create");
  const [lines, setLines] = useState<LineDraft[]>(() => toDraft(inv));
  const [notes, setNotes] = useState(inv.notes ?? "");
  const [due, setDue] = useState(inv.due_date ?? "");
  const [payLink, setPayLink] = useState(inv.pay_link);
  const [payDirect, setPayDirect] = useState(inv.pay_direct);
  const [repeat, setRepeat] = useState(inv.repeat_months ? String(inv.repeat_months) : "");
  const [split, setSplit] = useState({ count: String(Math.max(inv.installments.length, 2)), first: inv.installments[0]?.due_date ?? todayIso(), months: "1" });
  const [busy, setBusy] = useState(false);
  const defaultRate = rates.data?.find((r) => r.is_active)?.id ?? "";
  function body() {
    const out = [];
    for (const [i, l] of lines.entries()) {
      const unit = parseMoney(l.unit, inv.currency);
      const discount = parseMoney(l.discount || "0", inv.currency);
      const qty = Number(l.quantity);
      if (!l.description.trim()) throw new Error(`Line ${i + 1} needs a description`);
      if (unit === null || discount === null || !Number.isInteger(qty) || qty < 1) throw new Error(`Check the numbers on line ${i + 1}`);
      out.push({ description: l.description.trim(), quantity: qty, unit_price_minor: unit, discount_minor: discount, tax_rate_id: l.tax_rate_id || null, product_id: l.product_id });
    }
    return {
      version: inv.version,
      lines: out,
      notes,
      due_date: due || null,
      pay_link: payLink,
      pay_direct: payDirect,
      ...(repeat ? { repeat_months: Number(repeat) as 1 | 3 | 6 | 12, no_repeat: false } : { no_repeat: true }),
    };
  }
  async function save() {
    const out = unwrap(await api.PATCH("/api/v1/invoices/{invoice_id}", { params: { path: { invoice_id: inv.id } }, body: body() }));
    refresh();
    return out;
  }
  const set = (i: number, patch: Partial<LineDraft>) => setLines(lines.map((l, n) => (n === i ? { ...l, ...patch } : l)));

  return (
    <div className="grid items-start gap-4 p-4 md:px-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-4">
        <Section title="Lines">
          <div className="space-y-2">
            {lines.map((l, i) => (
              <div key={i} className="grid grid-cols-2 gap-2 rounded-lg border p-2 sm:grid-cols-[minmax(0,1fr)_64px_110px_100px_130px_32px]" data-line={i}>
                <Input aria-label="Description" className="col-span-2 sm:col-span-1" value={l.description} disabled={!editable} onChange={(e) => set(i, { description: e.target.value })} placeholder="What is it for" />
                <Input aria-label="Quantity" inputMode="numeric" value={l.quantity} disabled={!editable} onChange={(e) => set(i, { quantity: e.target.value })} />
                <Input aria-label="Unit price" inputMode="decimal" value={l.unit} disabled={!editable} onChange={(e) => set(i, { unit: e.target.value })} placeholder="Price" />
                <Input aria-label="Discount" inputMode="decimal" value={l.discount} disabled={!editable} onChange={(e) => set(i, { discount: e.target.value })} placeholder="Discount" />
                <NativeSelect aria-label="Tax" value={l.tax_rate_id} disabled={!editable} onChange={(e) => set(i, { tax_rate_id: e.target.value })}>
                  <option value="">No tax</option>
                  {(rates.data ?? [])
                    .filter((r) => r.is_active || r.id === l.tax_rate_id)
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}
                      </option>
                    ))}
                </NativeSelect>
                {editable && (
                  <Button size="icon" variant="ghost" aria-label="Remove line" onClick={() => setLines(lines.filter((_, n) => n !== i))}>
                    <Trash2 />
                  </Button>
                )}
              </div>
            ))}
          </div>
          {editable && (
            <Button size="sm" variant="outline" onClick={() => setLines([...lines, { description: "", quantity: "1", unit: "", discount: "", tax_rate_id: defaultRate, product_id: null }])}>
              <Plus /> Add line
            </Button>
          )}
          <Totals inv={inv} />
          <p className="text-[11px] text-muted-foreground">Totals update when you save. Tax is worked out on each line and rounded to the nearest {inv.currency === "JPY" ? "yen" : "paisa / cent"}.</p>
        </Section>
        <Section title="Installments">
          {inv.installments.length > 0 ? (
            <Schedule inv={inv} />
          ) : (
            <p className="text-xs text-muted-foreground">One payment of the full amount, due on the due date. Split it to let the customer pay in parts.</p>
          )}
          {editable && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <Label className="text-xs">Parts</Label>
                <Input className="w-16" inputMode="numeric" value={split.count} onChange={(e) => setSplit({ ...split, count: e.target.value })} aria-label="Number of installments" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">First due</Label>
                <Input type="date" value={split.first} onChange={(e) => setSplit({ ...split, first: e.target.value })} aria-label="First due date" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Every</Label>
                <NativeSelect className="w-28" value={split.months} onChange={(e) => setSplit({ ...split, months: e.target.value })} aria-label="Months between">
                  <option value="1">1 month</option>
                  <option value="2">2 months</option>
                  <option value="3">3 months</option>
                  <option value="6">6 months</option>
                </NativeSelect>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  await run(async () => {
                    await save();
                    unwrap(
                      await api.PUT("/api/v1/invoices/{invoice_id}/installments", {
                        params: { path: { invoice_id: inv.id } },
                        body: { count: Number(split.count), first_due_date: split.first, months_between: Number(split.months), days_between: 0 },
                      }),
                    );
                    refresh();
                  }, "Split into installments");
                  setBusy(false);
                }}
              >
                Split equally
              </Button>
            </div>
          )}
        </Section>
      </div>
      <div className="space-y-4">
        <Section title="Details">
          <div className="space-y-3 text-xs">
            <div className="space-y-1">
              <Label className="text-xs">Billed by</Label>
              <NativeSelect
                value={inv.entity_id}
                disabled={!editable}
                onChange={async (e) => {
                  await run(async () => {
                    unwrap(await api.PATCH("/api/v1/invoices/{invoice_id}", { params: { path: { invoice_id: inv.id } }, body: { version: inv.version, entity_id: e.target.value, no_repeat: false } }));
                    refresh();
                  });
                }}
              >
                {(entities.data ?? [])
                  .filter((x) => x.is_active)
                  .map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name} ({x.currency})
                    </option>
                  ))}
              </NativeSelect>
            </div>
            {inv.installments.length === 0 && (
              <div className="space-y-1">
                <Label className="text-xs">Due date</Label>
                <Input type="date" value={due} disabled={!editable} onChange={(e) => setDue(e.target.value)} />
                <p className="text-[11px] text-muted-foreground">Empty: the entity&apos;s usual days after issuing.</p>
              </div>
            )}
            <div className="space-y-2">
              <Label className="text-xs">How the customer can pay</Label>
              <label className="flex items-center justify-between gap-2">
                <span>Payment link (Razorpay / Stripe)</span>
                <Switch checked={payLink} disabled={!editable} onCheckedChange={setPayLink} aria-label="Payment link" />
              </label>
              <label className="flex items-center justify-between gap-2">
                <span>Pay directly (bank / UPI on the invoice)</span>
                <Switch checked={payDirect} disabled={!editable} onCheckedChange={setPayDirect} aria-label="Pay directly" />
              </label>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Repeat</Label>
              <NativeSelect value={repeat} disabled={!editable} onChange={(e) => setRepeat(e.target.value)} aria-label="Repeat">
                <option value="">Does not repeat</option>
                <option value="1">Every month</option>
                <option value="3">Every 3 months</option>
                <option value="6">Every 6 months</option>
                <option value="12">Every year</option>
              </NativeSelect>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Notes on the invoice</Label>
              <Textarea rows={3} value={notes} disabled={!editable} onChange={(e) => setNotes(e.target.value)} />
            </div>
          </div>
        </Section>
        {editable && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                await run(save, "Saved");
                setBusy(false);
              }}
            >
              Save draft
            </Button>
            <Button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                await run(async () => {
                  await save();
                  unwrap(await api.POST("/api/v1/invoices/{invoice_id}/issue", { params: { path: { invoice_id: inv.id } }, body: {} }));
                  refresh();
                }, "Invoice issued");
                setBusy(false);
              }}
            >
              <Receipt /> Issue invoice
            </Button>
            <Button variant="outline" onClick={() => openPdf("invoice", inv.id).catch((e) => toast.error(e.message))}>
              <FileText /> Preview
            </Button>
            <Button
              variant="ghost"
              className="text-muted-foreground hover:text-destructive"
              onClick={async () => {
                if (!confirm("Delete this draft?")) return;
                await run(async () => {
                  unwrap(await api.DELETE("/api/v1/invoices/{invoice_id}", { params: { path: { invoice_id: inv.id } } }));
                  refresh();
                  router.push(`/leads/${inv.lead_id}`);
                }, "Draft deleted");
              }}
            >
              Delete draft
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function Totals({ inv }: { inv: Invoice }) {
  const m = (n: number) => formatMoney(n, inv.currency);
  return (
    <dl className="ml-auto grid max-w-xs grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-[13px] tabular-nums" data-totals>
      <dt className="text-muted-foreground">Subtotal</dt>
      <dd className="text-right">{m(inv.subtotal_minor)}</dd>
      {inv.tax_breakdown.map((b) => (
        <div key={`${b.name}${b.rate_bp}`} className="contents">
          <dt className="text-muted-foreground">
            {String(b.name)} {percent(Number(b.rate_bp))}%
          </dt>
          <dd className="text-right">{m(Number(b.amount))}</dd>
        </div>
      ))}
      <dt className="border-t pt-1 font-semibold">Total</dt>
      <dd className="border-t pt-1 text-right font-semibold" data-total>
        {m(inv.total_minor)}
      </dd>
      {inv.paid_minor > 0 && (
        <>
          <dt className="text-muted-foreground">Paid</dt>
          <dd className="text-right text-emerald-700 dark:text-emerald-300">{m(inv.paid_minor)}</dd>
          <dt className="font-semibold">Balance due</dt>
          <dd className="text-right font-semibold" data-balance>
            {m(inv.total_minor - inv.paid_minor)}
          </dd>
        </>
      )}
    </dl>
  );
}

function Schedule({ inv, onLink }: { inv: Invoice; onLink?: (installmentId: string) => void }) {
  return (
    <ul className="divide-y text-xs">
      {inv.installments.map((i) => {
        const st = INSTALLMENT_STATE[i.state] ?? INSTALLMENT_STATE.due;
        const left = i.amount_minor - i.paid_minor;
        return (
          <li key={i.id} className="flex flex-wrap items-center gap-2 py-2" data-installment={i.position + 1}>
            <span className="w-6 text-muted-foreground">#{i.position + 1}</span>
            <span className="w-28">{day(i.due_date)}</span>
            <span className="font-medium tabular-nums">{formatMoney(i.amount_minor, inv.currency)}</span>
            <span className={cn("font-medium", st.tone)}>{st.label}</span>
            {i.paid_minor > 0 && left > 0 && <span className="text-muted-foreground">{formatMoney(left, inv.currency)} left</span>}
            {onLink && left > 0 && (
              <Button size="sm" variant="ghost" className="ml-auto h-7" onClick={() => onLink(i.id)}>
                <Link2 /> Payment link
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// ---------- issued / paid / void ----------
function Issued({ inv }: { inv: Invoice }) {
  const { can } = useAuth();
  const refresh = useRefreshMoney();
  const [paying, setPaying] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const open = inv.status === "issued" || inv.status === "partly_paid";
  const activeLinks = inv.links.filter((l) => l.status === "active");
  const canLink = open && inv.pay_link && Boolean(inv.gateway) && can("invoices.create");

  async function makeLink(installment_id: string | null) {
    const link = await run(async () => {
      const out = unwrap(await api.POST("/api/v1/invoices/{invoice_id}/links", { params: { path: { invoice_id: inv.id } }, body: { installment_id } }));
      refresh();
      return out;
    });
    if (link) {
      await navigator.clipboard?.writeText(link.url).catch(() => {});
      toast.success("Payment link created and copied");
    }
  }
  const message = useMemo(() => {
    const due = inv.total_minor - inv.paid_minor;
    const parts = [`Hello ${(inv.customer_name ?? "").split(" ")[0]}, here is invoice ${inv.number} for ${formatMoney(inv.total_minor, inv.currency)}.`];
    if (due > 0 && due !== inv.total_minor) parts.push(`Balance due: ${formatMoney(due, inv.currency)}.`);
    for (const l of activeLinks) parts.push(`Pay ${formatMoney(l.amount_minor, inv.currency)} online: ${l.url}`);
    if (inv.pay_direct) parts.push("Bank and UPI details are on the invoice.");
    return parts.join("\n");
  }, [inv, activeLinks]);

  return (
    <div className="grid items-start gap-4 p-4 md:px-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => openPdf("invoice", inv.id).catch((e) => toast.error(e.message))}>
            <FileText /> View PDF
          </Button>
          <Button variant="outline" onClick={() => openPdf("invoice", inv.id, true).catch((e) => toast.error(e.message))}>
            <Download /> Download
          </Button>
          {can("invoices.create") && (
            <Button
              variant="outline"
              onClick={() =>
                run(async () => {
                  unwrap(await api.POST("/api/v1/invoices/{invoice_id}/email", { params: { path: { invoice_id: inv.id } } }));
                  refresh();
                }, `Emailing ${inv.customer_email}`)
              }
            >
              <Mail /> Email
            </Button>
          )}
          {can("invoices.create") && inv.customer_phone && inv.status !== "void" && (
            <a
              className={buttonVariants({ variant: "outline" })}
              href={whatsappLink(inv.customer_phone, message)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => api.POST("/api/v1/invoices/{invoice_id}/shared", { params: { path: { invoice_id: inv.id } }, body: { channel: "whatsapp" } }).then(refresh)}
            >
              <MessageCircle /> Send on WhatsApp
            </a>
          )}
          {open && can("payments.record") && (
            <Button onClick={() => setPaying(true)}>
              <Wallet /> Record payment
            </Button>
          )}
          {inv.status !== "void" && can("invoices.void") && (
            <Button variant="ghost" className="text-muted-foreground hover:text-destructive" onClick={() => setVoiding(true)}>
              <Ban /> Void
            </Button>
          )}
        </div>
        <Section title="Lines">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="py-1 font-medium">Description</th>
                  <th className="py-1 text-right font-medium">Qty</th>
                  <th className="py-1 text-right font-medium">Price</th>
                  <th className="py-1 text-right font-medium">Discount</th>
                  <th className="py-1 text-right font-medium">Tax</th>
                  <th className="py-1 text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y tabular-nums">
                {inv.lines.map((l) => (
                  <tr key={l.id}>
                    <td className="py-1.5">{l.description}</td>
                    <td className="py-1.5 text-right">{l.quantity}</td>
                    <td className="py-1.5 text-right">{formatMoney(l.unit_price_minor, inv.currency)}</td>
                    <td className="py-1.5 text-right">{l.discount_minor ? formatMoney(l.discount_minor, inv.currency) : "—"}</td>
                    <td className="py-1.5 text-right">{l.tax_name ?? "—"}</td>
                    <td className="py-1.5 text-right">{formatMoney(l.total_minor, inv.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Totals inv={inv} />
        </Section>
        <Section
          title="Installments"
          action={
            canLink && inv.installments.length > 1 ? (
              <Button size="sm" variant="ghost" className="h-7" onClick={() => makeLink(null)}>
                <Link2 /> Link for the whole balance
              </Button>
            ) : undefined
          }
        >
          <Schedule inv={inv} onLink={canLink ? (id) => makeLink(inv.installments.length > 1 ? id : null) : undefined} />
          {open && inv.pay_link && !inv.gateway && (
            <p className="text-[11px] text-muted-foreground">
              Payment links need Razorpay or Stripe connected in{" "}
              <Link href="/settings/money" className="underline">
                Settings → Money
              </Link>
              . The customer can still pay directly.
            </p>
          )}
          {activeLinks.length > 0 && (
            <ul className="space-y-1 text-xs">
              {activeLinks.map((l) => (
                <li key={l.id} className="flex items-center gap-2">
                  <span className="text-muted-foreground">Link {formatMoney(l.amount_minor, inv.currency)}:</span>
                  <a href={l.url} target="_blank" rel="noopener noreferrer" className="truncate text-primary hover:underline">
                    {l.url}
                  </a>
                  <Button size="icon" variant="ghost" className="size-6" aria-label="Copy link" onClick={() => navigator.clipboard?.writeText(l.url).then(() => toast.success("Copied"))}>
                    <Copy />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Payments">
          {inv.payments.length === 0 ? (
            <p className="text-xs text-muted-foreground">No payments yet.</p>
          ) : (
            <ul className="divide-y text-xs">
              {inv.payments.map((p) => (
                <li key={p.id} className={cn("flex flex-wrap items-center gap-2 py-2", p.status === "reversed" && "opacity-60")} data-payment={p.receipt_number}>
                  <span className={cn("font-semibold tabular-nums", p.status === "reversed" && "line-through")}>{formatMoney(p.amount_minor, p.currency)}</span>
                  <span>{METHOD_LABEL[p.method] ?? p.method}</span>
                  <span className="text-muted-foreground">{day(p.paid_on)}</span>
                  {p.reference && <span className="text-muted-foreground">Ref {p.reference}</span>}
                  {p.status === "reversed" && <span className="text-red-700 dark:text-red-300">Reversed: {p.reverse_reason}</span>}
                  <span className="ml-auto flex items-center gap-1">
                    <Button size="sm" variant="ghost" className="h-7" onClick={() => openPdf("receipt", p.id).catch((e) => toast.error(e.message))}>
                      <Receipt /> {p.receipt_number}
                    </Button>
                    {p.has_proof && (
                      <Button size="sm" variant="ghost" className="h-7" onClick={() => openPdf("proof", p.id).catch((e) => toast.error(e.message))}>
                        Proof
                      </Button>
                    )}
                    {p.status === "ok" && can("payments.reverse") && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-muted-foreground hover:text-destructive"
                        onClick={async () => {
                          const reason = prompt("Why is this payment reversed? (for example: cheque bounced)");
                          if (!reason?.trim()) return;
                          await run(async () => {
                            unwrap(await api.POST("/api/v1/payments/{payment_id}/reverse", { params: { path: { payment_id: p.id } }, body: { reason } }));
                            refresh();
                          }, "Payment reversed");
                        }}
                      >
                        <Undo2 /> Reverse
                      </Button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <div className="space-y-4">
        <Section title="Summary">
          <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-xs">
            <dt className="text-muted-foreground">Total</dt>
            <dd className="font-semibold tabular-nums">{formatMoney(inv.total_minor, inv.currency)}</dd>
            <dt className="text-muted-foreground">Paid</dt>
            <dd className="tabular-nums">{formatMoney(inv.paid_minor, inv.currency)}</dd>
            <dt className="text-muted-foreground">Due</dt>
            <dd className={cn("tabular-nums", inv.overdue_minor > 0 && "font-semibold text-red-700 dark:text-red-300")}>
              {formatMoney(inv.status === "void" ? 0 : inv.total_minor - inv.paid_minor, inv.currency)}
              {inv.overdue_minor > 0 && ` (${formatMoney(inv.overdue_minor, inv.currency)} overdue)`}
            </dd>
            <dt className="text-muted-foreground">Due date</dt>
            <dd>{day(inv.due_date)}</dd>
            <dt className="text-muted-foreground">Pay by</dt>
            <dd>{[inv.pay_link && "Payment link", inv.pay_direct && "Bank / UPI"].filter(Boolean).join(" or ")}</dd>
            <dt className="text-muted-foreground">Repeats</dt>
            <dd>
              {inv.status !== "void" && can("invoices.create") ? (
                <NativeSelect
                  className="h-7"
                  aria-label="Repeat"
                  value={inv.repeat_months ? String(inv.repeat_months) : ""}
                  onChange={(e) =>
                    run(async () => {
                      const months = e.target.value ? (Number(e.target.value) as 1 | 3 | 6 | 12) : null;
                      unwrap(await api.POST("/api/v1/invoices/{invoice_id}/repeat", { params: { path: { invoice_id: inv.id } }, body: { months } }));
                      refresh();
                    })
                  }
                >
                  <option value="">No</option>
                  <option value="1">Every month</option>
                  <option value="3">Every 3 months</option>
                  <option value="6">Every 6 months</option>
                  <option value="12">Every year</option>
                </NativeSelect>
              ) : inv.repeat_months ? (
                `Every ${inv.repeat_months} months`
              ) : (
                "No"
              )}
              {inv.repeat_next_date && (
                <span className="mt-1 flex items-center gap-1 text-muted-foreground">
                  <Repeat className="size-3" /> Next on {day(inv.repeat_next_date)}
                </span>
              )}
            </dd>
          </dl>
        </Section>
        <Section title="Emails to the customer">
          {inv.messages.length === 0 ? (
            <p className="text-xs text-muted-foreground">None yet. Emails go from your company&apos;s mailbox once it is connected in Settings → Money.</p>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {inv.messages.map((m) => (
                <li key={m.id} className="flex items-center gap-2">
                  <span className="capitalize">{m.kind}</span>
                  <span className="truncate text-muted-foreground">{m.to_address}</span>
                  <span className={cn("ml-auto", m.status === "failed" ? "text-red-700 dark:text-red-300" : "text-muted-foreground")} title={m.error ?? undefined}>
                    {m.status === "sent" ? `sent ${relative(m.sent_at)}` : m.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      {paying && <RecordPayment inv={inv} onClose={() => setPaying(false)} />}
      {voiding && <VoidDialog inv={inv} onClose={() => setVoiding(false)} />}
    </div>
  );
}

function RecordPayment({ inv, onClose }: { inv: Invoice; onClose: () => void }) {
  const refresh = useRefreshMoney();
  const next = inv.installments.find((i) => i.paid_minor < i.amount_minor);
  const [amount, setAmount] = useState(moneyInput(next ? next.amount_minor - next.paid_minor : inv.total_minor - inv.paid_minor, inv.currency));
  const [method, setMethod] = useState<(typeof METHODS)[number]["value"]>("bank");
  const [paidOn, setPaidOn] = useState(todayIso());
  const [reference, setReference] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit() {
    const minor = parseMoney(amount, inv.currency);
    if (!minor) return toast.error("Enter the amount received");
    if (!file) return toast.error("Attach the proof: a photo or PDF of the transfer, receipt or cheque");
    setBusy(true);
    await run(async () => {
      const ready = await shrinkPhoto(file);
      unwrap(
        await api.POST("/api/v1/invoices/{invoice_id}/payments", {
          params: { path: { invoice_id: inv.id }, query: { amount_minor: minor, method, paid_on: paidOn, name: ready.name, reference: reference || null } },
          body: ready as unknown as string,
          bodySerializer: (b: unknown) => b as BodyInit,
          headers: { "Content-Type": "application/octet-stream" },
        }),
      );
      refresh();
      onClose();
    }, "Payment recorded");
    setBusy(false);
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Record a payment for {inv.number}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="pay-amount">Amount ({inv.currency})</Label>
            <Input id="pay-amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="pay-method">How it was paid</Label>
            <NativeSelect id="pay-method" value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
              {METHODS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-1">
            <Label htmlFor="pay-date">Paid on</Label>
            <Input id="pay-date" type="date" max={todayIso()} value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="pay-ref">Reference (UTR, cheque no.)</Label>
            <Input id="pay-ref" value={reference} onChange={(e) => setReference(e.target.value)} />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="pay-proof">Proof (required)</Label>
            <Input id="pay-proof" type="file" accept="application/pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={busy} onClick={submit}>
            Record payment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function VoidDialog({ inv, onClose }: { inv: Invoice; onClose: () => void }) {
  const refresh = useRefreshMoney();
  const [reason, setReason] = useState("");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Void {inv.number}?</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">The number stays used and the invoice stays on record, marked void. Open payment links are switched off. To change an invoice, void it and issue a new one.</p>
        <div className="space-y-1">
          <Label htmlFor="void-reason">Why is it voided?</Label>
          <Textarea id="void-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Keep it
          </Button>
          <Button
            variant="destructive"
            disabled={!reason.trim()}
            onClick={() =>
              run(async () => {
                unwrap(await api.POST("/api/v1/invoices/{invoice_id}/void", { params: { path: { invoice_id: inv.id } }, body: { reason } }));
                refresh();
                onClose();
              }, "Invoice voided")
            }
          >
            Void invoice
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
