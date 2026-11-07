"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Field } from "@/components/app/field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useAuth } from "@/lib/auth";

type StaffAccount = components["schemas"]["StaffAccountOut"];

export default function StaffPage() {
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const staff = useQuery({ queryKey: ["staff"], queryFn: async () => unwrap(await api.GET("/platform/staff")) });
  const [adding, setAdding] = useState(false);
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);

  async function setActive(s: StaffAccount, is_active: boolean) {
    if (!is_active && !window.confirm(`Deactivate ${s.name}? They are signed out everywhere.`)) return;
    try {
      unwrap(await api.PATCH("/platform/staff/{staff_id}", { params: { path: { staff_id: s.id } }, body: { is_active } }));
      queryClient.invalidateQueries({ queryKey: ["staff"] });
      toast.success(is_active ? `${s.name} reactivated.` : `${s.name} deactivated.`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <>
      <div className="mb-4 flex items-center">
        <h1 className="mr-auto text-base font-semibold">Staff</h1>
        <Button onClick={() => setAdding(true)}>Add staff</Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>2FA</TableHead>
            <TableHead className="w-32" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {staff.data?.map((s) => (
            <TableRow key={s.id}>
              <TableCell className="font-medium">
                {s.name}
                {s.id === me?.id && <span className="ml-1.5 text-xs text-muted-foreground">(you)</span>}
              </TableCell>
              <TableCell>{s.email}</TableCell>
              <TableCell>
                {!s.is_active ? (
                  <Badge variant="outline">Deactivated</Badge>
                ) : s.must_change_password ? (
                  <Badge variant="outline">Not signed in yet</Badge>
                ) : (
                  <Badge variant="secondary">Active</Badge>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground">{s.totp_enabled ? "On" : "Off"}</TableCell>
              <TableCell className="text-right">
                {s.id !== me?.id && (
                  <Button size="sm" variant="outline" onClick={() => setActive(s, !s.is_active)}>
                    {s.is_active ? "Deactivate" : "Reactivate"}
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {adding && (
        <AddStaffDialog
          onClose={() => setAdding(false)}
          onCreated={(email, password) => {
            setAdding(false);
            setCreated({ email, password });
          }}
        />
      )}
      <Dialog open={Boolean(created)} onOpenChange={(open) => !open && setCreated(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Temporary password for {created?.email}</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground">
            Share it privately. It is shown only once. They choose their own password and set up two-factor
            authentication when they first sign in.
          </p>
          <code className="rounded-md bg-muted px-3 py-2 text-center font-mono text-base select-all">{created?.password}</code>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => navigator.clipboard.writeText(created?.password ?? "").then(() => toast.success("Copied"))}
            >
              Copy
            </Button>
            <Button onClick={() => setCreated(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function AddStaffDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (email: string, password: string) => void }) {
  const queryClient = useQueryClient();
  const form = useForm<{ name: string; email: string }>();
  const { errors, isSubmitting } = form.formState;
  const submit = form.handleSubmit(async (body) => {
    try {
      const s = unwrap(await api.POST("/platform/staff", { body }));
      queryClient.invalidateQueries({ queryKey: ["staff"] });
      onCreated(s.email, s.temporary_password);
    } catch (e) {
      form.setError("email", { message: (e as Error).message });
    }
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add staff</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field id="name" label="Name" autoFocus error={errors.name?.message} {...form.register("name", { required: "Enter a name" })} />
          <Field id="email" label="Email" type="email" error={errors.email?.message} {...form.register("email", { required: "Enter an email" })} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              Add staff
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
