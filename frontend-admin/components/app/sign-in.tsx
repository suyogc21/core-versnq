"use client";

import { useMutation } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { BackupCodes } from "@/components/app/backup-codes";
import { Field, PASSWORD_RULE } from "@/components/app/field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";

export function AuthCard({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <div className="w-full max-w-sm space-y-4">
        <div className="text-center font-medium">
          Versnq <span className="text-muted-foreground">· Staff console</span>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{title}</CardTitle>
            {description ? <CardDescription>{description}</CardDescription> : null}
          </CardHeader>
          <CardContent>{children}</CardContent>
        </Card>
      </div>
    </main>
  );
}

export function LoginForm() {
  const { login, verifyTwoFactor } = useAuth();
  const [challenge, setChallenge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const creds = useForm<{ email: string; password: string }>();
  const code = useForm<{ code: string }>();

  const submitCreds = creds.handleSubmit(async ({ email, password }) => {
    setError(null);
    try {
      const result = await login(email, password);
      if (!result.done) setChallenge(result.challengeToken);
    } catch (e) {
      setError((e as Error).message);
    }
  });

  const submitCode = code.handleSubmit(async ({ code: value }) => {
    setError(null);
    try {
      await verifyTwoFactor(challenge as string, value.trim());
    } catch (e) {
      setError((e as Error).message);
    }
  });

  if (challenge) {
    return (
      <AuthCard title="Two-factor code" description="Enter the 6-digit code from your authenticator app. Lost your phone? Enter one of your backup codes.">
        <form onSubmit={submitCode} className="space-y-4">
          <Field
            id="code"
            label="Code"
            inputMode="text"
            autoComplete="one-time-code"
            autoFocus
            maxLength={9}
            error={error ?? undefined}
            {...code.register("code", { required: true, pattern: /^(\d{6}|[a-z0-9]{4}-?[a-z0-9]{4})$/i })}
          />
          <Button type="submit" className="w-full" disabled={code.formState.isSubmitting}>
            Verify
          </Button>
          <button type="button" className="w-full text-xs text-muted-foreground" onClick={() => setChallenge(null)}>
            Use a different account
          </button>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Staff sign in">
      <form onSubmit={submitCreds} className="space-y-4">
        <Field id="email" label="Email" type="email" autoComplete="email" autoFocus {...creds.register("email", { required: true })} />
        <Field id="password" label="Password" type="password" autoComplete="current-password" {...creds.register("password", { required: true })} />
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        <Button type="submit" className="w-full" disabled={creds.formState.isSubmitting}>
          Sign in
        </Button>
        <p className="text-center text-xs text-muted-foreground">Forgot your password? Ask another staff admin.</p>
      </form>
    </AuthCard>
  );
}

/** Shown while the staff member still has the temporary password they were given. */
export function ChangePasswordScreen() {
  const { logout } = useAuth();
  const form = useForm<{ current: string; next: string; confirm: string }>();
  const { errors } = form.formState;
  const submit = form.handleSubmit(async ({ current, next }) => {
    try {
      unwrap(
        await api.POST("/platform/auth/password/change", {
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

/** Every staff account must use two-factor authentication. */
export function TwoFactorSetupScreen() {
  const { reloadMe, logout } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const form = useForm<{ code: string }>();
  const start = useMutation({
    mutationFn: async () => unwrap(await api.POST("/platform/auth/2fa/setup")),
    onSuccess: setSetup,
    onError: (e) => toast.error(e.message),
  });
  const { mutate: startSetup } = start;
  useEffect(() => startSetup(), [startSetup]);

  const submit = form.handleSubmit(async ({ code }) => {
    try {
      const r = unwrap(await api.POST("/platform/auth/2fa/enable", { body: { code: code.trim() } }));
      toast.success("Two-factor authentication is on.");
      setCodes(r.recovery_codes); // shown once; Done then opens the console
    } catch (e) {
      form.setError("code", { message: (e as Error).message });
    }
  });

  return (
    <AuthCard
      title="Turn on two-factor authentication"
      description="Staff accounts can reach every company, so a second step is required. Scan the code with your authenticator app."
    >
      {codes ? (
        <BackupCodes codes={codes} onDone={reloadMe} />
      ) : setup ? (
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
      ) : (
        <p className="text-muted-foreground">Preparing…</p>
      )}
      <button type="button" className="mt-3 w-full text-xs text-muted-foreground" onClick={logout}>
        Sign out
      </button>
    </AuthCard>
  );
}
