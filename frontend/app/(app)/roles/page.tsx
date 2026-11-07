"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Lock, Plus, Trash2 } from "lucide-react";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type Permission, type Role, SCOPE_LABEL, usePermissions, useRoles } from "@/lib/directory";

type Form = { name: string; scope: "own" | "team" | "all"; permissions: string[] };

export default function RolesPage() {
  const roles = useRoles();
  const permissions = usePermissions();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Role | "new" | null>(null);

  async function remove(role: Role) {
    if (!window.confirm(`Delete the role "${role.name}"? This cannot be undone.`)) return;
    try {
      unwrap(await api.DELETE("/api/v1/roles/{role_id}", { params: { path: { role_id: role.id } } }));
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      toast.success("Role deleted.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <>
      <PageHeader
        title="Roles"
        count={roles.data?.length}
        actions={
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus /> New role
          </Button>
        }
      />
      <div className="p-4">
        {roles.isLoading ? (
          <p className="text-muted-foreground">Loading…</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Role</TableHead>
                <TableHead>Sees</TableHead>
                <TableHead>Permissions</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {(roles.data ?? []).map((r) => (
                <TableRow
                  key={r.id}
                  className={r.key === "owner" ? "" : "cursor-pointer"}
                  onClick={() => r.key !== "owner" && setEditing(r)}
                >
                  <TableCell className="font-medium">
                    {r.name}
                    {r.is_system && (
                      <Badge variant="outline" className="ml-2">
                        System
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>{SCOPE_LABEL[r.scope] ?? r.scope}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {r.key === "owner" ? "Everything" : r.permissions.length ? r.permissions.join(", ") : "None"}
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    {r.key === "owner" ? (
                      <Lock className="size-4 text-muted-foreground" aria-label="The Owner role cannot be changed" />
                    ) : (
                      !r.is_system && (
                        <Button variant="ghost" size="icon-sm" aria-label={`Delete ${r.name}`} onClick={() => remove(r)}>
                          <Trash2 />
                        </Button>
                      )
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
      {editing && (
        <RoleDialog
          role={editing === "new" ? null : editing}
          permissions={permissions.data ?? []}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}

function RoleDialog({ role, permissions, onClose }: { role: Role | null; permissions: Permission[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const form = useForm<Form>({
    defaultValues: {
      name: role?.name ?? "",
      scope: (role?.scope as Form["scope"]) ?? "own",
      permissions: role?.permissions ?? [],
    },
  });
  const { errors, isSubmitting } = form.formState;
  const byModule = Object.groupBy(permissions, (p) => p.module);

  const submit = form.handleSubmit(async (body) => {
    try {
      if (role) {
        unwrap(
          await api.PATCH("/api/v1/roles/{role_id}", {
            params: { path: { role_id: role.id } },
            body: role.is_system ? { scope: body.scope, permissions: body.permissions } : body,
          }),
        );
      } else {
        unwrap(await api.POST("/api/v1/roles", { body }));
      }
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      toast.success(role ? "Role saved." : "Role created.");
      onClose();
    } catch (e) {
      form.setError("root", { message: (e as Error).message });
    }
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{role ? `Edit ${role.name}` : "New role"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field
            id="name"
            label="Name"
            disabled={role?.is_system}
            hint={role?.is_system ? "System roles keep their name." : undefined}
            error={errors.name?.message}
            {...form.register("name", { required: "Enter a name" })}
          />
          <div className="space-y-1.5">
            <Label htmlFor="scope">Which records they see</Label>
            <NativeSelect id="scope" {...form.register("scope")}>
              {Object.entries(SCOPE_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </NativeSelect>
          </div>
          <fieldset className="space-y-3">
            <legend className="mb-1.5 text-sm font-medium">Permissions</legend>
            {Object.entries(byModule).map(([module, perms]) => (
              <div key={module} className="space-y-1.5">
                <div className="text-[11px] tracking-wide text-muted-foreground uppercase">{module}</div>
                {(perms ?? []).map((p) => (
                  <label key={p.code} className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      value={p.code}
                      className="mt-0.5 accent-primary"
                      {...form.register("permissions")}
                    />
                    <span>
                      <span className="font-mono text-xs">{p.code}</span>
                      <span className="block text-xs text-muted-foreground">{p.description}</span>
                    </span>
                  </label>
                ))}
              </div>
            ))}
            <p className="text-xs text-muted-foreground">You can only grant permissions you have yourself.</p>
          </fieldset>
          {errors.root && <p className="text-xs text-destructive">{errors.root.message}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {role ? "Save" : "Create role"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
