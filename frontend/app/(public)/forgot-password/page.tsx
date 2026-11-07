"use client";

import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { AuthCard } from "@/components/app/auth-card";
import { Field } from "@/components/app/field";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ email: string }>();

  const submit = form.handleSubmit(async ({ email }) => {
    setError(null);
    try {
      unwrap(await api.POST("/api/v1/auth/password/forgot", { body: { email } }));
      setSent(true);
    } catch (e) {
      setError((e as Error).message);
    }
  });

  return (
    <AuthCard
      title="Reset your password"
      description={sent ? "If that account exists, we've emailed a reset link. It works for 60 minutes." : undefined}
    >
      {sent ? (
        <Link href="/login" className="text-sm hover:underline">
          Back to sign in
        </Link>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field id="email" label="Email" type="email" autoFocus error={error ?? undefined} {...form.register("email", { required: true })} />
          <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
            Send reset link
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
