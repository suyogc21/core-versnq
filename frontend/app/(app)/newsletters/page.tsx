"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { pct, STATUS_LABELS, useNewsletters } from "@/lib/newsletters";

/** Newsletters (finishing plan, batch 5b): one email to many people. */
export default function NewslettersPage() {
  const { can } = useAuth();
  const router = useRouter();
  const list = useNewsletters();
  const [name, setName] = useState("");
  if (!can("newsletters.manage")) return <p className="p-8 text-center text-muted-foreground">Ask your admin to let you send newsletters.</p>;

  async function create() {
    try {
      const nl = unwrap(
        await api.POST("/api/v1/newsletters", {
          body: {
            name: name.trim(),
            subject: "News from {{company.name}}",
            body: "Hi {{lead.first_name|there}},\n\n",
            path: "mailboxes",
            audience: { view_id: null, filter: {}, customers_only: false },
          },
        }),
      );
      router.push(`/newsletters/${nl.id}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Newsletters" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-4xl space-y-4 p-4 sm:p-6">
          <p className="text-sm text-muted-foreground">
            One email to many people: a saved view, tags, or your customers. Only people who can get email receive it. Anyone who unsubscribed or opted out is left
            out automatically.
          </p>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) create();
            }}
          >
            <Input aria-label="Newsletter name" placeholder="Name, e.g. November update" value={name} onChange={(e) => setName(e.target.value)} />
            <Button type="submit" disabled={!name.trim()}>
              <Plus /> New newsletter
            </Button>
          </form>
          <div className="surface divide-y">
            {(list.data ?? []).length === 0 && <p className="p-4 text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "No newsletters yet."}</p>}
            {(list.data ?? []).map((n) => (
              <Link key={n.id} href={`/newsletters/${n.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm hover:bg-accent" data-newsletter={n.name}>
                <span className="font-medium">{n.name}</span>
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{STATUS_LABELS[n.status] ?? n.status}</span>
                <span className="ml-auto text-muted-foreground">
                  {n.report.sent ? `${n.report.sent} sent · ${pct(n.report.opened, n.report.sent)} opened · ${pct(n.report.clicked, n.report.sent)} clicked` : n.subject}
                </span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
