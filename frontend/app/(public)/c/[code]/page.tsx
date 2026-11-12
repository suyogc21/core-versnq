"use client";

import { CheckCircle2, FileText, Upload } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { CustomFieldInput } from "@/components/crm/bits";
import { Button } from "@/components/ui/button";
import type { FieldDef } from "@/lib/crm";
import { DOC_STATUS, type PublicLink, publicLink } from "@/lib/customers";
import { applyAccent } from "@/lib/theme";
import { cn } from "@/lib/utils";

/** The customer's own page: no login, opened from the link the company sent them. */
export default function CustomerLinkPage() {
  const { code } = useParams<{ code: string }>();
  const [page, setPage] = useState<PublicLink | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    publicLink
      .get(code)
      .then((p) => {
        setPage(p);
        setValues(Object.fromEntries(p.fields.map((f) => [f.key, f.value ?? null])));
      })
      .catch((e: Error) => setError(e.message));
  }, [code]);

  // The company's colour, exactly as in its own workspace (readable text colour included).
  useEffect(() => {
    if (page) applyAccent(page.colour);
  }, [page]);

  if (error || done) {
    return (
      <Shell company={page?.company}>
        <div className="surface space-y-2 p-6 text-center">
          {done ? <CheckCircle2 className="mx-auto size-10 text-emerald-600" /> : null}
          <h1 className="text-xl font-semibold tracking-tight">{done ? "All done, thank you!" : "This link isn't working"}</h1>
          <p className="text-sm text-muted-foreground">
            {done ? `${page?.company ?? "The team"} has your details and documents. They will contact you if anything else is needed.` : error}
          </p>
        </div>
      </Shell>
    );
  }
  if (!page) {
    return (
      <Shell>
        <p className="text-center text-muted-foreground">Loading…</p>
      </Shell>
    );
  }

  const missing = page.documents.filter((d) => d.is_required && (d.status === "pending" || d.status === "rejected"));
  return (
    <Shell company={page.company}>
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">Hi {page.customer_name},</h1>
        <p className="text-sm text-muted-foreground">
          {page.company} needs a few things from you. Upload clear photos or PDFs; you can come back to this page until{" "}
          {new Date(page.expires_at).toLocaleDateString(undefined, { day: "numeric", month: "long" })}.
        </p>
      </div>

      {page.fields.length > 0 && (
        <section className="surface space-y-4 p-4">
          <h2 className="text-[15px] font-semibold">Your details</h2>
          {page.fields.map((f) => (
            <CustomFieldInput
              key={f.key}
              field={{ ...f, id: f.key, options: f.options, depends_on: null, group_name: null } as unknown as FieldDef}
              value={values[f.key]}
              onChange={(v) => setValues({ ...values, [f.key]: v })}
            />
          ))}
        </section>
      )}

      {page.documents.length > 0 && (
        <section className="surface space-y-3 p-4">
          <h2 className="text-[15px] font-semibold">Documents</h2>
          <ul className="space-y-2">
            {page.documents.map((d) => (
              <DocRow
                key={d.id}
                doc={d}
                busy={busy === d.id}
                onFiles={async (files) => {
                  setBusy(d.id);
                  setProblem(null);
                  try {
                    let next = page;
                    for (const f of files) next = await publicLink.upload(code, d.id, f);
                    setPage(next);
                  } catch (e) {
                    setProblem((e as Error).message);
                  } finally {
                    setBusy(null);
                  }
                }}
              />
            ))}
          </ul>
        </section>
      )}

      {problem && <p className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{problem}</p>}
      <div className="space-y-2">
        <Button
          className="h-11 w-full text-base"
          disabled={busy !== null}
          onClick={async () => {
            setProblem(null);
            try {
              await publicLink.submit(code, values);
              setDone(true);
            } catch (e) {
              setProblem((e as Error).message);
            }
          }}
        >
          Send
        </Button>
        {missing.length > 0 && (
          <p className="text-center text-xs text-muted-foreground">
            Still needed: {missing.map((d) => d.name).join(", ")}. You can send what you have now and the rest later.
          </p>
        )}
      </div>
    </Shell>
  );
}

function Shell({ company, children }: { company?: string; children: React.ReactNode }) {
  return (
    <main className="min-h-dvh bg-background">
      <div className="mx-auto w-full max-w-lg space-y-5 px-4 py-6 sm:py-10">
        {company && (
          <div className="flex items-center gap-2">
            <div className="grid size-8 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">{company.charAt(0).toUpperCase()}</div>
            <span className="font-semibold">{company}</span>
          </div>
        )}
        {children}
        <p className="pt-4 text-center text-[11px] text-muted-foreground">Your files are sent securely and only {company ?? "the company"} can see them.</p>
      </div>
    </main>
  );
}

function DocRow({ doc, busy, onFiles }: { doc: PublicLink["documents"][number]; busy: boolean; onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const status = DOC_STATUS[doc.status] ?? DOC_STATUS.pending;
  const locked = doc.status === "verified";
  return (
    <li className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2">
        <FileText className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 text-sm font-medium">
          {doc.name}
          {doc.is_required && <span className="text-destructive"> *</span>}
        </span>
        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", status.tone)}>{doc.status === "received" ? "Sent" : status.label}</span>
      </div>
      {doc.hint && <p className="mt-1 pl-6 text-xs text-muted-foreground">{doc.hint}</p>}
      {doc.status === "rejected" && doc.reject_reason && <p className="mt-1 pl-6 text-xs text-destructive">Please send again: {doc.reject_reason}</p>}
      {doc.files > 0 && doc.status !== "rejected" && (
        <p className="mt-1 pl-6 text-xs text-muted-foreground">
          {doc.files} file{doc.files > 1 ? "s" : ""} sent
        </p>
      )}
      {!locked && (
        <div className="mt-2 pl-6">
          <input
            ref={input}
            type="file"
            multiple
            className="hidden"
            aria-label={`Upload ${doc.name}`}
            accept={doc.allow_office ? "image/*,application/pdf,.doc,.docx,.xls,.xlsx" : "image/*,application/pdf"}
            onChange={(e) => {
              if (e.target.files?.length) onFiles(Array.from(e.target.files));
              e.target.value = "";
            }}
          />
          <Button size="sm" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
            <Upload /> {busy ? "Sending…" : doc.status === "rejected" ? "Upload a new one" : doc.files > 0 ? "Add another" : "Upload"}
          </Button>
        </div>
      )}
    </li>
  );
}
