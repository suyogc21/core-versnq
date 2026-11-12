"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { HealthDot, TierPill } from "@/components/crm/key-accounts";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type KeyAccount, useCompetitors, useKeyAccounts, useKeyAccountsOn, useRefreshAccounts } from "@/lib/accounts";
import { useAuth } from "@/lib/auth";
import { formatMoney } from "@/lib/deals";
import { amounts } from "@/lib/reports";

type Tier = "strategic" | "growth" | "maintain";
type Health = "on_track" | "at_risk" | "off_track";

export default function KeyAccountsPage() {
  const { can } = useAuth();
  const on = useKeyAccountsOn();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [tier, setTier] = useState<Tier | "">("");
  const [health, setHealth] = useState<Health | "">("");
  const [mine, setMine] = useState(false);
  const [competitors, setCompetitors] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);
  const list = useKeyAccounts({ q: q || undefined, tier: tier || undefined, health: health || undefined, mine: mine || undefined }, on);
  const rows = list.data ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="Key accounts"
        count={list.data?.length}
        actions={<Input placeholder="Search accounts…" className="h-7 w-full sm:w-60" value={search} onChange={(e) => setSearch(e.target.value)} />}
      />
      {!on ? (
        <p className="p-8 text-center text-muted-foreground">The key accounts add-on is switched off for your company.</p>
      ) : (
        <div className="min-h-0 flex-1 space-y-3 overflow-auto p-4 sm:px-6">
          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect aria-label="Tier" className="h-7 w-36" value={tier} onChange={(e) => setTier(e.target.value as Tier | "")}>
              <option value="">All tiers</option>
              <option value="strategic">Strategic</option>
              <option value="growth">Growth</option>
              <option value="maintain">Maintain</option>
            </NativeSelect>
            <NativeSelect aria-label="Health" className="h-7 w-36" value={health} onChange={(e) => setHealth(e.target.value as Health | "")}>
              <option value="">Any health</option>
              <option value="on_track">On track</option>
              <option value="at_risk">At risk</option>
              <option value="off_track">Off track</option>
            </NativeSelect>
            <Button size="sm" variant={mine ? "default" : "outline"} onClick={() => setMine(!mine)}>
              Mine
            </Button>
            <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setCompetitors(true)}>
              Competitors
            </Button>
          </div>
          {rows.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">
              {list.isLoading ? "Loading…" : "No key accounts yet. Open an organisation and choose “Mark as key account”."}
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {rows.map((a) => (
                <AccountCard key={a.id} a={a} />
              ))}
            </div>
          )}
          {competitors && <CompetitorsDialog canEdit={can("key_accounts.manage")} onClose={() => setCompetitors(false)} />}
        </div>
      )}
    </div>
  );
}

function AccountCard({ a }: { a: KeyAccount }) {
  const won = a.target_currency ? (a.rollup.won_this_year.find((x) => x.currency === a.target_currency)?.minor ?? 0) : 0;
  const pct = a.target_minor ? Math.min(100, Math.round((won * 100) / a.target_minor)) : null;
  return (
    <Link href={`/key-accounts/${a.id}`} className="surface block space-y-2 p-4 transition-shadow hover:shadow-float" data-account={a.name}>
      <div className="flex items-center gap-2">
        <span className="truncate font-semibold">{a.name}</span>
        <TierPill tier={a.tier} />
        <span className="ml-auto">
          <HealthDot health={a.health} />
        </span>
      </div>
      <div className="text-xs text-muted-foreground">
        {a.parent_name ? `Part of ${a.parent_name} · ` : ""}
        {a.owner_name ?? "No owner"}
        {a.industry ? ` · ${a.industry}` : ""}
      </div>
      {pct !== null && (
        <div className="space-y-1">
          <div className="flex justify-between text-[11px] text-muted-foreground">
            <span>Won this year vs target</span>
            <span className="tabular-nums">
              {formatMoney(won, a.target_currency!, { compact: true })} / {formatMoney(a.target_minor!, a.target_currency!, { compact: true })}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <span>
          Pipeline <b className="tabular-nums">{amounts(a.rollup.pipeline)}</b>
        </span>
        <span>
          Collected <b className="tabular-nums">{amounts(a.rollup.collected_this_year)}</b>
        </span>
      </div>
      {a.hints.length > 0 && <div className="text-[11px] text-amber-700 dark:text-amber-300">{a.hints.join(" · ")}</div>}
    </Link>
  );
}

function CompetitorsDialog({ canEdit, onClose }: { canEdit: boolean; onClose: () => void }) {
  const list = useCompetitors();
  const refresh = useRefreshAccounts();
  const [name, setName] = useState("");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Competitors</DialogTitle>
        </DialogHeader>
        <ul className="divide-y text-sm">
          {(list.data ?? []).map((c) => (
            <li key={c.id} className="py-1.5">
              {c.name}
            </li>
          ))}
          {!list.data?.length && <li className="py-2 text-muted-foreground">None yet.</li>}
        </ul>
        {canEdit && (
          <div className="flex gap-2">
            <Input placeholder="Competitor name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Competitor name" />
            <Button
              disabled={!name.trim()}
              onClick={async () => {
                try {
                  unwrap(await api.POST("/api/v1/competitors", { body: { name, is_active: true } }));
                  setName("");
                  refresh();
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            >
              <Plus /> Add
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
