"use client";

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { components } from "@/lib/api/schema";
import { useFields } from "@/lib/crm";

export type FormSpec = components["schemas"]["FormSpec"];
type Field = FormSpec["fields"][number];

/** What a form can ask (the lead's own fields; UTM tags and consent are added on their own). */
export const BUILTIN: [string, string][] = [
  ["full_name", "Full name"],
  ["first_name", "First name"],
  ["last_name", "Last name"],
  ["email", "Email"],
  ["phone", "Phone"],
  ["whatsapp", "WhatsApp number"],
  ["org_name", "Company"],
  ["website", "Website"],
  ["linkedin", "LinkedIn profile"],
  ["industry", "Industry"],
  ["city", "City"],
  ["region", "State / region"],
  ["country_code", "Country"],
  ["preferred_language", "Language"],
  ["message", "Message"],
];
const ASKABLE = new Set(["text", "number", "date", "email", "phone", "url", "select", "multi_select"]);

export const STARTER: FormSpec = {
  title: "Get in touch",
  intro: null,
  button: "Send",
  fields: [
    { target: "full_name", label: "Your name", required: true },
    { target: "phone", label: "Phone", required: true },
    { target: "email", label: "Email", required: false },
    { target: "message", label: "How can we help?", required: false },
  ],
  ask_consent: [],
  thank_you: "Thank you. We'll be in touch soon.",
  redirect_url: null,
};

/** Build the questions, consent and thank-you of a form (real forms, Nov 16). */
export function FormBuilder({ spec, onChange }: { spec: FormSpec; onChange: (s: FormSpec) => void }) {
  const custom = (useFields().data ?? []).filter((f) => ASKABLE.has(f.type));
  const choices: [string, string][] = [...BUILTIN, ...custom.map((f) => [`cf.${f.key}`, f.label] as [string, string])];
  const labelOf = (t: string) => choices.find(([k]) => k === t)?.[1] ?? t;
  const used = new Set(spec.fields.map((f) => f.target));
  const setField = (i: number, patch: Partial<Field>) => onChange({ ...spec, fields: spec.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  const move = (i: number, dir: -1 | 1) => {
    const next = [...spec.fields];
    [next[i], next[i + dir]] = [next[i + dir], next[i]];
    onChange({ ...spec, fields: next });
  };
  const free = choices.find(([k]) => !used.has(k));
  const consent = (channel: "email" | "whatsapp", on: boolean) =>
    onChange({ ...spec, ask_consent: on ? [...(spec.ask_consent ?? []), channel] : (spec.ask_consent ?? []).filter((c) => c !== channel) });

  return (
    <div className="space-y-4" data-testid="form-builder">
      <div className="space-y-1.5">
        <Label htmlFor="fb-title">Title</Label>
        <Input id="fb-title" value={spec.title} maxLength={120} onChange={(e) => onChange({ ...spec, title: e.target.value })} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="fb-intro">Short intro (optional)</Label>
        <Textarea id="fb-intro" rows={2} maxLength={1000} value={spec.intro ?? ""} onChange={(e) => onChange({ ...spec, intro: e.target.value || null })} />
      </div>
      <div className="space-y-1.5">
        <Label>Questions</Label>
        {spec.fields.map((f, i) => (
          <div key={f.target} className="flex flex-wrap items-center gap-2 rounded-lg border p-2">
            <NativeSelect
              aria-label={`Question ${i + 1} saves into`}
              value={f.target}
              onChange={(e) => setField(i, { target: e.target.value, label: labelOf(e.target.value) })}
            >
              {choices
                .filter(([k]) => k === f.target || !used.has(k))
                .map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
            </NativeSelect>
            <Input aria-label={`Question ${i + 1} text`} className="h-8 min-w-40 flex-1" value={f.label} maxLength={120} onChange={(e) => setField(i, { label: e.target.value })} />
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={f.required ?? false} onChange={(e) => setField(i, { required: e.target.checked })} /> Required
            </label>
            <Button type="button" size="icon-sm" variant="ghost" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>
              <ArrowUp />
            </Button>
            <Button type="button" size="icon-sm" variant="ghost" aria-label="Move down" disabled={i === spec.fields.length - 1} onClick={() => move(i, 1)}>
              <ArrowDown />
            </Button>
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label={`Remove ${f.label}`}
              disabled={spec.fields.length === 1}
              onClick={() => onChange({ ...spec, fields: spec.fields.filter((_, j) => j !== i) })}
            >
              <Trash2 />
            </Button>
          </div>
        ))}
        {free && spec.fields.length < 30 && (
          <Button type="button" size="sm" variant="outline" onClick={() => onChange({ ...spec, fields: [...spec.fields, { target: free[0], label: free[1], required: false }] })}>
            <Plus /> Add a question
          </Button>
        )}
        <p className="text-xs text-muted-foreground">Ask for an email, phone or WhatsApp number so the lead can be reached. Dropdown answers come from the field&apos;s options.</p>
      </div>
      <div className="space-y-1.5">
        <Label>Ask for permission to contact</Label>
        <div className="flex gap-4 text-sm">
          {(["email", "whatsapp"] as const).map((c) => (
            <label key={c} className="flex items-center gap-1.5">
              <input type="checkbox" checked={(spec.ask_consent ?? []).includes(c)} onChange={(e) => consent(c, e.target.checked)} />
              {c === "email" ? "Email" : "WhatsApp"}
            </label>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">Each box shows the consent wording above; ticked boxes are saved as opt-ins with proof.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="fb-button">Button text</Label>
          <Input id="fb-button" value={spec.button ?? "Send"} maxLength={40} onChange={(e) => onChange({ ...spec, button: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="fb-redirect">After sending, go to (optional)</Label>
          <Input id="fb-redirect" placeholder="https://your-site.com/thanks" value={spec.redirect_url ?? ""} onChange={(e) => onChange({ ...spec, redirect_url: e.target.value || null })} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="fb-thanks">Thank-you message</Label>
        <Input id="fb-thanks" value={spec.thank_you ?? ""} maxLength={500} onChange={(e) => onChange({ ...spec, thank_you: e.target.value })} />
      </div>
    </div>
  );
}
