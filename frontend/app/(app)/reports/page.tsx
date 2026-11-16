"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { ReportChart } from "@/components/app/report-chart";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useAuth } from "@/lib/auth";
import { formatMoney } from "@/lib/deals";
import { useRoles } from "@/lib/directory";
import { cn } from "@/lib/utils";

type Definition = components["schemas"]["ReportDefinition"];
type Result = components["schemas"]["ReportResult"];
type Saved = components["schemas"]["SavedReportOut"];

const START: Definition = { source: "leads", group_by: [], measure: { op: "count" }, filters: {}, display: "table" };
const DISPLAYS = [
  ["table", "Table"],
  ["bar", "Bars"],
  ["line", "Line"],
  ["pie", "Pie"],
] as const;

/** Reports (finishing plan, batch 5c): build a report on leads, deals, tasks, calls, activities,
 * invoices or payments; it counts only what you can see. Save it, share it with roles, download
 * the table as CSV. */
export default function ReportsPage() {
  const [def, setDef] = useState<Definition>(START);
  const [savedId, setSavedId] = useState<string | null>(null);
  const saved = useQuery({ queryKey: ["saved-reports"], queryFn: async () => unwrap(await api.GET("/api/v1/reports/saved")) });
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Reports" />
      <div className="grid min-h-0 flex-1 gap-4 overflow-auto p-4 sm:px-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="space-y-2 text-sm">
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => {
              setDef(START);
              setSavedId(null);
            }}
          >
            New report
          </Button>
          <h2 className="pt-2 text-xs font-semibold text-muted-foreground uppercase">Saved</h2>
          {(saved.data ?? []).length === 0 && <p className="text-xs text-muted-foreground">Nothing saved yet.</p>}
          <ul className="space-y-0.5">
            {(saved.data ?? []).map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className={cn("w-full truncate rounded px-2 py-1 text-left hover:bg-accent", savedId === r.id && "bg-accent font-medium")}
                  onClick={() => {
                    setDef(r.definition);
                    setSavedId(r.id);
                  }}
                >
                  {r.name}
                  {!r.yours && <span className="ml-1 text-xs text-muted-foreground">(shared)</span>}
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <Builder key={savedId ?? "new"} def={def} onChange={setDef} saved={(saved.data ?? []).find((r) => r.id === savedId) ?? null} onSaved={setSavedId} />
      </div>
    </div>
  );
}

function Builder({ def, onChange, saved, onSaved }: { def: Definition; onChange: (d: Definition) => void; saved: Saved | null; onSaved: (id: string | null) => void }) {
  const catalogue = useQuery({ queryKey: ["report-catalogue"], queryFn: async () => unwrap(await api.GET("/api/v1/reports/catalogue")) });
  const source = catalogue.data?.find((s) => s.key === def.source);
  const result = useQuery({
    queryKey: ["report-run", def],
    queryFn: async () => unwrap(await api.POST("/api/v1/reports/run", { body: def })),
    enabled: !!source,
    retry: false,
  });
  const set = (patch: Partial<Definition>) => onChange({ ...def, ...patch });
  const groups = def.group_by ?? [];
  const measure = def.measure ?? { op: "count" };

  async function download() {
    const r = await api.POST("/api/v1/reports/run.csv", { body: def, parseAs: "blob" });
    if (!r.data) return toast.error("The report could not be downloaded");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(r.data as Blob);
    a.download = "report.csv";
    a.click();
  }

  if (!catalogue.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return (
    <div className="min-w-0 space-y-4">
      <section className="surface grid gap-3 p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <Pick label="Report on">
          <NativeSelect value={def.source} onChange={(e) => onChange({ ...START, source: e.target.value as Definition["source"] })}>
            {catalogue.data.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </NativeSelect>
        </Pick>
        {[0, 1].map((i) => (
          <Pick key={i} label={i === 0 ? "Group by" : "Then by"}>
            <NativeSelect
              value={groups[i] ?? ""}
              disabled={i === 1 && !groups[0]}
              onChange={(e) => {
                const next = [...groups];
                if (e.target.value) next[i] = e.target.value;
                else next.splice(i);
                set({ group_by: next.filter(Boolean) });
              }}
            >
              <option value="">{i === 0 ? "Nothing (one total)" : "Nothing"}</option>
              {source?.dimensions.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.label}
                </option>
              ))}
            </NativeSelect>
          </Pick>
        ))}
        <Pick label="Show">
          <NativeSelect
            value={measure.op === "count" ? "count" : `${measure.op}:${measure.field}`}
            onChange={(e) => {
              const [op, field] = e.target.value.split(":");
              set({ measure: op === "count" ? { op: "count" } : { op: op as "sum" | "avg", field } });
            }}
          >
            <option value="count">Count</option>
            {source?.measures.flatMap((m) => [
              <option key={`sum:${m.key}`} value={`sum:${m.key}`}>
                Total {m.label.toLowerCase()}
              </option>,
              <option key={`avg:${m.key}`} value={`avg:${m.key}`}>
                Average {m.label.toLowerCase()}
              </option>,
            ])}
          </NativeSelect>
        </Pick>
        <Pick label="From">
          <Input type="date" value={def.date_from ?? ""} onChange={(e) => set({ date_from: e.target.value || null })} />
        </Pick>
        <Pick label="To">
          <Input type="date" value={def.date_to ?? ""} onChange={(e) => set({ date_to: e.target.value || null })} />
        </Pick>
        <div className="flex flex-wrap items-end gap-1 sm:col-span-2 lg:col-span-3">
          {DISPLAYS.map(([k, label]) => (
            <Button key={k} size="sm" variant={def.display === k ? "default" : "outline"} onClick={() => set({ display: k })}>
              {label}
            </Button>
          ))}
          <Button size="sm" variant="ghost" className="ml-auto" onClick={download} disabled={!result.data}>
            Download CSV
          </Button>
        </div>
      </section>
      <section className="surface p-4 text-sm">
        {result.isError ? (
          <p className="text-destructive">{(result.error as Error).message}</p>
        ) : !result.data ? (
          <p className="text-muted-foreground">Working…</p>
        ) : (
          <Output result={result.data} display={def.display ?? "table"} />
        )}
      </section>
      <SaveBox def={def} saved={saved} onSaved={onSaved} />
    </div>
  );
}

function Pick({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function shown(result: Result, value: number, currency?: string | null) {
  return result.money && currency ? formatMoney(value, currency) : value.toLocaleString();
}

function Output({ result, display }: { result: Result; display: string }) {
  if (result.rows.length === 0) return <p className="text-muted-foreground">Nothing matches.</p>;
  return (
    <div className="space-y-4">
      {display !== "table" && <ReportChart result={result} display={display} format={(v, c) => shown(result, v, c)} />}
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              {result.columns.map((c, i) => (
                <TableHead key={i} className={i === result.columns.length - 1 ? "text-right" : ""}>
                  {c}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.rows.map((r, i) => (
              <TableRow key={i}>
                {r.labels.map((l, j) => (
                  <TableCell key={j}>{l}</TableCell>
                ))}
                {result.money && <TableCell>{r.currency}</TableCell>}
                <TableCell className="text-right tabular-nums">{shown(result, r.value, r.currency)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {result.truncated && <p className="text-xs text-muted-foreground">Showing the first 500 groups.</p>}
    </div>
  );
}

function SaveBox({ def, saved, onSaved }: { def: Definition; saved: Saved | null; onSaved: (id: string | null) => void }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const roles = useRoles();
  const mayShare = can("dashboards.business") || can("settings.manage");
  const editable = !saved || saved.yours || can("settings.manage");
  const [name, setName] = useState(saved?.name ?? "");
  const [shared, setShared] = useState<string[]>(saved?.shared_role_ids ?? []);
  async function save(asNew: boolean) {
    try {
      const body = { name, definition: def, shared_role_ids: shared };
      const out =
        saved && !asNew
          ? unwrap(await api.PUT("/api/v1/reports/saved/{report_id}", { params: { path: { report_id: saved.id } }, body }))
          : unwrap(await api.POST("/api/v1/reports/saved", { body }));
      qc.invalidateQueries({ queryKey: ["saved-reports"] });
      onSaved(out.id);
      toast.success("Report saved");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function remove() {
    if (!saved) return;
    try {
      unwrap(await api.DELETE("/api/v1/reports/saved/{report_id}", { params: { path: { report_id: saved.id } } }));
      qc.invalidateQueries({ queryKey: ["saved-reports"] });
      onSaved(null);
      toast.success("Report deleted");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <section className="surface space-y-3 p-4 text-sm">
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-48 flex-1 space-y-1">
          <span className="text-xs font-medium text-muted-foreground">Name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Leads by source this month" />
        </label>
        {editable && (
          <Button disabled={!name.trim()} onClick={() => save(false)}>
            {saved ? "Save changes" : "Save report"}
          </Button>
        )}
        {saved && (
          <Button variant="outline" disabled={!name.trim()} onClick={() => save(true)}>
            Save as new
          </Button>
        )}
        {saved && editable && (
          <Button variant="ghost" onClick={remove}>
            Delete
          </Button>
        )}
      </div>
      {mayShare && editable && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Share with roles (each person sees only what they may see)</p>
          <div className="flex flex-wrap gap-3">
            {(roles.data ?? []).map((r) => (
              <label key={r.id} className="flex items-center gap-1.5">
                <input type="checkbox" checked={shared.includes(r.id)} onChange={(e) => setShared(e.target.checked ? [...shared, r.id] : shared.filter((x) => x !== r.id))} />
                {r.name}
              </label>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
