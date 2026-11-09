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
import { LinkTypeDialog } from "@/components/crm/record-settings";
import { useAuth } from "@/lib/auth";
import { type LinkItem, type LinkType, type RecordType, useAllRecordTypes, useLinks, useLinkTypes, useRecordTypes, useRefreshRecords } from "@/lib/records";
import { useLabels } from "@/lib/settings";

/** This end: a lead, a deal (typeId null) or a record of a type. */
export type LinkEnd = { kind: "lead" | "deal" | "record"; id: string; typeId: string | null };
type Kind = LinkEnd["kind"];

type Option = { linkType: LinkType; outward: boolean; label: string; otherKind: Kind; otherTypeId: string | null };

/** Everything linked to this lead or record, grouped by how it is linked, with add/remove. */
export function LinksCard({ end, editable }: { end: LinkEnd; editable: boolean }) {
  const label = useLabels();
  const links = useLinks({ [`${end.kind}_id`]: end.id });
  const linkTypes = useLinkTypes();
  const types = useRecordTypes();
  const [adding, setAdding] = useState(false);
  const [newKind, setNewKind] = useState(false);
  const { can } = useAuth();
  const allTypes = useAllRecordTypes(can("crm.configure"));
  const typeById = new Map((types.data ?? []).map((t) => [t.id, t]));
  const kindName = (kind: Kind, typeId: string | null) =>
    kind === "record" ? (typeById.get(typeId ?? "")?.singular ?? "record") : label(kind);

  // Ways this end can be linked: as the "from" side and/or the "to" side of a link type.
  const options: Option[] = [];
  const isMe = (kind: string, typeId: string | null) => kind === end.kind && (kind !== "record" || typeId === end.typeId);
  const otherVisible = (kind: string, id: string | null) => kind !== "record" || (id !== null && typeById.has(id));
  for (const lt of linkTypes.data ?? []) {
    if (!lt.is_active) continue;
    const [fk, tk] = [lt.from_kind as Kind, lt.to_kind as Kind];
    if (isMe(fk, lt.from_type_id) && otherVisible(tk, lt.to_type_id)) {
      options.push({ linkType: lt, outward: true, label: `${lt.label} (${kindName(tk, lt.to_type_id)})`, otherKind: tk, otherTypeId: lt.to_type_id });
    }
    const symmetric = fk === tk && lt.from_type_id === lt.to_type_id && lt.label === lt.inverse_label;
    if (isMe(tk, lt.to_type_id) && otherVisible(fk, lt.from_type_id) && !symmetric) {
      options.push({ linkType: lt, outward: false, label: `${lt.inverse_label} (${kindName(fk, lt.from_type_id)})`, otherKind: fk, otherTypeId: lt.from_type_id });
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
              <Link href={l.other.kind === "lead" ? `/leads/${l.other.id}` : l.other.kind === "deal" ? `/deals/${l.other.id}` : `/r/${l.other.type_key}/${l.other.id}`} className="min-w-0 flex-1 truncate font-medium hover:underline">
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
      <div className="flex flex-wrap items-center gap-2">
        {editable && options.length > 0 && !adding && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            <Plus /> Link
          </Button>
        )}
        {can("crm.configure") && !adding && (
          <button className="text-primary hover:underline" onClick={() => setNewKind(true)}>
            + New kind of link
          </button>
        )}
      </div>
      {newKind && <LinkTypeDialog types={allTypes.data ?? []} onClose={() => setNewKind(false)} />}
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
    if (opt.otherKind === "lead") {
      const page = unwrap(await api.GET("/api/v1/leads", { params: { query: { q: term, limit: 15 } } }));
      setResults(page.items.filter((x) => !(end.kind === "lead" && x.id === end.id)).map((x) => ({ id: x.id, name: x.display_name, hint: x.primary_phone ?? x.primary_email ?? undefined })));
    } else if (opt.otherKind === "deal") {
      const page = unwrap(await api.GET("/api/v1/deals", { params: { query: { q: term, limit: 15 } } }));
      setResults(page.items.filter((x) => x.id !== end.id).map((x) => ({ id: x.id, name: x.name, hint: x.lead_name ?? undefined })));
    } else {
      const key = typeById.get(opt.otherTypeId ?? "")?.key;
      if (!key) return setResults([]);
      const page = unwrap(await api.GET("/api/v1/records", { params: { query: { type: key, q: term, limit: 15 } } }));
      setResults(page.items.filter((x) => x.id !== end.id).map((x) => ({ id: x.id, name: x.name })));
    }
  }

  async function link(otherId: string) {
    const here: Record<string, string> = { [`${end.kind}_id`]: end.id };
    const there: Record<string, string> = { [`${opt.otherKind}_id`]: otherId };
    const [from, to] = opt.outward ? [here, there] : [there, here];
    try {
      unwrap(
        await api.POST("/api/v1/links", {
          body: {
            link_type_id: opt.linkType.id,
            from_lead_id: from.lead_id ?? null,
            from_record_id: from.record_id ?? null,
            from_deal_id: from.deal_id ?? null,
            to_lead_id: to.lead_id ?? null,
            to_record_id: to.record_id ?? null,
            to_deal_id: to.deal_id ?? null,
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
