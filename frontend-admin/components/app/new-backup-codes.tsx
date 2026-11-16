"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";

import { BackupCodes } from "@/components/app/backup-codes";
import { Field } from "@/components/app/field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";

/** Header button: how many backup codes are left, and a way to get 10 new ones (go-live G-4). */
export function NewBackupCodes({ left }: { left: number }) {
  const { reloadMe } = useAuth();
  const [open, setOpen] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);
  const form = useForm<{ password: string; code: string }>();
  const { errors } = form.formState;

  const close = async () => {
    setOpen(false);
    setCodes(null);
    form.reset();
    await reloadMe();
  };
  const submit = form.handleSubmit(async ({ password, code }) => {
    try {
      const r = unwrap(await api.POST("/platform/auth/2fa/recovery-codes", { body: { password, code: code.trim() } }));
      setCodes(r.recovery_codes);
    } catch (e) {
      form.setError("code", { message: (e as Error).message });
    }
  });

  return (
    <>
      <Button size="sm" variant={left === 0 ? "destructive" : "outline"} onClick={() => setOpen(true)}>
        {left === 0 ? "No backup codes" : `Backup codes: ${left} left`}
      </Button>
      <Dialog open={open} onOpenChange={(o) => !o && close()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Get new backup codes</DialogTitle>
            <DialogDescription>
              If you lose your phone, a backup code signs you in once. New codes replace the old ones.
            </DialogDescription>
          </DialogHeader>
          {codes ? (
            <BackupCodes codes={codes} onDone={close} />
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <Field id="bc-password" label="Your password" type="password" autoComplete="current-password" error={errors.password?.message} {...form.register("password", { required: "Enter your password" })} />
              <Field
                id="bc-code"
                label="6-digit code from the app"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                error={errors.code?.message}
                {...form.register("code", { required: "Enter the code", pattern: { value: /^\d{6}$/, message: "6 digits" } })}
              />
              <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
                Get new codes
              </Button>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
