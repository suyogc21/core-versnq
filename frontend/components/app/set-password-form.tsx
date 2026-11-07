"use client";

import { useForm } from "react-hook-form";

import { Field, PASSWORD_RULE } from "@/components/app/field";
import { Button } from "@/components/ui/button";

type Values = { password: string; confirm: string };

/** New password + confirmation, 10-200 characters. */
export function SetPasswordForm({ submitLabel, onSubmit }: { submitLabel: string; onSubmit: (password: string) => Promise<void> }) {
  const form = useForm<Values>();
  const { errors } = form.formState;
  const submit = form.handleSubmit(async ({ password }) => {
    try {
      await onSubmit(password);
    } catch (e) {
      form.setError("password", { message: (e as Error).message });
    }
  });
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field
        id="password"
        label="New password"
        type="password"
        autoComplete="new-password"
        autoFocus
        hint="At least 10 characters."
        error={errors.password?.message}
        {...form.register("password", {
          required: "Enter a password",
          minLength: { value: PASSWORD_RULE.minLength, message: "Use at least 10 characters" },
          maxLength: { value: PASSWORD_RULE.maxLength, message: "Too long" },
        })}
      />
      <Field
        id="confirm"
        label="Repeat password"
        type="password"
        autoComplete="new-password"
        error={errors.confirm?.message}
        {...form.register("confirm", {
          validate: (v, all) => v === all.password || "Passwords do not match",
        })}
      />
      <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
        {submitLabel}
      </Button>
    </form>
  );
}
