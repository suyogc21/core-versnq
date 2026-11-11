"use client";

import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { useTeams } from "@/lib/directory";
import { useViews } from "@/lib/organise";

/** Save the current filters as a view tab: just me, a team I manage, or everyone (admins). */
export function SaveViewDialog({
  entity,
  filters,
  sort,
  dir,
  onClose,
  onSaved,
}: {
  entity: "leads" | "deals";
  filters: Record<string, unknown>;
  sort?: string;
  dir?: "asc" | "desc";
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const { me, can } = useAuth();
  const views = useViews(entity);
  const teams = useTeams();
  const admin = can("crm.configure");
  const shareable = (teams.data ?? []).filter((t) => admin || t.members.some((m) => m.user_id === me?.id && m.is_manager));
  const [name, setName] = useState("");
  const [sharing, setSharing] = useState("private");
  const [busy, setBusy] = useState(false);
  const clean = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== undefined && !(Array.isArray(v) && v.length === 0)));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const [kind, team] = sharing.startsWith("team:") ? ["team", sharing.slice(5)] : [sharing, null];
      const view = unwrap(
        await api.POST("/api/v1/views", {
          body: { entity, name: name.trim(), filters: clean, sort: sort ?? null, direction: dir ?? null, sharing: kind as "private", team_id: team },
        }),
      );
      await views.refetch();
      toast.success("View saved");
      onSaved(view.id);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Save as a view</DialogTitle>
        </DialogHeader>
        <form onSubmit={save} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="view-name">Name</Label>
            <Input id="view-name" autoFocus placeholder="e.g. Hot from Pune" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="view-share">Who sees it</Label>
            <NativeSelect id="view-share" value={sharing} onChange={(e) => setSharing(e.target.value)}>
              <option value="private">Just me</option>
              {shareable.map((t) => (
                <option key={t.id} value={`team:${t.id}`}>
                  Team: {t.name}
                </option>
              ))}
              {admin && <option value="everyone">Everyone</option>}
            </NativeSelect>
            <p className="text-xs text-muted-foreground">Everyone still sees only the records their role allows.</p>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || busy}>
              Save view
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
