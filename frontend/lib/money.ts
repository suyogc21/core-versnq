"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components, paths } from "@/lib/api/schema";

export type Invoice = components["schemas"]["InvoiceDetail"];
export type InvoiceRow = components["schemas"]["InvoiceRow"];
export type InvoiceLine = components["schemas"]["InvoiceLineOut"];
export type LineBody = components["schemas"]["LineBody"];
export type Payment = components["schemas"]["PaymentOut"];
export type Entity = components["schemas"]["EntityOut"];
export type TaxRate = components["schemas"]["TaxOut"];
export type Gateway = components["schemas"]["GatewayOut"];
export type Mailbox = components["schemas"]["MailOut"];
export type MoneySettings = components["schemas"]["MoneySettings"];
export type AgingRow = components["schemas"]["AgingRow"];
export type InvoiceQuery = NonNullable<paths["/api/v1/invoices"]["get"]["parameters"]["query"]>;

/** Is the money module switched on for this company? */
export function useMoneyOn() {
  const q = useQuery({
    queryKey: ["modules"],
    staleTime: 60_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/modules")),
  });
  return Boolean(q.data?.find((m) => m.key === "money")?.enabled);
}

export function useInvoices(query: InvoiceQuery, enabled = true) {
  return useQuery({ queryKey: ["invoices", query], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/invoices", { params: { query } })) });
}
export function useInvoice(id: string) {
  return useQuery({
    queryKey: ["invoice", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/invoices/{invoice_id}", { params: { path: { invoice_id: id } } })),
  });
}
export function useCustomerMoney(customerId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["customer-money", customerId],
    enabled: enabled && Boolean(customerId),
    queryFn: async () => unwrap(await api.GET("/api/v1/customers/{customer_id}/money", { params: { path: { customer_id: customerId! } } })),
  });
}
export function usePayments(enabled = true) {
  return useQuery({ queryKey: ["payments"], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/payments", { params: { query: { limit: 200 } } })) });
}
export function useAging(enabled = true) {
  return useQuery({ queryKey: ["aging"], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/money/aging")) });
}
export function useEntities() {
  return useQuery({ queryKey: ["entities"], queryFn: async () => unwrap(await api.GET("/api/v1/money/entities")) });
}
export function useTaxRates() {
  return useQuery({ queryKey: ["tax-rates"], queryFn: async () => unwrap(await api.GET("/api/v1/money/tax-rates")) });
}
export function useGateways(enabled = true) {
  return useQuery({ queryKey: ["gateways"], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/money/gateways")) });
}
export function useMailbox(enabled = true) {
  return useQuery({ queryKey: ["mailbox"], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/money/mailbox")) });
}
export function useMoneySettings() {
  return useQuery({ queryKey: ["money-settings"], queryFn: async () => unwrap(await api.GET("/api/v1/money/settings")) });
}

/** After any money change: refresh everything that shows money. */
export function useRefreshMoney() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["invoices", "invoice", "customer-money", "payments", "aging", "timeline", "tasks"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

export const INVOICE_STATUS: Record<string, { label: string; tone: string }> = {
  draft: { label: "Draft", tone: "bg-muted text-muted-foreground" },
  issued: { label: "Issued", tone: "bg-sky-500/10 text-sky-700 dark:text-sky-300" },
  partly_paid: { label: "Partly paid", tone: "bg-amber-500/10 text-amber-700 dark:text-amber-300" },
  paid: { label: "Paid", tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" },
  void: { label: "Void", tone: "bg-red-500/10 text-red-700 line-through dark:text-red-300" },
};
export const INSTALLMENT_STATE: Record<string, { label: string; tone: string }> = {
  due: { label: "Due", tone: "text-muted-foreground" },
  partly_paid: { label: "Partly paid", tone: "text-amber-700 dark:text-amber-300" },
  paid: { label: "Paid", tone: "text-emerald-700 dark:text-emerald-300" },
  overdue: { label: "Overdue", tone: "text-red-700 dark:text-red-300" },
};
export const METHODS: { value: "bank" | "upi" | "cash" | "cheque" | "card" | "other"; label: string }[] = [
  { value: "bank", label: "Bank transfer" },
  { value: "upi", label: "UPI" },
  { value: "cash", label: "Cash" },
  { value: "cheque", label: "Cheque" },
  { value: "card", label: "Card (machine)" },
  { value: "other", label: "Other" },
];
export const METHOD_LABEL: Record<string, string> = { gateway: "Online", ...Object.fromEntries(METHODS.map((m) => [m.value, m.label])) };

/** 900 basis points → "9". */
export const percent = (bp: number) => String(bp / 100).replace(/\.0+$/, "");
/** "9" or "2.5" → basis points, exactly (no floats kept). null when not valid. */
export function toBp(text: string): number | null {
  const m = text.trim().match(/^(\d{1,3})(?:\.(\d{1,2}))?$/);
  if (!m) return null;
  const bp = Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
  return bp <= 10000 ? bp : null;
}

export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** Open a PDF or file the signed-in person may see, in a new tab (fetched with their access). */
export async function openPdf(url: "invoice" | "receipt" | "proof", id: string, download = false) {
  const res =
    url === "invoice"
      ? await api.GET("/api/v1/invoices/{invoice_id}/pdf", { params: { path: { invoice_id: id }, query: { download } }, parseAs: "blob" })
      : url === "receipt"
        ? await api.GET("/api/v1/payments/{payment_id}/receipt", { params: { path: { payment_id: id }, query: { download } }, parseAs: "blob" })
        : await api.GET("/api/v1/payments/{payment_id}/proof", { params: { path: { payment_id: id }, query: { download } }, parseAs: "blob" });
  if (res.error || !res.data) throw new Error("Could not open the file");
  const href = URL.createObjectURL(res.data as Blob);
  if (download) {
    const a = document.createElement("a");
    a.href = href;
    a.download = "";
    a.click();
  } else {
    window.open(href, "_blank", "noopener");
  }
  setTimeout(() => URL.revokeObjectURL(href), 60_000);
}

/** wa.me link with the message ready: the rep presses send in their own WhatsApp. */
export function whatsappLink(phoneE164: string | null | undefined, text: string): string {
  const to = (phoneE164 ?? "").replace(/\D/g, "");
  return `https://wa.me/${to}?text=${encodeURIComponent(text)}`;
}
