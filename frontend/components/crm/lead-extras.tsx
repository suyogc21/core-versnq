"use client";

import { Building2, ShieldCheck, ShieldX, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import {
  type Lead,
  type LeadBrief,
  phone as formatPhone,
  relative,
  useDuplicates,
  useFields,
  useLead,
  useOrgPeople,
  useOrgSuggestions,
  useRefreshLead,
  useSources,
} from "@/lib/crm";
import { useUsers } from "@/lib/directory";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

// ---------- duplicates ----------
/** "Possible duplicate" banner at the top of a record, with Compare & merge. */
export function DuplicateBanner({ lead }: { lead: Lead }) {
  const { can } = useAuth();
  const dupes = useDuplicates(lead.id);
  const [other, setOther] = useState<LeadBrief | null>(null);
  const list = dupes.data ?? [];
  if (!list.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
      <span className="font-medium">Possible duplicate:</span>
      {list.map((d) => (
        <span key={d.id} className="inline-flex items-center gap-1.5">
          <Link href={`/leads/${d.id}`} className="underline">
            {d.display_name}
          </Link>
          <span className="text-muted-foreground">({d.primary_phone ? formatPhone(d.primary_phone) : d.primary_email}, added {relative(d.created_at)})</span>
          {can("leads.merge") && (
            <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={() => setOther(d)}>
              Compare & merge
            </Button>
          )}
        </span>
      ))}
      {other && <MergeDialog survivor={lead} otherId={other.id} onClose={() => setOther(null)} />}
    </div>
  );
}

const PLAIN: [string, string][] = [
  ["first_name", "First name"],
  ["last_name", "Last name"],
  ["org_name", "Company"],
  ["website", "Website"],
  ["city", "City"],
  ["region", "State / region"],
  ["country_code", "Country"],
  ["preferred_language", "Language"],
];

/** Side by side; where both have a value and they differ, choose which one to keep. */
function MergeDialog({ survivor, otherId, onClose }: { survivor: Lead; otherId: string; onClose: () => void }) {
  const other = useLead(otherId);
  const fields = useFields();
  const sources = useSources();
  const users = useUsers();
  const refresh = useRefreshLead();
  const router = useRouter();
  const [take, setTake] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const o = other.data;

  const sourceName = (id: string) => sources.data?.find((s) => s.id === id)?.name ?? "—";
  const userName = (id: string | null) => (id ? (users.data?.find((u) => u.id === id)?.name ?? "Someone") : "Unassigned");
  const show = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : Array.isArray(v) ? v.join(", ") : String(v));

  const rows: { key: string; label: string; mine: string; theirs: string }[] = [];
  if (o) {
    for (const [key, label] of PLAIN) {
      rows.push({ key, label, mine: show(survivor[key as keyof Lead]), theirs: show(o[key as keyof Lead]) });
    }
    rows.push({ key: "source_id", label: "Source", mine: sourceName(survivor.source_id), theirs: sourceName(o.source_id) });
    rows.push({ key: "owner", label: "Owner", mine: userName(survivor.owner_user_id), theirs: userName(o.owner_user_id) });
    for (const f of fields.data ?? []) {
      rows.push({
        key: `custom:${f.key}`,
        label: f.label,
        mine: show((survivor.custom_fields as Record<string, unknown>)[f.key]),
        theirs: show((o.custom_fields as Record<string, unknown>)[f.key]),
      });
    }
  }
  const differing = rows.filter((r) => r.mine !== r.theirs && r.theirs !== "—");

  async function merge() {
    if (!o) return;
    setSaving(true);
    try {
      const merged = unwrap(
        await api.POST("/api/v1/leads/merge", {
          body: {
            survivor_id: survivor.id,
            survivor_version: survivor.version,
            other_id: o.id,
            other_version: o.version,
            take_from_other: [...take],
          },
        }),
      );
      refresh(merged);
      toast.success(`Merged into ${merged.display_name}`);
      onClose();
      router.replace(`/leads/${merged.id}`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Merge two records</DialogTitle>
        </DialogHeader>
        {!o ? (
          <p className="text-muted-foreground">Loading…</p>
        ) : (
          <div className="space-y-3 text-sm">
            <p className="text-xs text-muted-foreground">
              <b>{survivor.display_name}</b> stays. Phones, emails, the timeline, tasks and consent from <b>{o.display_name}</b> move into it, and{" "}
              {o.display_name} is removed. Empty details are filled in automatically. An opt-out on either one is kept.
            </p>
            {differing.length === 0 ? (
              <p className="rounded-lg border p-3 text-xs">No conflicting details: nothing to choose.</p>
            ) : (
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50 text-start text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">Detail</th>
                      <th className="px-3 py-2 font-medium">Keep this ({survivor.display_name})</th>
                      <th className="px-3 py-2 font-medium">Or this ({o.display_name})</th>
                    </tr>
                  </thead>
                  <tbody>
                    {differing.map((r) => {
                      const theirs = take.has(r.key);
                      const pick = (useTheirs: boolean) => {
                        const next = new Set(take);
                        if (useTheirs) next.add(r.key);
                        else next.delete(r.key);
                        setTake(next);
                      };
                      return (
                        <tr key={r.key} className="border-t">
                          <td className="px-3 py-2 text-muted-foreground">{r.label}</td>
                          <td className="px-3 py-2">
                            <label className="flex items-center gap-2">
                              <input type="radio" name={r.key} checked={!theirs} onChange={() => pick(false)} className="accent-primary" />
                              {r.mine}
                            </label>
                          </td>
                          <td className="px-3 py-2">
                            <label className="flex items-center gap-2">
                              <input type="radio" name={r.key} checked={theirs} onChange={() => pick(true)} className="accent-primary" />
                              {r.theirs}
                            </label>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={merge} disabled={!o || saving}>
            Merge
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- consent ----------
const CONSENT_LABEL: Record<string, string> = { opted_in: "Opted in", opted_out: "Opted out" };

/** Email / WhatsApp / SMS consent with the rules: opting someone out is one click; recording a fresh
 * opt-in needs a note saying how they agreed. */
export function ConsentCard({ lead }: { lead: Lead }) {
  const { can } = useAuth();
  const refresh = useRefreshLead();
  const [optIn, setOptIn] = useState<"email" | "whatsapp" | "sms" | null>(null);
  const [note, setNote] = useState("");

  async function set(channel: "email" | "whatsapp" | "sms", status: "opted_in" | "opted_out", wording?: string) {
    try {
      const updated = unwrap(
        await api.POST("/api/v1/leads/{lead_id}/consents", {
          params: { path: { lead_id: lead.id } },
          body: { channel, status, wording: wording ?? null },
        }),
      );
      refresh(updated);
      toast.success(status === "opted_out" ? "Opted out — they won't be messaged on this channel" : "Opt-in recorded");
      setOptIn(null);
      setNote("");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-2 text-xs">
      {(["email", "whatsapp", "sms"] as const).map((channel) => {
        const state = { email: lead.email_consent, whatsapp: lead.whatsapp_consent, sms: lead.sms_consent }[channel];
        return (
          <div key={channel} className="flex items-center gap-2">
            {state === "opted_out" ? (
              <ShieldX className="size-3.5 text-destructive" />
            ) : (
              <ShieldCheck className={cn("size-3.5", state === "opted_in" ? "text-emerald-600" : "text-muted-foreground")} />
            )}
            <span className="w-16 text-muted-foreground">{{ email: "Email", whatsapp: "WhatsApp", sms: "SMS" }[channel]}</span>
            <span className={cn(state === "opted_out" && "font-medium text-destructive")}>{state ? CONSENT_LABEL[state] : "Not asked"}</span>
            {can("leads.edit") && (
              <span className="ms-auto">
                {state === "opted_out" ? (
                  <button className="text-primary hover:underline" onClick={() => setOptIn(channel)}>
                    Record opt-in
                  </button>
                ) : (
                  <span className="flex gap-2">
                    {state !== "opted_in" && (
                      <button className="text-primary hover:underline" onClick={() => setOptIn(channel)}>
                        Opt in
                      </button>
                    )}
                    <button className="text-muted-foreground hover:text-destructive hover:underline" onClick={() => set(channel, "opted_out")}>
                      Opt out
                    </button>
                  </span>
                )}
              </span>
            )}
          </div>
        );
      })}
      {optIn && (
        <form
          className="space-y-1.5 rounded-lg border p-2"
          onSubmit={(e) => {
            e.preventDefault();
            set(optIn, "opted_in", note.trim());
          }}
        >
          <label className="block text-[11px] text-muted-foreground" htmlFor="consent-note">
            How did they agree? (kept as proof)
          </label>
          <Input id="consent-note" autoFocus className="h-7" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Said yes on the call, 9 Nov" />
          <div className="flex gap-2">
            <Button size="sm" type="submit" disabled={!note.trim()}>
              Save
            </Button>
            <Button size="sm" type="button" variant="ghost" onClick={() => setOptIn(null)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

// ---------- organisations ----------
/** A person: their organisation (or suggestions / search to link one). An organisation: its people. */
export function OrganisationCard({ lead }: { lead: Lead }) {
  const { can } = useAuth();
  const label = useLabels();
  const isPerson = lead.kind === "person";
  const org = useLead(isPerson ? lead.organisation_id : null);
  const suggestions = useOrgSuggestions(lead.id, isPerson && !lead.organisation_id);
  const people = useOrgPeople(lead.id, !isPerson);
  const refresh = useRefreshLead();
  const [searching, setSearching] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Lead[]>([]);
  const editable = can("leads.edit");

  async function link(organisationId: string | null) {
    try {
      const updated = unwrap(
        await api.PUT("/api/v1/leads/{lead_id}/organisation", {
          params: { path: { lead_id: lead.id } },
          body: { organisation_id: organisationId },
        }),
      );
      refresh(updated);
      setSearching(false);
      toast.success(organisationId ? "Linked" : "Unlinked");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function dismiss(orgId: string) {
    await api.POST("/api/v1/leads/{lead_id}/organisation-suggestions/{org_id}/dismiss", {
      params: { path: { lead_id: lead.id, org_id: orgId } },
    });
    refresh();
  }
  async function search(term: string) {
    setQ(term);
    if (term.trim().length < 2) return setResults([]);
    const page = unwrap(await api.GET("/api/v1/leads", { params: { query: { q: term, limit: 20 } } }));
    setResults(page.items.filter((x) => x.kind === "organisation"));
  }

  if (!isPerson) {
    const list = people.data ?? [];
    return (
      <div className="space-y-1 text-xs">
        {list.length === 0 && <p className="text-muted-foreground">No people linked yet.</p>}
        {list.map((p) => (
          <Link key={p.id} href={`/leads/${p.id}`} className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-accent">
            <Users className="size-3.5 text-muted-foreground" />
            <span className="truncate">{p.display_name}</span>
            <span className="ms-auto truncate text-muted-foreground">{p.primary_email ?? (p.primary_phone && formatPhone(p.primary_phone))}</span>
          </Link>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-2 text-xs">
      {lead.organisation_id ? (
        <div className="flex items-center gap-2">
          <Building2 className="size-3.5 text-muted-foreground" />
          <Link href={`/leads/${lead.organisation_id}`} className="truncate font-medium hover:underline">
            {org.data?.display_name ?? "…"}
          </Link>
          {editable && (
            <button className="ms-auto text-muted-foreground hover:underline" onClick={() => link(null)}>
              Unlink
            </button>
          )}
        </div>
      ) : (
        <>
          {(suggestions.data ?? []).map((s) => (
            <div key={s.id} className="flex flex-wrap items-center gap-1.5 rounded-lg border border-dashed p-2">
              <Building2 className="size-3.5 text-muted-foreground" />
              <span>
                Looks like they&apos;re from <b>{s.display_name}</b>
                <span className="text-muted-foreground"> ({s.reason === "domain" ? "same email domain" : "same company name"})</span>
              </span>
              {editable && (
                <span className="ms-auto flex gap-2">
                  <button className="font-medium text-primary hover:underline" onClick={() => link(s.id)}>
                    Link
                  </button>
                  <button className="text-muted-foreground hover:underline" onClick={() => dismiss(s.id)}>
                    Not them
                  </button>
                </span>
              )}
            </div>
          ))}
          {!searching ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              Not linked to a company.
              {editable && (
                <button className="text-primary hover:underline" onClick={() => setSearching(true)}>
                  Link one
                </button>
              )}
            </div>
          ) : (
            <div className="space-y-1">
              <Input autoFocus className="h-7" placeholder={`Search ${label("lead", true).toLowerCase()} that are companies…`} value={q} onChange={(e) => search(e.target.value)} />
              {results.map((r) => (
                <button key={r.id} className="flex w-full items-center gap-2 rounded px-1 py-1 text-start hover:bg-accent" onClick={() => link(r.id)}>
                  <Building2 className="size-3.5 text-muted-foreground" />
                  {r.display_name}
                </button>
              ))}
              {q.trim().length >= 2 && results.length === 0 && <p className="text-muted-foreground">No company matches.</p>}
              <button className="text-muted-foreground hover:underline" onClick={() => setSearching(false)}>
                Cancel
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
