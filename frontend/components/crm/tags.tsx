"use client";

import { Check, Plus, Tag as TagIcon, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Popover } from "@/components/data-table/popover";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { BAND_LABEL, BAND_STYLE, type TagRef, useLeadScore, useRefreshTags, useTags } from "@/lib/organise";
import { cn } from "@/lib/utils";

export function TagChip({ tag, onRemove }: { tag: TagRef; onRemove?: () => void }) {
  return (
    <span
      className="inline-flex max-w-40 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] leading-4"
      style={{ borderColor: `${tag.colour ?? "#94a3b8"}66`, background: `${tag.colour ?? "#94a3b8"}1a` }}
    >
      <span className="size-1.5 shrink-0 rounded-full" style={{ background: tag.colour ?? "#94a3b8" }} />
      <span className="truncate">{tag.name}</span>
      {onRemove && (
        <button aria-label={`Remove tag ${tag.name}`} className="opacity-60 hover:opacity-100" onClick={onRemove}>
          <X className="size-3" />
        </button>
      )}
    </span>
  );
}

export function TagList({ tags, max = 3 }: { tags: TagRef[]; max?: number }) {
  if (!tags.length) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {tags.slice(0, max).map((t) => (
        <TagChip key={t.id} tag={t} />
      ))}
      {tags.length > max && <span className="text-[11px] text-muted-foreground">+{tags.length - max}</span>}
    </span>
  );
}

/** Pick tags from the list or type a new one. Used on records and for bulk tagging. */
export function TagPicker({ chosen, onPick, onCreate }: { chosen: string[]; onPick: (id: string) => void; onCreate: (name: string) => void }) {
  const tags = useTags();
  const [q, setQ] = useState("");
  const list = (tags.data ?? []).filter((t) => t.name.toLowerCase().includes(q.trim().toLowerCase()));
  const exact = (tags.data ?? []).some((t) => t.name.toLowerCase() === q.trim().toLowerCase());
  return (
    <div className="w-56 space-y-1 p-1">
      <Input autoFocus aria-label="Find or add a tag" placeholder="Find or add a tag…" className="h-7" value={q} onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && q.trim() && !exact) {
            e.preventDefault();
            onCreate(q.trim());
            setQ("");
          }
        }}
      />
      <div className="max-h-56 overflow-auto">
        {list.map((t) => (
          <button key={t.id} type="button" className="flex w-full items-center gap-2 rounded px-2 py-1 text-start text-xs hover:bg-accent" onClick={() => onPick(t.id)}>
            <span className="size-2 rounded-full" style={{ background: t.colour ?? "#94a3b8" }} />
            <span className="flex-1 truncate">{t.name}</span>
            {chosen.includes(t.id) && <Check className="size-3.5" />}
          </button>
        ))}
        {q.trim() && !exact && (
          <button type="button" className="flex w-full items-center gap-2 rounded px-2 py-1 text-start text-xs text-primary hover:bg-accent" onClick={() => (onCreate(q.trim()), setQ(""))}>
            <Plus className="size-3.5" /> Create “{q.trim()}”
          </button>
        )}
        {!q && list.length === 0 && <p className="px-2 py-1 text-xs text-muted-foreground">No tags yet. Type to add one.</p>}
      </div>
    </div>
  );
}

/** The tags on one lead or deal, editable in place. */
export function TagEditor({ kind, id, tags, editable }: { kind: "lead" | "deal"; id: string; tags: TagRef[]; editable: boolean }) {
  const refresh = useRefreshTags();
  async function save(tagIds: string[], create: string[] = []) {
    try {
      const body = { tag_ids: tagIds, new: create };
      if (kind === "lead") unwrap(await api.PUT("/api/v1/leads/{lead_id}/tags", { params: { path: { lead_id: id } }, body }));
      else unwrap(await api.PUT("/api/v1/deals/{deal_id}/tags", { params: { path: { deal_id: id } }, body }));
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  const ids = tags.map((t) => t.id);
  return (
    <span className="flex flex-wrap items-center gap-1">
      {tags.map((t) => (
        <TagChip key={t.id} tag={t} onRemove={editable ? () => save(ids.filter((x) => x !== t.id)) : undefined} />
      ))}
      {editable && (
        <Popover
          trigger={({ toggle }) => (
            <button aria-label="Add tag" onClick={toggle} className="inline-flex items-center gap-1 rounded-full border border-dashed px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground">
              <TagIcon className="size-3" /> Tag
            </button>
          )}
        >
          <TagPicker chosen={ids} onPick={(tid) => save(ids.includes(tid) ? ids.filter((x) => x !== tid) : [...ids, tid])} onCreate={(name) => save(ids, [name])} />
        </Popover>
      )}
    </span>
  );
}

export function BandPill({ band, score }: { band: string | null | undefined; score?: number }) {
  if (!band) return null;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", BAND_STYLE[band])}>
      {BAND_LABEL[band]}
      {score !== undefined && <span className="font-normal tabular-nums">{score}</span>}
    </span>
  );
}

/** The lead's score; click for how it was worked out. */
export function ScoreBadge({ leadId, band, score }: { leadId: string; band: string | null | undefined; score: number }) {
  const [open, setOpen] = useState(false);
  const detail = useLeadScore(leadId, open);
  return (
    <Popover
      align="end"
      trigger={({ toggle }) => (
        <button aria-label="Score breakdown" onClick={() => (setOpen(true), toggle())}>
          <BandPill band={band} score={score} />
        </button>
      )}
    >
      <div className="w-64 space-y-1 p-2 text-xs">
        <div className="flex justify-between font-medium">
          <span>Score</span>
          <span className="tabular-nums">{score}</span>
        </div>
        {detail.isLoading && <p className="text-muted-foreground">Loading…</p>}
        {detail.data && (
          <>
            <div className="text-muted-foreground">
              Fit {detail.data.fit} · Engagement {detail.data.engagement}
            </div>
            {detail.data.lines.length === 0 && <p className="text-muted-foreground">No scoring rules match yet.</p>}
            {detail.data.lines.map((l, i) => (
              <div key={i} className="flex justify-between gap-2 border-t pt-1">
                <span className="truncate">{l.label}</span>
                <span className={cn("tabular-nums", l.points < 0 && "text-destructive")}>{l.points > 0 ? `+${l.points}` : l.points}</span>
              </div>
            ))}
          </>
        )}
      </div>
    </Popover>
  );
}
