"use client";

import Link from "next/link";
import { Download } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { InvoiceStatus } from "@/components/crm/money";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { formatMoney } from "@/lib/deals";
import { type InvoiceQuery, METHOD_LABEL, day, openPdf, useAging, useInvoices, useMoneyOn, usePayments } from "@/lib/money";
import { exportCsv } from "@/lib/reports";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "invoices", label: "Invoices" },
  { key: "overdue", label: "Overdue" },
  { key: "payments", label: "Payments" },
  { key: "aging", label: "Aging" },
] as const;
type Tab = (typeof TABS)[number]["key"];
const STATUSES = ["draft", "issued", "partly_paid", "paid", "void"] as const;

export default function MoneyPage() {
  return (
    <Suspense>
      <MoneyTabs />
    </Suspense>
  );
}

function MoneyTabs() {
  const { can } = useAuth();
  const on = useMoneyOn();
  const asked = useSearchParams().get("tab");
  const [tab, setTab] = useState<Tab>(() => (TABS.some((t) => t.key === asked) ? (asked as Tab) : "invoices"));
  if (!can("invoices.read")) return <p className="p-8 text-center text-muted-foreground">You don&apos;t have access to money.</p>;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Money" />
      <div className="flex gap-1 border-b px-4 py-2 sm:px-6" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={cn("rounded-lg px-3 py-1 text-[13px] font-medium text-muted-foreground hover:text-foreground", tab === t.key && "bg-card text-foreground shadow-card")}
          >
            {t.label}
          </button>
        ))}
      </div>
      {!on ? (
        <p className="p-8 text-center text-muted-foreground">Money is switched off for your company.</p>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto p-4 sm:px-6">
          {tab === "invoices" && <Invoices />}
          {tab === "overdue" && <Invoices overdue />}
          {tab === "payments" && <Payments />}
          {tab === "aging" && <Aging />}
        </div>
      )}
    </div>
  );
}

function Invoices({ overdue = false }: { overdue?: boolean }) {
  const { can } = useAuth();
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<(typeof STATUSES)[number] | "">("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
  }, [search]);
  const query: InvoiceQuery = { q: q || undefined, status: status ? [status] : undefined, overdue: overdue || undefined, sort: overdue ? "due" : "-created", page, page_size: 50 };
  const list = useInvoices(query);
  const rows = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search number or customer…" className="h-8 w-full sm:w-72" value={search} onChange={(e) => setSearch(e.target.value)} />
        {!overdue && (
          <div className="flex flex-wrap gap-1">
            {(["", ...STATUSES] as const).map((s) => (
              <button
                key={s || "all"}
                onClick={() => (setStatus(s), setPage(1))}
                className={cn("rounded-full border px-2.5 py-0.5 text-xs", status === s ? "border-foreground/30 bg-card font-medium" : "text-muted-foreground")}
              >
                {s ? s.replace("_", " ").replace(/^./, (c) => c.toUpperCase()) : "All"}
              </button>
            ))}
          </div>
        )}
        <span className="ml-auto text-xs text-muted-foreground">{total} invoices</span>
        {can("invoices.export") && (
          <Button size="sm" variant="ghost" onClick={() => exportCsv("/api/v1/invoices/export", { q: query.q, status: query.status, overdue: query.overdue }, overdue ? "overdue-invoices" : "invoices").catch((e) => toast.error(e.message))}>
            <Download /> Export
          </Button>
        )}
      </div>
      <div className="surface overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="px-3 py-2 font-medium">Number</th>
              <th className="px-3 py-2 font-medium">Customer</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 text-right font-medium">Total</th>
              <th className="px-3 py-2 text-right font-medium">{overdue ? "Overdue" : "Due"}</th>
              <th className="hidden px-3 py-2 font-medium sm:table-cell">Next due</th>
              <th className="hidden px-3 py-2 font-medium md:table-cell">Owner</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((i) => (
              <tr key={i.id} className="cursor-pointer hover:bg-muted/40" onClick={() => router.push(`/invoices/${i.id}`)} data-invoice={i.number ?? "draft"}>
                <td className="px-3 py-2 font-medium tabular-nums">{i.number ?? "Draft"}</td>
                <td className="px-3 py-2">
                  {i.customer_name} <span className="text-xs text-muted-foreground">{i.customer_number}</span>
                </td>
                <td className="px-3 py-2">
                  <InvoiceStatus status={i.status} overdue={i.overdue_minor} />
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{formatMoney(i.total_minor, i.currency)}</td>
                <td className={cn("px-3 py-2 text-right tabular-nums", overdue && "font-medium text-red-700 dark:text-red-300")}>
                  {i.status === "void" || i.status === "draft" ? "—" : formatMoney(overdue ? i.overdue_minor : i.total_minor - i.paid_minor, i.currency)}
                </td>
                <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">{day(i.next_due_date)}</td>
                <td className="hidden px-3 py-2 text-muted-foreground md:table-cell">{i.owner_name ?? "Unassigned"}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
                  {list.isLoading ? "Loading…" : overdue ? "Nothing is overdue." : "No invoices yet. Open a customer and choose “New invoice”."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {total > 50 && (
        <div className="flex items-center justify-end gap-2 text-xs">
          <Button size="sm" variant="outline" disabled={page === 1} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <span>
            Page {page} of {Math.ceil(total / 50)}
          </span>
          <Button size="sm" variant="outline" disabled={page * 50 >= total} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}

function Payments() {
  const { can } = useAuth();
  const list = usePayments();
  const rows = list.data ?? [];
  return (
    <div className="space-y-3">
      {can("invoices.export") && (
        <div className="flex justify-end">
          <Button size="sm" variant="ghost" onClick={() => exportCsv("/api/v1/payments/export", {}, "payments").catch((e) => toast.error(e.message))}>
            <Download /> Export
          </Button>
        </div>
      )}
    <div className="surface overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="px-3 py-2 font-medium">Paid on</th>
            <th className="px-3 py-2 font-medium">Customer</th>
            <th className="px-3 py-2 font-medium">Invoice</th>
            <th className="px-3 py-2 text-right font-medium">Amount</th>
            <th className="hidden px-3 py-2 font-medium sm:table-cell">Method</th>
            <th className="px-3 py-2 font-medium">Receipt</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((p) => (
            <tr key={p.id} className={cn(p.status === "reversed" && "opacity-60")}>
              <td className="px-3 py-2">{day(p.paid_on)}</td>
              <td className="px-3 py-2">{p.customer_name}</td>
              <td className="px-3 py-2">
                <Link href={`/invoices/${p.invoice_id}`} className="hover:underline">
                  {p.invoice_number}
                </Link>
              </td>
              <td className={cn("px-3 py-2 text-right tabular-nums", p.status === "reversed" && "line-through")}>{formatMoney(p.amount_minor, p.currency)}</td>
              <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">{METHOD_LABEL[p.method] ?? p.method}</td>
              <td className="px-3 py-2">
                <button className="text-primary hover:underline" onClick={() => openPdf("receipt", p.id).catch((e) => toast.error(e.message))}>
                  {p.receipt_number}
                </button>
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                {list.isLoading ? "Loading…" : "No payments yet."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
    </div>
  );
}

function Aging() {
  const aging = useAging();
  const rows = aging.data ?? [];
  if (aging.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!rows.length) return <p className="p-8 text-center text-muted-foreground">Nothing is due.</p>;
  return (
    <div className="space-y-4">
      {rows.map((r) => (
        <section key={`${r.entity_id}${r.currency}`} className="surface space-y-3 p-4" data-aging={r.currency}>
          <h4 className="text-[13px] font-semibold">
            {r.entity_name} · {r.currency}
          </h4>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
            {[
              ["Not yet due", r.due_later_minor],
              ["0–30 days", r.buckets["0-30"]],
              ["31–60 days", r.buckets["31-60"]],
              ["61–90 days", r.buckets["61-90"]],
              ["90+ days", r.buckets["90+"]],
              ["Total overdue", r.total_minor],
            ].map(([name, amount], n) => (
              <div key={String(name)} className={cn("rounded-lg bg-muted/50 p-2.5", n === 5 && "bg-red-500/10")}>
                <div className="text-[11px] text-muted-foreground">{name}</div>
                <div className={cn("text-sm font-semibold tabular-nums", n > 0 && Number(amount) > 0 && "text-red-700 dark:text-red-300")}>{formatMoney(Number(amount), r.currency)}</div>
              </div>
            ))}
          </div>
        </section>
      ))}
      <p className="text-xs text-muted-foreground">Days late are counted from each installment&apos;s due date. Amounts in different currencies are never added together.</p>
    </div>
  );
}
