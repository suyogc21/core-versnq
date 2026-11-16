"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

/** Marketing → Landing pages (batch 5a): every page, its address, visits and leads. */
export default function LandingPagesPage() {
  const router = useRouter();
  const pages = useQuery({ queryKey: ["landing-pages"], queryFn: async () => unwrap(await api.GET("/api/v1/landing-pages")) });

  async function create() {
    try {
      const slug = `page-${Math.random().toString(36).slice(2, 7)}`;
      const page = unwrap(
        await api.POST("/api/v1/landing-pages", {
          body: { title: "New page", slug, published: false, blocks: [{ type: "heading", text: "Your headline", level: 1 }] },
        }),
      );
      router.push(`/landing-pages/${page.id}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Landing pages" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-4xl space-y-4 p-4 sm:p-6">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm text-muted-foreground">Simple pages with your forms, shared at your company&apos;s address. Leads from a page&apos;s form are counted for it.</p>
            <Button onClick={create}>New page</Button>
          </div>
          {pages.data && pages.data.length === 0 && <p className="text-sm text-muted-foreground">No pages yet.</p>}
          <ul className="divide-y rounded-lg border">
            {(pages.data ?? []).map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                <Link href={`/landing-pages/${p.id}`} className="font-medium hover:underline">
                  {p.title}
                </Link>
                <span className="font-mono text-xs text-muted-foreground">{p.path}</span>
                <span className={p.published ? "text-emerald-600" : "text-muted-foreground"}>{p.published ? "Published" : "Draft"}</span>
                <span className="ml-auto tabular-nums text-muted-foreground">
                  {p.visits} visits · {p.leads} leads
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
