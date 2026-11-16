"use client";

import { useParams } from "next/navigation";

import { HostedForm, useFormPage } from "@/components/public/hosted-form";

/** A company's hosted form (real forms, Nov 16): shared as a link or embedded on a website. */
export default function HostedFormPage() {
  const { id } = useParams<{ id: string }>();
  const page = useFormPage(id);

  if (page === null) return <Shell>Loading…</Shell>;
  if (page === "missing") return <Shell>This form doesn&apos;t exist.</Shell>;
  return (
    <main className="min-h-dvh bg-muted/40 px-4 py-8">
      <div className="mx-auto w-full max-w-lg rounded-2xl border bg-background p-6 shadow-sm">
        <header className="mb-5 flex items-center gap-3">
          {page.company.logo_url && (
            // eslint-disable-next-line @next/next/no-img-element -- the company's own logo, any https address
            <img src={page.company.logo_url} alt="" className="h-9 w-auto max-w-32 object-contain" />
          )}
          <span className="text-sm text-muted-foreground">{page.company.name}</span>
        </header>
        <HostedForm id={id} page={page} />
      </div>
    </main>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="grid min-h-dvh place-items-center p-6 text-muted-foreground">{children}</main>;
}
