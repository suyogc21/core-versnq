"use client";

import { useState } from "react";
import { toast } from "sonner";

import { CustomFieldsEditor } from "@/components/crm/bits";
import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { fromLocalInput, identity, quickFollowUps, type Lead, useFields, useRefreshLead, useSources, useStages } from "@/lib/crm";
import { accessOf, useLayout } from "@/lib/layouts";
import { useUsers } from "@/lib/directory";
import { useLabels } from "@/lib/settings";

/** Quick-add: name, a phone or email, source, owner, first follow-up, custom fields. */
export function AddLeadDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (lead: Lead) => void }) {
  const { me, can } = useAuth();
  const label = useLabels();
  const stages = useStages();
  const sources = useSources();
  const fields = useFields();
  const layout = useLayout("lead");
  const cityOk = accessOf(layout.data, "city") === "edit"; // a field you may not edit can't be filled in either
  const canAssign = can("leads.assign");
  const users = useUsers(canAssign && can("users.read"));
  const refresh = useRefreshLead();
  const [kind, setKind] = useState<"person" | "organisation">("person");
  const [v, setV] = useState({ first_name: "", last_name: "", org_name: "", phone: "", email: "", linkedin: "", city: "" });
  const [sourceId, setSourceId] = useState("");
  const [stageId, setStageId] = useState("");
  const [owner, setOwner] = useState<string>(me?.id ?? "");
  const [followUp, setFollowUp] = useState("");
  const [custom, setCustom] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<{ id: string; name: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const singular = label("lead");

  const openStages = (stages.data ?? []).filter((s) => s.is_open);
  const activeSources = (sources.data ?? []).filter((s) => s.is_active);
  const assignable = (users.data ?? []).filter((u) => u.status === "active");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setDuplicate(null);
    const identities = [
      v.phone ? identity("phone", v.phone, { is_whatsapp: true, is_primary: true }) : null,
      v.email ? identity("email", v.email, { is_primary: true }) : null,
      v.linkedin ? identity("linkedin", v.linkedin, { is_primary: true }) : null,
    ].filter((x) => x !== null);
    if (!identities.length) return setError("Add a phone, email or LinkedIn profile");
    if (!sourceId) return setError("Choose where this came from");
    setSaving(true);
    try {
      const lead = unwrap(
        await api.POST("/api/v1/leads", {
          body: {
            kind,
            origin: "outside", // added by hand: from outside the CRM (spec "Three ways a lead enters")
            first_name: kind === "person" ? v.first_name || null : null,
            last_name: kind === "person" ? v.last_name || null : null,
            org_name: kind === "organisation" ? v.org_name || null : null,
            city: cityOk ? v.city || null : null,
            identities,
            source_id: sourceId,
            stage_id: stageId || null,
            owner_user_id: canAssign && owner && owner !== "none" && owner !== "rules" ? owner : null,
            assign_to_me: canAssign ? owner !== "none" && owner !== "rules" : true,
            assign_by_rules: canAssign && owner === "rules",
            next_follow_up_at: fromLocalInput(followUp),
            custom_fields: Object.fromEntries(Object.entries(custom).filter(([, x]) => x !== null && x !== "")),
          },
        }),
      );
      refresh(lead);
      toast.success(`${singular} added`);
      onCreated(lead);
    } catch (err) {
      setError((err as Error).message);
      const body = err instanceof ApiError ? (err.body as { duplicate?: { id: string; name: string } | null }) : undefined;
      if (body?.duplicate) setDuplicate(body.duplicate);
    } finally {
      setSaving(false);
    }
  }

  const set = (key: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [key]: e.target.value });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add {singular.toLowerCase()}</DialogTitle>
        </DialogHeader>
        <form onSubmit={save} className="space-y-4">
          <div className="inline-flex rounded-lg border p-0.5 text-xs">
            {(["person", "organisation"] as const).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={`rounded-md px-3 py-1 capitalize ${kind === k ? "bg-accent font-medium" : "text-muted-foreground"}`}
              >
                {k === "person" ? "A person" : "A company"}
              </button>
            ))}
          </div>
          {kind === "person" ? (
            <div className="grid grid-cols-2 gap-3">
              <LabeledInput id="first_name" label="First name" value={v.first_name} onChange={set("first_name")} autoFocus />
              <LabeledInput id="last_name" label="Last name" value={v.last_name} onChange={set("last_name")} />
            </div>
          ) : (
            <LabeledInput id="org_name" label="Company name" value={v.org_name} onChange={set("org_name")} autoFocus />
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <LabeledInput id="phone" label="Phone" type="tel" placeholder="98765 43210" value={v.phone} onChange={set("phone")} />
            <LabeledInput id="email" label="Email" type="email" value={v.email} onChange={set("email")} />
            <LabeledInput id="linkedin" label="LinkedIn profile" placeholder="linkedin.com/in/…" value={v.linkedin} onChange={set("linkedin")} />
            {cityOk && <LabeledInput id="city" label="City" value={v.city} onChange={set("city")} />}
          </div>
          <p className="-mt-2 text-xs text-muted-foreground">At least one of phone, email or LinkedIn.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="source">Source</Label>
              <NativeSelect id="source" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
                <option value="">Choose…</option>
                {activeSources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="stage">Stage</Label>
              <NativeSelect id="stage" value={stageId} onChange={(e) => setStageId(e.target.value)}>
                <option value="">{openStages[0]?.name ?? "First stage"}</option>
                {openStages.slice(1).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            {canAssign && (
              <div className="space-y-1.5">
                <Label htmlFor="owner">Owner</Label>
                <NativeSelect id="owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
                  <option value={me?.id ?? ""}>Me</option>
                  <option value="rules">By assignment rules</option>
                  <option value="none">Unassigned</option>
                  {assignable
                    .filter((u) => u.id !== me?.id)
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                </NativeSelect>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="follow">First follow-up</Label>
              <Input id="follow" type="datetime-local" value={followUp} onChange={(e) => setFollowUp(e.target.value)} />
              <div className="flex flex-wrap gap-1">
                {quickFollowUps().map((q) => (
                  <button key={q.label} type="button" className="rounded border px-1.5 text-[11px] text-muted-foreground hover:bg-accent" onClick={() => setFollowUp(q.value)}>
                    {q.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          {(fields.data ?? []).length > 0 && (
            <CustomFieldsEditor fields={fields.data ?? []} values={custom} onChange={setCustom} layout={layout.data} mode="add" />
          )}
          {error && (
            <p className="text-xs text-destructive">
              {error}
              {duplicate && (
                <>
                  {" — "}
                  <Link href={`/leads/${duplicate.id}`} className="font-medium underline" onClick={onClose}>
                    open {duplicate.name}
                  </Link>
                </>
              )}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              Add {singular.toLowerCase()}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function LabeledInput({ id, label, ...props }: React.ComponentProps<typeof Input> & { id: string; label: string }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} {...props} />
    </div>
  );
}
