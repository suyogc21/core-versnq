"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Field } from "@/components/app/field";
import { NativeSelect } from "@/components/app/native-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { type Team, type User, useTeams, useUsers } from "@/lib/directory";
import { cn } from "@/lib/utils";

/** Teams in tree order (parents first), each with its depth. */
function flatten(teams: Team[]): { team: Team; depth: number }[] {
  const out: { team: Team; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) =>
    teams
      .filter((t) => t.parent_id === parent)
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((t) => {
        out.push({ team: t, depth });
        walk(t.id, depth + 1);
      });
  walk(null, 0);
  return out;
}

export default function TeamsPage() {
  const { can } = useAuth();
  const teams = useTeams();
  const users = useUsers();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"new" | "edit" | "members" | null>(null);
  const queryClient = useQueryClient();
  const manage = can("teams.manage");
  const tree = flatten(teams.data ?? []);
  const selected = teams.data?.find((t) => t.id === (selectedId ?? tree[0]?.team.id)) ?? null;
  const userById = new Map((users.data ?? []).map((u) => [u.id, u]));

  async function remove(team: Team) {
    if (!window.confirm(`Delete the team "${team.name}"? Members keep their accounts.`)) return;
    try {
      unwrap(await api.DELETE("/api/v1/teams/{team_id}", { params: { path: { team_id: team.id } } }));
      queryClient.invalidateQueries({ queryKey: ["teams"] });
      setSelectedId(null);
      toast.success("Team deleted.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <>
      <PageHeader back={{ href: "/settings", label: "Settings" }}
        title="Teams"
        count={teams.data?.length}
        actions={
          manage && (
            <Button size="sm" onClick={() => setDialog("new")}>
              <Plus /> New team
            </Button>
          )
        }
      />
      {teams.isLoading ? (
        <p className="p-4 text-muted-foreground">Loading…</p>
      ) : tree.length === 0 ? (
        <p className="p-8 text-center text-muted-foreground">No teams yet.</p>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          <nav className="max-h-56 w-full shrink-0 space-y-0.5 overflow-auto border-b p-2 md:max-h-none md:w-64 md:border-r md:border-b-0">
            {tree.map(({ team, depth }) => (
              <button
                key={team.id}
                onClick={() => setSelectedId(team.id)}
                style={{ paddingLeft: 8 + depth * 16 }}
                className={cn(
                  "flex w-full items-center justify-between rounded-md py-1.5 pr-2 text-left hover:bg-accent",
                  selected?.id === team.id && "bg-accent font-medium",
                )}
              >
                <span className="truncate">{team.name}</span>
                <span className="text-xs text-muted-foreground">{team.members.length}</span>
              </button>
            ))}
          </nav>
          {selected && (
            <section className="flex-1 overflow-auto p-4 md:p-6">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold">{selected.name}</h2>
                {manage && (
                  <div className="ml-auto flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => setDialog("members")}>
                      Edit members
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setDialog("edit")}>
                      Rename or move
                    </Button>
                    <Button size="icon-sm" variant="ghost" aria-label="Delete team" onClick={() => remove(selected)}>
                      <Trash2 />
                    </Button>
                  </div>
                )}
              </div>
              {selected.parent_id && (
                <p className="mt-0.5 text-muted-foreground">
                  Part of {teams.data?.find((t) => t.id === selected.parent_id)?.name}
                </p>
              )}
              <p className="mt-3 text-xs text-muted-foreground">
                Managers see the records of everyone in this team and its sub-teams.
              </p>
              <ul className="mt-3 divide-y surface">
                {selected.members.length === 0 && <li className="p-3 text-muted-foreground">No members yet.</li>}
                {[...selected.members]
                  .sort((a, b) => Number(b.is_manager) - Number(a.is_manager))
                  .map((m) => {
                    const u = userById.get(m.user_id);
                    return (
                      <li key={m.user_id} className="flex items-center gap-2 px-3 py-2">
                        <span className="font-medium">{u?.name ?? "A user outside your view"}</span>
                        <span className="text-muted-foreground">{u?.email}</span>
                        {m.is_manager && (
                          <Badge variant="secondary" className="ml-auto">
                            Manager
                          </Badge>
                        )}
                      </li>
                    );
                  })}
              </ul>
            </section>
          )}
        </div>
      )}
      {dialog === "new" && <TeamDialog team={null} teams={teams.data ?? []} onClose={() => setDialog(null)} />}
      {dialog === "edit" && selected && (
        <TeamDialog team={selected} teams={teams.data ?? []} onClose={() => setDialog(null)} />
      )}
      {dialog === "members" && selected && (
        <MembersDialog team={selected} users={users.data ?? []} onClose={() => setDialog(null)} />
      )}
    </>
  );
}

function TeamDialog({ team, teams, onClose }: { team: Team | null; teams: Team[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const form = useForm({ defaultValues: { name: team?.name ?? "", parent_id: team?.parent_id ?? "" } });
  const { errors, isSubmitting } = form.formState;
  const submit = form.handleSubmit(async ({ name, parent_id }) => {
    const body = { name, parent_id: parent_id || null };
    try {
      if (team) {
        unwrap(await api.PATCH("/api/v1/teams/{team_id}", { params: { path: { team_id: team.id } }, body }));
      } else {
        unwrap(await api.POST("/api/v1/teams", { body }));
      }
      queryClient.invalidateQueries({ queryKey: ["teams"] });
      toast.success(team ? "Team saved." : "Team created.");
      onClose();
    } catch (e) {
      form.setError("root", { message: (e as Error).message });
    }
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{team ? `Edit ${team.name}` : "New team"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field id="name" label="Name" autoFocus error={errors.name?.message} {...form.register("name", { required: "Enter a name" })} />
          <div className="space-y-1.5">
            <Label htmlFor="parent_id">Part of</Label>
            <NativeSelect id="parent_id" {...form.register("parent_id")}>
              <option value="">No parent (top level)</option>
              {flatten(teams)
                .filter(({ team: t }) => t.id !== team?.id)
                .map(({ team: t, depth }) => (
                  <option key={t.id} value={t.id}>
                    {"  ".repeat(depth) + t.name}
                  </option>
                ))}
            </NativeSelect>
          </div>
          {errors.root && <p className="text-xs text-destructive">{errors.root.message}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {team ? "Save" : "Create team"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type Membership = Record<string, "none" | "member" | "manager">;

function MembersDialog({ team, users, onClose }: { team: Team; users: User[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<Membership>(() =>
    Object.fromEntries(team.members.map((m) => [m.user_id, m.is_manager ? "manager" : "member"])),
  );
  const [saving, setSaving] = useState(false);
  const candidates = users.filter((u) => u.status !== "disabled" || state[u.id]);

  async function save() {
    setSaving(true);
    try {
      const body = Object.entries(state)
        .filter(([, v]) => v !== "none")
        .map(([user_id, v]) => ({ user_id, is_manager: v === "manager" }));
      unwrap(await api.PUT("/api/v1/teams/{team_id}/members", { params: { path: { team_id: team.id } }, body }));
      queryClient.invalidateQueries({ queryKey: ["teams"] });
      toast.success("Members saved.");
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Members of {team.name}</DialogTitle>
        </DialogHeader>
        <ul className="max-h-80 divide-y overflow-auto rounded-lg border">
          {candidates.map((u) => (
            <li key={u.id} className="flex items-center gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{u.name}</div>
                <div className="truncate text-xs text-muted-foreground">{u.email}</div>
              </div>
              <NativeSelect
                aria-label={`${u.name} in ${team.name}`}
                className="w-28"
                value={state[u.id] ?? "none"}
                onChange={(e) => setState((s) => ({ ...s, [u.id]: e.target.value as Membership[string] }))}
              >
                <option value="none">—</option>
                <option value="member">Member</option>
                <option value="manager">Manager</option>
              </NativeSelect>
            </li>
          ))}
        </ul>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} disabled={saving}>
            Save members
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
