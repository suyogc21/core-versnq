"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { api, tokenStore } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useAuth } from "@/lib/auth";
import { relative, useSources, useStages } from "@/lib/crm";
import { useUsers } from "@/lib/directory";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Upload = components["schemas"]["UploadOut"];
type ImportItem = components["schemas"]["ImportOut"];
const MAX_BYTES = 20 * 1024 * 1024;
const IDENTITY = new Set(["phone", "whatsapp", "email", "linkedin"]);

/** Upload a CSV → match its columns → run in the background → see what happened. */
export default function ImportPage() {
  const label = useLabels();
  const { can } = useAuth();
  const [upload, setUpload] = useState<Upload | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const plural = label("lead", true);
  if (!can("leads.import")) {
    return (
      <>
        <PageHeader title={`Import ${plural.toLowerCase()}`} />
        <p className="p-8 text-center text-muted-foreground">You don&apos;t have permission to do that.</p>
      </>
    );
  }
  return (
    <>
      <PageHeader title={`Import ${plural.toLowerCase()}`} />
      <div className="mx-auto w-full max-w-4xl space-y-8 p-4 sm:p-8">
        <Steps step={running ? 3 : upload ? 2 : 1} />
        {running ? (
          <Progress importId={running} onAgain={() => (setRunning(null), setUpload(null))} />
        ) : upload ? (
          <MapColumns upload={upload} onBack={() => setUpload(null)} onStarted={setRunning} />
        ) : (
          <Choose onUploaded={setUpload} />
        )}
        <Recent onOpen={setRunning} />
      </div>
    </>
  );
}

function Steps({ step }: { step: number }) {
  return (
    <ol className="flex flex-wrap gap-2 text-xs">
      {["Upload the file", "Match columns", "Import"].map((name, i) => (
        <li
          key={name}
          className={cn(
            "rounded-full border px-3 py-1 text-muted-foreground",
            step === i + 1 && "border-primary bg-primary font-medium text-primary-foreground",
            step > i + 1 && "border-primary/40 text-foreground",
          )}
        >
          {i + 1}. {name}
        </li>
      ))}
    </ol>
  );
}

function Choose({ onUploaded }: { onUploaded: (u: Upload) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pick(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (file.size > MAX_BYTES) return setError("The file is larger than 20 MB. Split it into parts.");
    if (!/\.(csv|txt|tsv)$/i.test(file.name)) return setError("Choose a CSV file (in Excel or Google Sheets: File → Save as / Download → CSV).");
    setBusy(true);
    try {
      const content = await file.text();
      onUploaded(unwrap(await api.POST("/api/v1/imports", { body: { file_name: file.name, content } })));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <label
        className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed p-10 text-center hover:bg-accent/40"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          pick(e.dataTransfer.files[0]);
        }}
      >
        <FileUp className="size-6 text-muted-foreground" />
        <span className="font-medium">{busy ? "Reading…" : "Choose a CSV file or drop it here"}</span>
        <span className="text-xs text-muted-foreground">Up to 50,000 rows and 20 MB. The first row must be the column names.</span>
        <input type="file" accept=".csv,.txt,.tsv,text/csv" className="sr-only" aria-label="CSV file" disabled={busy} onChange={(e) => pick(e.target.files?.[0])} />
      </label>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <p className="text-xs text-muted-foreground">
        Every row goes through the same rules as adding by hand: it needs a phone, email or LinkedIn profile, phones are cleaned up, and duplicates are
        caught. Rows that can&apos;t be imported are listed afterwards with the reason, so you can fix and import them again.
      </p>
    </div>
  );
}

function MapColumns({ upload, onBack, onStarted }: { upload: Upload; onBack: () => void; onStarted: (id: string) => void }) {
  const { me, can } = useAuth();
  const sources = useSources();
  const stages = useStages();
  const canAssign = can("leads.assign");
  const users = useUsers(canAssign && can("users.read"));
  const [mapping, setMapping] = useState<Record<string, string>>(upload.suggested);
  const [sourceId, setSourceId] = useState("");
  const [stageId, setStageId] = useState("");
  const [policy, setPolicy] = useState<"update" | "skip" | "create" | "flag">("update");
  const [owner, setOwner] = useState("me");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const targets = upload.targets.filter((t) => canAssign || t.key !== "owner_email");
  const used = new Set(Object.values(mapping));
  const mappedSource = used.has("source");
  const hasIdentity = [...used].some((t) => IDENTITY.has(t));

  async function start() {
    setError(null);
    if (!hasIdentity) return setError("Match at least one column to Phone, Email, WhatsApp number or LinkedIn profile.");
    if (!sourceId && !mappedSource) return setError("Choose where these came from.");
    setBusy(true);
    try {
      const started = unwrap(
        await api.POST("/api/v1/imports/{import_id}/start", {
          params: { path: { import_id: upload.id } },
          body: {
            mapping: Object.fromEntries(Object.entries(mapping).filter(([, t]) => t)),
            source_id: sourceId || null,
            stage_id: stageId || null,
            duplicate_policy: policy,
            owner,
          },
        }),
      );
      onStarted(started.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <p className="text-sm">
        <b>{upload.file_name}</b> · {upload.row_count.toLocaleString()} rows. Check what each column is. Columns left on &quot;Don&apos;t import&quot; are
        ignored.
      </p>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Column in your file</th>
              <th className="px-3 py-2 font-medium">Example values</th>
              <th className="px-3 py-2 font-medium">Import as</th>
            </tr>
          </thead>
          <tbody>
            {upload.headers.map((h, i) => (
              <tr key={h} className="border-t">
                <td className="px-3 py-2 font-medium">{h}</td>
                <td className="max-w-56 truncate px-3 py-2 text-xs text-muted-foreground">
                  {upload.sample
                    .map((r) => r[i])
                    .filter(Boolean)
                    .slice(0, 3)
                    .join(" · ") || "—"}
                </td>
                <td className="px-3 py-2">
                  <NativeSelect aria-label={`Import ${h} as`} value={mapping[h] ?? ""} onChange={(e) => setMapping({ ...mapping, [h]: e.target.value })}>
                    <option value="">Don&apos;t import</option>
                    {targets.map((t) => (
                      <option key={t.key} value={t.key} disabled={used.has(t.key) && mapping[h] !== t.key && !["phone", "email"].includes(t.key)}>
                        {t.label}
                      </option>
                    ))}
                  </NativeSelect>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="imp-source">Source {mappedSource && <span className="text-muted-foreground">(when the Source column is empty)</span>}</Label>
          <NativeSelect id="imp-source" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">Choose…</option>
            {(sources.data ?? [])
              .filter((s) => s.is_active)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
          </NativeSelect>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="imp-stage">Start in stage</Label>
          <NativeSelect id="imp-stage" value={stageId} onChange={(e) => setStageId(e.target.value)}>
            <option value="">First stage</option>
            {(stages.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="imp-owner">Owner</Label>
          <NativeSelect id="imp-owner" value={owner} onChange={(e) => setOwner(e.target.value)} disabled={!canAssign}>
            <option value="me">Me</option>
            {canAssign && <option value="rules">By assignment rules</option>}
            {canAssign && <option value="none">Unassigned</option>}
            {canAssign &&
              (users.data ?? [])
                .filter((u) => u.status === "active" && u.id !== me?.id)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
          </NativeSelect>
          {used.has("owner_email") && <p className="text-xs text-muted-foreground">Rows with an Owner email use that person.</p>}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="imp-dupes">If the phone or email already exists</Label>
          <NativeSelect id="imp-dupes" value={policy} onChange={(e) => setPolicy(e.target.value as typeof policy)}>
            <option value="update">Update it (fill empty details, keep the owner)</option>
            <option value="skip">Skip the row</option>
            <option value="flag">Add it, marked as a possible duplicate</option>
            <option value="create">Add it anyway</option>
          </NativeSelect>
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button variant="outline" onClick={onBack}>
          Choose another file
        </Button>
        <Button onClick={start} disabled={busy}>
          Import {upload.row_count.toLocaleString()} rows
        </Button>
      </div>
    </div>
  );
}

function useImport(id: string) {
  return useQuery({
    queryKey: ["import", id],
    refetchInterval: (q) => (["done", "cancelled"].includes(q.state.data?.status ?? "") ? false : 1500),
    queryFn: async () => unwrap(await api.GET("/api/v1/imports/{import_id}", { params: { path: { import_id: id } } })),
  });
}

async function downloadProblems(item: ImportItem) {
  // The file needs the sign-in token, so fetch it and hand the browser a local copy.
  const res = await fetch(`/api/v1/imports/${item.id}/problems`, { headers: { Authorization: `Bearer ${tokenStore.get()}` } });
  if (!res.ok) return toast.error("Could not download the file");
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: `${item.file_name.replace(/\.[^.]+$/, "")}-problems.csv` });
  a.click();
  URL.revokeObjectURL(url);
}

function Progress({ importId, onAgain }: { importId: string; onAgain: () => void }) {
  const label = useLabels();
  const qc = useQueryClient();
  const imp = useImport(importId);
  const i = imp.data;
  if (!i) return <p className="text-muted-foreground">Loading…</p>;
  const processed = i.created_count + i.updated_count + i.skipped_count + i.failed_count;
  const done = i.status === "done" || i.status === "cancelled";
  const pct = i.row_count ? Math.round((processed / i.row_count) * 100) : 0;

  async function cancel() {
    unwrap(await api.POST("/api/v1/imports/{import_id}/cancel", { params: { path: { import_id: importId } } }));
    qc.invalidateQueries({ queryKey: ["import", importId] });
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <div className="flex justify-between text-sm">
          <span className="font-medium">
            {i.status === "queued" ? "Waiting to start…" : i.status === "running" ? "Importing…" : i.status === "cancelled" ? "Stopped" : "Finished"}
          </span>
          <span className="tabular-nums text-muted-foreground">
            {processed.toLocaleString()} / {i.row_count.toLocaleString()}
          </span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-muted">
          <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          ["Added", i.created_count, ""],
          ["Updated", i.updated_count, ""],
          ["Skipped", i.skipped_count, ""],
          ["Failed", i.failed_count, i.failed_count ? "text-destructive" : ""],
        ].map(([name, n, cls]) => (
          <div key={name as string} className="rounded-lg border p-3">
            <div className={cn("text-xl font-semibold tabular-nums", cls as string)}>{(n as number).toLocaleString()}</div>
            <div className="text-xs text-muted-foreground">{name}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {!done && (
          <Button variant="outline" onClick={cancel}>
            Stop
          </Button>
        )}
        {done && i.failed_count + i.skipped_count > 0 && (
          <Button variant="outline" onClick={() => downloadProblems(i)}>
            <Download /> Download the {(i.failed_count + i.skipped_count).toLocaleString()} rows not imported
          </Button>
        )}
        {done && (
          <>
            <Link href="/leads" className="inline-flex h-8 items-center rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground">
              See {label("lead", true).toLowerCase()}
            </Link>
            <Button variant="ghost" onClick={onAgain}>
              Import another file
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

function Recent({ onOpen }: { onOpen: (id: string) => void }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["imports"], queryFn: async () => unwrap(await api.GET("/api/v1/imports")) });
  const items = list.data ?? [];
  if (!items.length) return null;

  async function remove(item: ImportItem) {
    if (!confirm(`Delete the stored rows of ${item.file_name}? The imported records stay.`)) return;
    try {
      unwrap(await api.DELETE("/api/v1/imports/{import_id}", { params: { path: { import_id: item.id } } }));
      qc.invalidateQueries({ queryKey: ["imports"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <section className="space-y-2">
      <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Recent imports</h3>
      <div className="divide-y surface text-sm">
        {items.map((i) => (
          <div key={i.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
            {i.status === "uploaded" ? (
              <span className="font-medium">{i.file_name}</span>
            ) : (
              <button className="font-medium hover:underline" onClick={() => onOpen(i.id)}>
                {i.file_name}
              </button>
            )}
            <span className="text-xs text-muted-foreground">
              {i.status === "uploaded" ? "not started" : i.status} · {i.created_count} added · {i.updated_count} updated · {i.failed_count} failed ·{" "}
              {relative(i.created_at)}
            </span>
            {!["queued", "running"].includes(i.status) && (
              <button className="ml-auto text-xs text-muted-foreground hover:text-destructive hover:underline" onClick={() => remove(i)}>
                Delete stored rows
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
