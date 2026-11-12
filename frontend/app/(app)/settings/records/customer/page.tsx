"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { FieldSettings } from "@/components/crm/field-settings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type Requirement, formatBytes, useCustomerSettings, useRequirements, useStorage } from "@/lib/customers";
import { useProducts } from "@/lib/deals";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Tab = "checklist" | "fields" | "settings";

function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      for (const k of ["requirements", "customer-settings", "checklist", "customers"]) qc.invalidateQueries({ queryKey: [k] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

export default function CustomerSetupPage() {
  const label = useLabels();
  const [tab, setTab] = useState<Tab>("checklist");
  const tabs: [Tab, string][] = [
    ["checklist", "Document checklist"],
    ["fields", "Custom fields"],
    ["settings", "Numbers and storage"],
  ];
  return (
    <>
      <PageHeader back={{ href: "/settings/records", label: "Records and fields" }} title={label("customer", true)} />
      <div className="mx-auto w-full max-w-3xl p-4 sm:p-8">
        <p className="mb-4 text-muted-foreground">
          What you collect once someone becomes {label("customer").toLowerCase()}: the documents your team gathers and uploads, and extra details.
        </p>
        <div className="mb-6 flex gap-4 overflow-x-auto border-b text-sm">
          {tabs.map(([key, name]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={cn("-mb-px border-b-2 border-transparent pb-2 whitespace-nowrap text-muted-foreground", tab === key && "border-primary font-medium text-foreground")}
            >
              {name}
            </button>
          ))}
        </div>
        {tab === "checklist" && <Checklist />}
        {tab === "fields" && <FieldSettings entity="customer" />}
        {tab === "settings" && <NumberSettings />}
      </div>
    </>
  );
}

function Checklist() {
  const reqs = useRequirements();
  const save = useSave();
  const [name, setName] = useState("");
  const list = reqs.data ?? [];
  const order = (i: number, d: -1 | 1) => {
    const ids = list.map((r) => r.id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    save(async () => unwrap(await api.PUT("/api/v1/document-requirements/order", { body: { ids } })));
  };
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Every new customer gets this list. An item can apply to everyone, or only when they bought certain products. Required items count towards
        “3 of 5 received”.
      </p>
      <ul className="divide-y surface">
        {list.length === 0 && <li className="p-3 text-sm text-muted-foreground">No documents on the checklist yet.</li>}
        {list.map((r, i) => (
          <RequirementRow key={`${r.id}-${r.name}`} req={r} first={i === 0} last={i === list.length - 1} onMove={(d) => order(i, d)} />
        ))}
      </ul>
      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await save(async () => unwrap(await api.POST("/api/v1/document-requirements", { body: { name, is_required: true, allow_office: false } })), "Added")) setName("");
        }}
      >
        <Input aria-label="New document" placeholder="e.g. Aadhaar card, Passport, 10th marksheet" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" disabled={!name.trim()}>
          <Plus /> Add
        </Button>
      </form>
    </div>
  );
}

function RequirementRow({ req, first, last, onMove }: { req: Requirement; first: boolean; last: boolean; onMove: (d: -1 | 1) => void }) {
  const save = useSave();
  const products = useProducts({ active: true });
  const [name, setName] = useState(req.name);
  const [hint, setHint] = useState(req.hint ?? "");
  const [open, setOpen] = useState(false);
  const patch = (body: Record<string, unknown>, ok = "Saved") =>
    save(async () => unwrap(await api.PATCH("/api/v1/document-requirements/{req_id}", { params: { path: { req_id: req.id } }, body })), ok);
  const chosen = new Set(req.product_ids);
  const productNames = (products.data ?? []).filter((p) => chosen.has(p.id)).map((p) => p.name);
  return (
    <li className="space-y-2 px-3 py-2.5 text-sm">
      <div className="flex items-center gap-2">
        <div className="flex flex-col">
          <button aria-label={`Move ${req.name} up`} disabled={first} className="text-muted-foreground disabled:opacity-30" onClick={() => onMove(-1)}>
            <ArrowUp className="size-3" />
          </button>
          <button aria-label={`Move ${req.name} down`} disabled={last} className="text-muted-foreground disabled:opacity-30" onClick={() => onMove(1)}>
            <ArrowDown className="size-3" />
          </button>
        </div>
        <Switch aria-label={`${req.name} on`} checked={req.is_active} onCheckedChange={(on) => patch({ is_active: on })} />
        <button className={cn("min-w-0 flex-1 truncate text-left font-medium", !req.is_active && "text-muted-foreground line-through")} onClick={() => setOpen(!open)}>
          {req.name}
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {req.is_required ? "required" : "optional"}
            {req.allow_office ? " · Word/Excel ok" : ""}
            {productNames.length ? ` · only for ${productNames.join(", ")}` : " · everyone"}
          </span>
        </button>
        <button
          aria-label={`Delete ${req.name}`}
          className="p-1 text-muted-foreground hover:text-destructive"
          onClick={() =>
            window.confirm(`Remove "${req.name}" from the checklist? Customers keep what they already sent (under "Other documents").`) &&
            save(async () => unwrap(await api.DELETE("/api/v1/document-requirements/{req_id}", { params: { path: { req_id: req.id } } })), "Removed")
          }
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
      {open && (
        <div className="space-y-3 rounded-lg border p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor={`n-${req.id}`}>Name</Label>
              <Input id={`n-${req.id}`} value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== req.name && patch({ name: name.trim() })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`h-${req.id}`}>Hint for the customer</Label>
              <Input
                id={`h-${req.id}`}
                placeholder="e.g. Front and back"
                value={hint}
                onChange={(e) => setHint(e.target.value)}
                onBlur={() => hint !== (req.hint ?? "") && patch({ hint: hint.trim() || null })}
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <label className="flex items-center gap-2 text-xs">
              <Switch checked={req.is_required} onCheckedChange={(on) => patch({ is_required: on })} /> Required
            </label>
            <label className="flex items-center gap-2 text-xs">
              <Switch checked={req.allow_office} onCheckedChange={(on) => patch({ allow_office: on })} /> Accept Word and Excel files
            </label>
          </div>
          <div className="space-y-1.5">
            <div className="text-xs font-medium">Only for customers who bought</div>
            {(products.data ?? []).length === 0 ? (
              <p className="text-xs text-muted-foreground">No products yet: this item applies to everyone.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {(products.data ?? []).map((p) => {
                  const on = chosen.has(p.id);
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => patch({ product_ids: on ? req.product_ids.filter((x) => x !== p.id) : [...req.product_ids, p.id] })}
                      className={cn("rounded-full border px-2 py-0.5 text-xs", on && "border-primary bg-primary/10")}
                    >
                      {p.name}
                    </button>
                  );
                })}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground">None chosen = everyone.</p>
          </div>
        </div>
      )}
    </li>
  );
}

function NumberSettings() {
  const settings = useCustomerSettings();
  const storage = useStorage();
  const save = useSave();
  const [v, setV] = useState<{ customer_prefix: string; document_reminder_days: string } | null>(null);
  const s = settings.data;
  if (!s) return null;
  const cur = v ?? { customer_prefix: s.customer_prefix, document_reminder_days: String(s.document_reminder_days) };
  const used = storage.data?.used_bytes ?? 0;
  const quota = storage.data?.quota_bytes ?? 1;
  const pct = Math.min(100, (used / quota) * 100);
  return (
    <div className="space-y-6">
      <form
        className="surface space-y-4 p-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await save(
            async () =>
              unwrap(
                await api.PUT("/api/v1/customer-settings", {
                  body: { customer_prefix: cur.customer_prefix, document_reminder_days: Number(cur.document_reminder_days) },
                }),
              ),
            "Saved",
          );
          if (ok) setV(null);
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="c-prefix">Number starts with</Label>
            <Input id="c-prefix" value={cur.customer_prefix} onChange={(e) => setV({ ...cur, customer_prefix: e.target.value })} />
            <p className="text-[11px] text-muted-foreground">e.g. {cur.customer_prefix || "C-"}0042</p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="c-remind">Remind owner after (days)</Label>
            <Input id="c-remind" type="number" min={1} max={60} value={cur.document_reminder_days} onChange={(e) => setV({ ...cur, document_reminder_days: e.target.value })} />
            <p className="text-[11px] text-muted-foreground">A task when required documents are still missing.</p>
          </div>
        </div>
        <Button size="sm" type="submit" disabled={!v}>
          Save
        </Button>
      </form>
      {storage.data && (
        <section className="surface space-y-2 p-4">
          <div className="flex items-baseline justify-between">
            <h3 className="font-medium">File storage</h3>
            <span className="text-sm tabular-nums">
              {formatBytes(used)} of {formatBytes(quota)} used
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className={cn("h-full rounded-full", pct >= 80 ? "bg-amber-500" : "bg-emerald-500")} style={{ width: `${Math.max(pct, 1)}%` }} />
          </div>
          <p className="text-xs text-muted-foreground">
            {pct >= 80 ? "You are close to your limit. Contact Versnq to add more storage." : "Photos are shrunk before upload, so they take little space."}
          </p>
        </section>
      )}
    </div>
  );
}
