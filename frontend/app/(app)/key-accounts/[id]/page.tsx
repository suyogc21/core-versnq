"use client";

import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { HealthDot, TierPill } from "@/components/crm/key-accounts";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  CELL,
  type Cell,
  type Grid,
  type KeyAccountDetail,
  ROLE,
  STANCE,
  useCompetitors,
  useGrid,
  useKeyAccount,
  useKeyAccounts,
  usePeopleMap,
  useRefreshAccounts,
} from "@/lib/accounts";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { relative } from "@/lib/crm";
import { formatMoney, parseMoney } from "@/lib/deals";
import { day } from "@/lib/money";
import { amounts } from "@/lib/reports";
import { cn } from "@/lib/utils";

type Tab = "overview" | "grid" | "people" | "tree";

async function run(work: () => Promise<unknown>, done?: string) {
  try {
    await work();
    if (done) toast.success(done);
    return true;
  } catch (e) {
    toast.error((e as Error).message);
    return false;
  }
}

function Card({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="surface space-y-3 p-4">
      <h4 className="flex items-center justify-between gap-2 text-[13px] font-semibold">
        {title}
        {action}
      </h4>
      {children}
    </section>
  );
}

export default function KeyAccountPage() {
  const { id } = useParams<{ id: string }>();
  const acc = useKeyAccount(id);
  const [tab, setTab] = useState<Tab>("overview");
  const a = acc.data;
  if (acc.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!a) {
    return (
      <>
        <PageHeader back={{ href: "/key-accounts", label: "Key accounts" }} title="Not found" />
        <p className="p-8 text-center text-muted-foreground">This account doesn&apos;t exist or you don&apos;t have access to it.</p>
      </>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <PageHeader back={{ href: "/key-accounts", label: "Key accounts" }} title={a.name} actions={<HealthDot health={a.health} />} />
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3 text-[13px] text-muted-foreground md:px-6">
        <TierPill tier={a.tier} />
        <span>Owner: {a.owner_name ?? "—"}</span>
        {a.parent_id && (
          <span>
            · Part of{" "}
            <Link href={`/key-accounts/${a.parent_id}`} className="text-foreground hover:underline">
              {a.parent_name}
            </Link>
          </span>
        )}
        <Link href={`/leads/${a.org_lead_id}`} className="ml-auto text-xs font-medium text-primary hover:underline">
          Open organisation ↗
        </Link>
      </div>
      <div className="flex gap-1 overflow-x-auto px-4 pt-3 md:px-6" role="tablist">
        {(
          [
            ["overview", "Overview"],
            ["grid", "Opportunity grid"],
            ["people", "People map"],
            ["tree", "Group tree"],
          ] as [Tab, string][]
        ).map(([k, name]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn("rounded-lg px-3 py-1 text-[13px] font-medium whitespace-nowrap text-muted-foreground hover:text-foreground", tab === k && "bg-card text-foreground shadow-card")}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="space-y-4 p-4 md:px-6">
        {tab === "overview" && <Overview a={a} />}
        {tab === "grid" && <GridTab a={a} />}
        {tab === "people" && <People a={a} />}
        {tab === "tree" && <Tree a={a} />}
      </div>
    </div>
  );
}

// ---------- overview ----------
function Overview({ a }: { a: KeyAccountDetail }) {
  const refresh = useRefreshAccounts();
  const patch = (body: Record<string, unknown>, done?: string) =>
    run(async () => {
      unwrap(await api.PATCH("/api/v1/key-accounts/{account_id}", { params: { path: { account_id: a.id } }, body: { version: a.version, no_parent: false, no_target: false, ...body } }));
      refresh();
    }, done);
  const [note, setNote] = useState(a.health_note ?? "");
  const won = a.target_currency ? (a.rollup.won_this_year.find((x) => x.currency === a.target_currency)?.minor ?? 0) : 0;
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            ["Won this year", amounts(a.rollup.won_this_year)],
            ["Open pipeline", `${amounts(a.rollup.pipeline)} (${a.rollup.open_deals})`],
            ["Collected this year", amounts(a.rollup.collected_this_year)],
            ["Overdue", amounts(a.rollup.overdue, "Nothing")],
          ].map(([k, v]) => (
            <div key={k} className="surface p-3" data-tile={k}>
              <div className="text-[11px] text-muted-foreground">{k}</div>
              <div className="text-sm font-semibold tabular-nums">{v}</div>
            </div>
          ))}
        </div>
        {a.tree.length > 1 && (
          <p className="text-xs text-muted-foreground">
            With the companies below it: won {amounts(a.group.won_this_year)} · pipeline {amounts(a.group.pipeline)} · collected {amounts(a.group.collected_this_year)}
          </p>
        )}
        <Goals a={a} />
        <Card title="Next actions">
          {a.actions.length === 0 ? (
            <p className="text-xs text-muted-foreground">No open tasks on this organisation. Add them from its page.</p>
          ) : (
            <ul className="divide-y text-xs">
              {a.actions.map((t) => (
                <li key={t.id} className="flex items-center gap-2 py-1.5">
                  <span className="flex-1">{t.title}</span>
                  <span className="text-muted-foreground">{t.owner_name}</span>
                  <span className="w-24 text-right text-muted-foreground">{relative(t.due_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Units a={a} />
      </div>
      <div className="space-y-4">
        <Card title="Health">
          {a.hints.length > 0 && <ul className="list-inside list-disc text-xs text-amber-700 dark:text-amber-300">{a.hints.map((h) => <li key={h}>{h}</li>)}</ul>}
          <NativeSelect aria-label="Health" value={a.health} disabled={!a.can_edit} onChange={(e) => patch({ health: e.target.value }, "Health updated")}>
            <option value="on_track">On track</option>
            <option value="at_risk">At risk</option>
            <option value="off_track">Off track</option>
          </NativeSelect>
          <Textarea rows={2} placeholder="Why? (what you know that the numbers don't)" value={note} disabled={!a.can_edit} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== (a.health_note ?? "") && patch({ health_note: note })} />
        </Card>
        <Card title="Account">
          <div className="space-y-2 text-xs">
            <Label className="text-xs">Tier</Label>
            <NativeSelect aria-label="Tier" value={a.tier} disabled={!a.can_edit} onChange={(e) => patch({ tier: e.target.value }, "Tier updated")}>
              <option value="strategic">Strategic</option>
              <option value="growth">Growth</option>
              <option value="maintain">Maintain</option>
            </NativeSelect>
            <ParentPicker a={a} onPick={(parent) => patch(parent ? { parent_id: parent } : { no_parent: true }, "Group updated")} />
            <TargetEditor a={a} won={won} onSave={(minor, cur) => patch(minor === null ? { no_target: true } : { target_minor: minor, target_currency: cur }, "Target saved")} />
          </div>
        </Card>
      </div>
    </div>
  );
}

function ParentPicker({ a, onPick }: { a: KeyAccountDetail; onPick: (parent: string | null) => void }) {
  const all = useKeyAccounts({});
  return (
    <div className="space-y-1">
      <Label className="text-xs">Part of (parent company)</Label>
      <NativeSelect aria-label="Parent company" value={a.parent_id ?? ""} disabled={!a.can_edit} onChange={(e) => onPick(e.target.value || null)}>
        <option value="">None (top of its group)</option>
        {(all.data ?? [])
          .filter((x) => x.id !== a.id) /* the server refuses a choice that would loop */
          .map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
      </NativeSelect>
    </div>
  );
}

function TargetEditor({ a, won, onSave }: { a: KeyAccountDetail; won: number; onSave: (minor: number | null, cur: string) => void }) {
  const cur = a.target_currency ?? "INR";
  const [text, setText] = useState(a.target_minor ? String(a.target_minor / 100) : "");
  const pct = a.target_minor ? Math.min(100, Math.round((won * 100) / a.target_minor)) : null;
  return (
    <div className="space-y-1">
      <Label className="text-xs">Yearly target ({cur})</Label>
      <Input
        aria-label="Yearly target"
        inputMode="decimal"
        value={text}
        disabled={!a.can_edit}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          const minor = text.trim() ? parseMoney(text, cur) : null;
          if (text.trim() && minor === null) return toast.error("Enter an amount like 5000000");
          if (minor !== a.target_minor) onSave(minor, cur);
        }}
      />
      {pct !== null && (
        <>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
          <div className="text-[11px] text-muted-foreground">
            {formatMoney(won, cur)} won this year · {pct}%
          </div>
        </>
      )}
    </div>
  );
}

function Goals({ a }: { a: KeyAccountDetail }) {
  const refresh = useRefreshAccounts();
  const [title, setTitle] = useState("");
  const url = { params: { path: { account_id: a.id } } };
  return (
    <Card title="Account plan">
      <ul className="divide-y text-xs">
        {a.goals.map((g) => (
          <li key={g.id} className="flex items-center gap-2 py-1.5" data-goal={g.title}>
            <input
              type="checkbox"
              aria-label={`Done: ${g.title}`}
              checked={g.status === "done"}
              disabled={!a.can_edit}
              onChange={(e) =>
                run(async () => {
                  unwrap(
                    await api.PUT("/api/v1/key-accounts/{account_id}/goals/{goal_id}", {
                      params: { path: { account_id: a.id, goal_id: g.id } },
                      body: { title: g.title, target_minor: g.target_minor, currency: g.currency, due_on: g.due_on, status: e.target.checked ? "done" : "open" },
                    }),
                  );
                  refresh();
                })
              }
            />
            <span className={cn("flex-1", g.status === "done" && "text-muted-foreground line-through")}>{g.title}</span>
            {g.target_minor !== null && g.currency && <span className="tabular-nums">{formatMoney(g.target_minor, g.currency, { compact: true })}</span>}
            {g.due_on && <span className="w-24 text-right text-muted-foreground">by {day(g.due_on)}</span>}
          </li>
        ))}
        {a.goals.length === 0 && <li className="py-1.5 text-muted-foreground">No goals yet.</li>}
      </ul>
      {a.can_edit && (
        <div className="flex gap-2">
          <Input placeholder="New goal, e.g. Payroll for all plants" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="New goal" />
          <Button
            size="sm"
            disabled={!title.trim()}
            onClick={() =>
              run(async () => {
                unwrap(await api.POST("/api/v1/key-accounts/{account_id}/goals", { ...url, body: { title, status: "open" } }));
                setTitle("");
                refresh();
              })
            }
          >
            <Plus /> Add
          </Button>
        </div>
      )}
    </Card>
  );
}

function Units({ a }: { a: KeyAccountDetail }) {
  const refresh = useRefreshAccounts();
  const people = usePeopleMap(a.id);
  const [name, setName] = useState("");
  return (
    <Card title="Departments and budget holders">
      <ul className="divide-y text-xs">
        {a.units.map((u) => (
          <li key={u.id} className="flex items-center gap-2 py-1.5" data-unit={u.name}>
            <span className="w-28 font-medium">{u.name}</span>
            <NativeSelect
              aria-label={`Budget holder for ${u.name}`}
              className="h-7 flex-1"
              value={u.budget_holder_lead_id ?? ""}
              disabled={!a.can_edit}
              onChange={(e) =>
                run(async () => {
                  unwrap(
                    await api.PUT("/api/v1/key-accounts/{account_id}/units/{unit_id}", {
                      params: { path: { account_id: a.id, unit_id: u.id } },
                      body: { name: u.name, budget_holder_lead_id: e.target.value || null, budget_minor: u.budget_minor, budget_currency: u.budget_currency },
                    }),
                  );
                  refresh();
                })
              }
            >
              <option value="">No budget holder</option>
              {(people.data ?? []).map((p) => (
                <option key={p.lead_id} value={p.lead_id}>
                  {p.name}
                </option>
              ))}
            </NativeSelect>
            <span className="w-24 text-right tabular-nums">{u.budget_minor !== null && u.budget_currency ? formatMoney(u.budget_minor, u.budget_currency, { compact: true }) : "—"}</span>
            {a.can_edit && (
              <Button
                size="icon"
                variant="ghost"
                className="size-6"
                aria-label={`Remove ${u.name}`}
                onClick={() =>
                  confirm(`Remove ${u.name}? Its deals stay.`) &&
                  run(async () => {
                    unwrap(await api.DELETE("/api/v1/key-accounts/{account_id}/units/{unit_id}", { params: { path: { account_id: a.id, unit_id: u.id } } }));
                    refresh();
                  })
                }
              >
                <Trash2 />
              </Button>
            )}
          </li>
        ))}
      </ul>
      {a.can_edit && (
        <div className="flex gap-2">
          <Input placeholder="Department, e.g. Operations" value={name} onChange={(e) => setName(e.target.value)} aria-label="New department" />
          <Button
            size="sm"
            disabled={!name.trim()}
            onClick={() =>
              run(async () => {
                unwrap(await api.POST("/api/v1/key-accounts/{account_id}/units", { params: { path: { account_id: a.id } }, body: { name } }));
                setName("");
                refresh();
              })
            }
          >
            <Plus /> Add
          </Button>
        </div>
      )}
    </Card>
  );
}

// ---------- opportunity grid ----------
function GridTab({ a }: { a: KeyAccountDetail }) {
  const grid = useGrid(a.id);
  const [open, setOpen] = useState<Cell | null>(null);
  const g = grid.data;
  if (!g) return <p className="text-muted-foreground">Loading…</p>;
  if (!g.units.length) return <p className="text-sm text-muted-foreground">Add the departments that buy (HR, Finance, IT) on the Overview tab to build the grid.</p>;
  const cell = (u: string, p: string) => g.cells.find((c) => c.unit_id === u && c.product_id === p)!;
  return (
    <>
      <div className="surface overflow-x-auto p-4">
        <table className="w-full border-separate border-spacing-1 text-xs" data-grid>
          <thead>
            <tr>
              <th className="text-left font-medium text-muted-foreground">Department</th>
              {g.products.map((p) => (
                <th key={p.id} className="min-w-28 text-left font-medium text-muted-foreground">
                  {p.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {g.units.map((u) => (
              <tr key={u.id}>
                <td className="pr-2 font-medium whitespace-nowrap">{u.name}</td>
                {g.products.map((p) => {
                  const c = cell(u.id, p.id);
                  const s = CELL[c.state] ?? CELL.empty;
                  return (
                    <td key={p.id}>
                      <button className={cn("w-full rounded-md px-2 py-2 text-left font-medium", s.tone)} onClick={() => setOpen(c)} data-cell={`${u.name}|${p.name}`}>
                        {s.label}
                        {c.deals.length > 0 && <span className="block text-[10px] font-normal opacity-80">{c.deals.length === 1 ? formatMoney(c.deals[0].amount_minor, c.deals[0].currency, { compact: true }) : `${c.deals.length} deals`}</span>}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          {Object.entries(CELL).map(([k, v]) => (
            <span key={k} className={cn("rounded px-1.5 py-0.5", v.tone)}>
              {v.label}
            </span>
          ))}
        </div>
      </div>
      {open && <CellDialog a={a} g={g} cell={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function CellDialog({ a, g, cell, onClose }: { a: KeyAccountDetail; g: Grid; cell: Cell; onClose: () => void }) {
  const refresh = useRefreshAccounts();
  const competitors = useCompetitors();
  const [competitor, setCompetitor] = useState(cell.competitor_id ?? "");
  const [note, setNote] = useState(cell.note ?? "");
  const unit = g.units.find((u) => u.id === cell.unit_id)!;
  const product = g.products.find((p) => p.id === cell.product_id)!;
  const setCell = (status: "competitor" | "not_fit" | null) =>
    run(async () => {
      unwrap(
        await api.PUT("/api/v1/key-accounts/{account_id}/grid/{unit_id}/{product_id}", {
          params: { path: { account_id: a.id, unit_id: unit.id, product_id: product.id } },
          body: { status, competitor_id: competitor || null, note },
        }),
      );
      refresh();
      onClose();
    }, "Saved");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {unit.name} × {product.name}
          </DialogTitle>
        </DialogHeader>
        {cell.deals.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {cell.deals.map((d) => (
              <li key={d.id}>
                <Link href={`/deals/${d.id}`} className="hover:underline">
                  {d.name}
                </Link>{" "}
                <span className="text-xs text-muted-foreground">
                  · {d.status} · {formatMoney(d.amount_minor, d.currency)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No deal here yet.</p>
        )}
        {a.can_edit && (
          <div className="space-y-2">
            <Label className="text-xs">If a competitor holds it</Label>
            <NativeSelect aria-label="Competitor" value={competitor} onChange={(e) => setCompetitor(e.target.value)}>
              <option value="">Choose a competitor…</option>
              {(competitors.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
            <Input placeholder="Note (e.g. their contract ends in March)" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        )}
        {a.can_edit && (
          <DialogFooter className="flex-wrap gap-2">
            <Button
              onClick={() =>
                run(async () => {
                  unwrap(await api.POST("/api/v1/key-accounts/{account_id}/grid/deal", { params: { path: { account_id: a.id } }, body: { unit_id: unit.id, product_id: product.id } }));
                  refresh();
                  onClose();
                }, "Deal started")
              }
            >
              <Plus /> Start a deal
            </Button>
            <Button variant="outline" disabled={!competitor} onClick={() => setCell("competitor")}>
              Competitor holds it
            </Button>
            <Button variant="outline" onClick={() => setCell("not_fit")}>
              Not a fit
            </Button>
            {(cell.state === "competitor" || cell.state === "not_fit") && (
              <Button variant="ghost" onClick={() => setCell(null)}>
                Clear
              </Button>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------- people map ----------
function People({ a }: { a: KeyAccountDetail }) {
  const people = usePeopleMap(a.id);
  const refresh = useRefreshAccounts();
  const list = people.data ?? [];
  const save = (leadId: string, body: { unit_id: string | null; role: string; stance: string; strength: number; note: string | null }) =>
    run(async () => {
      unwrap(
        await api.PUT("/api/v1/key-accounts/{account_id}/people/{lead_id}", {
          params: { path: { account_id: a.id, lead_id: leadId } },
          body: body as never,
        }),
      );
      refresh();
    });
  if (!list.length) return <p className="text-sm text-muted-foreground">No contacts at this organisation yet. Link people to it from their pages.</p>;
  return (
    <div className="surface overflow-x-auto p-4">
      <table className="w-full text-xs" data-people>
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="py-1 font-medium">Person</th>
            <th className="py-1 font-medium">Department</th>
            <th className="py-1 font-medium">Role</th>
            <th className="py-1 font-medium">Stance</th>
            <th className="py-1 font-medium">Strength</th>
            <th className="py-1 font-medium">Last touch</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {list.map((p) => {
            const v = { unit_id: p.unit_id ?? null, role: p.role ?? "influencer", stance: p.stance ?? "neutral", strength: p.strength ?? 3, note: p.note ?? null };
            return (
              <tr key={p.lead_id} className={cn(!p.on_map && "opacity-60")} data-person={p.name}>
                <td className="py-1.5">
                  <Link href={`/leads/${p.lead_id}`} className="font-medium hover:underline">
                    {p.name}
                  </Link>
                  {p.stance && <span className={cn("ml-2 rounded-full px-1.5 py-0.5 text-[10px] font-medium", STANCE[p.stance]?.tone)}>{STANCE[p.stance]?.label}</span>}
                </td>
                <td className="py-1.5">
                  <NativeSelect className="h-7" aria-label={`Department of ${p.name}`} disabled={!a.can_edit} value={p.unit_id ?? ""} onChange={(e) => save(p.lead_id, { ...v, unit_id: e.target.value || null })}>
                    <option value="">—</option>
                    {a.units.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                  </NativeSelect>
                </td>
                <td className="py-1.5">
                  <NativeSelect className="h-7" aria-label={`Role of ${p.name}`} disabled={!a.can_edit} value={p.role ?? ""} onChange={(e) => save(p.lead_id, { ...v, role: e.target.value })}>
                    {!p.on_map && <option value="">Not on the map</option>}
                    {Object.entries(ROLE).map(([k, l]) => (
                      <option key={k} value={k}>
                        {l}
                      </option>
                    ))}
                  </NativeSelect>
                </td>
                <td className="py-1.5">
                  <NativeSelect className="h-7" aria-label={`Stance of ${p.name}`} disabled={!a.can_edit} value={p.stance ?? ""} onChange={(e) => save(p.lead_id, { ...v, stance: e.target.value })}>
                    {!p.on_map && <option value="">—</option>}
                    {Object.entries(STANCE).map(([k, s]) => (
                      <option key={k} value={k}>
                        {s.label}
                      </option>
                    ))}
                  </NativeSelect>
                </td>
                <td className="py-1.5">
                  <span className="inline-flex gap-0.5" aria-label={`Strength ${p.strength ?? 0} of 5`}>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button key={n} disabled={!a.can_edit} onClick={() => save(p.lead_id, { ...v, strength: n })} className={cn("size-2.5 rounded-full", n <= (p.strength ?? 0) ? "bg-primary" : "bg-muted")} aria-label={`Strength ${n}`} />
                    ))}
                  </span>
                </td>
                <td className="py-1.5 text-muted-foreground">{relative(p.last_touch)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------- group tree ----------
function Tree({ a }: { a: KeyAccountDetail }) {
  const byParent = new Map<string | null, KeyAccountDetail["tree"]>();
  for (const n of a.tree) {
    const key = a.tree.some((x) => x.id === n.parent_id) ? n.parent_id! : null;
    byParent.set(key, [...(byParent.get(key) ?? []), n]);
  }
  const render = (parent: string | null, depth: number): React.ReactNode =>
    (byParent.get(parent) ?? []).map((n) => (
      <div key={n.id}>
        <Link
          href={`/key-accounts/${n.id}`}
          className={cn("flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 hover:bg-muted/50", n.id === a.id && "bg-muted/60")}
          style={{ marginLeft: depth * 24 }}
          data-node={n.name}
        >
          <HealthDot health={n.health} withLabel={false} />
          <span className="font-medium">{n.name}</span>
          <TierPill tier={n.tier} />
          <span className="ml-auto text-xs text-muted-foreground">
            won {amounts(n.rollup.won_this_year)} · pipeline {amounts(n.rollup.pipeline)}
          </span>
        </Link>
        {render(n.id, depth + 1)}
      </div>
    ));
  return (
    <Card title="Group tree">
      {a.tree.length <= 1 && <p className="text-xs text-muted-foreground">This account has no parent or subsidiaries yet. Set a parent from a subsidiary&apos;s page (Overview → Account).</p>}
      <div className="text-sm">{render(null, 0)}</div>
      <p className="text-[11px] text-muted-foreground">Each line adds up the company and everything below it, per currency.</p>
    </Card>
  );
}
