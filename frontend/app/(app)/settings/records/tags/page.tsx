"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type Tag, useRefreshTags, useTags } from "@/lib/organise";

const COLOURS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#8b5cf6", "#64748b"];

export default function TagsPage() {
  const tags = useTags();
  return (
    <>
      <PageHeader back={{ href: "/settings/records", label: "Records and fields" }} title="Tags" count={tags.data?.length} />
      <div className="mx-auto w-full max-w-3xl space-y-4 p-4 sm:p-8">
        <p className="text-sm text-muted-foreground">
          Anyone who works a record can add tags (and create new ones) right on the record or in bulk from a list. Here you tidy them up: rename, recolour, merge
          duplicates, or delete.
        </p>
        <div className="divide-y rounded-lg border">
          {tags.isLoading && <p className="p-4 text-muted-foreground">Loading…</p>}
          {tags.data?.length === 0 && <p className="p-4 text-sm text-muted-foreground">No tags yet.</p>}
          {(tags.data ?? []).map((t) => (
            <TagRow key={`${t.id}-${t.name}`} tag={t} all={tags.data ?? []} />
          ))}
        </div>
      </div>
    </>
  );
}

function TagRow({ tag, all }: { tag: Tag; all: Tag[] }) {
  const refresh = useRefreshTags();
  const [name, setName] = useState(tag.name);
  const [merging, setMerging] = useState(false);
  const [into, setInto] = useState("");
  async function run(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      refresh();
      toast.success(ok);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  const patch = (body: { name?: string; colour?: string }) =>
    run(async () => unwrap(await api.PATCH("/api/v1/tags/{tag_id}", { params: { path: { tag_id: tag.id } }, body })), "Saved");
  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
      <div className="flex gap-1">
        {COLOURS.map((c) => (
          <button
            key={c}
            aria-label={`Colour ${c}`}
            onClick={() => patch({ colour: c })}
            className="size-4 rounded-full border-2"
            style={{ background: c, borderColor: tag.colour === c ? "var(--foreground)" : "transparent" }}
          />
        ))}
      </div>
      <Input aria-label={`${tag.name} name`} className="h-7 w-44" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== tag.name && patch({ name: name.trim() })} />
      <span className="text-xs text-muted-foreground">used {tag.uses}×</span>
      <div className="ml-auto flex items-center gap-1.5">
        {merging ? (
          <>
            <NativeSelect aria-label="Merge into" className="h-7 w-auto" value={into} onChange={(e) => setInto(e.target.value)}>
              <option value="">Merge into…</option>
              {all
                .filter((t) => t.id !== tag.id)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
            </NativeSelect>
            <Button
              size="sm"
              disabled={!into}
              onClick={() => run(async () => unwrap(await api.POST("/api/v1/tags/{tag_id}/merge", { params: { path: { tag_id: tag.id }, query: { into } } })), "Merged")}
            >
              Merge
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMerging(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setMerging(true)} disabled={all.length < 2}>
            Merge…
          </Button>
        )}
        <button
          aria-label={`Delete ${tag.name}`}
          className="p-1 text-muted-foreground hover:text-destructive"
          onClick={() =>
            window.confirm(`Delete "${tag.name}"? It is removed from ${tag.uses} records.`) &&
            run(async () => unwrap(await api.DELETE("/api/v1/tags/{tag_id}", { params: { path: { tag_id: tag.id } } })), "Deleted")
          }
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
