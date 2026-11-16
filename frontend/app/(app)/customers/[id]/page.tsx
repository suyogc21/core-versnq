"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { PageHeader } from "@/components/app/app-shell";
import { Avatar } from "@/components/crm/bits";
import { CustomerCard, DocumentsCard } from "@/components/crm/customers";
import { MoneyCard } from "@/components/crm/money";
import { useAuth } from "@/lib/auth";
import { phone } from "@/lib/crm";
import { useCustomer } from "@/lib/customers";
import { useLabels } from "@/lib/settings";

/** One customer: for people who do not work leads (Finance), and a short view for everyone. */
export default function CustomerPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const label = useLabels();
  const customer = useCustomer(id);
  const c = customer.data;
  if (customer.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!c) {
    return (
      <>
        <PageHeader back={{ href: "/customers", label: label("customer", true) }} title="Not found" />
        <p className="p-8 text-center text-muted-foreground">This {label("customer").toLowerCase()} doesn&apos;t exist or you don&apos;t have access to it.</p>
      </>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="space-y-1 px-4 pt-4 pb-2 md:px-6 md:pt-5">
        <div className="text-xs text-muted-foreground">
          <Link href="/customers" className="hover:underline">
            {label("customer", true)}
          </Link>{" "}
          / {c.name}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Avatar name={c.name ?? "?"} colour="#10b981" size={12} />
          <div className="min-w-0">
            <h2 className="truncate text-2xl font-bold tracking-tight">{c.name}</h2>
            <div className="text-[13px] text-muted-foreground">{[c.number, c.phone && phone(c.phone), c.email, c.owner_name && `Owner: ${c.owner_name}`].filter(Boolean).join(" · ")}</div>
          </div>
          {can("leads.edit") && (
            <Link href={`/leads/${c.lead_id}`} className="ms-auto text-xs font-medium text-primary hover:underline">
              Open full record ↗
            </Link>
          )}
        </div>
      </div>
      <div className="grid items-start gap-4 p-4 md:px-6 lg:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-4">
          <CustomerCard customer={c} />
          <MoneyCard customerId={c.id} />
        </div>
        <DocumentsCard customer={c} />
      </div>
    </div>
  );
}
