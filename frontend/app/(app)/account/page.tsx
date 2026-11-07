"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Field, PASSWORD_RULE } from "@/components/app/field";
import { TwoFactorSetupForm } from "@/components/app/restriction-screens";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";

// Roles that must always have 2FA (matches the backend's REQUIRES_2FA).
const NEEDS_2FA = new Set(["owner", "admin"]);

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 border-b pb-8 last:border-0">
      <div>
        <h2 className="font-semibold">{title}</h2>
        {description && <p className="text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

export default function AccountPage() {
  const { me, logout } = useAuth();
  if (!me) return null;
  return (
    <>
      <PageHeader title="My account" />
      <div className="mx-auto w-full max-w-xl space-y-8 p-4 sm:p-8">
        <Section title="Profile">
          <dl className="grid grid-cols-[6rem_1fr] gap-y-1.5">
            <dt className="text-muted-foreground">Name</dt>
            <dd>{me.name}</dd>
            <dt className="text-muted-foreground">Email</dt>
            <dd className="break-all">{me.email}</dd>
            <dt className="text-muted-foreground">Role</dt>
            <dd>{me.role.name}</dd>
          </dl>
          <p className="text-xs text-muted-foreground">To change your name or role, ask an admin in your workspace.</p>
        </Section>
        <ChangePassword onDone={logout} />
        <TwoFactor />
        <Section
          title="Signed-in devices"
          description="Lost a phone or used a shared computer? Sign out everywhere, including here."
        >
          <Button
            variant="outline"
            onClick={async () => {
              try {
                unwrap(await api.POST("/api/v1/auth/logout-all"));
                toast.success("Signed out of all devices.");
                await logout();
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
          >
            Sign out of all devices
          </Button>
        </Section>
      </div>
    </>
  );
}

function ChangePassword({ onDone }: { onDone: () => Promise<void> }) {
  const form = useForm<{ current: string; next: string; confirm: string }>();
  const { errors, isSubmitting } = form.formState;
  const submit = form.handleSubmit(async ({ current, next }) => {
    try {
      unwrap(
        await api.POST("/api/v1/auth/password/change", { body: { current_password: current, new_password: next } }),
      );
      toast.success("Password changed. Sign in with your new password.");
      await onDone(); // every session is revoked after a password change
    } catch (e) {
      form.setError("current", { message: (e as Error).message });
    }
  });
  return (
    <Section title="Password" description="Changing it signs you out on every device.">
      <form onSubmit={submit} className="space-y-3">
        <Field
          id="current"
          label="Current password"
          type="password"
          autoComplete="current-password"
          error={errors.current?.message}
          {...form.register("current", { required: "Enter your current password" })}
        />
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
        <Button type="submit" disabled={isSubmitting}>
          Change password
        </Button>
      </form>
    </Section>
  );
}

function TwoFactor() {
  const { me, reloadMe } = useAuth();
  const [settingUp, setSettingUp] = useState(false);
  const form = useForm<{ password: string; code: string }>();
  const { errors, isSubmitting } = form.formState;
  if (!me) return null;
  const required = NEEDS_2FA.has(me.role.key ?? "");

  const turnOff = form.handleSubmit(async (body) => {
    try {
      unwrap(await api.POST("/api/v1/auth/2fa/disable", { body: { password: body.password, code: body.code.trim() } }));
      toast.success(required ? "Two-factor is off. Set it up on your new phone now." : "Two-factor is off.");
      form.reset();
      await reloadMe(); // Owner/Admin are taken straight to setup
    } catch (e) {
      form.setError("code", { message: (e as Error).message });
    }
  });

  return (
    <Section
      title="Two-factor authentication"
      description="A 6-digit code from an authenticator app, asked for each time you sign in."
    >
      <div className="flex items-center gap-2">
        <span>Status</span>
        <Badge variant={me.two_factor_enabled ? "secondary" : "outline"}>{me.two_factor_enabled ? "On" : "Off"}</Badge>
        {required && <span className="text-xs text-muted-foreground">Required for your role</span>}
      </div>
      {me.two_factor_enabled ? (
        <form onSubmit={turnOff} className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Moving to a new phone? Turn it off here, then set it up again.
            {required && " Your role will take you straight to setup."}
          </p>
          <Field
            id="tf-password"
            label="Password"
            type="password"
            autoComplete="current-password"
            {...form.register("password", { required: true })}
          />
          <Field
            id="tf-code"
            label="Current 6-digit code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            error={errors.code?.message}
            {...form.register("code", { required: true, pattern: { value: /^\d{6}$/, message: "6 digits" } })}
          />
          <Button type="submit" variant="outline" disabled={isSubmitting}>
            Turn off two-factor
          </Button>
        </form>
      ) : settingUp ? (
        <div className="max-w-xs">
          <TwoFactorSetupForm
            onDone={async () => {
              setSettingUp(false);
              await reloadMe();
            }}
          />
        </div>
      ) : (
        <Button onClick={() => setSettingUp(true)}>Turn on two-factor</Button>
      )}
    </Section>
  );
}
