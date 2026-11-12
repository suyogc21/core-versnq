"use client";

import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { formatMoney } from "@/lib/deals";
import { METHOD_LABEL, useMoneyOn } from "@/lib/money";
import {
  type Amount,
  type Headline,
  PERIODS,
  type PeriodQuery,
  amounts,
  change,
  useBusinessDashboard,
  useMoneyDashboard,
  useMyDashboard,
  useTeamDashboard,
} from "@/lib/reports";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Tab = "me" | "team" | "business" | "money";

export default function DashboardsPage() {
  const { can } = useAuth();
  const moneyOn = useMoneyOn();
  const tabs: [Tab, string][] = [
    ...(can("leads.edit") ? [["me", "My numbers"] as [Tab, string]] : []),
    ...(can("dashboards.team") ? [["team", "Team"] as [Tab, string]] : []),
    ...(can("dashboards.business") ? [["business", "Business"] as [Tab, string]] : []),
    ...(moneyOn && can("dashboards.money") ? [["money", "Money"] as [Tab, string]] : []),
  ];
  const [picked, setTab] = useState<Tab | null>(null);
  const tab = picked && tabs.some(([k]) => k === picked) ? picked : tabs[0]?.[0];
  const [q, setQ] = useState<PeriodQuery>({ period: "month" });
  if (!tab) return <p className="p-8 text-center text-muted-foreground">You have no dashboards. Ask your admin.</p>;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Dashboards" actions={<PeriodPicker q={q} onChange={setQ} />} />
      <div className="flex gap-1 overflow-x-auto border-b px-4 py-2 sm:px-6" role="tablist">
        {tabs.map(([k, name]) => (
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
      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4 sm:px-6">
        {tab === "me" && <Me q={q} />}
        {tab === "team" && <Team q={q} />}
        {tab === "business" && <Business q={q} />}
        {tab === "money" && <Money q={q} />}
      </div>
    </div>
  );
}

function PeriodPicker({ q, onChange }: { q: PeriodQuery; onChange: (q: PeriodQuery) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <NativeSelect aria-label="Period" className="h-7 w-36" value={q.period} onChange={(e) => onChange({ period: e.target.value as PeriodQuery["period"] })}>
        {PERIODS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </NativeSelect>
      {q.period === "custom" && (
        <>
          <Input type="date" aria-label="From date" className="h-7 w-36" value={q.from ?? ""} onChange={(e) => onChange({ ...q, from: e.target.value })} />
          <Input type="date" aria-label="To date" className="h-7 w-36" value={q.to ?? ""} onChange={(e) => onChange({ ...q, to: e.target.value })} />
        </>
      )}
    </div>
  );
}

// ---------- building blocks ----------
function Tile({ label, value, now, before, hint, href, danger }: { label: string; value: React.ReactNode; now?: number; before?: number; hint?: string; href?: string; danger?: boolean }) {
  const ch = now !== undefined && before !== undefined ? change(now, before) : null;
  const body = (
    <>
      <div className="text-[11px] text-muted-foreground" title={hint}>
        {label}
      </div>
      <div className={cn("text-xl font-semibold tracking-tight tabular-nums", danger && "text-red-700 dark:text-red-300")}>{value}</div>
      {ch && <div className={cn("text-[11px]", ch.tone === "up" ? "text-emerald-700 dark:text-emerald-300" : ch.tone === "down" ? "text-red-700 dark:text-red-300" : "text-muted-foreground")}>{ch.text}</div>}
    </>
  );
  const cls = "surface block min-w-0 space-y-0.5 p-3";
  return href ? (
    <Link href={href} className={cn(cls, "transition-shadow hover:shadow-float")} data-tile={label}>
      {body}
    </Link>
  ) : (
    <div className={cls} data-tile={label}>
      {body}
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">{children}</div>;
}

function Card({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="surface space-y-3 p-4">
      <h4 className="text-[13px] font-semibold" title={hint}>
        {title}
      </h4>
      {children}
    </section>
  );
}

/** Simple horizontal bars, drawn by Core itself (Decision log #35: no chart library). */
function Bars({ items, empty = "Nothing in this period." }: { items: { label: React.ReactNode; value: number; text?: string; href?: string; tone?: string }[]; empty?: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  if (!items.length || items.every((i) => !i.value)) return <p className="text-xs text-muted-foreground">{empty}</p>;
  return (
    <ul className="space-y-1.5 text-xs">
      {items.map((i, n) => {
        const row = (
          <>
            <span className="w-32 shrink-0 truncate">{i.label}</span>
            <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
              <span className={cn("block h-full rounded-full", i.tone ?? "bg-primary")} style={{ width: `${(i.value / max) * 100}%` }} />
            </span>
            <span className="min-w-28 shrink-0 text-right whitespace-nowrap tabular-nums">{i.text ?? i.value}</span>
          </>
        );
        return (
          <li key={n}>
            {i.href ? (
              <Link href={i.href} className="flex items-center gap-2 hover:underline">
                {row}
              </Link>
            ) : (
              <div className="flex items-center gap-2">{row}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function leadsLink(p: { start: string; end: string }, extra: Record<string, string> = {}) {
  const params = new URLSearchParams({ created_from: p.start, created_to: p.end, ...extra });
  return `/leads?${params}`;
}

function HeadlineTiles({ cur, prev, period, owner }: { cur: Headline; prev: Headline; period: { start: string; end: string }; owner?: string }) {
  const label = useLabels();
  const leads = label("lead", true);
  return (
    <>
      <Tile label={`New ${leads.toLowerCase()}`} value={cur.new_leads} now={cur.new_leads} before={prev.new_leads} hint="Leads that reached the owner in the period" href={leadsLink(period, owner ? { owner } : {})} />
      <Tile label="Calls logged" value={cur.calls} now={cur.calls} before={prev.calls} />
      <Tile label="Follow-ups done" value={cur.follow_ups_done} now={cur.follow_ups_done} before={prev.follow_ups_done} />
      <Tile label={`${label("deal", true)} won`} value={cur.deals_won} now={cur.deals_won} before={prev.deals_won} href="/deals" />
      <Tile label="Booked" value={amounts(cur.booked)} hint="Value of deals won in the period" />
      <Tile label={`New ${label("customer", true).toLowerCase()}`} value={cur.converted} now={cur.converted} before={prev.converted} hint="Became a customer in the period" href="/customers" />
    </>
  );
}

function money(list: Amount[]): number {
  return list.length === 1 ? list[0].minor : 0;
}

// ---------- tabs ----------
function Me({ q }: { q: PeriodQuery }) {
  const d = useMyDashboard(q);
  if (!d.data) return <p className="text-muted-foreground">{d.isError ? d.error.message : "Loading…"}</p>;
  const { current: cur, previous: prev, now } = d.data;
  return (
    <>
      <Grid>
        <HeadlineTiles cur={cur} prev={prev} period={d.data.period} owner="me" />
      </Grid>
      <Grid>
        <Tile label="Collected from my customers" value={amounts(cur.collected)} now={money(cur.collected)} before={money(prev.collected)} />
        <Tile label="Follow-ups overdue" value={now.tasks_overdue} danger={now.tasks_overdue > 0} href="/" />
        <Tile label="Due today" value={now.tasks_due_today} href="/" />
        <Tile label="My open deals" value={now.open_deals} href="/deals" />
        <Tile label="Open pipeline" value={amounts(now.pipeline)} hint="Weighted by each stage's win %" />
        <Tile label="Overdue money" value={amounts(now.overdue_money, "Nothing")} danger={now.overdue_money.length > 0} />
      </Grid>
      <p className="text-xs text-muted-foreground">Weighted pipeline: {amounts(now.weighted)}. Overdue and due figures are as of now; the rest are for the period chosen.</p>
    </>
  );
}

function Team({ q }: { q: PeriodQuery }) {
  const label = useLabels();
  const d = useTeamDashboard(q);
  if (!d.data) return <p className="text-muted-foreground">{d.isError ? d.error.message : "Loading…"}</p>;
  const t = d.data;
  const p = t.period;
  return (
    <>
      <p className="text-xs text-muted-foreground">{t.everyone ? "Everyone in the company." : "You and your team."}</p>
      <Grid>
        <HeadlineTiles cur={t.current} prev={t.previous} period={p} />
      </Grid>
      <Grid>
        <Tile label="Collected" value={amounts(t.current.collected)} now={money(t.current.collected)} before={money(t.previous.collected)} />
        <Tile label="Not touched in time" value={t.now.leaking} danger={t.now.leaking > 0} hint="Open leads the leakage guard flagged" />
        <Tile label="Slow first response" value={t.sla_breaches} danger={t.sla_breaches > 0} hint="Response-time rules missed in the period" />
        <Tile label="Follow-ups overdue" value={t.now.tasks_overdue} danger={t.now.tasks_overdue > 0} />
        <Tile label="Open pipeline" value={amounts(t.now.pipeline)} />
        <Tile label="Weighted forecast" value={amounts(t.now.weighted)} hint="Open deal value × each stage's win %" />
      </Grid>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Funnel" hint={`${label("lead", true)} that came in this period, and how far they got`}>
          <Bars items={t.funnel.map((s) => ({ label: s.label, value: s.count }))} />
        </Card>
        <Card title="Sources" hint="Leads per source in the period, and how many became customers">
          <Bars
            items={t.sources.map((s) => ({
              label: s.name,
              value: s.leads,
              text: `${s.leads} leads · ${(s.conversion_bp / 100).toFixed(1).replace(/\.0$/, "")}% converted`,
              href: leadsLink(p, { source_id: s.source_id }),
            }))}
          />
        </Card>
      </div>
      <Card title="Leaderboard">
        {t.leaderboard.length === 0 ? (
          <p className="text-xs text-muted-foreground">No activity in this period.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-leaderboard>
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="py-1 font-medium">Person</th>
                  <th className="py-1 text-right font-medium">New leads</th>
                  <th className="py-1 text-right font-medium">Calls</th>
                  <th className="py-1 text-right font-medium">Follow-ups</th>
                  <th className="py-1 text-right font-medium">Won</th>
                  <th className="py-1 text-right font-medium">Booked</th>
                  <th className="py-1 text-right font-medium">Collected</th>
                  <th className="py-1 text-right font-medium">Slow responses</th>
                </tr>
              </thead>
              <tbody className="divide-y tabular-nums">
                {t.leaderboard.map((r) => (
                  <tr key={r.user_id}>
                    <td className="py-1.5">
                      <Link href={leadsLink(p, { owner: r.user_id })} className="hover:underline">
                        {r.name}
                      </Link>
                    </td>
                    <td className="py-1.5 text-right">{r.new_leads}</td>
                    <td className="py-1.5 text-right">{r.calls}</td>
                    <td className="py-1.5 text-right">{r.follow_ups_done}</td>
                    <td className="py-1.5 text-right font-medium">{r.deals_won}</td>
                    <td className="py-1.5 text-right">{amounts(r.booked)}</td>
                    <td className="py-1.5 text-right">{amounts(r.collected)}</td>
                    <td className={cn("py-1.5 text-right", r.sla_missed > 0 && "text-red-700 dark:text-red-300")}>{r.sla_missed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Why deals were lost">
        <Bars items={t.lost_reasons.map((r) => ({ label: r.name, value: r.count, tone: "bg-red-400/70" }))} empty="No deals lost in this period." />
      </Card>
    </>
  );
}

function Business({ q }: { q: PeriodQuery }) {
  const label = useLabels();
  const d = useBusinessDashboard(q);
  if (!d.data) return <p className="text-muted-foreground">{d.isError ? d.error.message : "Loading…"}</p>;
  const b = d.data;
  const currencies = [...new Set(b.trend.flatMap((m) => [...m.booked, ...m.collected].map((a) => a.currency)))];
  const cur = currencies[0];
  const pick = (list: Amount[]) => list.find((a) => a.currency === cur)?.minor ?? 0;
  return (
    <>
      <Grid>
        <HeadlineTiles cur={b.current} prev={b.previous} period={b.period} />
      </Grid>
      <Grid>
        <Tile label="Collected" value={amounts(b.current.collected)} now={money(b.current.collected)} before={money(b.previous.collected)} hint="Payments received in the period" href="/money" />
        <Tile label="Overdue" value={amounts(b.now.overdue_money, "Nothing")} danger={b.now.overdue_money.length > 0} href="/money" />
        <Tile label="Open pipeline" value={amounts(b.now.pipeline)} />
        <Tile label="Weighted forecast" value={amounts(b.now.weighted)} />
        <Tile label="Follow-ups overdue" value={b.now.tasks_overdue} danger={b.now.tasks_overdue > 0} />
        <Tile label="Not touched in time" value={b.now.leaking} danger={b.now.leaking > 0} />
      </Grid>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`New ${label("lead", true).toLowerCase()} and ${label("customer", true).toLowerCase()} by month`}>
          <Bars items={b.trend.map((m) => ({ label: monthName(m.month), value: m.new_leads, text: `${m.new_leads} · ${m.converted} converted` }))} />
        </Card>
        <Card title={`Booked and collected by month${cur ? ` (${cur})` : ""}`} hint="Booked = deals won; collected = payments received">
          {cur ? (
            <Bars
              items={b.trend.map((m) => ({
                label: monthName(m.month),
                value: Math.max(pick(m.booked), pick(m.collected)),
                text: `${formatMoney(pick(m.booked), cur, { compact: true })} / ${formatMoney(pick(m.collected), cur, { compact: true })}`,
              }))}
            />
          ) : (
            <p className="text-xs text-muted-foreground">No money yet.</p>
          )}
        </Card>
      </div>
      <p className="text-xs text-muted-foreground">Email and WhatsApp performance join this page once those channels are built (steps 9 and 10).</p>
    </>
  );
}

function monthName(ym: string) {
  return new Date(`${ym}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

function Money({ q }: { q: PeriodQuery }) {
  const d = useMoneyDashboard(q);
  if (!d.data) return <p className="text-muted-foreground">{d.isError ? d.error.message : "Loading…"}</p>;
  const m = d.data.current;
  return (
    <>
      <Grid>
        <Tile label="Invoiced" value={amounts(m.invoiced)} now={money(m.invoiced)} before={money(d.data.previous_invoiced)} hint="Invoices issued in the period" href="/money" />
        <Tile label="Collected" value={amounts(m.collected)} now={money(m.collected)} before={money(d.data.previous_collected)} href="/money?tab=payments" />
        <Tile label="Due now" value={amounts(m.due, "Nothing")} href="/money" />
        <Tile label="Overdue" value={amounts(m.overdue, "Nothing")} danger={m.overdue.length > 0} href="/money?tab=overdue" />
        <Tile label="Due in the next 30 days" value={amounts(m.due_next_30_days, "Nothing")} hint={`${m.installments_next_30_days} installments`} />
        <Tile label="Invoices issued" value={m.invoices_issued} />
      </Grid>
      {m.aging.map((r) => (
        <Card key={`${r.entity_id}${r.currency}`} title={`Overdue by how late · ${r.entity_name} · ${r.currency}`}>
          <Bars items={Object.entries(r.buckets).map(([k, v]) => ({ label: `${k.replace("-", "–")} days`, value: v, text: formatMoney(v, r.currency), tone: "bg-red-400/70", href: "/money?tab=aging" }))} />
        </Card>
      ))}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Collected by payment method">
          <Bars items={m.by_method.map((x) => ({ label: `${METHOD_LABEL[x.method] ?? x.method} (${x.currency})`, value: x.minor, text: formatMoney(x.minor, x.currency) }))} empty="No payments in this period." />
        </Card>
        <Card title="Collected by billing entity">
          <Bars items={m.by_entity.map((x) => ({ label: `${x.entity_name} (${x.currency})`, value: x.minor, text: formatMoney(x.minor, x.currency) }))} empty="No payments in this period." />
        </Card>
      </div>
      <Card title="Who owes the most (overdue)">
        {m.top_overdue.length === 0 ? (
          <p className="text-xs text-muted-foreground">Nothing is overdue.</p>
        ) : (
          <ul className="divide-y text-xs">
            {m.top_overdue.map((x) => (
              <li key={`${x.customer_id}${x.currency}`} className="flex items-center gap-2 py-1.5">
                <Link href={`/customers/${x.customer_id}`} className="font-medium hover:underline">
                  {x.name}
                </Link>
                <span className="text-muted-foreground">{x.number}</span>
                <span className="ml-auto font-medium text-red-700 tabular-nums dark:text-red-300">{formatMoney(x.minor, x.currency)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
