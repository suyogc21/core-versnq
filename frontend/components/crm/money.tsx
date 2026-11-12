"use client";

import { FilePlus2, ReceiptText } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { formatMoney } from "@/lib/deals";
import { INVOICE_STATUS, day, useCustomerMoney, useMoneyOn, useRefreshMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

export function InvoiceStatus({ status, overdue = 0 }: { status: string; overdue?: number }) {
  const s = INVOICE_STATUS[status] ?? INVOICE_STATUS.draft;
  return (
    <span className="inline-flex items-center gap-1">
      <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", s.tone)}>{s.label}</span>
      {overdue > 0 && <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-[11px] font-medium text-red-700 dark:text-red-300">Overdue</span>}
    </span>
  );
}

/** "New invoice" for a customer (optionally from a won deal): makes a draft and opens it. */
export function NewInvoiceButton({ customerId, dealId, size = "sm", variant = "default" }: { customerId: string; dealId?: string; size?: "sm" | "default"; variant?: "default" | "outline" }) {
  const router = useRouter();
  const refresh = useRefreshMoney();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size={size}
      variant={variant}
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          const inv = unwrap(await api.POST("/api/v1/invoices", { body: { customer_id: customerId, deal_id: dealId ?? null } }));
          refresh();
          router.push(`/invoices/${inv.id}`);
        } catch (e) {
          toast.error((e as Error).message);
          setBusy(false);
        }
      }}
    >
      <FilePlus2 /> {dealId ? "Create invoice" : "New invoice"}
    </Button>
  );
}

/** The customer's money on their page: balance per currency and their invoices. */
export function MoneyCard({ customerId }: { customerId: string }) {
  const { can } = useAuth();
  const on = useMoneyOn();
  const money = useCustomerMoney(customerId, on && can("invoices.read"));
  if (!on || !can("invoices.read")) return null;
  const data = money.data;
  return (
    <section className="surface space-y-3 p-4" data-card="money">
      <h4 className="flex items-center justify-between gap-2 text-[13px] font-semibold">
        <span className="flex items-center gap-1.5">
          <ReceiptText className="size-4 opacity-70" /> Money
        </span>
        {can("invoices.create") && <NewInvoiceButton customerId={customerId} variant="outline" />}
      </h4>
      {money.isLoading ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : !data?.invoices.length ? (
        <p className="text-xs text-muted-foreground">No invoices yet.</p>
      ) : (
        <>
          {data.balances.map((b) => (
            <div key={b.currency} className="grid grid-cols-3 gap-2 rounded-lg bg-muted/50 p-2.5 text-center">
              <div>
                <div className="text-[11px] text-muted-foreground">Billed</div>
                <div className="text-sm font-semibold tabular-nums">{formatMoney(b.billed_minor, b.currency)}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">Paid</div>
                <div className="text-sm font-semibold text-emerald-700 tabular-nums dark:text-emerald-300">{formatMoney(b.paid_minor, b.currency)}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">{b.overdue_minor ? "Overdue" : "Due"}</div>
                <div className={cn("text-sm font-semibold tabular-nums", b.overdue_minor ? "text-red-700 dark:text-red-300" : "")}>
                  {formatMoney(b.overdue_minor || b.due_minor, b.currency)}
                </div>
              </div>
            </div>
          ))}
          <ul className="divide-y text-xs">
            {data.invoices.map((i) => (
              <li key={i.id}>
                <Link href={`/invoices/${i.id}`} className="flex items-center gap-2 py-2 hover:bg-muted/40">
                  <span className="font-medium tabular-nums">{i.number ?? "Draft"}</span>
                  <InvoiceStatus status={i.status} overdue={i.overdue_minor} />
                  <span className="ml-auto tabular-nums">{formatMoney(i.total_minor, i.currency)}</span>
                  {i.next_due_date && <span className="w-20 text-right text-muted-foreground">due {day(i.next_due_date).replace(/ \d{4}$/, "")}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
