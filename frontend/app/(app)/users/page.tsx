"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Field } from "@/components/app/field";
import { NativeSelect } from "@/components/app/native-select";
import { Badge } from "@/components/ui/badge";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { type Role, type User, useRoles, useUsers } from "@/lib/directory";

const STATUS: Record<string, "default" | "secondary" | "outline"> = {
  active: "secondary",
  invited: "outline",
  disabled: "outline",
};

export default function UsersPage() {
  const { me, can } = useAuth();
  const users = useUsers();
  const roles = useRoles();
  const [search, setSearch] = useState("");
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [tempPassword, setTempPassword] = useState<{ name: string; password: string } | null>(null);
  const queryClient = useQueryClient();
  const manage = can("users.manage");
  const roleName = (id: string) => roles.data?.find((r) => r.id === id)?.name ?? "—";

  const action = useMutation({
    mutationFn: async ({ user, kind }: { user: User; kind: "disable" | "enable" | "resend" | "temp" }) => {
      const path = { params: { path: { user_id: user.id } } };
      if (kind === "disable") return unwrap(await api.POST("/api/v1/users/{user_id}/disable", path));
      if (kind === "enable") return unwrap(await api.POST("/api/v1/users/{user_id}/enable", path));
      if (kind === "resend") return unwrap(await api.POST("/api/v1/users/{user_id}/resend-invite", path));
      return unwrap(await api.POST("/api/v1/users/{user_id}/temporary-password", path));
    },
    onSuccess: (data, { user, kind }) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      if (kind === "disable") toast.success(`${user.name} is disabled and signed out everywhere.`);
      if (kind === "enable") toast.success(`${user.name} can sign in again.`);
      if (kind === "resend") {
        const sent = (data as { invite_sent: boolean }).invite_sent;
        if (sent) toast.success(`Invite sent to ${user.email}.`);
        else toast.error("The invite email could not be sent. Try again or set a temporary password.");
      }
      if (kind === "temp") {
        setTempPassword({ name: user.name, password: (data as { temporary_password: string }).temporary_password });
      }
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const q = search.trim().toLowerCase();
  const rows = (users.data ?? []).filter(
    (u) => !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q),
  );

  return (
    <>
      <PageHeader
        title="Users"
        count={users.data?.length}
        actions={
          <>
            <Input
              placeholder="Search name or email"
              className="h-7 w-56"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {manage && (
              <Button size="sm" onClick={() => setInviting(true)}>
                <Plus /> Invite user
              </Button>
            )}
          </>
        }
      />
      <div className="p-4">
        {users.isLoading ? (
          <p className="text-muted-foreground">Loading…</p>
        ) : users.isError ? (
          <p className="text-destructive">{users.error.message}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>2FA</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">
                    {u.name}
                    {u.id === me?.id && <span className="ml-1.5 text-xs text-muted-foreground">(you)</span>}
                  </TableCell>
                  <TableCell>{u.email}</TableCell>
                  <TableCell className="text-muted-foreground">{u.phone ?? "—"}</TableCell>
                  <TableCell>{roleName(u.role_id)}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS[u.status] ?? "outline"} className="capitalize">
                      {u.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{u.totp_enabled ? "On" : "Off"}</TableCell>
                  <TableCell>
                    {manage && u.id !== me?.id && (
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          render={<Button variant="ghost" size="icon-sm" aria-label={`Actions for ${u.name}`} />}
                        >
                          <MoreHorizontal />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-52">
                          <DropdownMenuItem onClick={() => setEditing(u)}>Edit details and role</DropdownMenuItem>
                          {u.status === "invited" && (
                            <DropdownMenuItem onClick={() => action.mutate({ user: u, kind: "resend" })}>
                              Resend invite
                            </DropdownMenuItem>
                          )}
                          {u.status === "active" && (
                            <DropdownMenuItem onClick={() => action.mutate({ user: u, kind: "temp" })}>
                              Set temporary password
                            </DropdownMenuItem>
                          )}
                          {u.status === "disabled" ? (
                            <DropdownMenuItem onClick={() => action.mutate({ user: u, kind: "enable" })}>
                              Enable
                            </DropdownMenuItem>
                          ) : (
                            <DropdownMenuItem
                              variant="destructive"
                              onClick={() => action.mutate({ user: u, kind: "disable" })}
                            >
                              Disable
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                    No users match.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </div>

      {inviting && <InviteDialog roles={roles.data ?? []} onClose={() => setInviting(false)} />}
      {editing && <EditDialog user={editing} roles={roles.data ?? []} onClose={() => setEditing(null)} />}
      <Dialog open={Boolean(tempPassword)} onOpenChange={(open) => !open && setTempPassword(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Temporary password for {tempPassword?.name}</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground">
            Share it privately. It is shown only once. They must choose their own password when they sign in, and
            their other sessions have been signed out.
          </p>
          <code className="rounded-md bg-muted px-3 py-2 text-center font-mono text-base select-all">
            {tempPassword?.password}
          </code>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => navigator.clipboard.writeText(tempPassword?.password ?? "").then(() => toast.success("Copied"))}
            >
              Copy
            </Button>
            <Button onClick={() => setTempPassword(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
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
