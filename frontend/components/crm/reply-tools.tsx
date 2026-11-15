"use client";

import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type Sorting, useReplyCategories, useRefreshSorting, useSorting } from "@/lib/replies";

/** A reply's category (step O3): ACE's or a person's; anyone who can answer may change it. */
export function CategoryChip({ convId, messageId, sorting, onChanged }: { convId: string; messageId: string; sorting?: Sorting; onChanged?: () => void }) {
  const cats = useReplyCategories();
  const refresh = useRefreshSorting();
  const [editing, setEditing] = useState(false);
  const name = (key: string) => cats.data?.categories.find((c) => c.key === key)?.name ?? key;
  if (editing) {
    return (
      <NativeSelect
        aria-label="Category"
        className="h-7 w-auto text-xs"
        autoFocus
        defaultValue={sorting?.category ?? ""}
        onBlur={() => setEditing(false)}
        onChange={async (e) => {
          if (!e.target.value) return;
          try {
            const r = unwrap(
              await api.PUT("/api/v1/messages/{message_id}/classification", {
                params: { path: { message_id: messageId } },
                body: { category: e.target.value, reasons: [] },
              }),
            );
            toast.success(r.rules_run.length ? `Sorted. Done: ${r.rules_run.join(", ")}` : "Sorted");
            setEditing(false);
            await refresh(convId);
            onChanged?.();
          } catch (err) {
            toast.error((err as Error).message);
          }
        }}
      >
        <option value="">Choose a category…</option>
        {(cats.data?.categories ?? [])
          .filter((c) => c.active)
          .map((c) => (
            <option key={c.key} value={c.key}>
              {c.name}
            </option>
          ))}
      </NativeSelect>
    );
  }
  return (
    <button type="button" onClick={() => setEditing(true)} title={sorting?.summary ?? "Sort this reply"} data-category={sorting?.category ?? ""}>
      <Badge variant={sorting ? (sorting.category === "needs_human" ? "destructive" : "secondary") : "outline"}>
        {sorting ? `${name(sorting.category)}${sorting.by === "ace" && sorting.confidence != null ? ` · ACE ${sorting.confidence}%` : ""}` : "Not sorted"}
      </Badge>
    </button>
  );
}

/** The waiting draft above the reply box: approve and send, edit, or reject. */
export function DraftPanel({ convId, onSent }: { convId: string; onSent?: () => void }) {
  const sorting = useSorting(convId);
  const refresh = useRefreshSorting();
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const d = sorting.data?.draft;
  if (!d) return null;
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await fn();
      toast.success(done);
      setEditing(null);
      await refresh(convId);
      onSent?.();
    } catch (e) {
      toast.error((e as Error).message);
      await refresh(convId);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2 rounded-lg border border-primary/40 bg-primary/5 p-3 text-sm" data-testid="draft">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="secondary">Draft by ACE</Badge>
        {d.reasons.length > 0 && <span className="truncate">{d.reasons.join(" · ")}</span>}
      </div>
      {editing !== null ? (
        <Textarea aria-label="Edit the draft" rows={6} value={editing} onChange={(e) => setEditing(e.target.value)} />
      ) : (
        <div className="whitespace-pre-wrap">{d.body}</div>
      )}
      {d.error && <p className="text-xs text-destructive">Not sent: {d.error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={busy}
          onClick={() =>
            act(
              async () =>
                unwrap(
                  await api.POST("/api/v1/drafts/{draft_id}/approve", {
                    params: { path: { draft_id: d.id } },
                    body: { body: editing ?? undefined },
                  }),
                ),
              "Sent",
            )
          }
        >
          {editing !== null ? "Send edited" : "Approve and send"}
        </Button>
        {editing === null && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(d.body)}>
            Edit
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => {
            const reason = prompt("Why reject it? (optional)") ?? undefined;
            act(async () => unwrap(await api.POST("/api/v1/drafts/{draft_id}/reject", { params: { path: { draft_id: d.id } }, body: { reason } })), "Rejected");
          }}
        >
          Reject
        </Button>
      </div>
    </div>
  );
}
