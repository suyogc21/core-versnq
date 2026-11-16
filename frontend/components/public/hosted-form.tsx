"use client";

import { useEffect, useState } from "react";

import type { components } from "@/lib/api/schema";

export type FormPage = components["schemas"]["FormPageOut"];
type PageField = FormPage["fields"][number];
const PASS_ON = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid", "msclkid"];

/** Loads a hosted form's questions (real forms, Nov 16). */
export function useFormPage(id: string) {
  const [page, setPage] = useState<FormPage | null | "missing">(null);
  useEffect(() => {
    fetch(`/api/v1/forms/${encodeURIComponent(id)}`)
      .then(async (r) => setPage(r.ok ? ((await r.json()) as FormPage) : "missing"))
      .catch(() => setPage("missing"));
  }, [id]);
  return page;
}

/** A hosted form's questions, the spam trap and sending it. `extra` is sent along with the
 * answers (a landing page adds landing_page=/p/<slug>). */
export function HostedForm({ id, page, extra, showTitle = true }: { id: string; page: FormPage; extra?: Record<string, string>; showTitle?: boolean }) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  async function send(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const data: Record<string, string | string[]> = {};
    for (const [k, v] of form.entries()) {
      const value = String(v);
      const prev = data[k];
      data[k] = prev === undefined ? value : [...(Array.isArray(prev) ? prev : [prev]), value];
    }
    const params = new URLSearchParams(window.location.search);
    for (const k of PASS_ON) if (params.get(k)) data[k] = params.get(k) as string;
    data.page_url = document.referrer && window.self !== window.top ? document.referrer : window.location.href;
    Object.assign(data, extra ?? {});
    setSending(true);
    setErrors({});
    try {
      const r = await fetch(`/api/v1/forms/${encodeURIComponent(id)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const body = await r.json().catch(() => ({}));
      if (r.ok) {
        if (body.redirect_url) window.top?.location.assign(body.redirect_url);
        else setDone(body.thank_you);
      } else {
        setErrors(body.fields ?? { _form: body.detail ?? "Something went wrong. Please try again." });
      }
    } catch {
      setErrors({ _form: "No connection. Please try again." });
    } finally {
      setSending(false);
    }
  }

  const accent = page.company.primary_color ?? undefined;
  if (page.closed) return <p>This form is closed.</p>;
  if (done)
    return (
      <p className="text-lg" role="status">
        {done}
      </p>
    );
  return (
    <form onSubmit={send} noValidate className="space-y-4">
      {showTitle && <h1 className="text-2xl font-semibold">{page.title}</h1>}
      {!showTitle && page.title && <h2 className="text-xl font-semibold">{page.title}</h2>}
      {page.intro && <p className="whitespace-pre-line text-sm text-muted-foreground">{page.intro}</p>}
      {page.fields.map((f) => (
        <Question key={f.name} f={f} error={errors[f.name]} />
      ))}
      {(page.ask_consent ?? []).map((c) => (
        <label key={c} className="flex items-start gap-2 text-sm">
          <input type="checkbox" name={`consent_${c}`} value="yes" className="mt-1" />
          <span>
            {page.consent_text || "I agree to be contacted"} ({c === "email" ? "email" : "WhatsApp"})
          </span>
        </label>
      ))}
      <input name="_gotcha" tabIndex={-1} autoComplete="off" aria-hidden className="hidden" />
      {errors._form && (
        <p className="text-sm text-destructive" role="alert">
          {errors._form}
        </p>
      )}
      <button
        type="submit"
        disabled={sending}
        className="w-full rounded-lg bg-primary px-4 py-2.5 font-medium text-primary-foreground disabled:opacity-60"
        style={accent ? { background: accent } : undefined}
      >
        {sending ? "Sending…" : page.button}
      </button>
    </form>
  );
}

function Question({ f, error }: { f: PageField; error?: string }) {
  const id = `q-${f.name}`;
  const base = "w-full rounded-lg border bg-background px-3 py-2 text-sm aria-invalid:border-destructive";
  const label = (
    <label htmlFor={id} className="text-sm font-medium">
      {f.label}
      {f.required && <span className="text-destructive"> *</span>}
    </label>
  );
  let input: React.ReactNode;
  if (f.input === "textarea") input = <textarea id={id} name={f.name} rows={3} className={base} aria-invalid={!!error} required={f.required} />;
  else if (f.input === "select")
    input = (
      <select id={id} name={f.name} className={base} aria-invalid={!!error} required={f.required} defaultValue="">
        <option value="">Choose…</option>
        {(f.options ?? []).map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    );
  else if (f.input === "multi_select")
    return (
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">
          {f.label}
          {f.required && <span className="text-destructive"> *</span>}
        </legend>
        {(f.options ?? []).map((o) => (
          <label key={o} className="flex items-center gap-2 text-sm">
            <input type="checkbox" name={f.name} value={o} /> {o}
          </label>
        ))}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </fieldset>
    );
  else input = <input id={id} name={f.name} type={f.input} className={base} aria-invalid={!!error} required={f.required} />;
  return (
    <div className="space-y-1">
      {label}
      {input}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
