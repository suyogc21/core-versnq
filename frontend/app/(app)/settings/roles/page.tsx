"use client";

import { useQueries, useQueryClient } from "@tanstack/react-query";
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
import { useAuth } from "@/lib/auth";
import { type Permission, type Role, SCOPE_LABEL, usePermissions, useRoles } from "@/lib/directory";
import { type RoleAccess, useAllRecordTypes } from "@/lib/records";

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
      <PageHeader back={{ href: "/settings", label: "Settings" }}
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
                      <Badge variant="outline" className="ms-2">
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
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
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
          {role && role.key !== "owner" && <RecordAccess roleId={role.id} />}
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

/** This role's access to each of the company's own record types (saved as you change it).
 * The same table is on each record type's settings page; this is the role's view of it. */
function RecordAccess({ roleId }: { roleId: string }) {
  const { can } = useAuth();
  const types = useAllRecordTypes(can("crm.configure"));
  const qc = useQueryClient();
  const list = types.data ?? [];
  const access = useQueries({
    queries: list.map((t) => ({
      queryKey: ["record-access", t.id],
      queryFn: async () => unwrap(await api.GET("/api/v1/record-types/{type_id}/access", { params: { path: { type_id: t.id } } })),
    })),
  });
  if (!can("crm.configure") || list.length === 0) return null;

  async function update(typeId: string, row: RoleAccess, patch: Partial<RoleAccess>) {
    const next = { ...row, ...patch };
    if (patch.view === false) Object.assign(next, { create: false, edit: false, delete: false });
    if (patch.create || patch.edit || patch.delete) next.view = true;
    try {
      unwrap(await api.PUT("/api/v1/record-types/{type_id}/access", { params: { path: { type_id: typeId } }, body: [next] }));
      qc.invalidateQueries({ queryKey: ["record-access", typeId] });
      qc.invalidateQueries({ queryKey: ["record-types"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <fieldset className="space-y-2">
      <legend className="mb-1.5 text-sm font-medium">Your own record types</legend>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50 text-start text-muted-foreground">
            <tr>
              <th className="px-2 py-1.5 font-medium">Type</th>
              {["View", "Add", "Edit", "Delete"].map((h) => (
                <th key={h} className="px-2 py-1.5 text-center font-medium">
                  {h}
                </th>
              ))}
              <th className="px-2 py-1.5 font-medium">Sees</th>
            </tr>
          </thead>
          <tbody>
            {list.map((t, i) => {
              const row = access[i]?.data?.find((a) => a.role_id === roleId);
              if (!row) return null;
              return (
                <tr key={t.id} className="border-t">
                  <td className="px-2 py-1.5 font-medium">{t.plural}</td>
                  {(["view", "create", "edit", "delete"] as const).map((k) => (
                    <td key={k} className="px-2 py-1.5 text-center">
                      <input type="checkbox" aria-label={`${t.plural} ${k}`} className="accent-primary" checked={row[k]} onChange={(e) => update(t.id, row, { [k]: e.target.checked })} />
                    </td>
                  ))}
                  <td className="px-2 py-1.5">
                    {t.has_owner ? (
                      <NativeSelect aria-label={`${t.plural} sees`} className="h-7 w-auto" value={row.scope} onChange={(e) => update(t.id, row, { scope: e.target.value as RoleAccess["scope"] })}>
                        <option value="own">Own</option>
                        <option value="team">Team&apos;s</option>
                        <option value="all">All</option>
                      </NativeSelect>
                    ) : (
                      <span className="text-muted-foreground">All (shared)</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">Saved as you change it.</p>
    </fieldset>
  );
}
