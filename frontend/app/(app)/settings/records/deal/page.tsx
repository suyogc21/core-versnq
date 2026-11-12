"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { MoneyInput } from "@/components/crm/deals";
import { FieldSettings } from "@/components/crm/field-settings";
import { FieldAccessSettings, LayoutSettings } from "@/components/crm/layout-settings";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type Pipeline, type PipelineStage, type Product, formatMoney, useDealFields, useLostReasons, usePipelines, useProducts } from "@/lib/deals";
import { useLabels, useWorkspaceSettings } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Tab = "pipelines" | "reasons" | "products" | "fields" | "layout" | "access";
const BUILTIN_REQUIRABLE: [string, string][] = [
  ["amount", "Value"],
  ["expected_close_on", "Expected close"],
  ["owner", "Owner"],
  ["products", "Products"],
];

function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      for (const k of ["pipelines", "lost-reasons", "products", "deals", "fields"]) qc.invalidateQueries({ queryKey: [k] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

export default function DealSetupPage() {
  const label = useLabels();
  const [tab, setTab] = useState<Tab>("pipelines");
  const tabs: [Tab, string][] = [
    ["pipelines", label("pipeline", true)],
    ["reasons", "Lost reasons"],
    ["products", "Products"],
    ["fields", "Custom fields"],
    ["layout", "Page layout"],
    ["access", "Field access"],
  ];
  return (
    <>
      <PageHeader back={{ href: "/settings/records", label: "Records and fields" }} title={label("deal", true)} />
      <div className="mx-auto w-full max-w-3xl p-4 sm:p-8">
        <p className="mb-4 text-muted-foreground">
          How your team sells: {label("pipeline", true).toLowerCase()} and their stages, why deals are lost, and what you sell.
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
        {tab === "pipelines" && <Pipelines />}
        {tab === "reasons" && <Reasons />}
        {tab === "products" && <Products />}
        {tab === "fields" && <FieldSettings entity="deal" />}
        {tab === "layout" && <LayoutSettings entity="deal" />}
        {tab === "access" && <FieldAccessSettings entity="deal" />}
      </div>
    </>
  );
}

// ---------- pipelines and stages ----------
function Pipelines() {
  const label = useLabels();
  const pipelines = usePipelines();
  const save = useSave();
  const settings = useWorkspaceSettings();
  const [pid, setPid] = useState("");
  const [adding, setAdding] = useState(false);
  const list = pipelines.data ?? [];
  const p = list.find((x) => x.id === pid) ?? list[0];
  if (pipelines.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect aria-label={label("pipeline")} className="h-8 w-auto" value={p?.id ?? ""} onChange={(e) => setPid(e.target.value)}>
          {list.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name} ({x.currency}){x.is_active ? "" : " — off"}
            </option>
          ))}
        </NativeSelect>
        <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
          <Plus /> New {label("pipeline").toLowerCase()}
        </Button>
      </div>
      {p && <PipelineEditor key={p.id} p={p} />}
      {adding && (
        <NewPipeline
          currency={settings.data?.default_currency ?? "USD"}
          onClose={() => setAdding(false)}
          onSave={async (body) => {
            let id = "";
            const ok = await save(async () => {
              id = unwrap(await api.POST("/api/v1/pipelines", { body: { ...body, stages: [] } })).id;
            }, "Created");
            if (ok) {
              setPid(id);
              setAdding(false);
            }
          }}
        />
      )}
    </div>
  );
}

function NewPipeline({ currency, onClose, onSave }: { currency: string; onClose: () => void; onSave: (b: { name: string; currency: string }) => void }) {
  const [name, setName] = useState("");
  const [cur, setCur] = useState(currency);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>New pipeline</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            onSave({ name: name.trim(), currency: cur.trim().toUpperCase() });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="np-name">Name</Label>
            <Input id="np-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="np-cur">Currency</Label>
            <Input id="np-cur" value={cur} onChange={(e) => setCur(e.target.value)} maxLength={3} className="w-24 uppercase" />
            <p className="text-xs text-muted-foreground">Every deal in a pipeline uses its currency. It starts with New, Won and Lost stages.</p>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || cur.trim().length !== 3}>
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PipelineEditor({ p }: { p: Pipeline }) {
  const save = useSave();
  const [name, setName] = useState(p.name);
  const [stageName, setStageName] = useState("");
  const [requires, setRequires] = useState<PipelineStage | null>(null);
  const [removing, setRemoving] = useState<PipelineStage | null>(null);
  const stages = p.stages ?? [];
  const patchPipeline = (body: Record<string, unknown>, ok?: string) =>
    save(async () => unwrap(await api.PATCH("/api/v1/pipelines/{pipeline_id}", { params: { path: { pipeline_id: p.id } }, body })), ok);
  const patchStage = (s: PipelineStage, body: Record<string, unknown>) =>
    save(async () => unwrap(await api.PATCH("/api/v1/pipeline-stages/{stage_id}", { params: { path: { stage_id: s.id } }, body })));
  function order(i: number, dir: -1 | 1) {
    const ids = stages.map((s) => s.id);
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    save(async () => unwrap(await api.PUT("/api/v1/pipelines/{pipeline_id}/stages/order", { params: { path: { pipeline_id: p.id } }, body: { ids } })));
  }
  async function remove(s: PipelineStage, moveTo?: string) {
    const ok = await save(
      async () => unwrap(await api.DELETE("/api/v1/pipeline-stages/{stage_id}", { params: { path: { stage_id: s.id }, query: { move_to: moveTo ?? null } } })),
      "Stage removed",
    );
    if (ok) setRemoving(null);
  }
  async function deletePipeline() {
    if (!confirm(`Delete ${p.name}? Only a pipeline without deals can be deleted.`)) return;
    await save(async () => unwrap(await api.DELETE("/api/v1/pipelines/{pipeline_id}", { params: { path: { pipeline_id: p.id } } })), "Deleted");
  }

  return (
    <div className="space-y-4">
      <div className="surface flex flex-wrap items-end gap-3 p-4">
        <div className="space-y-1">
          <Label htmlFor="p-name">Name</Label>
          <Input id="p-name" className="h-8 w-56" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== p.name && patchPipeline({ name: name.trim() }, "Saved")} />
        </div>
        <div className="text-sm">
          <div className="text-xs text-muted-foreground">Currency</div>
          <div className="py-1.5">{p.currency}</div>
        </div>
        <label className="flex items-center gap-2 py-1.5 text-sm">
          <Switch checked={p.is_active} onCheckedChange={(v) => patchPipeline({ is_active: v })} aria-label="Switched on" />
          Switched on
        </label>
        <span className="text-xs text-muted-foreground">{p.deal_count} deals</span>
        {p.deal_count === 0 && (
          <Button size="sm" variant="ghost" className="ml-auto text-muted-foreground hover:text-destructive" onClick={deletePipeline}>
            Delete
          </Button>
        )}
      </div>
      <div className="divide-y surface">
        {stages.map((s, i) => (
          <StageRow key={s.id} s={s} first={i === 0} last={i === stages.length - 1} onMove={(d) => order(i, d)} onPatch={(b) => patchStage(s, b)} onRequires={() => setRequires(s)} onRemove={() => setRemoving(s)} />
        ))}
      </div>
      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await save(
            async () => unwrap(await api.POST("/api/v1/pipelines/{pipeline_id}/stages", { params: { path: { pipeline_id: p.id } }, body: { name: stageName.trim(), kind: "open", probability: 50, required_fields: [] } })),
            "Stage added",
          );
          if (ok) setStageName("");
        }}
      >
        <Input aria-label="New stage" placeholder="New open stage…" className="h-8" value={stageName} onChange={(e) => setStageName(e.target.value)} maxLength={80} />
        <Button size="sm" type="submit" disabled={!stageName.trim()}>
          Add stage
        </Button>
      </form>
      {requires && <RequiresDialog stage={requires} onClose={() => setRequires(null)} onSave={async (keys) => (await patchStage(requires, { required_fields: keys })) && setRequires(null)} />}
      {removing && <RemoveStage stage={removing} stages={stages} onClose={() => setRemoving(null)} onRemove={(to) => remove(removing, to)} />}
    </div>
  );
}

function StageRow({
  s,
  first,
  last,
  onMove,
  onPatch,
  onRequires,
  onRemove,
}: {
  s: PipelineStage;
  first: boolean;
  last: boolean;
  onMove: (d: -1 | 1) => void;
  onPatch: (b: Record<string, unknown>) => void;
  onRequires: () => void;
  onRemove: () => void;
}) {
  const [name, setName] = useState(s.name);
  const [prob, setProb] = useState(String(s.probability));
  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
      <div className="flex flex-col">
        <button aria-label={`Move ${s.name} up`} disabled={first} className="text-muted-foreground disabled:opacity-30" onClick={() => onMove(-1)}>
          <ArrowUp className="size-3" />
        </button>
        <button aria-label={`Move ${s.name} down`} disabled={last} className="text-muted-foreground disabled:opacity-30" onClick={() => onMove(1)}>
          <ArrowDown className="size-3" />
        </button>
      </div>
      <span className="size-2.5 rounded-full" style={{ background: s.colour ?? "#94a3b8" }} />
      <Input aria-label={`${s.name} name`} className="h-7 w-44" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== s.name && onPatch({ name: name.trim() })} />
      <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", s.kind === "won" ? "bg-emerald-500/15 text-emerald-700" : s.kind === "lost" ? "bg-red-500/15 text-red-700" : "bg-muted text-muted-foreground")}>
        {s.kind}
      </span>
      {s.kind === "open" && (
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          Win
          <Input
            aria-label={`${s.name} win %`}
            type="number"
            min={0}
            max={100}
            className="h-7 w-16"
            value={prob}
            onChange={(e) => setProb(e.target.value)}
            onBlur={() => Number(prob) !== s.probability && onPatch({ probability: Math.min(100, Math.max(0, Math.round(Number(prob) || 0))) })}
          />
          %
        </label>
      )}
      <button className="text-xs text-primary hover:underline" onClick={onRequires}>
        {s.required_fields.length ? `Requires ${s.required_fields.length}` : "Required fields"}
      </button>
      <button aria-label={`Remove ${s.name}`} className="ml-auto text-muted-foreground hover:text-destructive" onClick={onRemove}>
        <Trash2 className="size-3.5" />
      </button>
    </div>
  );
}

function RequiresDialog({ stage, onClose, onSave }: { stage: PipelineStage; onClose: () => void; onSave: (keys: string[]) => void }) {
  const fields = useDealFields();
  const [keys, setKeys] = useState<string[]>(stage.required_fields);
  const all: [string, string][] = [...BUILTIN_REQUIRABLE, ...(fields.data ?? []).map((f) => [f.key, f.label] as [string, string])];
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>To move into {stage.name}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">A deal must have these filled in first.</p>
        <div className="space-y-1.5">
          {all.map(([k, l]) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="accent-primary" checked={keys.includes(k)} onChange={(e) => setKeys(e.target.checked ? [...keys, k] : keys.filter((x) => x !== k))} />
              {l}
            </label>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => onSave(keys)}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RemoveStage({ stage, stages, onClose, onRemove }: { stage: PipelineStage; stages: PipelineStage[]; onClose: () => void; onRemove: (to?: string) => void }) {
  const targets = stages.filter((s) => s.id !== stage.id && s.kind === stage.kind);
  const [to, setTo] = useState(targets[0]?.id ?? "");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Remove {stage.name}?</DialogTitle>
        </DialogHeader>
        {targets.length === 0 ? (
          <p className="text-sm text-muted-foreground">A pipeline needs at least one {stage.kind} stage, so this one stays.</p>
        ) : (
          <div className="space-y-1.5">
            <Label htmlFor="move-to">Deals in it move to</Label>
            <NativeSelect id="move-to" value={to} onChange={(e) => setTo(e.target.value)}>
              {targets.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          {targets.length > 0 && (
            <Button variant="destructive" onClick={() => onRemove(to)}>
              Remove stage
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- lost reasons ----------
function Reasons() {
  const reasons = useLostReasons();
  const save = useSave();
  const [name, setName] = useState("");
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Asked every time a deal is lost, so you can see why deals are lost. A reason that has been used can only be switched off.</p>
      <div className="divide-y surface">
        {(reasons.data ?? []).map((r) => (
          <div key={r.id} className="flex items-center gap-3 px-3 py-2 text-sm">
            <span className={cn("flex-1", !r.is_active && "text-muted-foreground line-through")}>{r.name}</span>
            <Switch
              aria-label={`${r.name} switched on`}
              checked={r.is_active}
              onCheckedChange={(v) => save(async () => unwrap(await api.PATCH("/api/v1/lost-reasons/{reason_id}", { params: { path: { reason_id: r.id } }, body: { is_active: v } })))}
            />
            <button
              aria-label={`Delete ${r.name}`}
              className="text-muted-foreground hover:text-destructive"
              onClick={() => save(async () => unwrap(await api.DELETE("/api/v1/lost-reasons/{reason_id}", { params: { path: { reason_id: r.id } } })), "Deleted")}
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        ))}
      </div>
      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await save(async () => unwrap(await api.POST("/api/v1/lost-reasons", { body: { name: name.trim() } })), "Added")) setName("");
        }}
      >
        <Input aria-label="New reason" placeholder="New reason…" className="h-8" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        <Button size="sm" type="submit" disabled={!name.trim()}>
          Add
        </Button>
      </form>
    </div>
  );
}

// ---------- products ----------
function Products() {
  const products = useProducts();
  const save = useSave();
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Your price list. Adding a product to a deal copies its price; changing a price later does not change existing deals.</p>
      <div className="divide-y surface">
        {(products.data ?? []).length === 0 && <p className="px-3 py-4 text-sm text-muted-foreground">No products yet.</p>}
        {(products.data ?? []).map((p) => (
          <div key={p.id} className="flex items-center gap-3 px-3 py-2 text-sm">
            <button className={cn("min-w-0 flex-1 truncate text-left font-medium hover:underline", !p.is_active && "text-muted-foreground line-through")} onClick={() => setEditing(p)}>
              {p.name}
              {p.code && <span className="ml-2 text-xs font-normal text-muted-foreground">{p.code}</span>}
            </button>
            <span className="tabular-nums">{formatMoney(p.price_minor, p.currency)}</span>
            <Switch
              aria-label={`${p.name} switched on`}
              checked={p.is_active}
              onCheckedChange={(v) => save(async () => unwrap(await api.PATCH("/api/v1/products/{product_id}", { params: { path: { product_id: p.id } }, body: { is_active: v } })))}
            />
          </div>
        ))}
      </div>
      <Button size="sm" variant="outline" onClick={() => setEditing("new")}>
        <Plus /> New product
      </Button>
      {editing && <ProductDialog product={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ProductDialog({ product, onClose }: { product: Product | null; onClose: () => void }) {
  const settings = useWorkspaceSettings();
  const save = useSave();
  const [name, setName] = useState(product?.name ?? "");
  const [code, setCode] = useState(product?.code ?? "");
  const [description, setDescription] = useState(product?.description ?? "");
  const [currency, setCurrency] = useState(product?.currency ?? settings.data?.default_currency ?? "USD");
  const [price, setPrice] = useState<number | null>(product?.price_minor ?? 0);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (price === null) return;
    const body = { name: name.trim(), code: code.trim() || null, description: description.trim() || null, price_minor: price, currency };
    const ok = await save(
      async () =>
        product
          ? unwrap(await api.PATCH("/api/v1/products/{product_id}", { params: { path: { product_id: product.id } }, body }))
          : unwrap(await api.POST("/api/v1/products", { body })),
      "Saved",
    );
    if (ok) onClose();
  }
  async function remove() {
    if (!product || !confirm(`Delete ${product.name}? Products already on deals can only be switched off.`)) return;
    if (await save(async () => unwrap(await api.DELETE("/api/v1/products/{product_id}", { params: { path: { product_id: product.id } } })), "Deleted")) onClose();
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{product ? product.name : "New product"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="pr-name">Name</Label>
            <Input id="pr-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="pr-code">Code (optional)</Label>
              <Input id="pr-code" value={code} onChange={(e) => setCode(e.target.value)} maxLength={60} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pr-cur">Currency</Label>
              <Input id="pr-cur" className="uppercase" value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={3} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pr-price">Price</Label>
            {currency.length === 3 && <MoneyInput key={currency} id="pr-price" currency={currency} value={product?.price_minor ?? 0} onChange={setPrice} />}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pr-desc">Description (optional)</Label>
            <Input id="pr-desc" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
          </div>
          <DialogFooter>
            {product && (
              <Button type="button" variant="ghost" className="mr-auto text-muted-foreground hover:text-destructive" onClick={remove}>
                Delete
              </Button>
            )}
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || price === null || currency.length !== 3}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
