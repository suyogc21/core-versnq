"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { ACTION_LABEL, type ReplyCategory, type ReplyRule, useReplyCategories } from "@/lib/replies";

type Editable = Omit<ReplyCategory, "position" | "needs_human"> & { needs_human?: boolean };

/** Settings → Reply categories (step O3): the company's own list and what happens for each. */
export default function ReplyCategoriesPage() {
  const cats = useReplyCategories();
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader back={{ href: "/settings", label: "Settings" }} title="Reply categories" />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-3xl p-4 sm:p-6">
          <p className="mb-4 text-sm text-muted-foreground">
            Every reply (from campaigns and from leads) is sorted into one of these, by ACE or by a person. Then its rules run, once per reply. A
            person&apos;s choice always wins over ACE&apos;s. &quot;Needs a human&quot; is always there: ACE uses it when it isn&apos;t sure.
          </p>
          {cats.data ? <Editor initial={cats.data.categories} /> : <p className="text-sm text-muted-foreground">Loading…</p>}
        </div>
      </div>
    </div>
  );
}

function keyFrom(name: string) {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^([0-9])/, "c_$1")
      .slice(0, 40) || "category"
  );
}

function Editor({ initial }: { initial: ReplyCategory[] }) {
  const cats = useReplyCategories();
  const [list, setList] = useState<Editable[]>(initial);
  const [busy, setBusy] = useState(false);
  const set = (i: number, c: Editable) => setList(list.map((x, n) => (n === i ? c : x)));
  return (
    <div className="space-y-3">
      {list.map((c, i) => (
        <div key={c.key} className="space-y-2 surface p-3" data-category-row={c.key}>
          <div className="flex flex-wrap items-center gap-2">
            <Input aria-label={`Name of ${c.key}`} className="h-8 max-w-60 font-medium" value={c.name} onChange={(e) => set(i, { ...c, name: e.target.value })} />
            {!c.needs_human && (
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Switch checked={c.active} onCheckedChange={(on) => set(i, { ...c, active: on })} aria-label={`${c.name} on`} /> On
              </label>
            )}
            {c.needs_human ? (
              <span className="text-xs text-muted-foreground">Always on</span>
            ) : (
              <Button size="sm" variant="ghost" className="ml-auto" aria-label={`Remove ${c.name}`} onClick={() => setList(list.filter((_, n) => n !== i))}>
                <Trash2 />
              </Button>
            )}
          </div>
          <Input
            aria-label={`What ${c.name} means`}
            placeholder="What this means (ACE reads it)"
            className="h-8"
            value={c.description ?? ""}
            onChange={(e) => set(i, { ...c, description: e.target.value })}
          />
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Then:</div>
            {(Object.keys(ACTION_LABEL) as ReplyRule["action"][])
              .filter((a) => !(c.needs_human && a === "convert"))
              .map((a) => {
                const rule = c.rules.find((r) => r.action === a);
                return (
                  <div key={a} className="flex flex-wrap items-center gap-2 text-sm">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={!!rule}
                        onChange={(e) =>
                          set(i, { ...c, rules: e.target.checked ? [...c.rules, { action: a, instructions: null }] : c.rules.filter((r) => r.action !== a) })
                        }
                      />
                      {ACTION_LABEL[a]}
                    </label>
                    {rule && a === "draft" && (
                      <Input
                        aria-label={`Instructions for ${c.name} drafts`}
                        placeholder="Instructions for ACE (optional), e.g. offer a call next week"
                        className="h-7 min-w-60 flex-1"
                        value={rule.instructions ?? ""}
                        onChange={(e) => set(i, { ...c, rules: c.rules.map((r) => (r.action === "draft" ? { ...r, instructions: e.target.value || null } : r)) })}
                      />
                    )}
                  </div>
                );
              })}
          </div>
        </div>
      ))}
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            const name = prompt("Name of the new category");
            if (!name?.trim()) return;
            const key = keyFrom(name);
            if (list.some((c) => c.key === key)) return toast.error("That category already exists");
            const at = Math.max(0, list.findIndex((c) => c.needs_human));
            const next = [...list];
            next.splice(at, 0, { key, name: name.trim(), description: null, active: true, auto_send_allowed: false, rules: [] });
            setList(next);
          }}
        >
          <Plus /> Add a category
        </Button>
        <Button
          size="sm"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const r = unwrap(
                await api.PUT("/api/v1/reply-categories", {
                  body: {
                    categories: list.map((c) => ({
                      key: c.key,
                      name: c.name,
                      description: c.description || null,
                      active: c.active,
                      auto_send_allowed: c.auto_send_allowed,
                      rules: c.rules,
                    })),
                  },
                }),
              );
              setList(r.categories);
              await cats.refetch();
              toast.success("Saved");
            } catch (e) {
              toast.error((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Save
        </Button>
      </div>
    </div>
  );
}
