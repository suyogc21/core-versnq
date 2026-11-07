"use client";

import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { Avatar, StagePill } from "@/components/crm/bits";
import { AddLeadDialog } from "@/components/crm/lead-form";
import { LeadPanel } from "@/components/crm/lead-panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { fieldValue, isOverdue, type LeadQuery, phone, relative, useFields, useLeads, useSources, useStages, when } from "@/lib/crm";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

type View = { key: string; label: string; query: LeadQuery; managersOnly?: boolean };

const PAGE = 50;

export default function LeadsPage() {
  const { me, can } = useAuth();
  const label = useLabels();
  const router = useRouter();
  const stages = useStages();
  const sources = useSources();
  const fields = useFields();
  const plural = label("lead", true);
  const views: View[] = [
    { key: "mine", label: `My ${plural.toLowerCase()}`, query: { owner: "me", status: "open" } },
    { key: "today", label: "Due today", query: { follow_up: "today", sort: "follow_up" } },
    { key: "overdue", label: "Overdue", query: { follow_up: "overdue", sort: "follow_up" } },
    { key: "none", label: "No follow-up", query: { follow_up: "none" } },
    { key: "unassigned", label: "Unassigned", query: { owner: "unassigned", status: "open" }, managersOnly: true },
    { key: "all", label: "All", query: {} },
  ];
  const isManager = me?.role.scope !== "own";
  const [view, setView] = useState(isManager ? "all" : "mine");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [stageId, setStageId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  const current = views.find((v) => v.key === view) ?? views[0];
  const query: LeadQuery = {
    ...current.query,
    q: q || undefined,
    stage_id: stageId || undefined,
    source_id: sourceId || undefined,
    limit,
  };
  const leads = useLeads(query);
  const stageById = new Map((stages.data ?? []).map((s) => [s.id, s]));
  const sourceById = new Map((sources.data ?? []).map((s) => [s.id, s.name]));
  const firstField = (fields.data ?? []).find((f) => f.type === "select");

  function open(id: string) {
    // Wide screens: side panel. Phones: the lead's own page.
    if (window.matchMedia("(min-width: 1280px)").matches) setSelected(id);
    else router.push(`/leads/${id}`);
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          title={plural}
          count={leads.data?.total}
          actions={
            <>
              <Input
                placeholder="Search name, phone, email…"
                className="h-7 w-full sm:w-64"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {can("leads.create") && (
                <Button size="sm" onClick={() => setAdding(true)}>
                  <Plus /> Add {label("lead").toLowerCase()}
                </Button>
              )}
            </>
          }
        />
        <div className="flex flex-wrap items-center gap-1 border-b px-4 py-2">
          {views
            .filter((v) => !v.managersOnly || isManager)
            .map((v) => (
              <button
                key={v.key}
                onClick={() => {
                  setView(v.key);
                  setLimit(PAGE);
                }}
                className={cn("rounded-md px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent", view === v.key && "bg-accent font-medium text-foreground")}
              >
                {v.label}
              </button>
            ))}
          <div className="ml-auto flex gap-1.5">
            <NativeSelect aria-label="Stage" className="h-7 w-auto text-xs" value={stageId} onChange={(e) => setStageId(e.target.value)}>
              <option value="">Any stage</option>
              {(stages.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect aria-label="Source" className="h-7 w-auto text-xs" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
              <option value="">Any source</option>
              {(sources.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {leads.isLoading ? (
            <p className="p-4 text-muted-foreground">Loading…</p>
          ) : leads.isError ? (
            <p className="p-4 text-destructive">{leads.error.message}</p>
          ) : (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-background text-left text-muted-foreground">
                <tr className="border-b">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-2 py-2 font-medium">Stage</th>
                  <th className="px-2 py-2 font-medium">Next follow-up</th>
                  <th className="hidden px-2 py-2 font-medium md:table-cell">Source</th>
                  {firstField && <th className="hidden px-2 py-2 font-medium lg:table-cell">{firstField.label}</th>}
                  <th className="hidden px-2 py-2 font-medium sm:table-cell">Owner</th>
                  <th className="hidden px-2 py-2 font-medium lg:table-cell">Last activity</th>
                </tr>
              </thead>
              <tbody>
                {leads.data?.items.map((l) => {
                  const late = l.is_open && isOverdue(l.next_follow_up_at);
                  const missing = l.is_open && !l.next_follow_up_at;
                  return (
                    <tr
                      key={l.id}
                      onClick={() => open(l.id)}
                      className={cn("cursor-pointer border-b hover:bg-accent/50", selected === l.id && "bg-accent")}
                    >
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          <Avatar name={l.display_name} colour={stageById.get(l.stage_id)?.colour} />
                          <div className="min-w-0">
                            <div className="truncate font-medium">{l.display_name}</div>
                            <div className="truncate text-muted-foreground">{l.primary_phone ? phone(l.primary_phone) : l.primary_email}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <StagePill stage={stageById.get(l.stage_id)} />
                      </td>
                      <td className={cn("px-2 py-2 whitespace-nowrap", (late || missing) && "text-destructive")}>
                        {missing ? "Not set" : l.is_open ? when(l.next_follow_up_at) : "—"}
                      </td>
                      <td className="hidden px-2 py-2 text-muted-foreground md:table-cell">{sourceById.get(l.source_id)}</td>
                      {firstField && (
                        <td className="hidden px-2 py-2 text-muted-foreground lg:table-cell">
                          {fieldValue(firstField, (l.custom_fields as Record<string, unknown>)[firstField.key])}
                        </td>
                      )}
                      <td className="hidden px-2 py-2 sm:table-cell">
                        {l.owner_name ? <Avatar name={l.owner_name} colour="#475569" /> : <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="hidden px-2 py-2 text-muted-foreground lg:table-cell">
                        {l.last_disposition ? `${l.last_disposition} · ` : ""}
                        {relative(l.last_activity_at ?? l.created_at)}
                      </td>
                    </tr>
                  );
                })}
                {leads.data?.items.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-muted-foreground">
                      No {plural.toLowerCase()} here.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
          {leads.data && leads.data.items.length < leads.data.total && (
            <div className="flex justify-center p-4">
              <Button variant="outline" size="sm" onClick={() => setLimit(limit + PAGE)}>
                Show more ({leads.data.total - leads.data.items.length} left)
              </Button>
            </div>
          )}
        </div>
      </div>
      {selected && (
        <aside className="hidden w-[440px] shrink-0 overflow-auto border-l xl:block">
          <LeadPanel key={selected} leadId={selected} onClose={() => setSelected(null)} />
        </aside>
      )}
      {adding && (
        <AddLeadDialog
          onClose={() => setAdding(false)}
          onCreated={(lead) => {
            setAdding(false);
            open(lead.id);
          }}
        />
      )}
    </div>
  );
}
