"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Field } from "@/components/app/field";
import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import type { components, paths } from "@/lib/api/schema";
import { Avatar } from "@/components/crm/bits";
import { BulkButton, type Column, DataTable, emptySelection, type Paging, type Selection, TableTools, useTablePrefs } from "@/components/data-table/data-table";
import { FilterChip, ViewTabs } from "@/components/data-table/filters";
import { Popover, PopoverItem } from "@/components/data-table/popover";
import { type Role, type User, useRoles, useTeams } from "@/lib/directory";

type Row = components["schemas"]["UserRow"];

const STATUS_DOT: Record<string, string> = { active: "#16a34a", invited: "#d97706", disabled: "#94a3b8" };
const STATUS_VIEWS = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "invited", label: "Invited" },
  { key: "disabled", label: "Disabled" },
] as const;

function relativeTime(iso: string | null | undefined) {
  if (!iso) return "Never";
  const days = Math.round((Date.now() - new Date(iso).getTime()) / 86400000);
  return days <= 0 ? "Today" : days === 1 ? "Yesterday" : `${days} days ago`;
}

/** Users this person may see, a page at a time (built for hundreds of people). */
function usePagedUsers(query: UserPageQuery) {
  return useQuery({
    queryKey: ["users", "page", query],
    queryFn: async () => unwrap(await api.GET("/api/v1/users/page", { params: { query } })),
  });
}
type UserPageQuery = NonNullable<paths["/api/v1/users/page"]["get"]["parameters"]["query"]>;

export default function UsersPage() {
  const { me, can } = useAuth();
  const roles = useRoles();
  const teams = useTeams();
  const queryClient = useQueryClient();
  const manage = can("users.manage");
  const [view, setView] = useState<(typeof STATUS_VIEWS)[number]["key"]>("all");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [teamIds, setTeamIds] = useState<string[]>([]);
  const [paging, setPaging] = useState<Paging>({ page: 1, size: 50, sort: "name", dir: "asc" });
  const [selection, setSelection] = useState<Selection>(emptySelection);
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<Row | null>(null);
  const [tempPassword, setTempPassword] = useState<{ name: string; password: string } | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      if (search.trim() === q) return;
      setQ(search.trim());
      setPaging((p) => ({ ...p, page: 1 }));
      setSelection(emptySelection());
    }, 250);
    return () => clearTimeout(t);
  }, [search, q]);
  const reset = () => {
    setPaging((p) => ({ ...p, page: 1 }));
    setSelection(emptySelection());
  };

  const base = { q: q || undefined, role_id: roleIds.length ? roleIds : undefined, team_id: teamIds.length ? teamIds : undefined };
  const users = usePagedUsers({
    ...base,
    status: view === "all" ? undefined : [view],
    sort: paging.sort as UserPageQuery["sort"],
    dir: paging.dir,
    limit: paging.size,
    offset: (paging.page - 1) * paging.size,
  });
  // Tab counts: one tiny query per status, with the same search and filters.
  const countQueries = useQueries({
    queries: STATUS_VIEWS.map((v) => {
      const query: UserPageQuery = { ...base, status: v.key === "all" ? undefined : [v.key], limit: 1 };
      return {
        queryKey: ["users", "page", query],
        queryFn: async () => unwrap(await api.GET("/api/v1/users/page", { params: { query } })),
      };
    }),
  });
  const counts = Object.fromEntries(STATUS_VIEWS.map((v, i) => [v.key, countQueries[i].data?.total]));

  const action = useMutation({
    mutationFn: async ({ user, kind }: { user: Row; kind: "disable" | "enable" | "resend" | "temp" | "reset2fa" }) => {
      const path = { params: { path: { user_id: user.id } } };
      if (kind === "reset2fa") return unwrap(await api.POST("/api/v1/users/{user_id}/2fa/reset", path));
      if (kind === "disable") return unwrap(await api.POST("/api/v1/users/{user_id}/disable", path));
      if (kind === "enable") return unwrap(await api.POST("/api/v1/users/{user_id}/enable", path));
      if (kind === "resend") return unwrap(await api.POST("/api/v1/users/{user_id}/resend-invite", path));
      return unwrap(await api.POST("/api/v1/users/{user_id}/temporary-password", path));
    },
    onSuccess: (data, { user, kind }) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      if (kind === "disable") toast.success(`${user.name} is disabled and signed out everywhere.`);
      if (kind === "enable") toast.success(`${user.name} can sign in again.`);
      if (kind === "reset2fa") toast.success(`${user.name}'s authenticator app is removed. They sign in with an emailed code now.`);
      if (kind === "resend") {
        if ((data as { invite_sent: boolean }).invite_sent) toast.success(`Invite sent to ${user.email}.`);
        else toast.error("The invite email could not be sent. Try again or set a temporary password.");
      }
      if (kind === "temp") setTempPassword({ name: user.name, password: (data as { temporary_password: string }).temporary_password });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  /** Bulk: the same per-user call for each selected person; failures are reported, not hidden. */
  async function bulk(label: string, run: (u: Row) => Promise<unknown>) {
    const chosen = (users.data?.items ?? []).filter((u) => selection.ids.has(u.id) && u.id !== me?.id);
    const failures: string[] = [];
    for (const u of chosen) {
      try {
        await run(u);
      } catch (e) {
        failures.push(`${u.name}: ${(e as Error).message}`);
      }
    }
    queryClient.invalidateQueries({ queryKey: ["users"] });
    setSelection(emptySelection());
    if (failures.length) toast.warning(`${label} ${chosen.length - failures.length}. Skipped ${failures.length}: ${failures[0]}`);
    else toast.success(`${label} ${chosen.length}`);
  }

  const columns: Column<Row>[] = [
    {
      key: "name",
      label: "Name",
      sort: "name",
      pinned: true,
      cell: (u) => (
        <span className="flex items-center gap-2">
          <Avatar name={u.name} colour="#64748b" size={5} />
          <span className="max-w-56 truncate font-medium">{u.name}</span>
          {u.id === me?.id && <span className="text-xs text-muted-foreground">(you)</span>}
        </span>
      ),
    },
    { key: "email", label: "Email", sort: "email", cell: (u) => <span className="text-muted-foreground">{u.email}</span> },
    { key: "role", label: "Role", sort: "role", cell: (u) => u.role_name },
    { key: "teams", label: "Teams", cell: (u) => <span className="text-muted-foreground">{u.teams.join(", ") || "—"}</span> },
    {
      key: "status",
      label: "Status",
      sort: "status",
      cell: (u) => (
        <span className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs capitalize">
          <span className="size-1.5 rounded-full" style={{ background: STATUS_DOT[u.status] }} />
          {u.status}
        </span>
      ),
    },
    { key: "tfa", label: "2FA", cell: (u) => (u.totp_enabled ? "On" : <span className="text-muted-foreground">Off</span>) },
    { key: "last_login", label: "Last sign-in", sort: "last_login", cell: (u) => <span className="text-muted-foreground">{relativeTime(u.last_login_at)}</span> },
    { key: "phone", label: "Phone", hiddenByDefault: true, cell: (u) => <span className="text-muted-foreground">{u.phone ?? "—"}</span> },
    {
      key: "actions",
      label: "",
      cell: (u) =>
        manage && u.id !== me?.id ? (
          <span onClick={(e) => e.stopPropagation()}>
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label={`Actions for ${u.name}`} />}>
                <MoreHorizontal />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-52">
                <DropdownMenuItem onClick={() => setEditing(u)}>Edit details and role</DropdownMenuItem>
                {u.status === "invited" && <DropdownMenuItem onClick={() => action.mutate({ user: u, kind: "resend" })}>Resend invite</DropdownMenuItem>}
                {u.status === "active" && <DropdownMenuItem onClick={() => action.mutate({ user: u, kind: "temp" })}>Set temporary password</DropdownMenuItem>}
                {u.totp_enabled && u.id !== me?.id && (
                  <DropdownMenuItem
                    onClick={() => {
                      if (confirm(`Remove ${u.name}'s authenticator app (lost phone)? They will be signed out and sign in with an emailed code.`))
                        action.mutate({ user: u, kind: "reset2fa" });
                    }}
                  >
                    Reset authenticator app
                  </DropdownMenuItem>
                )}
                {u.status === "disabled" ? (
                  <DropdownMenuItem onClick={() => action.mutate({ user: u, kind: "enable" })}>Enable</DropdownMenuItem>
                ) : (
                  <DropdownMenuItem variant="destructive" onClick={() => action.mutate({ user: u, kind: "disable" })}>
                    Disable
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </span>
        ) : null,
    },
  ];
  const prefs = useTablePrefs("users", columns as Column<unknown>[]);
  const assignableRoles = (roles.data ?? []).filter((r) => r.key !== "owner" || me?.role.key === "owner");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader back={{ href: "/settings", label: "Settings" }}
        title="Users"
        count={counts.all}
        actions={
          <>
            <Input data-table-search placeholder="Search name or email  ( / )" className="h-7 w-full sm:w-64" value={search} onChange={(e) => setSearch(e.target.value)} />
            {manage && (
              <Button size="sm" onClick={() => setInviting(true)}>
                <Plus /> Invite user
              </Button>
            )}
          </>
        }
      />
      <ViewTabs
        views={STATUS_VIEWS.map((v) => ({ key: v.key, label: v.label, count: counts[v.key] }))}
        active={view}
        onChange={(v) => {
          setView(v as typeof view);
          reset();
        }}
      />
      <div className="flex flex-wrap items-center gap-1.5 border-b px-4 py-2">
        <FilterChip
          label="Role"
          options={(roles.data ?? []).map((r) => ({ value: r.id, label: r.name }))}
          values={roleIds}
          onChange={(v) => {
            setRoleIds(v);
            reset();
          }}
        />
        <FilterChip
          label="Team"
          options={(teams.data ?? []).map((t) => ({ value: t.id, label: t.name }))}
          values={teamIds}
          onChange={(v) => {
            setTeamIds(v);
            reset();
          }}
        />
        <div className="ml-auto hidden md:block">
          <TableTools columns={columns} prefs={prefs} />
        </div>
      </div>
      <DataTable
        columns={columns}
        rows={users.data?.items ?? []}
        total={users.data?.total ?? 0}
        loading={users.isFetching}
        error={users.isError ? users.error.message : null}
        getId={(u) => u.id}
        paging={paging}
        onPaging={setPaging}
        selection={manage ? selection : undefined}
        onSelection={manage ? setSelection : undefined}
        allowAllMatching={false}
        onOpen={(u) => manage && u.id !== me?.id && setEditing(u)}
        prefs={prefs}
        noun="users"
        card={(u) => (
          <div className="space-y-0.5">
            <div className="flex justify-between gap-2">
              <span className="truncate font-medium">{u.name}</span>
              <span className="text-xs text-muted-foreground capitalize">{u.status}</span>
            </div>
            <div className="text-xs text-muted-foreground">
              {u.role_name} · {u.teams.join(", ") || "No team"}
            </div>
          </div>
        )}
        bulk={() => (
          <>
            <div className="text-foreground">
              <Popover className="bottom-full top-auto mb-2" trigger={({ toggle }) => <BulkButton onClick={toggle}>Change role ▾</BulkButton>}>
                {(close) =>
                  assignableRoles.map((r) => (
                    <PopoverItem
                      key={r.id}
                      onClick={() => {
                        close();
                        bulk("Role changed for", async (u) =>
                          unwrap(await api.PATCH("/api/v1/users/{user_id}", { params: { path: { user_id: u.id } }, body: { role_id: r.id } })),
                        );
                      }}
                    >
                      {r.name}
                    </PopoverItem>
                  ))
                }
              </Popover>
            </div>
            <BulkButton
              onClick={() =>
                bulk("Invites sent to", async (u) => {
                  if (u.status !== "invited") throw new Error("already joined");
                  return unwrap(await api.POST("/api/v1/users/{user_id}/resend-invite", { params: { path: { user_id: u.id } } }));
                })
              }
            >
              Resend invites
            </BulkButton>
            <BulkButton
              danger
              onClick={() =>
                window.confirm(`Disable ${selection.ids.size} users? They are signed out everywhere.`) &&
                bulk("Disabled", async (u) => unwrap(await api.POST("/api/v1/users/{user_id}/disable", { params: { path: { user_id: u.id } } })))
              }
            >
              Disable
            </BulkButton>
          </>
        )}
      />

      {inviting && <InviteDialog roles={roles.data ?? []} onClose={() => setInviting(false)} />}
      {editing && <EditDialog user={editing} roles={roles.data ?? []} onClose={() => setEditing(null)} />}
      <Dialog open={Boolean(tempPassword)} onOpenChange={(open) => !open && setTempPassword(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Temporary password for {tempPassword?.name}</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground">
            Share it privately. It is shown only once. They must choose their own password when they sign in, and their other
            sessions have been signed out.
          </p>
          <code className="rounded-md bg-muted px-3 py-2 text-center font-mono text-base select-all">{tempPassword?.password}</code>
          <DialogFooter>
            <Button variant="outline" onClick={() => navigator.clipboard.writeText(tempPassword?.password ?? "").then(() => toast.success("Copied"))}>
              Copy
            </Button>
            <Button onClick={() => setTempPassword(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function RoleSelect({ roles, ...props }: { roles: Role[] } & React.ComponentProps<"select">) {
  // Only an Owner may assign the Owner role (the backend enforces this too).
  const { me } = useAuth();
  const allowOwner = me?.role.key === "owner";
  return (
    <NativeSelect {...props}>
      <option value="">Choose a role</option>
      {roles
        .filter((r) => allowOwner || r.key !== "owner")
        .map((r) => (
          <option key={r.id} value={r.id}>
            {r.name}
          </option>
        ))}
    </NativeSelect>
  );
}

function InviteDialog({ roles, onClose }: { roles: Role[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const form = useForm<{ name: string; email: string; role_id: string }>();
  const { errors, isSubmitting } = form.formState;
  const submit = form.handleSubmit(async (body) => {
    try {
      const user = unwrap(await api.POST("/api/v1/users", { body }));
      queryClient.invalidateQueries({ queryKey: ["users"] });
      if (user.invite_sent) toast.success(`Invite sent to ${user.email}.`);
      else toast.error("User added, but the invite email could not be sent. Use 'Resend invite'.");
      onClose();
    } catch (e) {
      form.setError("email", { message: (e as Error).message });
    }
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a user</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field id="name" label="Name" autoFocus error={errors.name?.message} {...form.register("name", { required: "Enter a name" })} />
          <Field
            id="email"
            label="Work email"
            type="email"
            error={errors.email?.message}
            {...form.register("email", { required: "Enter an email" })}
          />
          <div className="space-y-1.5">
            <Label htmlFor="role_id">Role</Label>
            <RoleSelect id="role_id" roles={roles} {...form.register("role_id", { required: "Choose a role" })} />
            {errors.role_id && <p className="text-xs text-destructive">{errors.role_id.message}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              Send invite
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditDialog({ user, roles, onClose }: { user: User; roles: Role[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { me } = useAuth();
  const isOwner = roles.find((r) => r.id === user.role_id)?.key === "owner";
  const lockedRole = isOwner && me?.role.key !== "owner";
  const form = useForm({ defaultValues: { name: user.name, phone: user.phone ?? "", role_id: user.role_id } });
  const { errors, isSubmitting } = form.formState;
  const submit = form.handleSubmit(async ({ name, phone, role_id }) => {
    try {
      unwrap(
        await api.PATCH("/api/v1/users/{user_id}", {
          params: { path: { user_id: user.id } },
          body: { name, phone: phone || null, ...(lockedRole ? {} : { role_id }) },
        }),
      );
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success("Saved.");
      onClose();
    } catch (e) {
      form.setError("root", { message: (e as Error).message });
    }
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit {user.name}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field id="name" label="Name" error={errors.name?.message} {...form.register("name", { required: "Enter a name" })} />
          <Field id="phone" label="Phone" hint="With country code, e.g. +91 98765 43210" {...form.register("phone")} />
          <div className="space-y-1.5">
            <Label htmlFor="role_id">Role</Label>
            {lockedRole ? (
              <p className="text-muted-foreground">Owner (only an Owner can change this)</p>
            ) : (
              <RoleSelect id="role_id" roles={roles} {...form.register("role_id", { required: true })} />
            )}
          </div>
          {errors.root && <p className="text-xs text-destructive">{errors.root.message}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
