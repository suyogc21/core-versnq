"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import {
  type Deal,
  type PipelineStage,
  currencyDigits,
  formatMoney,
  moneyInput,
  parseMoney,
  useDeals,
  useLostReasons,
  usePipelines,
  useRefreshDeals,
} from "@/lib/deals";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

/** An amount box that keeps exact minor units (no float rounding). */
export function MoneyInput({
  id,
  currency,
  value,
  onChange,
  className,
}: {
  id?: string;
  currency: string;
  value: number;
  onChange: (minor: number | null) => void;
  className?: string;
}) {
  const [text, setText] = useState(value ? moneyInput(value, currency) : "");
  const bad = parseMoney(text, currency) === null;
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <span className="text-xs text-muted-foreground">{currency}</span>
      <Input
        id={id}
        inputMode={currencyDigits(currency) ? "decimal" : "numeric"}
        aria-invalid={bad}
        className={cn("h-8", bad && "border-destructive")}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          onChange(parseMoney(e.target.value, currency));
        }}
      />
    </div>
  );
}

/** Move a deal; on a lost stage the caller first asks for a reason. Returns the deal or null. */
export async function moveDeal(deal: Deal, stage: PipelineStage, lost?: { reason: string; note: string }, onOpen?: () => void) {
  try {
    return unwrap(
      await api.POST("/api/v1/deals/{deal_id}/move", {
        params: { path: { deal_id: deal.id } },
        body: { version: deal.version, stage_id: stage.id, lost_reason_id: lost?.reason ?? null, note: lost?.note || null },
      }),
    );
  } catch (e) {
    const msg = (e as Error).message;
    // Missing required fields: offer to open the deal and fill them in.
    toast.error(msg, onOpen && /fill in/.test(msg) ? { action: { label: "Open deal", onClick: onOpen } } : undefined);
    return null;
  }
}

export function LostDialog({ deal, onConfirm, onClose }: { deal: Deal; onConfirm: (lost: { reason: string; note: string }) => void; onClose: () => void }) {
  const reasons = useLostReasons();
  const active = (reasons.data ?? []).filter((r) => r.is_active);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Why was it lost?</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{deal.name}</p>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (reason) onConfirm({ reason, note });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="lost-reason">Reason</Label>
            <NativeSelect id="lost-reason" value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="">Choose a reason…</option>
              {active.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="lost-note">Note (optional)</Label>
            <Textarea id="lost-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!reason}>
              Mark lost
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type LeadHit = { id: string; name: string; hint?: string };

/** New deal. From a lead page the lead is fixed; from the deals page you search for one. */
export function NewDealDialog({ lead, pipelineId, onClose }: { lead?: LeadHit; pipelineId?: string; onClose: () => void }) {
  const router = useRouter();
  const label = useLabels();
  const pipelines = usePipelines();
  const refresh = useRefreshDeals();
  const active = (pipelines.data ?? []).filter((p) => p.is_active);
  const [chosen, setChosen] = useState<LeadHit | null>(lead ?? null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<LeadHit[]>([]);
  const [pid, setPid] = useState(pipelineId ?? "");
  const pipeline = active.find((p) => p.id === pid) ?? active[0];
  const [name, setName] = useState("");
  const [amount, setAmount] = useState<number | null>(0);
  const [close, setClose] = useState("");
  const [busy, setBusy] = useState(false);

  async function search(term: string) {
    setQ(term);
    if (term.trim().length < 2) return setHits([]);
    const page = unwrap(await api.GET("/api/v1/leads", { params: { query: { q: term, limit: 10 } } }));
    setHits(page.items.map((x) => ({ id: x.id, name: x.display_name, hint: x.primary_phone ?? x.primary_email ?? undefined })));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!chosen || !pipeline || amount === null) return;
    setBusy(true);
    try {
      const deal = unwrap(
        await api.POST("/api/v1/deals", {
          body: {
            lead_id: chosen.id,
            pipeline_id: pipeline.id,
            name: name.trim() || null,
            amount_minor: amount,
            expected_close_on: close || null,
            assign_to_me: true,
            custom_fields: {},
            lines: [],
          },
        }),
      );
      refresh();
      toast.success("Deal added");
      onClose();
      router.push(`/deals/${deal.id}`);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New {label("deal").toLowerCase()}</DialogTitle>
        </DialogHeader>
        <form onSubmit={save} className="space-y-3 text-sm">
          <div className="space-y-1.5">
            <Label htmlFor="deal-lead">{label("lead")}</Label>
            {chosen ? (
              <div className="flex items-center gap-2 rounded-md border px-2 py-1.5">
                <span className="flex-1 truncate font-medium">{chosen.name}</span>
                {!lead && (
                  <button type="button" className="text-xs text-muted-foreground hover:underline" onClick={() => setChosen(null)}>
                    Change
                  </button>
                )}
              </div>
            ) : (
              <>
                <Input id="deal-lead" autoFocus placeholder="Search by name, phone or email…" value={q} onChange={(e) => search(e.target.value)} />
                {hits.map((h) => (
                  <button key={h.id} type="button" className="flex w-full items-center gap-2 rounded px-1 py-1 text-start text-xs hover:bg-accent" onClick={() => setChosen(h)}>
                    <span className="truncate">{h.name}</span>
                    {h.hint && <span className="ms-auto truncate text-muted-foreground">{h.hint}</span>}
                  </button>
                ))}
                {q.trim().length >= 2 && hits.length === 0 && <p className="text-xs text-muted-foreground">No match.</p>}
              </>
            )}
          </div>
          {active.length > 1 && (
            <div className="space-y-1.5">
              <Label htmlFor="deal-pipeline">{label("pipeline")}</Label>
              <NativeSelect id="deal-pipeline" value={pipeline?.id ?? ""} onChange={(e) => setPid(e.target.value)}>
                {active.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.currency})
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="deal-name">Name</Label>
            <Input id="deal-name" placeholder={chosen?.name ?? "Defaults to the name above"} value={name} onChange={(e) => setName(e.target.value)} maxLength={300} />
          </div>
          {pipeline && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="deal-amount">Value</Label>
                <MoneyInput key={pipeline.currency} id="deal-amount" currency={pipeline.currency} value={0} onChange={setAmount} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="deal-close">Expected close</Label>
                <Input id="deal-close" type="date" className="h-8" value={close} onChange={(e) => setClose(e.target.value)} />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!chosen || !pipeline || amount === null || busy}>
              Add deal
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function StatusBadge({ status }: { status: string }) {
  if (status === "open") return null;
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
        status === "won" ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400" : "bg-red-500/15 text-red-700 dark:text-red-400",
      )}
    >
      {status}
    </span>
  );
}

/** The lead's deals, on the lead page. */
export function DealsCard({ leadId, leadName }: { leadId: string; leadName: string }) {
  const { can } = useAuth();
  const label = useLabels();
  const deals = useDeals({ lead_id: leadId, limit: 50 });
  const [adding, setAdding] = useState(false);
  const items = deals.data?.items ?? [];
  return (
    <div className="space-y-1.5 text-xs">
      {deals.isLoading && <p className="text-muted-foreground">Loading…</p>}
      {deals.data && items.length === 0 && <p className="text-muted-foreground">No {label("deal", true).toLowerCase()} yet.</p>}
      {items.map((d) => (
        <Link key={d.id} href={`/deals/${d.id}`} className="flex items-center gap-2 rounded-md border px-2 py-1.5 hover:bg-accent">
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{d.name}</span>
            <span className="text-muted-foreground">{d.stage_name}</span>
          </span>
          <StatusBadge status={d.status} />
          <span className="tabular-nums">{formatMoney(d.amount_minor, d.currency)}</span>
        </Link>
      ))}
      {can("deals.create") && (
        <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
          <Plus /> New {label("deal").toLowerCase()}
        </Button>
      )}
      {adding && <NewDealDialog lead={{ id: leadId, name: leadName }} onClose={() => setAdding(false)} />}
    </div>
  );
}
