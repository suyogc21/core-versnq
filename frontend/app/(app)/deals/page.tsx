"use client";

import {
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { CalendarDays, Columns3, List, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { LostDialog, NewDealDialog, StatusBadge, moveDeal } from "@/components/crm/deals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { relative } from "@/lib/crm";
import { type Board, type Deal, type PipelineStage, formatMoney, useBoard, useDeals, usePipelines, useRefreshDeals } from "@/lib/deals";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

type View = "board" | "list";

function load<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {}
}

export default function DealsPage() {
  const { can } = useAuth();
  const label = useLabels();
  const pipelines = usePipelines();
  const active = (pipelines.data ?? []).filter((p) => p.is_active);
  // The app shell renders pages only after sign-in on the client, so storage is available here.
  const [pid, setPid] = useState<string>(() => load<string>("deals-pipeline", ""));
  const [view, setView] = useState<View>(() => load<View>("deals-view", "board"));
  const [mine, setMine] = useState(false);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);
  const pipeline = active.find((p) => p.id === pid) ?? active[0];
  const owner = mine ? ["me"] : undefined;

  return (
    <>
      <PageHeader
        title={label("deal", true)}
        actions={
          <>
            {active.length > 1 && (
              <NativeSelect
                aria-label={label("pipeline")}
                className="h-8 w-auto"
                value={pipeline?.id ?? ""}
                onChange={(e) => {
                  setPid(e.target.value);
                  save("deals-pipeline", e.target.value);
                }}
              >
                {active.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </NativeSelect>
            )}
            <Input aria-label="Search deals" placeholder="Search…" className="h-8 w-40" value={search} onChange={(e) => setSearch(e.target.value)} />
            <Button size="sm" variant={mine ? "default" : "outline"} onClick={() => setMine(!mine)}>
              Mine
            </Button>
            <div className="flex rounded-md border">
              {(["board", "list"] as const).map((v) => (
                <button
                  key={v}
                  aria-label={v === "board" ? "Board view" : "List view"}
                  aria-pressed={view === v}
                  className={cn("px-2 py-1 text-muted-foreground", view === v && "bg-accent text-foreground")}
                  onClick={() => {
                    setView(v);
                    save("deals-view", v);
                  }}
                >
                  {v === "board" ? <Columns3 className="size-4" /> : <List className="size-4" />}
                </button>
              ))}
            </div>
            {can("deals.create") && (
              <Button size="sm" onClick={() => setAdding(true)}>
                <Plus /> New {label("deal").toLowerCase()}
              </Button>
            )}
          </>
        }
      />
      {pipelines.isLoading ? (
        <p className="p-6 text-muted-foreground">Loading…</p>
      ) : !pipeline ? (
        <p className="p-8 text-center text-muted-foreground">No {label("pipeline").toLowerCase()} is switched on.</p>
      ) : view === "board" ? (
        <BoardView pipelineId={pipeline.id} owner={owner} q={q} />
      ) : (
        <ListView pipelineId={pipeline.id} owner={owner} q={q} />
      )}
      {adding && <NewDealDialog pipelineId={pipeline?.id} onClose={() => setAdding(false)} />}
    </>
  );
}

// ---------- board ----------
function BoardView({ pipelineId, owner, q }: { pipelineId: string; owner?: string[]; q: string }) {
  const { can } = useAuth();
  const router = useRouter();
  const board = useBoard({ pipeline_id: pipelineId, owner, q: q || undefined });
  const refresh = useRefreshDeals();
  const [dragging, setDragging] = useState<Deal | null>(null);
  const [losing, setLosing] = useState<{ deal: Deal; stage: PipelineStage } | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
    useSensor(KeyboardSensor),
  );
  const editable = can("deals.edit");
  const data = board.data;
  if (board.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!data) return <p className="p-6 text-destructive">{board.error?.message}</p>;
  const stageOf = (id: string) => data.columns.find((c) => c.stage_id === id);

  async function go(deal: Deal, stage: PipelineStage, lost?: { reason: string; note: string }) {
    const done = await moveDeal(deal, stage, lost, () => router.push(`/deals/${deal.id}`));
    if (done) toast.success(`${deal.name} → ${stage.name}`);
    refresh();
  }

  function onDragEnd(e: DragEndEvent) {
    setDragging(null);
    const deal = e.active.data.current as Deal | undefined;
    const col = e.over ? stageOf(String(e.over.id)) : undefined;
    if (!deal || !col || col.stage_id === deal.stage_id) return;
    const stage = { id: col.stage_id, name: col.name, kind: col.kind } as PipelineStage;
    if (col.kind === "lost") setLosing({ deal, stage });
    else go(deal, stage);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Totals board={data} />
      <DndContext
        sensors={sensors}
        onDragStart={(e: DragStartEvent) => setDragging((e.active.data.current as Deal) ?? null)}
        onDragEnd={onDragEnd}
        onDragCancel={() => setDragging(null)}
      >
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto p-3">
          {data.columns.map((col) => (
            <Column key={col.stage_id} col={col} currency={data.currency} editable={editable} />
          ))}
        </div>
        <DragOverlay>{dragging ? <Card deal={dragging} overlay /> : null}</DragOverlay>
      </DndContext>
      {losing && (
        <LostDialog
          deal={losing.deal}
          onClose={() => setLosing(null)}
          onConfirm={(lost) => {
            go(losing.deal, losing.stage, lost);
            setLosing(null);
          }}
        />
      )}
    </div>
  );
}

function Totals({ board }: { board: Board }) {
  const items = [
    ["Open", `${board.open_count} · ${formatMoney(board.open_minor, board.currency)}`],
    ["Weighted forecast", formatMoney(board.weighted_minor, board.currency)],
    ["Won", formatMoney(board.won_minor, board.currency)],
  ];
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-1 border-b px-4 py-2 text-xs">
      {items.map(([k, v]) => (
        <div key={k}>
          <span className="text-muted-foreground">{k}</span> <span className="font-semibold tabular-nums">{v}</span>
        </div>
      ))}
    </div>
  );
}

function Column({ col, currency, editable }: { col: Board["columns"][number]; currency: string; editable: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: col.stage_id, disabled: !editable });
  return (
    <section
      ref={setNodeRef}
      aria-label={col.name}
      className={cn("flex w-72 shrink-0 flex-col rounded-lg border bg-muted/30", isOver && "ring-2 ring-primary")}
    >
      <header className="space-y-0.5 border-b px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <span className="size-2 rounded-full" style={{ background: col.colour ?? "#94a3b8" }} />
          <span className="truncate">{col.name}</span>
          <span className="text-muted-foreground">{col.count}</span>
          {col.kind === "open" && <span className="ml-auto text-[11px] text-muted-foreground">{col.probability}%</span>}
        </div>
        <div className="text-xs text-muted-foreground tabular-nums">
          {formatMoney(col.amount_minor, currency)}
          {col.kind === "open" && col.amount_minor > 0 && ` · weighted ${formatMoney(col.weighted_minor, currency)}`}
        </div>
      </header>
      <div className="flex min-h-24 flex-1 flex-col gap-2 overflow-y-auto p-2">
        {col.deals.map((d) => (
          <DraggableCard key={d.id} deal={d} editable={editable} />
        ))}
        {col.count > col.deals.length && <p className="px-1 text-[11px] text-muted-foreground">+{col.count - col.deals.length} more — use the list view</p>}
      </div>
    </section>
  );
}

function DraggableCard({ deal, editable }: { deal: Deal; editable: boolean }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: deal.id, data: deal, disabled: !editable });
  return (
    <div ref={setNodeRef} {...listeners} {...attributes} className={cn("touch-manipulation", isDragging && "opacity-40")}>
      <Card deal={deal} />
    </div>
  );
}

function Card({ deal, overlay }: { deal: Deal; overlay?: boolean }) {
  const today = new Date().toISOString().slice(0, 10);
  const late = deal.status === "open" && deal.expected_close_on && deal.expected_close_on < today;
  return (
    <div className={cn("space-y-1 rounded-md border bg-background p-2.5 text-xs shadow-xs", overlay && "rotate-2 shadow-lg")}>
      <div className="flex items-start gap-2">
        <Link href={`/deals/${deal.id}`} className="min-w-0 flex-1 truncate font-medium hover:underline" onClick={(e) => overlay && e.preventDefault()}>
          {deal.name}
        </Link>
        <StatusBadge status={deal.status} />
      </div>
      {deal.lead_name !== deal.name && <div className="truncate text-muted-foreground">{deal.lead_name}</div>}
      <div className="flex items-center gap-2">
        <span className="font-semibold tabular-nums">{formatMoney(deal.amount_minor, deal.currency)}</span>
        {deal.expected_close_on && deal.status === "open" && (
          <span className={cn("ml-auto flex items-center gap-1 text-muted-foreground", late && "text-destructive")}>
            <CalendarDays className="size-3" />
            {deal.expected_close_on}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="truncate">{deal.owner_name ?? "Unassigned"}</span>
        <span>{deal.status === "lost" && deal.lost_reason ? deal.lost_reason : `moved ${relative(deal.stage_changed_at)}`}</span>
      </div>
    </div>
  );
}

// ---------- list ----------
type Sort = "created" | "amount" | "close" | "name" | "stage";

function ListView({ pipelineId, owner, q }: { pipelineId: string; owner?: string[]; q: string }) {
  const [status, setStatus] = useState<"" | "open" | "won" | "lost">("open");
  const [sort, setSort] = useState<Sort>("close");
  const [page, setPage] = useState(0);
  const size = 50;
  const deals = useDeals({
    pipeline_id: pipelineId,
    owner,
    q: q || undefined,
    status: status || undefined,
    sort,
    dir: sort === "amount" || sort === "created" ? "desc" : "asc",
    limit: size,
    offset: page * size,
  });
  const rows = deals.data?.items ?? [];
  const total = deals.data?.total ?? 0;
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 text-xs">
        <NativeSelect aria-label="Status" className="h-7 w-auto" value={status} onChange={(e) => (setStatus(e.target.value as typeof status), setPage(0))}>
          <option value="open">Open</option>
          <option value="won">Won</option>
          <option value="lost">Lost</option>
          <option value="">All</option>
        </NativeSelect>
        <NativeSelect aria-label="Sort" className="h-7 w-auto" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
          <option value="close">Expected close</option>
          <option value="amount">Value</option>
          <option value="stage">Stage</option>
          <option value="name">Name</option>
          <option value="created">Newest</option>
        </NativeSelect>
        <span className="text-muted-foreground">{total} deals</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="border-y bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">Deal</th>
              <th className="px-2 py-2 font-medium">Stage</th>
              <th className="px-2 py-2 text-right font-medium">Value</th>
              <th className="px-2 py-2 font-medium">Expected close</th>
              <th className="px-2 py-2 font-medium">Owner</th>
            </tr>
          </thead>
          <tbody>
            {deals.isLoading && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-muted-foreground">
                  Loading…
                </td>
              </tr>
            )}
            {!deals.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                  No deals here.
                </td>
              </tr>
            )}
            {rows.map((d) => (
              <tr key={d.id} className="border-b hover:bg-accent/50">
                <td className="px-4 py-2">
                  <Link href={`/deals/${d.id}`} className="font-medium hover:underline">
                    {d.name}
                  </Link>
                  {d.lead_name !== d.name && <div className="text-xs text-muted-foreground">{d.lead_name}</div>}
                </td>
                <td className="px-2 py-2">
                  <span className="flex items-center gap-1.5">
                    {d.stage_name} <StatusBadge status={d.status} />
                  </span>
                </td>
                <td className="px-2 py-2 text-right tabular-nums">{formatMoney(d.amount_minor, d.currency)}</td>
                <td className="px-2 py-2 text-muted-foreground">{d.expected_close_on ?? "—"}</td>
                <td className="px-2 py-2 text-muted-foreground">{d.owner_name ?? "Unassigned"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > size && (
        <div className="flex items-center gap-2 px-4 py-2 text-xs">
          <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <span>
            {page * size + 1}–{Math.min(total, (page + 1) * size)} of {total}
          </span>
          <Button size="sm" variant="outline" disabled={(page + 1) * size >= total} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
