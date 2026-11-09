"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { CustomFieldsEditor } from "@/components/crm/bits";
import { AddFieldButton } from "@/components/crm/field-settings";
import { LinksCard } from "@/components/crm/links-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { fieldValue, fromLocalInput, relative, toLocalInput, when } from "@/lib/crm";
import { useUsers } from "@/lib/directory";
import {
  type RecordItem,
  type RecordStage,
  type RecordType,
  useRecord,
  useRecordFields,
  useRecordStages,
  useRecordTasks,
  useRecordTimeline,
  useRecordTypes,
  useRefreshRecords,
} from "@/lib/records";
import { cn } from "@/lib/utils";

export default function RecordPage() {
  const { type: key, id } = useParams<{ type: string; id: string }>();
  const types = useRecordTypes();
  const record = useRecord(id);
  const rtype = types.data?.find((t) => t.key === key);
  if (types.isLoading || record.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!rtype || !record.data) return <p className="p-6 text-destructive">{record.error?.message ?? "Not found"}</p>;
  return <RecordView key={record.data.id} rtype={rtype} record={record.data} />;
}

function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="flex items-center justify-between text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        {title}
        {action}
      </h4>
      {children}
    </section>
  );
}

async function patch(record: RecordItem, body: Record<string, unknown>) {
  return unwrap(
    await api.PATCH("/api/v1/records/{record_id}", {
      params: { path: { record_id: record.id } },
      body: { version: record.version, ...body },
    }),
  );
}

function RecordView({ rtype, record }: { rtype: RecordType; record: RecordItem }) {
  const acc = rtype.my_access!;
  const router = useRouter();
  const refresh = useRefreshRecords();
  const [editing, setEditing] = useState(false);

  async function remove() {
    if (!confirm(`Delete ${record.name} for good? Its timeline, tasks and links are removed too.`)) return;
    try {
      unwrap(await api.DELETE("/api/v1/records/{record_id}", { params: { path: { record_id: record.id } } }));
      refresh();
      toast.success("Deleted");
      router.push(`/r/${rtype.key}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="space-y-3 border-b px-4 py-3 md:px-6">
        <div className="text-xs text-muted-foreground">
          <Link href={`/r/${rtype.key}`} className="hover:underline">
            {rtype.plural}
          </Link>{" "}
          / {record.name}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="min-w-0 truncate text-lg font-semibold">{record.name}</h2>
          <span className="text-xs text-muted-foreground">
            {rtype.singular} · added {relative(record.created_at)}
          </span>
          {acc.delete && (
            <Button size="sm" variant="ghost" className="ml-auto text-muted-foreground hover:text-destructive" onClick={remove}>
              Delete
            </Button>
          )}
        </div>
        {rtype.has_stages && <Stepper rtype={rtype} record={record} editable={acc.edit} />}
      </div>
      <div className="grid min-h-0 flex-1 lg:grid-cols-[320px_minmax(0,1fr)_320px]">
        <div className="space-y-5 border-b p-4 lg:border-r lg:border-b-0">
          <Section
            title="About"
            action={
              acc.edit ? (
                <button className="normal-case" onClick={() => setEditing(!editing)}>
                  {editing ? "Cancel" : "Edit"}
                </button>
              ) : undefined
            }
          >
            {editing ? <EditRecord rtype={rtype} record={record} onDone={() => setEditing(false)} /> : <Facts rtype={rtype} record={record} />}
          </Section>
        </div>
        <div className="space-y-4 border-b p-4 lg:border-b-0">
          {acc.edit && <NoteBox record={record} />}
          <RecordTimeline recordId={record.id} />
        </div>
        <div className="space-y-5 p-4 lg:border-l">
          <Section title="Linked">
            <LinksCard end={{ kind: "record", id: record.id, typeId: rtype.id }} editable={acc.edit} />
          </Section>
          <Section title="Tasks">
            <RecordTasks record={record} editable={acc.edit} />
          </Section>
        </div>
      </div>
    </div>
  );
}

function Stepper({ rtype, record, editable }: { rtype: RecordType; record: RecordItem; editable: boolean }) {
  const stages = useRecordStages(rtype.id);
  const refresh = useRefreshRecords();
  const list = stages.data ?? [];
  const here = list.findIndex((s) => s.id === record.stage_id);
  async function move(s: RecordStage) {
    if (s.id === record.stage_id) return;
    try {
      await patch(record, { stage_id: s.id });
      refresh();
      toast.success(`Moved to ${s.name}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <div className="flex overflow-x-auto rounded-lg border text-xs [scrollbar-width:none]">
      {list.map((s, i) => (
        <button
          key={s.id}
          type="button"
          disabled={!editable}
          onClick={() => move(s)}
          title={`Move to ${s.name}`}
          className={cn(
            "min-w-28 flex-1 border-r px-3 py-1.5 whitespace-nowrap text-muted-foreground last:border-r-0 hover:bg-accent",
            here > -1 && i < here && "bg-primary/10 text-foreground",
            s.id === record.stage_id && "bg-primary font-semibold text-primary-foreground hover:bg-primary",
          )}
        >
          {here > -1 && i < here && <Check className="mr-1 inline size-3" />}
          {s.name}
        </button>
      ))}
    </div>
  );
}

function Facts({ rtype, record }: { rtype: RecordType; record: RecordItem }) {
  const fields = useRecordFields(rtype.key);
  const values = record.custom_fields as Record<string, unknown>;
  const rows: [string, React.ReactNode][] = [];
  if (rtype.has_owner) rows.push(["Owner", record.owner_name ?? "Unassigned"]);
  for (const f of fields.data ?? []) rows.push([f.label, fieldValue(f, values[f.key])]);
  rows.push(["Updated", relative(record.updated_at)]);
  return (
    <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="truncate">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function EditRecord({ rtype, record, onDone }: { rtype: RecordType; record: RecordItem; onDone: () => void }) {
  const { can } = useAuth();
  const acc = rtype.my_access!;
  const fields = useRecordFields(rtype.key);
  const users = useUsers(rtype.has_owner && acc.scope !== "own" && can("users.read"));
  const refresh = useRefreshRecords();
  const [name, setName] = useState(record.name);
  const [owner, setOwner] = useState(record.owner_user_id ?? "none");
  const [custom, setCustom] = useState<Record<string, unknown>>(record.custom_fields as Record<string, unknown>);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      const body: Record<string, unknown> = { name, custom_fields: custom };
      if (rtype.has_owner && acc.scope !== "own") body.owner_user_id = owner === "none" ? null : owner;
      await patch(record, body);
      refresh();
      toast.success("Saved");
      onDone();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }

  return (
    <form onSubmit={save} className="space-y-3 text-xs">
      <div className="space-y-1">
        <label htmlFor="r-name" className="text-muted-foreground">
          Name
        </label>
        <Input id="r-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      {rtype.has_owner && acc.scope !== "own" && (
        <div className="space-y-1">
          <label htmlFor="r-owner" className="text-muted-foreground">
            Owner
          </label>
          <NativeSelect id="r-owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="none">Unassigned</option>
            {(users.data ?? [])
              .filter((u) => u.status === "active")
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
          </NativeSelect>
        </div>
      )}
      <CustomFieldsEditor fields={fields.data ?? []} values={custom} onChange={setCustom} />
      {can("crm.configure") && (
        <div>
          <AddFieldButton entity={`rt:${rtype.key}`} />
        </div>
      )}
      <Button size="sm" type="submit" disabled={!name.trim()}>
        Save
      </Button>
    </form>
  );
}

function NoteBox({ record }: { record: RecordItem }) {
  const refresh = useRefreshRecords();
  const [text, setText] = useState("");
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      unwrap(await api.POST("/api/v1/records/{record_id}/notes", { params: { path: { record_id: record.id } }, body: { body: text } }));
      setText("");
      refresh();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }
  return (
    <form onSubmit={save} className="space-y-2 rounded-lg border p-3">
      <Textarea aria-label="Note" placeholder="Write a note…" value={text} onChange={(e) => setText(e.target.value)} />
      <Button size="sm" type="submit" disabled={!text.trim()}>
        Add note
      </Button>
    </form>
  );
}

function RecordTimeline({ recordId }: { recordId: string }) {
  const timeline = useRecordTimeline(recordId);
  if (timeline.isLoading) return <p className="text-xs text-muted-foreground">Loading…</p>;
  const items = timeline.data ?? [];
  if (!items.length) return <p className="text-xs text-muted-foreground">Nothing yet.</p>;
  return (
    <ol className="space-y-3">
      {items.map((a) => (
        <li key={a.id} className="text-xs">
          <div className="text-muted-foreground">
            {when(a.occurred_at)}
            {a.actor_name ? ` · ${a.actor_name}` : ""}
          </div>
          <div className="font-medium">{a.summary}</div>
          {a.body && a.type_key === "note" && a.body !== a.summary && <div className="mt-1 rounded-md bg-muted px-2 py-1 whitespace-pre-wrap">{a.body}</div>}
        </li>
      ))}
    </ol>
  );
}

function RecordTasks({ record, editable }: { record: RecordItem; editable: boolean }) {
  const tasks = useRecordTasks(record.id);
  const refresh = useRefreshRecords();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState(() => toLocalInput(new Date(Date.now() + 86400000).toISOString()));
  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      unwrap(await api.POST("/api/v1/tasks", { body: { title, due_at: fromLocalInput(due)!, record_id: record.id, priority: "normal" } }));
      setTitle("");
      refresh();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }
  async function complete(id: string) {
    try {
      unwrap(await api.PATCH("/api/v1/tasks/{task_id}", { params: { path: { task_id: id } }, body: { status: "done" } }));
      refresh();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }
  return (
    <div className="space-y-2 text-xs">
      {tasks.isLoading && <p className="text-muted-foreground">Loading…</p>}
      {tasks.data && tasks.data.length === 0 && <p className="text-muted-foreground">No open tasks.</p>}
      {(tasks.data ?? []).map((t) => (
        <label key={t.id} className="flex items-center gap-2 rounded-md border px-2 py-1.5">
          <input type="checkbox" className="accent-primary" disabled={!editable} onChange={() => complete(t.id)} />
          <span className="flex-1">{t.title}</span>
          <span className="text-muted-foreground">{when(t.due_at)}</span>
        </label>
      ))}
      {editable && (
        <form onSubmit={add} className="space-y-1.5">
          <Input aria-label="New task" placeholder="Add a task…" className="h-7" value={title} onChange={(e) => setTitle(e.target.value)} />
          <div className="flex gap-1.5">
            <Input aria-label="Due" type="datetime-local" className="h-7" value={due} onChange={(e) => setDue(e.target.value)} />
            <Button size="sm" type="submit" disabled={!title.trim()}>
              Add
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
