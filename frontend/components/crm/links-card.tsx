"use client";

import { Link2, Plus, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type LinkItem, type LinkType, type RecordType, useLinks, useLinkTypes, useRecordTypes, useRefreshRecords } from "@/lib/records";
import { useLabels } from "@/lib/settings";

/** This end: a lead (typeId null) or a record of a type. */
export type LinkEnd = { kind: "lead" | "record"; id: string; typeId: string | null };

type Option = { linkType: LinkType; outward: boolean; label: string; otherTypeId: string | null };

/** Everything linked to this lead or record, grouped by how it is linked, with add/remove. */
export function LinksCard({ end, editable }: { end: LinkEnd; editable: boolean }) {
  const label = useLabels();
  const links = useLinks(end.kind === "lead" ? { lead_id: end.id } : { record_id: end.id });
  const linkTypes = useLinkTypes();
  const types = useRecordTypes();
  const [adding, setAdding] = useState(false);
  const typeById = new Map((types.data ?? []).map((t) => [t.id, t]));
  const kindName = (typeId: string | null) => (typeId ? (typeById.get(typeId)?.singular ?? "record") : label("lead"));

  // Ways this end can be linked: as the "from" side and/or the "to" side of a link type.
  const options: Option[] = [];
  for (const lt of linkTypes.data ?? []) {
    if (!lt.is_active) continue;
    const mine = end.kind === "lead" ? null : end.typeId;
    const otherVisible = (id: string | null) => id === null || typeById.has(id);
    if (lt.from_type_id === mine && otherVisible(lt.to_type_id)) {
      options.push({ linkType: lt, outward: true, label: `${lt.label} (${kindName(lt.to_type_id)})`, otherTypeId: lt.to_type_id });
    }
    if (lt.to_type_id === mine && otherVisible(lt.from_type_id) && !(lt.from_type_id === mine && lt.label === lt.inverse_label)) {
      options.push({ linkType: lt, outward: false, label: `${lt.inverse_label} (${kindName(lt.from_type_id)})`, otherTypeId: lt.from_type_id });
    }
  }

  const groups = new Map<string, LinkItem[]>();
  for (const l of links.data ?? []) groups.set(l.label, [...(groups.get(l.label) ?? []), l]);
  const refresh = useRefreshRecords();

  async function remove(link: LinkItem) {
    try {
      unwrap(await api.DELETE("/api/v1/links/{link_id}", { params: { path: { link_id: link.id } } }));
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-3 text-xs">
      {links.isLoading && <p className="text-muted-foreground">Loading…</p>}
      {links.data && links.data.length === 0 && !adding && <p className="text-muted-foreground">Nothing linked yet.</p>}
      {[...groups.entries()].map(([name, items]) => (
        <div key={name} className="space-y-1">
          <div className="text-[11px] text-muted-foreground">
            {name} · {items.length}
          </div>
          {items.map((l) => (
            <div key={l.id} className="group flex items-center gap-2 rounded-md border px-2 py-1.5">
              <Link2 className="size-3.5 shrink-0 text-muted-foreground" />
              <Link href={l.other.kind === "lead" ? `/leads/${l.other.id}` : `/r/${l.other.type_key}/${l.other.id}`} className="min-w-0 flex-1 truncate font-medium hover:underline">
                {l.other.name}
              </Link>
              {editable && (
                <button aria-label={`Remove link to ${l.other.name}`} className="text-muted-foreground opacity-60 hover:text-destructive hover:opacity-100" onClick={() => remove(l)}>
                  <X className="size-3.5" />
                </button>
              )}
            </div>
          ))}
        </div>
      ))}
      {editable && options.length > 0 && !adding && (
        <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
          <Plus /> Link
        </Button>
      )}
      {adding && <AddLink end={end} options={options} typeById={typeById} onDone={() => setAdding(false)} />}
    </div>
  );
}

function AddLink({ end, options, typeById, onDone }: { end: LinkEnd; options: Option[]; typeById: Map<string, RecordType>; onDone: () => void }) {
  const [choice, setChoice] = useState(0);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ id: string; name: string; hint?: string }[]>([]);
  const refresh = useRefreshRecords();
  const opt = options[choice];

  async function search(term: string) {
    setQ(term);
    if (term.trim().length < 2) return setResults([]);
    if (opt.otherTypeId === null) {
      const page = unwrap(await api.GET("/api/v1/leads", { params: { query: { q: term, limit: 15 } } }));
      setResults(page.items.filter((x) => !(end.kind === "lead" && x.id === end.id)).map((x) => ({ id: x.id, name: x.display_name, hint: x.primary_phone ?? x.primary_email ?? undefined })));
    } else {
      const key = typeById.get(opt.otherTypeId)?.key;
      if (!key) return setResults([]);
      const page = unwrap(await api.GET("/api/v1/records", { params: { query: { type: key, q: term, limit: 15 } } }));
      setResults(page.items.filter((x) => x.id !== end.id).map((x) => ({ id: x.id, name: x.name })));
    }
  }

  async function link(otherId: string) {
    const here = end.kind === "lead" ? { lead_id: end.id } : { record_id: end.id };
    const there = opt.otherTypeId === null ? { lead_id: otherId } : { record_id: otherId };
    const [from, to] = opt.outward ? [here, there] : [there, here];
    try {
      unwrap(
        await api.POST("/api/v1/links", {
          body: {
            link_type_id: opt.linkType.id,
            from_lead_id: from.lead_id ?? null,
            from_record_id: from.record_id ?? null,
            to_lead_id: to.lead_id ?? null,
            to_record_id: to.record_id ?? null,
          },
        }),
      );
      refresh();
      toast.success("Linked");
      onDone();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-1.5 rounded-lg border p-2">
      <NativeSelect aria-label="How are they linked?" value={choice} onChange={(e) => (setChoice(Number(e.target.value)), setResults([]), setQ(""))}>
        {options.map((o, i) => (
          <option key={`${o.linkType.id}-${o.outward}`} value={i}>
            {o.label}
          </option>
        ))}
      </NativeSelect>
      <Input autoFocus aria-label="Search to link" className="h-7" placeholder="Search by name…" value={q} onChange={(e) => search(e.target.value)} />
      {results.map((r) => (
        <button key={r.id} className="flex w-full items-center gap-2 rounded px-1 py-1 text-left hover:bg-accent" onClick={() => link(r.id)}>
          <span className="truncate">{r.name}</span>
          {r.hint && <span className="ml-auto truncate text-muted-foreground">{r.hint}</span>}
        </button>
      ))}
      {q.trim().length >= 2 && results.length === 0 && <p className="text-muted-foreground">No match.</p>}
      <button className="text-muted-foreground hover:underline" onClick={onDone}>
        Cancel
      </button>
    </div>
  );
}
