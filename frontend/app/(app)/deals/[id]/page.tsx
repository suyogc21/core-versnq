"use client";

import { Check, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { CustomFieldsEditor } from "@/components/crm/bits";
import { MakeCustomerButton } from "@/components/crm/customers";
import { LostDialog, MoneyInput, StatusBadge, moveDeal } from "@/components/crm/deals";
import { AddFieldButton } from "@/components/crm/field-settings";
import { TagEditor } from "@/components/crm/tags";
import { LinksCard } from "@/components/crm/links-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { fieldValue, fromLocalInput, relative, toLocalInput, when } from "@/lib/crm";
import {
  type Deal,
  type DealLine,
  type PipelineStage,
  formatMoney,
  useDeal,
  useDealFields,
  useDealLines,
  useDealTasks,
  useDealTimeline,
  usePipelines,
  useProducts,
  useRefreshDeals,
} from "@/lib/deals";
import { useLeadCustomer } from "@/lib/customers";
import { useUsers } from "@/lib/directory";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";
import { NewInvoiceButton } from "@/components/crm/money";
import { useMoneyOn } from "@/lib/money";

export default function DealPage() {
  const { id } = useParams<{ id: string }>();
  const deal = useDeal(id);
  if (deal.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!deal.data) return <p className="p-6 text-destructive">{deal.error?.message ?? "Not found"}</p>;
  return <DealView key={deal.data.id} deal={deal.data} />;
}

function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="surface space-y-3 p-4">
      <h4 className="flex items-center justify-between text-[13px] font-semibold">
        {title}
        {action}
      </h4>
      {children}
    </section>
  );
}

function DealView({ deal }: { deal: Deal }) {
  const { can } = useAuth();
  const label = useLabels();
  const router = useRouter();
  const refresh = useRefreshDeals();
  const editable = can("deals.edit");
  const [editing, setEditing] = useState(false);

  async function remove() {
    if (!confirm(`Delete ${deal.name} for good? Its products, tasks, links and timeline are removed too.`)) return;
    try {
      unwrap(await api.DELETE("/api/v1/deals/{deal_id}", { params: { path: { deal_id: deal.id } } }));
      refresh();
      toast.success("Deleted");
      router.push("/deals");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="space-y-4 px-4 pt-4 pb-2 md:px-6 md:pt-5">
        <div className="text-xs text-muted-foreground">
          <Link href="/deals" className="hover:underline">
            {label("deal", true)}
          </Link>{" "}
          / {deal.name}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="min-w-0 truncate text-2xl font-bold tracking-tight">{deal.name}</h2>
          <StatusBadge status={deal.status} />
          <span className="text-2xl font-semibold tracking-tight tabular-nums">{formatMoney(deal.amount_minor, deal.currency)}</span>
          <span className="text-xs text-muted-foreground">added {relative(deal.created_at)}</span>
          <TagEditor kind="deal" id={deal.id} tags={deal.tags ?? []} editable={editable} />
          {deal.status === "won" && <WonCustomer leadId={deal.lead_id} dealId={deal.id} />}
          {can("deals.delete") && (
            <Button size="sm" variant="ghost" className="ml-auto text-muted-foreground hover:text-destructive" onClick={remove}>
              Delete
            </Button>
          )}
        </div>
        <Stepper deal={deal} editable={editable} />
        {deal.status === "lost" && (
          <p className="text-xs text-muted-foreground">
            Lost: <span className="font-medium text-foreground">{deal.lost_reason}</span>
            {deal.close_note ? ` — ${deal.close_note}` : ""}
          </p>
        )}
      </div>
      <div className="grid min-h-0 flex-1 items-start gap-4 p-4 md:px-6 lg:grid-cols-[340px_minmax(0,1fr)_320px]">
        <div className="space-y-4">
          <Section
            title="About"
            action={
              editable ? (
                <button className="text-xs font-medium text-muted-foreground hover:text-foreground" onClick={() => setEditing(!editing)}>
                  {editing ? "Cancel" : "Edit"}
                </button>
              ) : undefined
            }
          >
            {editing ? <EditDeal deal={deal} onDone={() => setEditing(false)} /> : <Facts deal={deal} />}
          </Section>
          <Section title="Products">
            <Lines deal={deal} editable={editable} />
          </Section>
        </div>
        <div className="space-y-4">
          {editable && <NoteBox deal={deal} />}
          <div className="surface p-4">
            <Timeline dealId={deal.id} />
          </div>
        </div>
        <div className="space-y-4">
          <Section title={label("lead")}>
            <Link href={`/leads/${deal.lead_id}`} className="block rounded-md border px-2 py-1.5 text-xs font-medium hover:bg-accent">
              {deal.lead_name}
            </Link>
          </Section>
          <Section title="Linked">
            <LinksCard end={{ kind: "deal", id: deal.id, typeId: null }} editable={editable} />
          </Section>
          <Section title="Tasks">
            <Tasks deal={deal} editable={editable} />
          </Section>
        </div>
      </div>
    </div>
  );
}

function Stepper({ deal, editable }: { deal: Deal; editable: boolean }) {
  const router = useRouter();
  const pipelines = usePipelines();
  const refresh = useRefreshDeals();
  const [losing, setLosing] = useState<PipelineStage | null>(null);
  const stages = pipelines.data?.find((p) => p.id === deal.pipeline_id)?.stages ?? [];
  const open = stages.filter((s) => s.kind === "open");
  const here = open.findIndex((s) => s.id === deal.stage_id);
  async function go(s: PipelineStage, lost?: { reason: string; note: string }) {
    const done = await moveDeal(deal, s, lost, () => router.push(`/deals/${deal.id}`));
    if (done) toast.success(`Moved to ${s.name}`);
    refresh();
  }
  function pick(s: PipelineStage) {
    if (s.id === deal.stage_id) return;
    if (s.kind === "lost") setLosing(s);
    else go(s);
  }
  return (
    <div className="flex flex-wrap gap-2">
      <div className="flex min-w-0 flex-1 overflow-x-auto rounded-lg border text-xs [scrollbar-width:none]">
        {open.map((s, i) => (
          <button
            key={s.id}
            type="button"
            disabled={!editable}
            onClick={() => pick(s)}
            title={`Move to ${s.name}`}
            className={cn(
              "min-w-28 flex-1 border-r px-3 py-1.5 whitespace-nowrap text-muted-foreground last:border-r-0 hover:bg-accent",
              deal.status === "open" && here > -1 && i < here && "bg-primary/10 text-foreground",
              s.id === deal.stage_id && "bg-primary font-semibold text-primary-foreground hover:bg-primary",
            )}
          >
            {deal.status === "open" && here > -1 && i < here && <Check className="mr-1 inline size-3" />}
            {s.name}
          </button>
        ))}
      </div>
      {editable &&
        stages
          .filter((s) => s.kind !== "open")
          .map((s) => (
            <Button
              key={s.id}
              size="sm"
              variant={s.id === deal.stage_id ? "default" : "outline"}
              className={cn(s.kind === "won" && s.id === deal.stage_id && "bg-emerald-600 hover:bg-emerald-600", s.kind === "lost" && s.id === deal.stage_id && "bg-red-600 hover:bg-red-600")}
              onClick={() => pick(s)}
            >
              {s.kind === "won" ? "Won" : "Lost"}
              {s.name.toLowerCase() !== s.kind ? ` · ${s.name}` : ""}
            </Button>
          ))}
      {losing && (
        <LostDialog
          deal={deal}
          onClose={() => setLosing(null)}
          onConfirm={(lost) => {
            go(losing, lost);
            setLosing(null);
          }}
        />
      )}
    </div>
  );
}

function Facts({ deal }: { deal: Deal }) {
  const label = useLabels();
  const fields = useDealFields();
  const pipelines = usePipelines();
  const values = deal.custom_fields as Record<string, unknown>;
  const rows: [string, React.ReactNode][] = [
    [label("pipeline"), pipelines.data?.find((p) => p.id === deal.pipeline_id)?.name ?? "—"],
    ["Stage", deal.stage_name],
    ["Value", formatMoney(deal.amount_minor, deal.currency)],
    ["Expected close", deal.expected_close_on ?? "—"],
    ["Owner", deal.owner_name ?? "Unassigned"],
  ];
  for (const f of fields.data ?? []) rows.push([f.label, fieldValue(f, values[f.key])]);
  if (deal.closed_at) rows.push(["Closed", when(deal.closed_at)]);
  rows.push(["Updated", relative(deal.updated_at)]);
  return (
    <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="truncate">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function EditDeal({ deal, onDone }: { deal: Deal; onDone: () => void }) {
  const { me, can } = useAuth();
  const fields = useDealFields();
  const ownScope = me?.role.scope === "own";
  const users = useUsers(!ownScope && can("users.read"));
  const refresh = useRefreshDeals();
  const [name, setName] = useState(deal.name);
  const [amount, setAmount] = useState<number | null>(deal.amount_minor);
  const [close, setClose] = useState(deal.expected_close_on ?? "");
  const [owner, setOwner] = useState(deal.owner_user_id ?? "none");
  const [custom, setCustom] = useState<Record<string, unknown>>(deal.custom_fields as Record<string, unknown>);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (amount === null) return;
    try {
      const body: Record<string, unknown> = { version: deal.version, name, expected_close_on: close || null, custom_fields: custom };
      if (!deal.has_lines) body.amount_minor = amount;
      if (!ownScope) body.owner_user_id = owner === "none" ? null : owner;
      unwrap(await api.PATCH("/api/v1/deals/{deal_id}", { params: { path: { deal_id: deal.id } }, body: body as never }));
      refresh();
      toast.success("Saved");
      onDone();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }

  return (
    <form onSubmit={save} className="space-y-3 text-xs">
      <div className="space-y-1">
        <label htmlFor="d-name" className="text-muted-foreground">
          Name
        </label>
        <Input id="d-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-1">
        <label htmlFor="d-amount" className="text-muted-foreground">
          Value
        </label>
        {deal.has_lines ? (
          <p className="text-muted-foreground">{formatMoney(deal.amount_minor, deal.currency)} — the sum of the products below</p>
        ) : (
          <MoneyInput id="d-amount" currency={deal.currency} value={deal.amount_minor} onChange={setAmount} />
        )}
      </div>
      <div className="space-y-1">
        <label htmlFor="d-close" className="text-muted-foreground">
          Expected close
        </label>
        <Input id="d-close" type="date" className="h-8" value={close} onChange={(e) => setClose(e.target.value)} />
      </div>
      {!ownScope && (
        <div className="space-y-1">
          <label htmlFor="d-owner" className="text-muted-foreground">
            Owner
          </label>
          <NativeSelect id="d-owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="none">Unassigned</option>
            {(users.data ?? [])
              .filter((u) => u.status === "active")
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
          </NativeSelect>
        </div>
      )}
      <CustomFieldsEditor fields={fields.data ?? []} values={custom} onChange={setCustom} />
      {can("crm.configure") && (
        <div>
          <AddFieldButton entity="deal" />
        </div>
      )}
      <Button size="sm" type="submit" disabled={!name.trim() || amount === null}>
        Save
      </Button>
    </form>
  );
}

type Draft = { key: string; product_id: string | null; name: string; quantity: number; unit_price_minor: number | null; discount_minor: number | null };

function Lines({ deal, editable }: { deal: Deal; editable: boolean }) {
  const lines = useDealLines(deal.id);
  const [editing, setEditing] = useState(false);
  const items = lines.data ?? [];
  if (lines.isLoading) return <p className="text-xs text-muted-foreground">Loading…</p>;
  if (editing) return <LinesEditor deal={deal} lines={items} onDone={() => setEditing(false)} />;
  return (
    <div className="space-y-1.5 text-xs">
      {items.length === 0 && <p className="text-muted-foreground">No products. The value is typed in by hand.</p>}
      {items.map((l) => (
        <div key={l.id} className="flex items-baseline gap-2 border-b py-1 last:border-b-0">
          <span className="min-w-0 flex-1 truncate">
            {l.name}
            <span className="text-muted-foreground">
              {" "}
              × {l.quantity}
              {l.discount_minor > 0 && ` − ${formatMoney(l.discount_minor, deal.currency)}`}
            </span>
          </span>
          <span className="tabular-nums">{formatMoney(l.total_minor, deal.currency)}</span>
        </div>
      ))}
      {items.length > 0 && (
        <div className="flex justify-between pt-1 font-semibold">
          <span>Total</span>
          <span className="tabular-nums">{formatMoney(deal.amount_minor, deal.currency)}</span>
        </div>
      )}
      {editable && (
        <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
          {items.length ? "Edit products" : "Add products"}
        </Button>
      )}
    </div>
  );
}

function LinesEditor({ deal, lines, onDone }: { deal: Deal; lines: DealLine[]; onDone: () => void }) {
  const products = useProducts({ active: true, currency: deal.currency });
  const refresh = useRefreshDeals();
  const [rows, setRows] = useState<Draft[]>(() =>
    lines.map((l) => ({ key: l.id, product_id: l.product_id, name: l.name, quantity: l.quantity, unit_price_minor: l.unit_price_minor, discount_minor: l.discount_minor })),
  );
  const set = (i: number, patch: Partial<Draft>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const totalOf = (r: Draft) => (r.unit_price_minor ?? 0) * r.quantity - (r.discount_minor ?? 0);
  const invalid = rows.some((r) => !r.name.trim() || r.unit_price_minor === null || r.discount_minor === null || r.quantity < 1 || totalOf(r) < 0);

  function addProduct(id: string) {
    const p = (products.data ?? []).find((x) => x.id === id);
    if (p) setRows([...rows, { key: crypto.randomUUID(), product_id: p.id, name: p.name, quantity: 1, unit_price_minor: p.price_minor, discount_minor: 0 }]);
  }

  async function save() {
    try {
      unwrap(
        await api.PUT("/api/v1/deals/{deal_id}/products", {
          params: { path: { deal_id: deal.id } },
          body: {
            version: deal.version,
            lines: rows.map((r) => ({ product_id: r.product_id, name: r.name, quantity: r.quantity, unit_price_minor: r.unit_price_minor, discount_minor: r.discount_minor ?? 0 })),
          },
        }),
      );
      refresh();
      toast.success("Products saved");
      onDone();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-2 text-xs">
      {rows.map((r, i) => (
        <div key={r.key} className="space-y-1.5 rounded-md border p-2">
          <div className="flex items-center gap-1.5">
            <Input aria-label="Line name" className="h-7" value={r.name} onChange={(e) => set(i, { name: e.target.value })} />
            <button aria-label={`Remove ${r.name}`} className="text-muted-foreground hover:text-destructive" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
              <Trash2 className="size-3.5" />
            </button>
          </div>
          <div className="grid grid-cols-[56px_1fr] items-center gap-1.5">
            <span className="text-muted-foreground">Qty</span>
            <Input aria-label="Quantity" type="number" min={1} className="h-7 w-20" value={r.quantity} onChange={(e) => set(i, { quantity: Math.max(1, Math.floor(Number(e.target.value) || 1)) })} />
            <span className="text-muted-foreground">Price</span>
            <MoneyInput currency={deal.currency} value={r.unit_price_minor ?? 0} onChange={(v) => set(i, { unit_price_minor: v })} />
            <span className="text-muted-foreground">Discount</span>
            <MoneyInput currency={deal.currency} value={r.discount_minor ?? 0} onChange={(v) => set(i, { discount_minor: v })} />
          </div>
          <div className={cn("text-right tabular-nums", totalOf(r) < 0 && "text-destructive")}>
            {totalOf(r) < 0 ? "Discount is more than the line" : formatMoney(totalOf(r), deal.currency)}
          </div>
        </div>
      ))}
      <div className="flex flex-wrap gap-1.5">
        <NativeSelect aria-label="Add a product" className="h-7 w-auto" value="" onChange={(e) => addProduct(e.target.value)}>
          <option value="">+ Product from catalogue…</option>
          {(products.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} — {formatMoney(p.price_minor, p.currency)}
            </option>
          ))}
        </NativeSelect>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setRows([...rows, { key: crypto.randomUUID(), product_id: null, name: "", quantity: 1, unit_price_minor: 0, discount_minor: 0 }])}
        >
          + Custom line
        </Button>
      </div>
      <div className="flex justify-between border-t pt-1.5 font-semibold">
        <span>Total</span>
        <span className="tabular-nums">{formatMoney(Math.max(0, rows.reduce((s, r) => s + totalOf(r), 0)), deal.currency)}</span>
      </div>
      <div className="flex gap-1.5">
        <Button size="sm" disabled={invalid} onClick={save}>
          Save products
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function NoteBox({ deal }: { deal: Deal }) {
  const refresh = useRefreshDeals();
  const [text, setText] = useState("");
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      unwrap(await api.POST("/api/v1/deals/{deal_id}/notes", { params: { path: { deal_id: deal.id } }, body: { body: text } }));
      setText("");
      refresh();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }
  return (
    <form onSubmit={save} className="surface space-y-2 p-4">
      <Textarea aria-label="Note" placeholder="Write a note…" value={text} onChange={(e) => setText(e.target.value)} />
      <Button size="sm" type="submit" disabled={!text.trim()}>
        Add note
      </Button>
    </form>
  );
}

function Timeline({ dealId }: { dealId: string }) {
  const timeline = useDealTimeline(dealId);
  if (timeline.isLoading) return <p className="text-xs text-muted-foreground">Loading…</p>;
  const items = timeline.data ?? [];
  if (!items.length) return <p className="text-xs text-muted-foreground">Nothing yet.</p>;
  return (
    <ol className="space-y-3">
      {items.map((a) => (
        <li key={a.id} className="text-xs">
          <div className="text-muted-foreground">
            {when(a.occurred_at)}
            {a.actor_name ? ` · ${a.actor_name}` : ""}
            {a.actor_type === "automation" ? ` · Automation: ${(a.data as { automation?: string }).automation ?? ""}` : ""}
          </div>
          <div className="font-medium">{a.summary}</div>
          {a.body && a.body !== a.summary && <div className="mt-1 rounded-md bg-muted px-2 py-1 whitespace-pre-wrap">{a.body}</div>}
        </li>
      ))}
    </ol>
  );
}

function Tasks({ deal, editable }: { deal: Deal; editable: boolean }) {
  const tasks = useDealTasks(deal.id);
  const refresh = useRefreshDeals();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState(() => toLocalInput(new Date(Date.now() + 86400000).toISOString()));
  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      unwrap(await api.POST("/api/v1/tasks", { body: { title, due_at: fromLocalInput(due)!, deal_id: deal.id, priority: "normal" } }));
      setTitle("");
      refresh();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }
  async function complete(id: string) {
    try {
      unwrap(await api.PATCH("/api/v1/tasks/{task_id}", { params: { path: { task_id: id } }, body: { status: "done" } }));
      refresh();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }
  return (
    <div className="space-y-2 text-xs">
      {tasks.isLoading && <p className="text-muted-foreground">Loading…</p>}
      {tasks.data && tasks.data.length === 0 && <p className="text-muted-foreground">No open tasks.</p>}
      {(tasks.data ?? []).map((t) => (
        <label key={t.id} className="flex items-center gap-2 rounded-md border px-2 py-1.5">
          <input type="checkbox" className="accent-primary" disabled={!editable} onChange={() => complete(t.id)} />
          <span className="flex-1">{t.title}</span>
          <span className="text-muted-foreground">{when(t.due_at)}</span>
        </label>
      ))}
      {editable && (
        <form onSubmit={add} className="space-y-1.5">
          <Input aria-label="New task" placeholder="Add a task…" className="h-7" value={title} onChange={(e) => setTitle(e.target.value)} />
          <div className="flex gap-1.5">
            <Input aria-label="Due" type="datetime-local" className="h-7" value={due} onChange={(e) => setDue(e.target.value)} />
            <Button size="sm" type="submit" disabled={!title.trim()}>
              Add
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

/** After a win: one step to make the lead a customer (or a link to it if it already is). */
function WonCustomer({ leadId, dealId }: { leadId: string; dealId: string }) {
  const { can } = useAuth();
  const label = useLabels();
  const customer = useLeadCustomer(leadId, can("customers.read"));
  const moneyOn = useMoneyOn();
  if (customer.isLoading || !can("customers.read")) return null;
  if (customer.data) {
    return (
      <>
        <Link href={`/leads/${leadId}`} className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-700 hover:underline dark:text-emerald-300">
          {label("customer")} {customer.data.number}
        </Link>
        {moneyOn && can("invoices.create") && <NewInvoiceButton customerId={customer.data.id} dealId={dealId} variant="outline" />}
      </>
    );
  }
  return can("customers.create") && can("leads.edit") ? <MakeCustomerButton leadId={leadId} dealId={dealId} /> : null;
}
