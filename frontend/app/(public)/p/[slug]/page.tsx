"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { HostedForm, useFormPage } from "@/components/public/hosted-form";
import type { components } from "@/lib/api/schema";

type Page = components["schemas"]["PublicPageOut"];
type Block = Record<string, string | number | undefined>;

/** A company's landing page (batch 5a), at /p/<slug>. Every block's text is shown as text,
 * never as HTML; links and images are https addresses checked by Core when the page was saved. */
export default function LandingPage() {
  const { slug } = useParams<{ slug: string }>();
  const [page, setPage] = useState<Page | null | "missing">(null);

  useEffect(() => {
    fetch(`/api/v1/pages/${encodeURIComponent(slug)}`)
      .then(async (r) => setPage(r.ok ? ((await r.json()) as Page) : "missing"))
      .catch(() => setPage("missing"));
    fetch(`/api/v1/pages/${encodeURIComponent(slug)}/visit`, { method: "POST" }).catch(() => {});
  }, [slug]);

  useEffect(() => {
    if (!page || page === "missing") return;
    document.title = page.seo_title || page.title;
    let meta = document.querySelector<HTMLMetaElement>('meta[name="description"]');
    if (page.seo_description) {
      if (!meta) {
        meta = document.createElement("meta");
        meta.name = "description";
        document.head.appendChild(meta);
      }
      meta.content = page.seo_description;
    }
  }, [page]);

  if (page === null) return <main className="grid min-h-dvh place-items-center text-muted-foreground">Loading…</main>;
  if (page === "missing") return <main className="grid min-h-dvh place-items-center p-6 text-muted-foreground">This page doesn&apos;t exist.</main>;
  const accent = page.company.primary_color ?? undefined;
  return (
    <main className="min-h-dvh bg-background">
      <header className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-5">
        {page.company.logo_url && (
          // eslint-disable-next-line @next/next/no-img-element -- the company's own logo, any https address
          <img src={page.company.logo_url} alt="" className="h-9 w-auto max-w-32 object-contain" />
        )}
        <span className="text-sm text-muted-foreground">{page.company.name}</span>
      </header>
      <article className="mx-auto max-w-3xl space-y-6 px-4 pb-16">
        {page.blocks.map((b, i) => (
          <PageBlock key={i} b={b as Block} accent={accent} slug={page.slug} />
        ))}
      </article>
    </main>
  );
}

function PageBlock({ b, accent, slug }: { b: Block; accent?: string; slug: string }) {
  const text = (k: string) => String(b[k] ?? "");
  switch (b.type) {
    case "heading":
      return b.level === 2 ? <h2 className="text-2xl font-semibold">{text("text")}</h2> : <h1 className="text-4xl font-bold tracking-tight">{text("text")}</h1>;
    case "text":
      return <p className="whitespace-pre-line text-lg leading-relaxed text-muted-foreground">{text("text")}</p>;
    case "image":
      // eslint-disable-next-line @next/next/no-img-element -- any https address the company chose
      return <img src={text("url")} alt={text("alt")} className="w-full rounded-xl object-cover" loading="lazy" />;
    case "video":
      return (
        <div className="aspect-video overflow-hidden rounded-xl bg-muted">
          <iframe
            src={text("embed_url")}
            title="Video"
            className="h-full w-full"
            allow="encrypted-media; picture-in-picture; fullscreen"
            referrerPolicy="strict-origin-when-cross-origin"
            sandbox="allow-scripts allow-same-origin allow-presentation"
          />
        </div>
      );
    case "button":
      return (
        <a
          href={text("url")}
          rel="noopener noreferrer"
          className="inline-block rounded-lg bg-primary px-5 py-3 font-medium text-primary-foreground"
          style={accent ? { background: accent } : undefined}
        >
          {text("label")}
        </a>
      );
    case "form":
      return <FormBlock id={text("form_id")} slug={slug} />;
    default:
      return null;
  }
}

function FormBlock({ id, slug }: { id: string; slug: string }) {
  const page = useFormPage(id);
  if (!page || page === "missing") return null;
  return (
    <section className="rounded-2xl border p-6 shadow-sm">
      <HostedForm id={id} page={page} extra={{ landing_page: `/p/${slug}` }} showTitle={false} />
    </section>
  );
}
