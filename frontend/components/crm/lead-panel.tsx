"use client";

import { Phone, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { CustomFieldsEditor, StagePill } from "@/components/crm/bits";
import { AddFieldButton } from "@/components/crm/field-settings";
import { LabeledInput } from "@/components/crm/lead-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import {
  type ActivityItem,
  fieldValue,
  fromLocalInput,
  identity,
  isOverdue,
  type Lead,
  relative,
  toLocalInput,
  useActivityTypes,
  useFields,
  useLeadTasks,
  useRefreshLead,
  useSources,
  useStages,
  useTimeline,
  when,
} from "@/lib/crm";
import { useUsers } from "@/lib/directory";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

export function ActionButton({
  icon: Icon,
  label,
  href,
  onClick,
  primary,
  external,
}: {
  icon: typeof Phone;
  label: string;
  href?: string;
  onClick?: () => void;
  primary?: boolean;
  external?: boolean;
}) {
  const cls = cn(
    "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium hover:bg-accent",
    primary && "border-primary bg-primary text-primary-foreground hover:bg-primary/90",
  );
  const content = (
    <>
      <Icon className="size-3.5" />
      {label}
    </>
  );
  return href ? (
    <a className={cls} href={href} onClick={onClick} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined}>
      {content}
    </a>
  ) : (
    <button type="button" className={cls} onClick={onClick}>
      {content}
    </button>
  );
}

/** Stage, owner, source and custom field values, with stage and owner changeable in place. */
export function Facts({ lead, showStage = true }: { lead: Lead; showStage?: boolean }) {
  const { can, me } = useAuth();
  const stages = useStages();
  const sources = useSources();
  const fields = useFields();
  const users = useUsers(can("leads.assign") && can("users.read"));
  const refresh = useRefreshLead();
  const [reasonFor, setReasonFor] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const editable = can("leads.edit");

  async function moveTo(stageId: string, unqualifiedReason?: string) {
    const target = stages.data?.find((s) => s.id === stageId);
    if (target?.is_unqualified && !unqualifiedReason) {
      setReasonFor(stageId);
      return;
    }
    try {
      const updated = unwrap(
        await api.PATCH("/api/v1/leads/{lead_id}", {
          params: { path: { lead_id: lead.id } },
          body: { version: lead.version, stage_id: stageId, unqualified_reason: unqualifiedReason ?? lead.unqualified_reason },
        }),
      );
      refresh(updated);
      setReasonFor(null);
      setReason("");
      toast.success(`Moved to ${target?.name}`);
    } catch (e) {
      toast.error((e as Error).message);
      refresh();
    }
  }

  async function assign(ownerId: string) {
    try {
      const updated = unwrap(
        await api.PUT("/api/v1/leads/{lead_id}/owner", {
          params: { path: { lead_id: lead.id } },
          body: { owner_user_id: ownerId === "none" ? null : ownerId },
        }),
      );
      refresh(updated);
      toast.success(updated.owner_name ? `Assigned to ${updated.owner_name}` : "Unassigned");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const source = sources.data?.find((s) => s.id === lead.source_id);
  const values = lead.custom_fields as Record<string, unknown>;
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-[7rem_minmax(0,1fr)] items-center gap-x-3 gap-y-2 text-xs">
        {showStage && <dt className="text-muted-foreground">Stage</dt>}
        {showStage && <dd>
          {editable ? (
            <NativeSelect aria-label="Stage" className="h-7 w-auto" value={lead.stage_id} onChange={(e) => moveTo(e.target.value)}>
              {(stages.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          ) : (
            <StagePill stage={stages.data?.find((s) => s.id === lead.stage_id)} />
          )}
        </dd>}
        {reasonFor && (
          <>
            <dt className="text-muted-foreground">Reason</dt>
            <dd className="flex gap-1.5">
              <Input autoFocus aria-label="Reason" className="h-7" placeholder="Why?" value={reason} onChange={(e) => setReason(e.target.value)} />
              <Button size="sm" disabled={!reason.trim()} onClick={() => moveTo(reasonFor, reason.trim())}>
                Move
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setReasonFor(null)}>
                Cancel
              </Button>
            </dd>
          </>
        )}
        {lead.unqualified_reason && !lead.is_open && (
          <>
            <dt className="text-muted-foreground">Reason</dt>
            <dd>{lead.unqualified_reason}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Owner</dt>
        <dd>
          {can("leads.assign") && users.data ? (
            <NativeSelect aria-label="Owner" className="h-7 w-auto max-w-full" value={lead.owner_user_id ?? "none"} onChange={(e) => assign(e.target.value)}>
              <option value="none">Unassigned</option>
              {users.data
                .filter((u) => u.status === "active" || u.id === lead.owner_user_id)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.id === me?.id ? `${u.name} (me)` : u.name}
                  </option>
                ))}
            </NativeSelect>
          ) : (
            (lead.owner_name ?? "Unassigned")
          )}
        </dd>
        <dt className="text-muted-foreground">Source</dt>
        <dd>
          {source?.name ?? "—"}
          {lead.utm_campaign && <span className="ml-1 rounded border px-1 text-[10px] text-muted-foreground">{lead.utm_campaign}</span>}
        </dd>
        {lead.last_disposition && (
          <>
            <dt className="text-muted-foreground">Last outcome</dt>
            <dd>{lead.last_disposition}</dd>
          </>
        )}
        {(fields.data ?? [])
          .filter((f) => values[f.key] !== undefined)
          .map((f) => (
            <FactRow key={f.key} label={f.label} value={fieldValue(f, values[f.key])} />
          ))}
        {lead.city && <FactRow label="City" value={lead.city} />}
        <FactRow label="Added" value={relative(lead.created_at)} />
      </dl>
    </div>
  );
}

export function FactRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="break-words">{value}</dd>
    </>
  );
}

const ICON: Record<string, string> = {
  call: "📞",
  note: "📝",
  lead_created: "➕",
  lead_updated: "✎",
  stage_changed: "↗",
  owner_changed: "👤",
  task_completed: "✓",
};

/** Which timeline entries each filter shows. */
export const TIMELINE_FILTERS: Record<string, ((type: string) => boolean) | null> = {
  All: null,
  Calls: (t) => t === "call",
  Notes: (t) => t === "note",
  "Stage changes": (t) => t === "stage_changed",
  Tasks: (t) => t === "task_completed",
  System: (t) => ["lead_created", "lead_updated", "owner_changed"].includes(t),
};

export function Timeline({ leadId, filter = "All" }: { leadId: string; filter?: string }) {
  const timeline = useTimeline(leadId);
  const types = useActivityTypes();
  const typeLabel = (key: string) => types.data?.find((t) => t.key === key)?.label ?? key;
  if (timeline.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  const keep = TIMELINE_FILTERS[filter];
  const items = (timeline.data ?? []).filter((a) => !keep || keep(a.type_key));
  if (!items.length) return <p className="text-muted-foreground">Nothing here yet.</p>;
  return (
    <ol className="space-y-3">
      {items.map((a: ActivityItem) => (
        <li key={a.id} className="flex gap-2.5">
          <div className="grid size-6 shrink-0 place-items-center rounded-full border bg-card text-[11px]" title={typeLabel(a.type_key)}>
            {ICON[a.type_key] ?? "•"}
          </div>
          <div className="min-w-0 flex-1 text-xs">
            <div className="text-muted-foreground">
              {when(a.occurred_at)}
              {a.actor_name && ` · ${a.actor_name}`}
              {a.actor_type === "automation" && ` · Automation: ${(a.data as { automation?: string }).automation ?? ""}`}
            </div>
            <div className="font-medium">{a.summary}</div>
            {a.body && a.type_key !== "note" && <div className="mt-1 rounded-md bg-muted px-2 py-1 whitespace-pre-wrap">{a.body}</div>}
            {a.body && a.type_key === "note" && a.body.includes("\n") && (
              <div className="mt-1 rounded-md bg-muted px-2 py-1 whitespace-pre-wrap">{a.body}</div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Edit names, identities, city, source and custom fields. Stale edits are refused (409). */
export function EditLead({ lead, onDeleted }: { lead: Lead; onDeleted?: () => void }) {
  const { can } = useAuth();
  const router = useRouter();
  const fields = useFields();
  const sources = useSources();
  const refresh = useRefreshLead();
  const label = useLabels();
  const first = (type: string) => lead.identities.find((i) => i.type === type)?.value ?? "";
  const [v, setV] = useState({
    first_name: lead.first_name ?? "",
    last_name: lead.last_name ?? "",
    org_name: lead.org_name ?? "",
    phone: first("phone"),
    email: first("email"),
    linkedin: first("linkedin"),
    city: lead.city ?? "",
    source_id: lead.source_id,
  });
  const [custom, setCustom] = useState<Record<string, unknown>>(lead.custom_fields as Record<string, unknown>);
  const [saving, setSaving] = useState(false);
  const editable = can("leads.edit");
  const set = (k: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV({ ...v, [k]: e.target.value });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    // Keep extra identities (second phone, etc.) and replace the first of each type.
    const others = lead.identities.filter((i, idx, all) => all.findIndex((x) => x.type === i.type) !== idx);
    const identities = [
      v.phone
        ? identity("phone", v.phone, { is_primary: true, is_whatsapp: lead.identities.find((i) => i.type === "phone")?.is_whatsapp ?? true })
        : null,
      v.email ? identity("email", v.email, { is_primary: true }) : null,
      v.linkedin ? identity("linkedin", v.linkedin, { is_primary: true }) : null,
      ...others.map((i) => identity(i.type as "phone" | "email" | "linkedin", i.value, { label: i.label, is_whatsapp: i.is_whatsapp })),
    ].filter((x) => x !== null);
    try {
      const updated = unwrap(
        await api.PATCH("/api/v1/leads/{lead_id}", {
          params: { path: { lead_id: lead.id } },
          body: {
            version: lead.version,
            first_name: v.first_name || null,
            last_name: v.last_name || null,
            org_name: v.org_name || null,
            city: v.city || null,
            source_id: v.source_id,
            identities,
            custom_fields: custom,
          },
        }),
      );
      refresh(updated);
      toast.success("Saved");
    } catch (err) {
      toast.error((err as Error).message);
      refresh();
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete ${lead.display_name} for good? Its whole timeline is removed. To keep it, move it to "Invalid" instead.`)) return;
    try {
      unwrap(await api.DELETE("/api/v1/leads/{lead_id}", { params: { path: { lead_id: lead.id } } }));
      refresh();
      toast.success(`${label("lead")} deleted`);
      if (onDeleted) onDeleted();
      else router.push("/leads");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <form onSubmit={save} className="space-y-4">
      <fieldset disabled={!editable} className="space-y-4">
        {lead.kind === "person" ? (
          <div className="grid grid-cols-2 gap-3">
            <LabeledInput id="e-first" label="First name" value={v.first_name} onChange={set("first_name")} />
            <LabeledInput id="e-last" label="Last name" value={v.last_name} onChange={set("last_name")} />
          </div>
        ) : (
          <LabeledInput id="e-org" label="Company name" value={v.org_name} onChange={set("org_name")} />
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <LabeledInput id="e-phone" label="Phone" type="tel" value={v.phone} onChange={set("phone")} />
          <LabeledInput id="e-email" label="Email" type="email" value={v.email} onChange={set("email")} />
          <LabeledInput id="e-linkedin" label="LinkedIn profile" value={v.linkedin} onChange={set("linkedin")} />
          <LabeledInput id="e-city" label="City" value={v.city} onChange={set("city")} />
          <div className="space-y-1.5">
            <label htmlFor="e-source" className="text-sm font-medium">
              Source
            </label>
            <NativeSelect id="e-source" value={v.source_id} onChange={set("source_id")}>
              {(sources.data ?? []).filter((s) => s.is_active || s.id === lead.source_id).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </div>
        </div>
        {(fields.data ?? []).length > 0 && <CustomFieldsEditor fields={fields.data ?? []} values={custom} onChange={setCustom} />}
        {can("crm.configure") && <AddFieldButton entity="lead" />}
      </fieldset>
      <div className="flex items-center gap-2">
        {editable && (
          <Button type="submit" size="sm" disabled={saving}>
            Save changes
          </Button>
        )}
        {can("leads.delete") && (
          <Button type="button" size="sm" variant="ghost" className="ml-auto text-destructive" onClick={remove}>
            <Trash2 /> Delete
          </Button>
        )}
      </div>
    </form>
  );
}

export function LeadTasks({ lead }: { lead: Lead }) {
  const tasks = useLeadTasks(lead.id);
  const refresh = useRefreshLead();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState(() => toLocalInput(new Date(Date.now() + 86400000).toISOString()));

  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      unwrap(await api.POST("/api/v1/tasks", { body: { title, due_at: fromLocalInput(due)!, lead_id: lead.id, priority: "normal" } }));
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
    <div className="space-y-3">
      <ul className="divide-y surface">
        {tasks.isLoading && <li className="p-3 text-xs text-muted-foreground">Loading…</li>}
        {tasks.data && tasks.data.length === 0 && <li className="p-3 text-xs text-muted-foreground">No open tasks.</li>}
        {(tasks.data ?? []).map((t) => (
          <li key={t.id} className="flex items-center gap-2 px-3 py-2 text-xs">
            <input type="checkbox" aria-label={`Done: ${t.title}`} className="accent-primary" onChange={() => complete(t.id)} />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{t.title}</div>
              <div className={cn("text-muted-foreground", isOverdue(t.due_at) && "text-destructive")}>{when(t.due_at)}</div>
            </div>
            {t.is_follow_up && <span className="rounded border px-1 text-[10px] text-muted-foreground">Follow-up</span>}
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="flex flex-wrap gap-1.5">
        <Input aria-label="New task" placeholder="Add a task…" className="h-8 min-w-40 flex-1" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Input aria-label="Due" type="datetime-local" className="h-8 w-auto" value={due} onChange={(e) => setDue(e.target.value)} />
        <Button size="sm" type="submit" disabled={!title.trim()}>
          Add
        </Button>
      </form>
    </div>
  );
}
