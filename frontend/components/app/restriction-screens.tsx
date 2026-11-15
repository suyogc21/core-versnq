"use client";

import { useMutation } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { AuthCard } from "@/components/app/auth-card";
import { BackupCodes } from "@/components/app/backup-codes";
import { Field, PASSWORD_RULE } from "@/components/app/field";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";

/** Shown while the user still has a temporary password. */
export function ChangePasswordScreen() {
  const { logout } = useAuth();
  const form = useForm<{ current: string; next: string; confirm: string }>();
  const { errors } = form.formState;
  const submit = form.handleSubmit(async ({ current, next }) => {
    try {
      unwrap(
        await api.POST("/api/v1/auth/password/change", {
          body: { current_password: current, new_password: next },
        }),
      );
      toast.success("Password changed. Sign in with your new password.");
      await logout(); // every session is revoked after a password change
    } catch (e) {
      form.setError("current", { message: (e as Error).message });
    }
  });
  return (
    <AuthCard title="Set your own password" description="You signed in with a temporary password. Choose your own to continue.">
      <form onSubmit={submit} className="space-y-4">
        <Field id="current" label="Temporary password" type="password" autoFocus error={errors.current?.message} {...form.register("current", { required: true })} />
        <Field
          id="next"
          label="New password"
          type="password"
          autoComplete="new-password"
          hint="At least 10 characters."
          error={errors.next?.message}
          {...form.register("next", {
            required: "Enter a password",
            minLength: { value: PASSWORD_RULE.minLength, message: "Use at least 10 characters" },
          })}
        />
        <Field
          id="confirm"
          label="Repeat new password"
          type="password"
          autoComplete="new-password"
          error={errors.confirm?.message}
          {...form.register("confirm", { validate: (v, all) => v === all.next || "Passwords do not match" })}
        />
        <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
          Save password
        </Button>
      </form>
    </AuthCard>
  );
}

/** QR code + code field. Used by the forced setup screen and by My account. */
export function TwoFactorSetupForm({ onDone }: { onDone: () => Promise<void> | void }) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const form = useForm<{ code: string }>();
  const start = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/auth/2fa/setup")),
    onSuccess: setSetup,
    onError: (e) => toast.error(e.message),
  });
  const { mutate: startSetup } = start;
  useEffect(() => startSetup(), [startSetup]);

  const submit = form.handleSubmit(async ({ code }) => {
    try {
      const r = unwrap(await api.POST("/api/v1/auth/2fa/enable", { body: { code: code.trim() } }));
      toast.success("Two-factor authentication is on.");
      setCodes(r.recovery_codes); // shown once, then onDone
    } catch (e) {
      form.setError("code", { message: (e as Error).message });
    }
  });

  if (codes) return <BackupCodes codes={codes} onDone={onDone} />;
  if (!setup) return <p className="text-muted-foreground">Preparing…</p>;
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="flex justify-center rounded-lg border bg-white p-3">
        <QRCodeSVG value={setup.otpauth_uri} size={168} />
      </div>
      <p className="break-all text-center font-mono text-xs text-muted-foreground">{setup.secret}</p>
      <Field
        id="code"
        label="6-digit code from the app"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        error={form.formState.errors.code?.message}
        {...form.register("code", { required: "Enter the code", pattern: { value: /^\d{6}$/, message: "6 digits" } })}
      />
      <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
        Turn on
      </Button>
    </form>
  );
}
